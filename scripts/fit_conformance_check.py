# -*- coding: utf-8 -*-
"""FIT 文件规范校验器（通用，不依赖目标平台）。

**这是"编辑 FIT 过程 + 最后复查"都必须跑的强制门禁。**
它把 `references/fit_format_spec.md` 里的每一条要求都实现成可执行断言，
而不是靠人记得去查规范。

覆盖范围（十节）：
  §1 文件头          header_size / protocol / profile_version / data_size / magic / 双 CRC
  §2 记录流结构      DEF 结构（reserved/endian/nfields）/ local 分配 / 完整解析 / 无 desync
  §3 类型码          类型码合法性 / 字段 size 与 base type 相容 / 类型码 vs 官方定义
  §4 无效哨兵        声明了却没填值的字段应是哨兵而非 0 / 有符号类型不许出现 0xFF 族误填
  §5 scale-offset    物理量换算合理性（按官方定义，不硬编码字段号）
  §6 消息顺序        fileId 首条 / 207 先于 206 / 206 先于引用它的消息
  §7 开发者字段      ref_index 必须指向已声明的 206 / 206 字段完整性
  §8 时间戳          epoch 正确 / 单调 / 区间闭合 / 采样间隔
  §9 数值合理性      按**官方字段名**做区间校验（跨品牌通用）
  §10 一致性         与源文件逐点比对（可选）；与目标平台模板一致（可选）

用法
----
    # 基本校验（任意 fit）
    python fit_conformance_check.py 文件.fit

    # 与源文件做一致性比对
    python fit_conformance_check.py 产物.fit --src 源.fit

    # 同时校验是否复刻了目标平台模板
    python fit_conformance_check.py 产物.fit --temp apex4

    # 只做快速结构校验（跳过数值合理性）
    python fit_conformance_check.py 文件.fit --quick

退出码：0 = 全 PASS（允许 WARN）；1 = 存在 FAIL
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fit_lib import (BASE_TYPES, TYPE_IDS, FitFile, Profile, TEMPLATE_DIR,
                     invalid_bytes, is_invalid)

# ---------------------------------------------------------------------------
# 结果收集
# ---------------------------------------------------------------------------

class Report:
    def __init__(self, title):
        self.title = title
        self.rows = []       # (level, section, item, detail)
        self.section = None

    def sec(self, name):
        self.section = name
        print()
        print('=' * 78)
        print(f'  {name}')
        print('=' * 78)

    def _add(self, level, item, detail=''):
        self.rows.append((level, self.section, item, detail))
        icon = {'PASS': '[ OK ]', 'FAIL': '[FAIL]', 'WARN': '[WARN]',
                'INFO': '[INFO]'}[level]
        line = f'  {icon} {item}'
        if detail:
            line += f'  —— {detail}'
        print(line)

    def ok(self, item, detail=''):
        self._add('PASS', item, detail)

    def fail(self, item, detail=''):
        self._add('FAIL', item, detail)

    def warn(self, item, detail=''):
        self._add('WARN', item, detail)

    def info(self, item, detail=''):
        self._add('INFO', item, detail)

    def check(self, cond, item, detail='', fail_detail='', note=''):
        """cond 为真 → PASS（附注用 note）；为假 → FAIL（原因用 fail_detail 或 detail）。

        ⚠️ detail 的语义是**失败原因**（形如「应为X，实际Y」），
        过去在 PASS 时也照打，造成「[ OK ] ... —— 应为 16，实际 16」这类
        自相矛盾的输出，会误导人工复核。现在 PASS 只显示 note。
        """
        if cond:
            self.ok(item, note)
        else:
            self.fail(item, fail_detail or detail)
        return cond

    def counts(self):
        c = {'PASS': 0, 'FAIL': 0, 'WARN': 0, 'INFO': 0}
        for lv, *_ in self.rows:
            c[lv] += 1
        return c

    def verdict(self):
        c = self.counts()
        return c['FAIL'] == 0, c


# ---------------------------------------------------------------------------
# 按官方字段名定义的物理量合理区间（跨品牌通用，不写字段号）
# name -> (min, max, unit, 说明)
# ---------------------------------------------------------------------------

RANGES = {
    'altitude': (-500, 9000, 'm', '海拔'),
    'enhancedAltitude': (-500, 9000, 'm', '海拔'),
    'speed': (0, 30, 'm/s', '速度（0=暂停，必须允许）'),
    'enhancedSpeed': (0, 30, 'm/s', '速度（0=暂停，必须允许）'),
    'verticalSpeed': (-20, 20, 'm/s', '垂直速度'),
    'heartRate': (20, 250, 'bpm', '心率'),
    'cadence': (0, 255, 'rpm', '步频（跑步 ×2 = spm）'),
    'fractionalCadence': (0, 1, 'rpm', '步频小数部分'),
    'power': (0, 2500, 'W', '功率'),
    'temperature': (-60, 80, '℃', '温度'),
    'distance': (0, 500000, 'm', '距离'),
    'totalDistance': (0, 500000, 'm', '总距离'),
    'verticalOscillation': (0, 300, 'mm', '垂直振幅'),
    'avgVerticalOscillation': (0, 300, 'mm', '平均垂直振幅'),
    'stanceTime': (0, 1200, 'ms', '触地时间'),
    'avgStanceTime': (0, 1200, 'ms', '平均触地时间'),
    'stanceTimePercent': (0, 100, '%', '触地时间占比'),
    'avgStanceTimePercent': (0, 100, '%', '平均触地时间占比'),
    'stanceTimeBalance': (0, 100, '%', '触地平衡'),
    'avgStanceTimeBalance': (0, 100, '%', '平均触地平衡'),
    'verticalRatio': (0, 100, '%', '垂直步幅比'),
    'avgVerticalRatio': (0, 100, '%', '平均垂直步幅比'),
    'stepLength': (0, 3000, 'mm', '步幅'),
    'avgStepLength': (0, 3000, 'mm', '平均步幅'),
    'totalCalories': (0, 20000, 'kcal', '卡路里'),
    'totalAscent': (-500, 20000, 'm', '累计爬升'),
    'totalDescent': (-500, 20000, 'm', '累计下降'),
    'totalTimerTime': (0, 86400 * 7, 's', '计时时间'),
    'totalElapsedTime': (0, 86400 * 7, 's', '经过时间'),
    'enhancedAvgSpeed': (0, 30, 'm/s', '平均速度'),
    'enhancedMaxSpeed': (0, 30, 'm/s', '最大速度'),
    'avgSpeed': (0, 30, 'm/s', '平均速度'),
    'maxSpeed': (0, 30, 'm/s', '最大速度'),
    'avgHeartRate': (20, 250, 'bpm', '平均心率'),
    'maxHeartRate': (20, 250, 'bpm', '最大心率'),
    'minHeartRate': (20, 250, 'bpm', '最小心率'),
    'avgCadence': (0, 255, 'rpm', '平均步频'),
    'maxCadence': (0, 255, 'rpm', '最大步频'),
    'avgTemperature': (-60, 80, '℃', '平均温度'),
    'avgPower': (0, 2500, 'W', '平均功率'),
    'maxPower': (0, 2500, 'W', '最大功率'),
    'trainingEffect': (0, 6, '', '训练效果'),
    'totalTrainingEffect': (0, 6, '', '总训练效果'),
    'anaerobicTrainingEffect': (0, 6, '', '无氧训练效果'),
    'activityTrainingLoad': (0, 5000, '', '训练负荷'),
    'grade': (-100, 100, '%', '坡度'),
    'avgGrade': (-100, 100, '%', '平均坡度'),
    'sport': (0, 254, '', '运动类型'),
    'subSport': (0, 254, '', '子类型'),
}

# 有符号类型的合法无效哨兵（用于检测"按无符号填哨兵"的历史 bug）
SIGNED_SENTINELS = {
    'sint8': {0x7F},
    'sint16': {0x7FFF},
    'sint32': {0x7FFFFFFF},
    'sint64': {0x7FFFFFFFFFFFFFFF},
}


# ---------------------------------------------------------------------------
# 校验器
# ---------------------------------------------------------------------------

class Checker:
    def __init__(self, path, prof, quick=False):
        self.path = path
        self.prof = prof
        self.quick = quick
        self.f = FitFile(path)
        self.r = Report(f'FIT 规范校验：{os.path.basename(path)}')

    # -- §1 文件头 ----------------------------------------------------------
    def head(self):
        r, h = self.r, self.f.header
        data = self.f.data
        r.sec('§1 文件头（文件级结构）')
        r.check(h['size'] in (12, 14), f'header_size = {h["size"]}（标准 14，12=无头CRC）')
        r.check(0 < h['protocol'] <= 0x7F or h['protocol'] >= 0x80,
                f'protocol_version = {h["protocol"]}（0x80 位表示支持 profile 版本）')
        r.check(h['profile_version'] > 0, f'profile_version = {h["profile_version"]}')
        r.check(h['data_size'] > 0, f'data_size = {h["data_size"]}')
        r.check(len(data) == h['size'] + h['data_size'] + 2,
                f'文件总长 = {len(data)}（= header + data_size + 2 尾部CRC）',
                f'文件总长 {len(data)} != {h["size"]}+{h["data_size"]}+2 = '
                f'{h["size"] + h["data_size"] + 2} —— data_size 与实际字节数不符')
        r.check(data[8:12] == b'.FIT', f'data_type magic = {data[8:12]!r}（须为 ".FIT"）',
                f'data_type = {data[8:12]!r}，不是 ".FIT"')
        r.check(bool(h.get('crc_ok')), '头部 CRC 校验',
                f'头部 CRC 错误：文件值 0x{h.get("crc") or 0:04X} != '
                f'计算值 0x{_crc16(data[:12]):04X}')
        r.check(bool(self.f.trailer_crc_ok), '尾部 CRC 校验',
                f'尾部 CRC 错误：文件值 0x{h.get("trailer_crc") or 0:04X} != '
                f'计算值 0x{_crc16(data[:self.f.data_end]):04X}')

    # -- §2 记录流结构 ------------------------------------------------------
    def structure(self):
        r, f = self.r, self.f
        r.sec('§2 记录流结构')
        r.check(f.integrity(),
                f'完整解析：终点 {f.end} == 数据区终点 {f.data_end}',
                f'解析不完整！终点 {f.end} != 数据区终点 {f.data_end}'
                + (f'，desync @ 0x{f.desync:X}' if f.desync is not None else '')
                + ' —— 存在结构错位（DEF 结构写错 / 字段长度不符 / local 未定义）')
        # DEF 结构
        bad_res, bad_end, bad_loc, bad_ftype = [], [], [], []
        subfield_ok = []          # 被 sub_field 重载豁免的字段
        for dd in f.defs:
            if dd.endian not in '<>':
                bad_end.append(dd)
            if dd.local > 15:
                bad_loc.append(dd)
            for fd in dd.fields + dd.devs:
                if fd.base_type not in BASE_TYPES:
                    bad_ftype.append((dd.g, fd.num, fd.base_type))
                    continue
                bsz = BASE_TYPES[fd.base_type][1]
                if fd.size == 0 or fd.size % bsz != 0:
                    # 官方 profile 的 sub_field 允许同一字段号用不同基础类型重载
                    # （如 event.f3「data」可被 timerTrigger/enum 或 uint8 覆盖）。
                    # 真机就是这么写的，SDK 解码 0 error → 合法，单独放行。
                    if _subfield_allows(self.prof, dd.g, fd.num, fd.base_type):
                        subfield_ok.append((dd.g, fd.num, fd.size))
                        continue
                    bad_ftype.append((dd.g, fd.num, fd.base_type, fd.size))
        r.check(True, f'DEF 条数 = {len(f.defs)}（含重复声明）')
        r.check(not bad_loc, 'local 号范围 0-15',
                f'越界 local: {bad_loc[:5]}')
        r.check(not bad_ftype,
                '字段 size 与 fitBaseType 相容',
                f'不相容的字段定义（global, 字段号, 类型, size）: {bad_ftype[:8]}')
        if subfield_ok:
            r.info(f'{len(subfield_ok)} 处字段用 sub_field 重载类型'
                   f'（官方 profile 允许，真机同款写法）', str(subfield_ok[:5]))
        r.check(not bad_end, 'DEF architecture 字节合法（0=小端 1=大端）')
        # reserved 字节（易漏点）
        res_bad = []
        for dd in f.defs:
            if data_reserved(f, dd) != 0:
                res_bad.append((dd.g, hex(dd.offset)))
        r.check(not res_bad, 'DEF reserved 字节恒为 0x00',
                f'reserved 非 0 的 DEF: {res_bad[:5]}')
        r.info(f'消息 {len(f.msgs)} 条 / 涉及 {len(f.global_counts())} 种消息')

    # -- §3 类型码 ----------------------------------------------------------
    def type_codes(self):
        r, f = self.r, self.f
        r.sec('§3 类型码与官方定义一致性')
        unknown_msg = sorted({m.g for m in f.msgs if self.prof.msg_num_by_num(m.g) is None})
        if unknown_msg:
            r.info(f'非官方消息 {len(unknown_msg)} 种（厂商私有扩展）: {unknown_msg[:12]}')
        mismatch, private = [], []
        for dd in f.defs:
            known_msg = self.prof.msg_num_by_num(dd.g) is not None
            for fd in dd.fields:
                oid = self.prof.type_id(dd.g, fd.num)
                if not known_msg or oid is None:
                    private.append((dd.g, fd.num))
                elif oid != fd.base_type:
                    mismatch.append({
                        'global': dd.g, 'msg': self.prof.msg_name(dd.g),
                        'field': fd.num, 'name': self.prof.fname(dd.g, fd.num),
                        'official': f'0x{oid:02X}',
                        'actual': f'0x{fd.base_type:02X}',
                    })
        if mismatch:
            r.warn(f'与官方定义类型码不符 {len(mismatch)} 处（须照抄实际值）',
                   '; '.join(f'g={m["global"]} f{m["field"]} {m["name"]} '
                             f'{m["official"]}→{m["actual"]}' for m in mismatch[:6]))
        else:
            r.ok('所有官方字段的类型码与官方定义一致',
                 f'（另有 {len(private)} 个私有扩展字段，官方无定义，属正常）')
        return mismatch

    # -- §4 哨兵 -----------------------------------------------------------
    def sentinels(self):
        r, f = self.r, self.f
        r.sec('§4 无效哨兵（按类型族，不可一律 0xFF）')
        problems = []
        all_invalid = []
        for dd in f.defs:
            for fd in dd.fields:
                tn = self.prof.type_name(dd.g, fd.num)
                if tn is None:
                    continue          # 私有字段无官方类型，跳过
                vals = []
                for m in f.msgs:
                    if m.def_.g != dd.g or m.def_.signature() != dd.signature():
                        continue
                    raw = m.raw.get(fd.num)
                    if raw is not None:
                        vals.append(raw)
                if not vals:
                    continue
                n_inv = sum(1 for v in vals if is_invalid(v, tn))
                if n_inv == len(vals):
                    all_invalid.append((dd.g, fd.num, self.prof.fname(dd.g, fd.num), len(vals)))
                # 有符号类型：检查是否被填成无符号哨兵族（0xFF..）
                if tn in SIGNED_SENTINELS:
                    want = invalid_bytes(tn, fd.size)
                    for v in vals:
                        if bytes(v) in (b'\xFF' * fd.size, b'\x00' * fd.size) \
                                and bytes(v) != want:
                            problems.append((dd.g, fd.num, self.prof.fname(dd.g, fd.num),
                                             tn, v.hex(' '), want.hex(' ')))
                            break
        if problems:
            # ⚠️ 实测：佳明真机自己也会把 sint32 填成 0xFFFFFFFF / sint8 填 0x00，
            #    官方 SDK 解码 0 error。因此这属「风险提示」而非规范违规。
            #    但我们自己生成产物时**必须**按官方哨兵写（S8→0x7F），
            #    否则遇到按无符号读取的解析器会显示 255℃ 这类异常值。
            r.warn(f'{len(problems)} 处有符号字段未用官方哨兵'
                   f'（部分厂商习惯，若解析器按无符号读会显示异常值）',
                   '; '.join(f'g={g} f{n}({nm}) {tn} 实际 {a} 应为 {w}'
                             for g, n, nm, tn, a, w in problems[:4]))
            r.info('我们生成产物时一律用官方哨兵：S8=0x7F / S16=0x7FFF / S32=0x7FFFFFFF')
        else:
            r.ok('有符号字段均使用官方哨兵（S8=0x7F / S16=0x7FFF / S32=0x7FFFFFFF）')
        if all_invalid:
            r.info(f'声明但全为无效值的字段 {len(all_invalid)} 个（真机也会这样，正常）',
                   '; '.join(f'g={g} f{n}({nm})×{c}' for g, n, nm, c in all_invalid[:8]))
        else:
            r.ok('无"整列全无效"的字段')

    # -- §5 scale/offset ---------------------------------------------------
    def ranges(self):
        if self.quick:
            return
        r, f = self.r, self.f
        r.sec('§5 物理量换算合理性（按官方 scale/offset，按字段名判定）')
        checked = 0
        for dd in f.defs:
            for fd in dd.fields:
                name = self.prof.fname(dd.g, fd.num)
                if name not in RANGES or name.startswith('f'):
                    continue
                lo, hi, unit, note = RANGES[name]
                vals = []
                for m in f.msgs:
                    if m.def_.g != dd.g or m.def_.signature() != dd.signature():
                        continue
                    v = f.value(m, fd.num, self.prof)
                    if v is not None and isinstance(v, (int, float)):
                        vals.append(v)
                if not vals:
                    continue
                checked += 1
                mn, mx = min(vals), max(vals)
                bad = [v for v in vals if not (lo <= v <= hi)]
                tag = f'{name}({note})'
                if bad:
                    r.fail(f'{tag} 区间 {lo}~{hi} {unit}',
                           f'实际 {mn:.3f} ~ {mx:.3f}，越界 {len(bad)} 个'
                           f'（例 {bad[:3]}）—— 检查 scale/offset 是否按官方定义')
                else:
                    r.ok(f'{tag} = {mn:.3f} ~ {mx:.3f} {unit}（{len(vals)} 点）')
        if checked == 0:
            r.info('未发现可校验的已知物理量字段')

    # -- §6 消息顺序 -------------------------------------------------------
    def order(self):
        r, f = self.r, self.f
        r.sec('§6 消息顺序')
        first = f.msgs[0].g if f.msgs else None
        r.check(first == 0, f'首条消息是 fileId(g=0)（实际 g={first}）',
                f'首条消息 g={first}，应为 fileId(0)')
        idx207 = [i for i, m in enumerate(f.msgs) if m.g == 207]
        idx206 = [i for i, m in enumerate(f.msgs) if m.g == 206]
        if idx207 and idx206:
            r.check(min(idx207) < min(idx206),
                    f'developerDataId(207) 先于 fieldDescription(206)'
                    f'（207@{min(idx207)} < 206@{min(idx206)}）',
                    f'顺序错误：207@{min(idx207)} 应在 206@{min(idx206)} 之前')
        # 引用开发字段的消息必须晚于 206
        # ⚠️ 实测：高驰真机的 record 带 dev 字段出现在第 9 条，而 206 声明在第 17 条
        #    （@296）——即「先引用、后声明」，官方 SDK 解码 0 error，属合法写法。
        #    真正必须满足的是：206 必须**存在于文件中**且被 207 前置声明。
        #    因此这一条从 FAIL 降级为 INFO（只报告，不判违规）。
        dev_users = []
        for i, m in enumerate(f.msgs):
            if m.def_.devs:
                dev_users.append((i, m.g))
        if dev_users and idx206:
            last206 = max(idx206)
            early = [(i, g) for i, g in dev_users if i < last206]
            if early:
                r.info(f'{len(early)} 条引用开发字段的消息在最后一条 206 之前出现'
                       f'（真机同款：高驰 record 第 9 条即带 dev，206 在第 17 条声明）')
            else:
                r.ok(f'引用开发字段的消息都晚于 206 声明（{len(dev_users)} 条）')
        # session/lap 位置
        if idx := [i for i, m in enumerate(f.msgs) if m.g == 18]:
            r.check(min(idx) > 0, f'session 位于记录流后段（@{min(idx)}/{len(f.msgs)}）')
        r.info('消息首次出现顺序: ' + ' → '.join(
            f'{g}({self.prof.msg_name(g)})' for g in _msg_order(f, limit=14)))

    # -- §7 开发者字段 -----------------------------------------------------
    def dev_fields(self):
        r, f = self.r, self.f
        r.sec('§7 开发者字段（206/207）机制')
        fd_msgs = [m for m in f.msgs if m.g == 206]
        dd_msgs = [m for m in f.msgs if m.g == 207]
        if not fd_msgs and not dd_msgs:
            r.info('本文件未使用开发者字段（正常，非必需）')
            return
        r.check(bool(dd_msgs), f'developerDataId(207) 已声明 ×{len(dd_msgs)}')
        r.check(bool(fd_msgs), f'fieldDescription(206) 已声明 ×{len(fd_msgs)}')
        # 207 必含 developerDataIndex
        declared_idx = set()
        for m in dd_msgs:
            v = f.value(m, 3, self.prof)
            if v is not None:
                declared_idx.add(int(v))
            else:
                r.fail('207 缺 developerDataIndex(f3)')
        r.ok(f'developerDataIndex 声明值: {sorted(declared_idx)}')
        # 206 完整性
        dev_decls = {}
        for m in fd_msgs:
            ddi = f.value(m, 0, self.prof)
            fdn = f.value(m, 1, self.prof)
            bti = f.value(m, 2, self.prof)
            name = f.value(m, 3, self.prof)
            units = f.value(m, 8, self.prof)
            if None in (ddi, fdn, bti):
                r.fail('206 字段声明不完整（缺 developerDataIndex / '
                       'fieldDefinitionNumber / fitBaseTypeId）')
                continue
            dev_decls[int(fdn)] = {
                'developerDataIndex': int(ddi), 'fitBaseTypeId': int(bti),
                'name': name, 'units': units,
            }
            r.ok(f'206 声明 f{int(fdn)} "{name}" type=0x{int(bti):02X} units="{units}" '
                 f'(ddi={int(ddi)})')
        # DEF 里的 dev 字段 ref_index 必须指向已声明的 developerDataIndex
        bad_ref = []
        for dd in f.defs:
            for fd in dd.devs:
                if fd.base_type not in declared_idx:
                    bad_ref.append((dd.g, fd.num, fd.base_type))
                if fd.num not in dev_decls:
                    bad_ref.append((dd.g, fd.num, '未声明'))
        r.check(not bad_ref,
                'DEF 里开发字段的第三字节 = 已声明的 developerDataIndex',
                f'引用无效: {bad_ref[:5]} —— 该字节不是类型码，是 206 索引')
        # 值域诊断
        for dd in f.defs:
            if not dd.devs:
                continue
            for fd in dd.devs:
                decl = dev_decls.get(fd.num, {})
                vals = []
                for m in f.msgs:
                    if m.def_.signature() != dd.signature():
                        continue
                    raw = m.dev_raw.get(fd.num)
                    if raw is not None:
                        vals.append(struct.unpack('<f', raw)[0]
                                    if len(raw) == 4 else None)
                vals = [v for v in vals if v is not None]
                if vals:
                    nz = sum(1 for v in vals if v == 0)
                    r.info(f'开发字段 {decl.get("name")} (g={dd.g} f{fd.num}): '
                           f'{len(vals)} 点，range {min(vals):.4f}~{max(vals):.4f}，'
                           f'其中 0 值 {nz} 个')

    # -- §8 时间戳 ---------------------------------------------------------
    def timestamps(self):
        r, f = self.r, self.f
        r.sec('§8 时间戳')
        ts_list = []
        for m in f.msgs:
            if 253 in m.raw:
                v = f.value(m, 253, self.prof)
                if v is not None:
                    ts_list.append((m.offset, m.g, int(v)))
        if not ts_list:
            r.warn('文件中未找到 timestamp(f253)')
            return
        vals = [t for _, _, t in ts_list]
        mn, mx = min(vals), max(vals)
        import datetime as dt
        conv = lambda t: dt.datetime.utcfromtimestamp(t + 631065600).strftime(
            '%Y-%m-%d %H:%M:%S')
        r.check(1989 * 0 + 100000000 < mn,
                f'timestamp 落在合理 epoch（FIT epoch 1989-12-31）',
                f'最小值 {mn} 过小，epoch 可能算错')
        r.info(f'时间范围 {conv(mn)} ~ {conv(mx)} UTC（{mx - mn} 秒）')
        # 单调性（record 内）
        rec_ts = [t for _, g, t in ts_list if g == 20]
        if len(rec_ts) > 1:
            drops = [i for i in range(1, len(rec_ts)) if rec_ts[i] < rec_ts[i - 1]]
            r.check(not drops,
                    f'record 时间戳单调不减（{len(rec_ts)} 点，最大步进 '
                    f'{max(b - a for a, b in zip(rec_ts, rec_ts[1:]))}s）',
                    f'{len(drops)} 处时间回退（例 @{drops[:5]}）')
            gaps = [b - a for a, b in zip(rec_ts, rec_ts[1:])]
            from collections import Counter
            r.info(f'采样间隔分布: {dict(Counter(gaps).most_common(5))}')
        # session 区间闭合
        # ⚠️ 实测两家语义不同（都是厂商惯例，SDK 均 0 error）：
        #    佳明 session.timestamp = **开始时间**（等于 startTime）
        #    高驰 session.timestamp = **结束时间**
        #    FIT 官方文档语义是「session 结束时刻」。因此这里只在两者都排不上时告警。
        sess = f.one(18)
        if sess:
            st = f.value(sess, 2, self.prof)
            en = f.value(sess, 253, self.prof)
            if st is not None and rec_ts:
                r.check(abs(rec_ts[0] - int(st)) <= 2,
                        f'session.startTime 与首条 record 对齐（差 '
                        f'{rec_ts[0] - int(st)}s）',
                        f'session.startTime 与首条 record 相差 '
                        f'{rec_ts[0] - int(st)}s，可能时区/换算不一致')
            if en is not None and rec_ts:
                if abs(int(en) - int(st)) <= 2:
                    r.info(f'session.timestamp = 开始时间（佳明惯例，非官方"结束时刻"语义）')
                elif rec_ts[-1] <= int(en) + 2:
                    r.ok(f'session.timestamp = 结束时间，覆盖末条 record'
                         f'（高驰惯例 / 符合官方语义）')
                else:
                    r.warn(f'session.timestamp({conv(int(en))}) 既不等于开始时间，'
                           f'也不覆盖末条 record({conv(rec_ts[-1])})')

    # -- §9 跨字段一致性 ---------------------------------------------------
    def consistency(self):
        if self.quick:
            return
        r, f = self.r, self.f
        r.sec('§9 跨字段一致性')
        sess = f.one(18)
        if not sess:
            r.warn('无 session 消息，跳过')
            return
        dist = f.value(sess, 9, self.prof)
        timer = f.value(sess, 8, self.prof)
        avg = f.value(sess, 14, self.prof)
        if dist and timer and avg:
            calc = dist / timer
            diff = abs(calc - avg)
            r.check(diff < max(0.05, avg * 0.03),
                    f'session 平均速度自洽：distance/timer = {calc:.4f} m/s，'
                    f'字段值 {avg:.4f} m/s（差 {diff:.4f}）',
                    f'平均速度不自洽：distance/timer = {calc:.4f}，'
                    f'avgSpeed 字段 = {avg:.4f}（差 {diff:.4f}，超 3%）')
        # record 距离非递减
        recs = f.by_global(20)
        ds = [f.value(m, 5, self.prof) for m in recs]
        ds = [d for d in ds if d is not None]
        if len(ds) > 1:
            drops = [i for i in range(1, len(ds)) if ds[i] < ds[i - 1] - 0.5]
            r.check(not drops,
                    f'record 距离单调不减（{len(ds)} 点，末值 {ds[-1]:.1f} m）',
                    f'{len(drops)} 处距离回退（例 @{drops[:5]}）')
        # lap 汇总 vs session
        laps = f.by_global(19)
        if laps:
            ld = sum(x for x in (f.value(l, 9, self.prof) for l in laps) if x)
            if dist:
                r.check(abs(ld - dist) < max(50, dist * 0.03),
                        f'lap 距离合计 {ld:.1f} m ≈ session 总距离 {dist:.1f} m',
                        f'lap 距离合计 {ld:.1f} m 与 session {dist:.1f} m 相差过大')
        # 派生成绩可行性：零速点决定"移动时间"能否算出
        # ⚠️ 必须按**官方字段名**解析：佳明 record 用 enhancedSpeed(73)，
        #    高驰用 speed(6)，硬编码字段号会永远读到 0 个点而误报（历史教训）。
        sp_num = None
        sp_name = None
        for nm in ('enhancedSpeed', 'speed'):
            n = self.prof.field_num(20, nm)
            if n is None:
                continue
            if any(n in m.raw for m in recs):
                sp_num, sp_name = n, nm
                break
        if sp_num is None:
            r.info('本文件 record 未携带速度字段，跳过零速点统计')
        else:
            vals = [f.value(m, sp_num, self.prof) for m in recs]
            vals = [v for v in vals if v is not None]
            zero = sum(1 for v in vals if v == 0)
            r.info(f'速度=0 的点 {zero} 个'
                   f'（字段 {sp_name}[{sp_num}]，{len(vals)} 点有值）'
                   f'（平台据此划分移动段、计算最快 1KM 等区间成绩）')
            if zero == 0:
                r.warn('无速度=0 的点', '若源文件有暂停段，可能是 0 被平滑/差分覆盖 —— '
                                        '会导致平台算不出区间成绩（最快 1KM / 最佳配速）')

    # -- §10 与源文件比对 --------------------------------------------------
    def vs_source(self, src_path):
        r = self.r
        r.sec(f'§10 与源文件一致性比对（{os.path.basename(src_path)}）')
        s = FitFile(src_path)
        sr = s.by_global(20)
        nr = self.f.by_global(20)
        r.check(len(nr) == len(sr), f'record 条数一致（{len(nr)} vs 源 {len(sr)}）',
                f'record 条数不等：产物 {len(nr)} vs 源 {len(sr)} —— 有点位丢失或多余')
        # 速度零速点专项比对（必须在**可比区间**内判，否则会被渐进式布局误导）
        # ─────────────────────────────────────────────────────────────
        # 教训（2026-09-18）：佳明前 3 个点位用 27 字段布局、高驰前 3 个用
        # 3/6 字段布局，后者结构上不含 speed 字段。若按索引硬对，会得出
        # 「零速点从 12 变 10、丢了 2 个」的**假警报**。
        # 正确做法：只在「两端该点位都携带速度值」的区间内比对。
        snum = None
        sprof = Profile()
        for nm in ('enhancedSpeed', 'speed'):
            n = sprof.field_num(20, nm)
            if n is not None and any(n in m.raw for m in sr):
                snum = n
                break
        nnum = None
        for nm in ('enhancedSpeed', 'speed'):
            n = self.prof.field_num(20, nm)
            if n is not None and any(n in m.raw for m in nr):
                nnum = n
                break
        if snum is not None and nnum is not None:
            comp = 0
            same = 0
            mism = []
            zero_pair = 0
            for i, (ms, md) in enumerate(zip(sr, nr)):
                vs = s.value(ms, snum, sprof)
                vd = self.f.value(md, nnum, self.prof)
                if vs is None or vd is None:
                    continue
                comp += 1
                if abs(vs - vd) < 1e-9:
                    same += 1
                    if vs == 0:
                        zero_pair += 1
                else:
                    mism.append((i, vs, vd))
            skipped = len(nr) - comp
            r.check(not mism,
                    f'速度逐点一致（可比区间 {comp} 点，含 {zero_pair} 个零速点）',
                    f'速度不一致 {len(mism)} 处，例 @{mism[:3]}')
            if skipped:
                r.info(f'{skipped} 个点位因目标渐进式布局未声明速度字段而无法比对'
                       f'（非数据丢失，是该平台的布局特性）')
        # 海拔逐点（按官方名找目标字段）
        for fname in ('enhancedAltitude', 'altitude'):
            nnum = self.prof.field_num(20, fname)
            snum = s.prof if False else None
            snum = Profile().field_num(20, fname)
            if nnum is None or snum is None:
                continue
            nv = [self.f.value(m, nnum, self.prof) for m in nr]
            sv = [s.value(m, snum, Profile()) for m in sr]
            pairs = [(a, b) for a, b in zip(nv, sv) if a is not None and b is not None]
            if not pairs:
                continue
            mx = max(abs(a - b) for a, b in pairs)
            r.check(mx < 0.101,
                    f'{fname} 逐点最大差异 {mx:.4f} m（{len(pairs)} 点）',
                    f'{fname} 逐点最大差异 {mx:.4f} m 超阈值（应为 0，检查换算）')
            break
        # 速度逐点
        nnum = self.prof.field_num(20, 'speed') or self.prof.field_num(20, 'enhancedSpeed')
        snum = Profile().field_num(20, 'enhancedSpeed') or Profile().field_num(20, 'speed')
        if nnum and snum:
            pairs = []
            for a, b in zip(nr, sr):
                va = self.f.value(a, nnum, self.prof)
                vb = s.value(b, snum, Profile())
                if va is not None and vb is not None:
                    pairs.append((va, vb))
            if pairs:
                mx = max(abs(a - b) for a, b in pairs)
                r.check(mx < 0.011, f'速度逐点最大差异 {mx:.5f} m/s（{len(pairs)} 点）',
                        f'速度逐点最大差异 {mx:.5f} m/s 超阈值')

    # -- §11 与目标规范比对 ------------------------------------------------
    def vs_template(self, temp_name, src_path=None):
        r = self.r
        # 与转换器保持一致：优先读「规范」（references/profiles/，入库可复用），
        # 没有再退回「模板」（references/templates/，本地学习产物）。
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sp = os.path.join(base, 'references', 'profiles', f'{temp_name}.json')
        tp = os.path.join(TEMPLATE_DIR, f'{temp_name}.json')
        if os.path.exists(sp):
            try:
                from fit_convert_by_template import _spec_to_template
                t = _spec_to_template(json.load(open(sp, encoding='utf-8')))
            except Exception as e:
                r.sec('§11 目标平台规范一致性')
                r.fail(f'规范读取失败: {sp}', str(e))
                return
        elif os.path.exists(tp):
            t = json.load(open(tp, encoding='utf-8'))
        else:
            r.sec('§11 目标平台规范一致性')
            r.fail(f'既无规范也无模板: {temp_name}',
                   '先学真机文件：fit_learn_template.py，再精炼：fit_distill_spec.py')
            return
        r.sec(f'§11 目标平台规范一致性（{temp_name} / {t.get("_note","")}）')
        pmap = self.prof
        # header
        r.check(self.f.header['protocol'] == t['header']['protocol_version'],
                f'protocol_version = {self.f.header["protocol"]}'
                f'（模板 {t["header"]["protocol_version"]}）',
                f'protocol_version 应为 {t["header"]["protocol_version"]}，'
                f'实际 {self.f.header["protocol"]}')
        r.check(self.f.header['profile_version'] == t['header']['profile_version'],
                f'profile_version = {self.f.header["profile_version"]}'
                f'（模板 {t["header"]["profile_version"]}）',
                f'profile_version 应为 {t["header"]["profile_version"]}，'
                f'实际 {self.f.header["profile_version"]}')
        # 消息集合
        # ⚠️ 缺失消息分两种，绝不能一律判 FAIL（历史误报）：
        #    ①源文件本身就没有这类数据（跨品牌转换必然发生，如高驰→佳明时的
        #      佳明私有消息 gpsMetadata/g=160 等）→ INFO，不是转换的错；
        #    ②源文件有、产物却丢了 → FAIL，这才是真丢数据。
        want = set(int(g) for g in t['messages'])
        got = set(self.f.global_counts())
        missing = want - got
        extra = got - want
        src_have = None
        if src_path and os.path.exists(src_path):
            try:
                src_have = set(FitFile(src_path).global_counts())
            except Exception:
                src_have = None
        # 先统一算出两个集合，避免分支里定义、分支外引用（曾因此崩过）
        lost = sorted(g for g in missing if src_have and g in src_have)
        absent = sorted(g for g in missing if not (src_have and g in src_have))
        if not missing:
            r.ok(f'模板要求的消息种类齐全（{len(want)} 种）')
        elif lost:
            r.fail(f'模板要求的消息种类齐全（{len(want)} 种）',
                   f'源文件有但产物丢失的消息: {lost} —— 转换过程丢数据')
        else:
            r.ok(f'模板要求的消息种类齐全（{len(want)} 种）',
                 f'缺 {len(absent)} 种模板私有消息 {absent[:8]}'
                 f'{"..." if len(absent) > 8 else ""}，'
                 f'但源文件同缺 → 源无此类数据，非转换丢失')
        if absent:
            r.info(f'跨品牌必然缺失 {len(absent)} 种消息（源文件无对应数据，'
                   f'无法映射；这些消息已从产物中省略而非填哨兵占位）')
        if extra:
            r.warn(f'多出模板未用的消息 {sorted(extra)}',
                   '目标平台若做消息白名单校验，多余消息可能导致异常')
        else:
            r.ok('无多余消息（严格白名单）')
        # 逐消息布局
        for gs, mi in t['messages'].items():
            g = int(gs)
            if g not in got:
                continue
            tlays = []
            for lay in mi['layouts']:
                tlays.append((
                    tuple((f['num'], f['size'], f['base_type']) for f in lay['fields']),
                    tuple((f['num'], f['size'], lay['dev_fields'][i]['ref_index'])
                          for i, f in enumerate(lay['dev_fields'])) if lay['dev_fields'] else (),
                ))
            nlays = self.f.layouts(g)
            glays = [dd.signature() for dd in nlays]
            if len(tlays) > 1:
                r.check(len(glays) == len(tlays),
                        f'g={g}({mi["name"]}) 布局数 {len(glays)} == 模板 {len(tlays)}（渐进式）',
                        f'g={g}({mi["name"]}) 布局数 {len(glays)} != 模板 {len(tlays)}'
                        f' —— 渐进式布局节奏未复刻')
                hit = sum(1 for x in tlays if x in glays)
                if hit != len(tlays):
                    miss = [x for x in tlays if x not in glays]
                    r.fail(f'g={g} 全部 {len(tlays)} 种布局与模板逐位一致',
                           f'有 {len(miss)} 种布局不匹配，首个不匹配字段序列 '
                           f'{[f[0] for f in miss[0][0]]}')
                else:
                    r.ok(f'g={g} 全部 {len(tlays)} 种布局与模板逐位一致')
            else:
                if tlays and tlays[0] not in glays:
                    r.fail(f'g={g}({mi["name"]}) 布局与模板逐位一致',
                           f'产物 {[f[0] for f in glays[0]]} vs '
                           f'模板 {[f[0] for f in tlays[0][0]]}')
                else:
                    r.ok(f'g={g}({mi["name"]}) 布局与模板逐位一致')
        # ── 布局一致 ≠ 值完整：检查「模板必填字段产物却留哨兵」 ──────────────
        # 教训（2026-09-18）：产物 fileId 布局与模板逐位一致，但 f8(productName)
        # 填的是哨兵，而真机有值 → 布局检查完全抓不到这类"空洞"。
        # 这里对**单条消息**（如 fileId/deviceInfo/activity/session）做值级核对：
        # 模板里该字段有值 → 产物同位置不应是哨兵。
        single_msg = t.get('single_message_values') or {}
        for gs, fields in single_msg.items():
            g = int(gs)
            got_msgs = self.f.by_global(g)
            if not got_msgs:
                continue
            m = got_msgs[0]
            hollow = []
            for fnum_s, tval in fields.items():
                fnum = int(fnum_s)
                # 模板该字段本身是哨兵/空 → 跳过（不要求产物有值）
                if tval is None or tval == '':
                    continue
                # 产物该字段必须存在且非哨兵
                if fnum not in m.raw:
                    hollow.append((fnum, tval, '字段缺失'))
                    continue
                v = self.f.value(m, fnum, self.prof)
                if v is None:
                    hollow.append((fnum, tval, '值为哨兵'))
            fname = t['messages'].get(str(g), {}).get('name', '?')
            if hollow:
                desc = '; '.join(f'f{n}(模板={tv!r} → 产物{d})'
                                 for n, tv, d in hollow[:5])
                r.fail(f'g={g}({fname}) 模板有值的字段产物未填',
                       f'{len(hollow)} 个字段为空: {desc}')
            else:
                r.ok(f'g={g}({fname}) 模板有值的身份/单条字段均已填充'
                     f'（{len(fields)} 项）')
        # 开发者字段
        tdev = t.get('developer_data', [])
        n206 = [m for m in self.f.msgs if m.g == 206]
        t206 = [d for d in tdev if d['global'] == 206]
        if t206:
            r.check(len(n206) == len(t206),
                    f'fieldDescription 声明次数 {len(n206)} == 模板 {len(t206)}',
                    f'fieldDescription 声明 {len(n206)} 次，模板为 {len(t206)} 次')

    # -- 运行 --------------------------------------------------------------
    def run(self, src=None, temp=None):
        self.head()
        self.structure()
        self.type_codes()
        self.sentinels()
        self.ranges()
        self.order()
        self.dev_fields()
        self.timestamps()
        self.consistency()
        if src:
            self.vs_source(src)
        if temp:
            self.vs_template(temp, src_path=src)
        return self.r


def _crc16(data):
    from fit_lib import crc16
    return crc16(data)


def _subfield_allows(prof, g, num, base_type):
    """官方字段的 sub_field 是否允许该字段号使用 base_type。"""
    fld = prof.field(g, num)
    if not fld:
        return False
    for sf in fld.get('sub_fields') or []:
        if TYPE_IDS.get(sf.get('base_type')) == base_type:
            return True
    return False


def data_reserved(f, dd):
    """读 DEF 的 reserved 字节。"""
    return f.data[dd.offset + 1]


def _msg_order(f, limit=None):
    out = []
    for m in f.msgs:
        if m.g not in out:
            out.append(m.g)
    return out[:limit] if limit else out


# ---------------------------------------------------------------------------
# 兼容旧 profile（无 base_type 字段时的 msg_num_by_num 辅助）
# ---------------------------------------------------------------------------

def _patch_profile(prof):
    if not hasattr(prof, 'msg_num_by_num'):
        prof.msg_num_by_num = lambda g: g if str(g) in prof.messages else None


def main():
    ap = argparse.ArgumentParser(description='FIT 规范校验器（通用）')
    ap.add_argument('fit')
    ap.add_argument('--src', help='源文件，做逐点一致性比对')
    ap.add_argument('--temp', help='目标平台模板名（references/templates/<name>.json）')
    ap.add_argument('--quick', action='store_true', help='跳过数值合理性/一致性检查')
    ap.add_argument('--json', help='把结果同时写到指定 JSON 文件')
    a = ap.parse_args()

    prof = Profile()
    _patch_profile(prof)
    ck = Checker(a.fit, prof, quick=a.quick)
    rep = ck.run(src=a.src, temp=a.temp)

    ok, c = rep.verdict()
    print()
    print('=' * 78)
    print(f'  汇总：PASS {c["PASS"]} / FAIL {c["FAIL"]} / WARN {c["WARN"]} / '
          f'INFO {c["INFO"]}')
    print(f'  结论：{"✅ 全部符合 FIT 规范" if ok else "❌ 存在规范违规，必须修复"}')
    print('=' * 78)

    if a.json:
        json.dump({'path': a.fit, 'verdict': ok, 'counts': c,
                   'rows': [{'level': l, 'section': s, 'item': i, 'detail': d}
                            for l, s, i, d in rep.rows]},
                  open(a.json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
        print(f'结果已写入 {a.json}')

    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
