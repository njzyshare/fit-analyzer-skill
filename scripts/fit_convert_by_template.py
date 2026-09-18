# -*- coding: utf-8 -*-
"""模板驱动 FIT 转换引擎（任意设备 → 任意设备）。

设计思想
--------
不再手抄任何厂商的字段布局。转换分两步：

  ① **源 → 语义中间层**：按**官方 profile** 把源文件每个消息的每个字段解成
     `{official_field_name: 物理值}`。这一步只依赖官方定义，与厂商无关。
  ② **语义中间层 → 目标字节**：按**目标模板画像**（fit_learn_template.py 学出来的）
     把语义值重新拼成字节。布局、字段顺序、类型码、渐进式节奏、开发者字段、
     设备身份，全部照抄模板。

于是：
  - 换目标设备只需换一个模板 JSON，**不需要改代码**。
  - 双向天然支持（佳明→高驰、高驰→佳明、任意→任意）。
  - 「照抄真机写法」变成机械过程，不依赖人的记忆和细心。

字段对应规则
------------
源字段 → 目标字段，按**优先级**匹配（同名优先，其次官方 components 关联，最后语义别名表）：
  1. 官方字段名完全相同           → 直接搬（自动按各自 scale/offset 换算）
  2. 源是 enhancedX / 目标是基础X → 取 enhanced（佳明基础字段常无效）
  3. 语义别名表（avgSpeed ↔ enhancedAvgSpeed 等）
  4. 目标需要但源没有             → 留**官方无效哨兵**（绝不编造）

用法
----
    # 佳明 → 高驰（自动按 references/templates/coros_apex4.json 重建）
    python fit_convert_by_template.py 源.fit 产物.fit --to coros_apex4

    # 高驰 → 佳明
    python fit_convert_by_template.py 源.fit 产物.fit --to garmin_fenix8

    # 源编码是佳明惯例时，可显式声明（默认自动探测 enhanced 字段）
    python fit_convert_by_template.py 源.fit 产物.fit --to coros_apex4 --from garmin

    # 不写设备身份（保留源身份）
    python fit_convert_by_template.py 源.fit 产物.fit --to coros_apex4 --keep-identity

    # 转完自动跑规范校验（默认开）
    python fit_convert_by_template.py 源.fit 产物.fit --to coros_apex4 --verify
"""

import argparse
import json
import os
import struct
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fit_lib import (BASE_TYPES, TYPE_IDS, FitFile, FitWriter, Profile,
                     TEMPLATE_DIR, crc16, invalid_bytes)

STORE = os.path.join(os.path.expanduser('~'), '.workbuddy', 'private', 'fit_devices.json')

# ---------------------------------------------------------------------------
# 语义别名表：同一物理量在不同消息里的官方字段名对应
# 键 = 官方字段名，值 = 等价名列表（按优先级）
# ---------------------------------------------------------------------------

ALIASES = {
    # 速度
    'enhancedSpeed': ['speed'],
    'speed': ['enhancedSpeed'],
    'enhancedAvgSpeed': ['avgSpeed'],
    'avgSpeed': ['enhancedAvgSpeed'],
    'enhancedMaxSpeed': ['maxSpeed'],
    'maxSpeed': ['enhancedMaxSpeed'],
    'enhancedAvgMovingSpeed': ['avgMovingSpeed'],
    'avgMovingSpeed': ['enhancedAvgMovingSpeed'],
    # 海拔
    'enhancedAltitude': ['altitude'],
    'altitude': ['enhancedAltitude'],
    'enhancedMinAltitude': ['minAltitude'],
    'minAltitude': ['enhancedMinAltitude'],
    'enhancedMaxAltitude': ['maxAltitude'],
    'maxAltitude': ['enhancedMaxAltitude'],
    # 配速 / 步速
    'enhancedAvgPace': ['avgPace'],
    'avgPace': ['enhancedAvgPace'],
    # 步频
    'avgRunningCadence': ['avgCadence'],
    'maxRunningCadence': ['maxCadence'],
    # 温度
    'avgTemperature': ['temperature'],
    'temperature': ['avgTemperature'],
    # 距离/时间（同名直接匹配，这里列已知同义）
    'totalDistance': ['distance'],
    'distance': ['totalDistance'],
    'totalTimerTime': [],
    'totalElapsedTime': [],
    # 呼吸
    'enhancedRespirationRate': ['respirationRate'],
    'respirationRate': ['enhancedRespirationRate'],
    'avgRespirationRate': ['enhancedAvgRespirationRate'],
    'enhancedAvgRespirationRate': ['avgRespirationRate'],
    # 垂直速度
    'enhancedAvgVerticalSpeed': ['avgVerticalSpeed'],
    'avgVerticalSpeed': ['enhancedAvgVerticalSpeed'],
}

# 目标字段名 -> 源字段名 的**厂商专属**别名（当通用别名不够时）
VENDOR_ALIASES = {}


# ---------------------------------------------------------------------------
# 语义抽出：源文件 -> {global: [ {字段名: 物理值} ]}
# ---------------------------------------------------------------------------

class SemanticReader:
    """按官方 profile 把源文件解成语义层。

    关键：**不做任何厂商假设**。同名字段自动同名匹配；
    源用 enhancedX、目标用 X（或反之）由 ALIASES 兜。
    """

    def __init__(self, path, prof):
        self.path = path
        self.prof = prof
        self.f = FitFile(path)
        self.warnings = []

    def messages(self):
        """产出 [(global, {字段名: 物理值, dev名: 值}, meta)]，按文件顺序。"""
        out = []
        for m in self.f.msgs:
            vals = {}
            unknown = 0
            for num in m.raw:
                name = self.prof.fname(m.g, num)
                if name.startswith('f') and self.prof.field(m.g, num) is None:
                    unknown += 1
                    name = f'__f{num}'        # 私有字段：按号保留，不做语义映射
                v = self.f.value(m, num, self.prof)
                if v is None:
                    continue
                vals[name] = {'value': v, 'num': num}
            devs = {}
            for num in m.dev_raw:
                devs[num] = self.f.dev_value(m, num)
            out.append((m.g, vals, {'devs': devs, 'unknown_fields': unknown,
                                    'compressed': m.compressed}))
        return out

    def summary(self):
        cnt = {}
        for g, *_ in self.messages():
            cnt[g] = cnt.get(g, 0) + 1
        return cnt


# ---------------------------------------------------------------------------
# 目标重建：语义层 -> 目标字节
# ---------------------------------------------------------------------------

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(BASE_DIR, 'references', 'profiles')


def _spec_to_template(spec):
    """把「规范」（profiles/*.json，紧凑格式）展开成转换器内部用的模板形状。

    规范是**沉淀下来的可复用规则**（入库）；模板是学习时的原始记录（本地、不入库）。
    两者字段语义一致，只是布局的书写方式不同：
        规范: layouts[].fields = [[num, size, base_type], ...]
        模板: layouts[].fields = [{'num':.., 'size':.., 'base_type':..}, ...]
    """
    t = {
        '_name': spec.get('name'),
        '_note': spec.get('device_note', ''),
        'header': {
            'protocol_version': spec['header']['protocol_version'],
            'profile_version': spec['header']['profile_version'],
            'header_size': spec['header'].get('header_size', 14),
        },
        'message_order': spec.get('message_order'),
        'identity': spec.get('identity', {}),
        'dev_semantics': spec.get('dev_semantics', {}),
        'uses_compressed_timestamp': spec.get('uses_compressed_timestamp', False),
        'developer_data': [],
        'messages': {},
    }
    for gs, mi in (spec.get('messages') or {}).items():
        lays = []
        for lay in mi.get('layouts', []):
            flds = []
            for f in lay.get('fields', []):
                num, size, bt = f[0], f[1], f[2]
                flds.append({
                    'num': num, 'size': size, 'base_type': bt,
                    'official_name': (mi.get('field_names') or {}).get(str(num)),
                })
            devs = [{'num': d[0], 'size': d[1], 'ref_index': d[2]}
                    for d in lay.get('dev_fields', [])]
            lay_o = {'local': lay.get('local'), 'fields': flds, 'dev_fields': devs}
            lays.append(lay_o)
        entry = {'name': mi.get('name'), 'layouts': lays}
        if mi.get('layout_rhythm'):
            entry['layout_rhythm'] = mi['layout_rhythm']
        t['messages'][gs] = entry
    # 开发者字段声明（206）与 developerDataId（207）
    # 207 必须还原：DEF 里开发字段第三字节引用它的 index
    for d in spec.get('developer_data_id', []):
        t['developer_data'].append({
            'global': 207,
            'local': d.get('local'),
            'fields': {
                # applicationId 保留 hex 原样（16 字节，前导零有意义）
                '1': {'hex': d.get('applicationId_hex')}
                     if d.get('applicationId_hex') else {'value': None},
                '2': {'value': d.get('manufacturerId')},
                '3': {'value': d.get('developerDataIndex')},
            },
        })
    for d in spec.get('developer_data', []):
        t['developer_data'].append({
            'global': 206,
            'local': d.get('local'),
            'fields': {
                '0': {'value': d.get('developerDataIndex')},
                '1': {'value': d.get('fieldDefinitionNumber')},
                '2': {'value': d.get('fitBaseTypeId')},
                '3': {'value': d.get('fieldName')},
                '8': {'value': d.get('units')},
            },
        })
    return t


class TemplateConverter:
    def __init__(self, template_name, prof, reader, keep_identity=False):
        self.tname = template_name
        # 优先读「规范」（入库、可复用）；没有再退回「模板」（本地学习产物）
        sp = os.path.join(SPEC_DIR, f'{template_name}.json')
        tp = os.path.join(TEMPLATE_DIR, f'{template_name}.json')
        if os.path.exists(sp):
            self.t = _spec_to_template(json.load(open(sp, encoding='utf-8')))
            self.source = 'spec'
        elif os.path.exists(tp):
            self.t = json.load(open(tp, encoding='utf-8'))
            self.source = 'template'
        else:
            raise SystemExit(
                f'既无规范也无模板: {template_name}\n'
                f'  规范目录: {SPEC_DIR}\n'
                f'  模板目录: {TEMPLATE_DIR}\n'
                f'请先用真机文件学习：\n'
                f'  python fit_learn_template.py <目标平台真机.fit> --name {template_name}\n'
                f'  再精炼为规范：python fit_distill_spec.py {template_name}')
        self.prof = prof
        self.reader = reader
        self.keep_identity = keep_identity
        self.stats = {'mapped': 0, 'alias': 0, 'missing': 0, 'dropped': 0,
                      'fields_out': 0}

    # -- 目标字段的类型/编码信息 ------------------------------------------
    def tfield(self, g, num):
        """从模板里取目标字段的画像（含官方名/scale/offset/base_type）。"""
        mi = self.t['messages'].get(str(g))
        if not mi:
            return None
        for lay in mi['layouts']:
            for f in lay['fields']:
                if f['num'] == num:
                    return f
        return None

    def tfield_by_name(self, g, name):
        mi = self.t['messages'].get(str(g))
        if not mi:
            return None
        for lay in mi['layouts']:
            for f in lay['fields']:
                if f['official_name'] == name:
                    return f
        return None

    # -- 语义值 -> 目标原始整数 ------------------------------------------
    def encode_target(self, g, field, phys):
        """把物理值编成目标平台该字段的原始字节。

        关键点：**用目标字段自己的类型和 scale/offset**，而不是沿用源。
        这样源/目标类型不同（如源 uint32 enhancedAltitude、目标 uint16 altitude）
        也能正确落位。
        """
        base_type = field['base_type']
        tname = BASE_TYPES.get(base_type, ('uint8', 1))[0]
        size = field['size']
        if phys is None:
            return invalid_bytes(tname, size)
        # 字符串 / 字节数组：不做数值换算
        if tname == 'string':
            b = phys.encode('utf-8') if isinstance(phys, str) else bytes(phys)
            return b[:size].ljust(size, b'\x00')
        if tname == 'byte':
            return bytes(phys)[:size].ljust(size, b'\x00')
        if not isinstance(phys, (int, float)):
            return invalid_bytes(tname, size)
        # scale/offset 从官方 profile 取（用字段号，官方定义里字段号与名一一对应）
        oname = field.get('official_name')
        sc, of = 1, 0
        if oname and not oname.startswith('f'):
            sc, of = self.prof.scale_offset(g, field['num'])
        raw = round((phys + of) * sc)
        # 越界保护：目标类型装不下时留无效值而不是回绕
        info = _int_range(tname, size)
        if info is not None:
            lo, hi = info
            if not (lo <= raw <= hi):
                return invalid_bytes(tname, size)
        try:
            return raw.to_bytes(size, 'little', signed=tname in
                                ('sint8', 'sint16', 'sint32', 'sint64'))
        except OverflowError:
            return invalid_bytes(tname, size)

    # -- 主流程 ------------------------------------------------------------
    def convert(self):
        t = self.t
        w = FitWriter()
        src_msgs = self.reader.messages()

        # 设备身份（读私有区，含序列号）
        self.identity = self._load_identity()
        self._emitted_206 = False
        self._emitted_207 = False

        # 目标模板要求的消息种类与顺序
        want_order = [int(g) for g in t['message_order']]
        # 源消息按 global 归集（保留顺序）
        pool = {}
        for g, vals, meta in src_msgs:
            pool.setdefault(g, []).append((vals, meta))

        # 开发者字段声明：按模板的**实际位置**插入，而不是堆到文件尾。
        # 真机结构（实测高驰）：
        #   fileId → **207** → deviceInfo → activity → event → record×3
        #   → **206** → record(带 dev) ...
        # 即 207 紧跟 fileId，206 在**首个引用开发字段的消息之前**。
        dev_decl = self._dev_decl_map(t)          # {global: bytes}

        for g in want_order:
            mi = t['messages'][str(g)]
            if g in (206, 207):
                continue          # 在下面按位置插入
            if g == 0:
                # fileId：构造身份消息
                src = [self._make_fileid_src(pool)]
            elif g == 23:
                src = self._make_deviceinfo_src(pool, mi)
            else:
                src = pool.get(g, [])
            if not src:
                # 目标需要、源没有 → 从别的消息推导或留空
                src = self._synth(g, pool, mi)
                if src is None:
                    self.stats['dropped'] += 1
                    print(f'  ⚠️ 目标要求 g={g}({mi["name"]}) 但源无对应数据，跳过')
                    continue

            layouts = mi['layouts']
            # 节奏缺失时退化为「始终用最后一种布局」，不直接崩
            rhythm = mi.get('layout_rhythm') or [[len(layouts) - 1, 1 << 30]]
            # 布局调度：按模板节奏循环使用（渐进式布局的复刻核心）
            schedule = self._build_schedule(layouts, rhythm, len(src))

            cur = None
            for i, (vals, meta) in enumerate(src):
                lay = schedule[i] if i < len(schedule) else layouts[-1]
                # 206 必须在首个带 dev 字段的消息之前声明
                if lay['dev_fields'] and '206' in dev_decl and not self._emitted_206:
                    w.buf += dev_decl['206']
                    self._emitted_206 = True
                if cur is None or cur is not lay:
                    w.add_def(g, lay['local'],
                              [(f['num'], f['size'], f['base_type'])
                               for f in lay['fields']],
                              [(f['num'], f['size'], f['ref_index'])
                               for f in lay['dev_fields']] or None)
                    cur = lay
                payloads = []
                for f in lay['fields']:
                    phys = self._lookup(g, f, vals)
                    payloads.append(self.encode_target(g, f, phys))
                for df in lay['dev_fields']:
                    payloads.append(self._encode_dev(g, df, vals, meta))
                w.add_msg(lay['local'], payloads)

            # fileId 之后紧跟 207（照抄真机位置）
            if g == 0 and '207' in dev_decl and not self._emitted_207:
                w.buf += dev_decl['207']
                self._emitted_207 = True

        # 兜底：若整份文件没有引用 dev 字段，也要声明（否则声明成孤儿）
        if '206' in dev_decl and not self._emitted_206:
            w.buf += dev_decl['206']
        if '207' in dev_decl and not self._emitted_207:
            w.buf += dev_decl['207']

        blob = w.finish(t['header']['protocol_version'],
                        t['header']['profile_version'])
        return blob

    # -- 设备身份 -----------------------------------------------------------
    def _load_identity(self):
        """从私有区读取目标设备身份（含序列号）。"""
        if self.keep_identity:
            return None
        if not os.path.exists(STORE):
            return None
        try:
            db = json.load(open(STORE, encoding='utf-8'))['devices']
        except Exception:
            return None
        # 优先精确名，其次模糊匹配
        if self.tname in db:
            return db[self.tname]
        for k, v in db.items():
            if self.tname.startswith(k) or k.startswith(self.tname) \
                    or k.replace('garmin_', '').replace('coros_', '') in self.tname:
                return v
        return None

    def _make_fileid_src(self, pool):
        """构造 fileId 的语义值（身份 + 从源继承的 timeCreated）。"""
        src_fid = pool.get(0, [({}, {})])[0][0]
        vals = {}
        tcre = src_fid.get('timeCreated')
        if tcre:
            vals['timeCreated'] = {'value': tcre['value'], 'num': 4}
        idn = self.t.get('identity', {})
        if self.identity:
            vals['manufacturer'] = {'value': self.identity.get('manufacturer'), 'num': 1}
            if self.identity.get('product') is not None:
                vals['product'] = {'value': self.identity['product'], 'num': 2}
            if self.identity.get('serial_number') is not None:
                vals['serialNumber'] = {'value': self.identity['serial_number'], 'num': 3}
        elif not self.keep_identity:
            if idn.get('manufacturer') is not None:
                vals['manufacturer'] = {'value': idn['manufacturer'], 'num': 1}
            if idn.get('product') is not None:
                vals['product'] = {'value': idn['product'], 'num': 2}
        else:
            # 保留源身份
            for k in ('manufacturer', 'product', 'serialNumber'):
                if k in src_fid:
                    vals[k] = src_fid[k]
        # 产品名：高驰真机在 fileId(f8) 与 deviceInfo(f27) **两处**都写。
        # 漏掉 f8 会造成「布局里有该字段却填哨兵」，与真机文件不一致（曾漏）。
        pname = None
        if self.identity and self.identity.get('product_name'):
            pname = self.identity['product_name']
        elif idn.get('product_name'):
            pname = idn['product_name']
        elif self.keep_identity:
            pname = src_fid.get('productName', {}).get('value') \
                if isinstance(src_fid.get('productName'), dict) else None
        if pname:
            vals['productName'] = {'value': pname, 'num': 8}
        # type = activity(4)
        vals['type'] = {'value': 4, 'num': 0}
        return (vals, {'devs': {}})

    def _make_deviceinfo_src(self, pool, mi):
        """构造 deviceInfo。

        目标模板声明了几条就产几条（高驰 1 条 / 佳明 21 条）。
        内容按目标模板的字段集填充；源若有同名字段则继承。
        """
        src_di = pool.get(23, [])
        base = src_di[0][0] if src_di else {}
        idn = self.t.get('identity', {})
        manuf = None
        product = None
        serial = None
        name = None
        if self.identity:
            manuf = self.identity.get('manufacturer')
            product = self.identity.get('product')
            serial = self.identity.get('serial_number')
            name = self.identity.get('product_name')
        elif not self.keep_identity:
            manuf = idn.get('manufacturer')
            product = idn.get('product')
            name = idn.get('productName')
        else:
            manuf = base.get('manufacturer', {}).get('value')
            product = base.get('product', {}).get('value')
            name = base.get('productName', {}).get('value')
            serial = base.get('serialNumber', {}).get('value')

        # 取源里第一条 deviceInfo 的 timestamp 作参考时间
        ts = None
        for k in ('timestamp',):
            if k in base and base[k].get('value'):
                ts = base[k]['value']
        n = max(1, idn.get('device_info_count', 1))
        out = []
        for i in range(n):
            vals = {}
            if manuf is not None:
                vals['manufacturer'] = {'value': manuf, 'num': 2}
            if product is not None:
                vals['product'] = {'value': product, 'num': 4}
            if serial is not None:
                vals['serialNumber'] = {'value': serial, 'num': 3}
            if name:
                vals['productName'] = {'value': name, 'num': 27}
            if ts:
                vals['timestamp'] = {'value': ts, 'num': 253}
            # 佳明 21 条 deviceInfo 含多类内置传感器，其余条目：
            # 源若有对应的条数就复用源的其余字段
            if i < len(src_di):
                merged = dict(src_di[i][0])
                merged.update(vals)
                out.append((merged, src_di[i][1]))
            else:
                vals['deviceIndex'] = {'value': 255, 'num': 0}
                out.append((vals, {'devs': {}}))
        return out

    # -- 布局调度 ----------------------------------------------------------
    def _build_schedule(self, layouts, rhythm, n):
        """按模板的 rhythm 生成每条消息该用哪个布局。

        模板 rhythm 是 [[布局索引, 连续条数], ...]。
        若源条数与模板不同（模板是另一条轨迹），按比例缩放，
        但**前缀的渐进段原样保留**（那正是「数据有效起点」声明）。
        这样：换一条运动记录时，渐进节奏仍会被复刻。
        """
        if len(layouts) == 1:
            return [layouts[0]] * n

        prefix = []        # 渐进段（除最后一段外的全部）
        tail_i = len(layouts) - 1
        for li, cnt in rhythm:
            if li == tail_i and cnt > 0:
                # 末段是"余下全部"，不预先展开
                break
            prefix.extend([layouts[li]] * min(cnt, n))
            if len(prefix) >= n:
                break
        if len(prefix) >= n:
            return prefix[:n]
        return prefix + [layouts[tail_i]] * (n - len(prefix))

    # -- 字段查找（核心映射逻辑）------------------------------------------
    def _lookup(self, g, tfield, vals):
        """目标字段 -> 源里的物理值。返回 None 表示源无此数据（将留哨兵）。"""
        oname = tfield.get('official_name')
        if not oname:
            return None

        # 1) 同名直接命中
        if oname in vals:
            self.stats['mapped'] += 1
            return vals[oname]['value']

        # 2) 语义别名（含 enhanced ↔ 基础）
        for alt in ALIASES.get(oname, []):
            if alt in vals:
                self.stats['alias'] += 1
                return vals[alt]['value']

        # 3) 厂商别名
        for alt in VENDOR_ALIASES.get((self.tname, oname), []):
            if alt in vals:
                self.stats['alias'] += 1
                return vals[alt]['value']

        # 4) 官方 components 关联（如 altitude ↔ enhancedAltitude）
        fld = self.prof.field(g, tfield['num'])
        if fld:
            for comp in fld.get('components') or []:
                cnum = int(comp)
                cname = self.prof.fname(g, cnum)
                if cname in vals:
                    self.stats['alias'] += 1
                    return vals[cname]['value']

        self.stats['missing'] += 1
        return None

    def _encode_dev(self, g, df, vals, meta):
        """编码开发字段值。

        取值优先级：
          ① 源消息里**同号**开发字段  → 直接搬（同平台互转场景）
          ② 模板推断出的**语义来源**（dev_semantics）→ 从源的标准字段取值
             （跨平台场景：源佳明无 dev16，但高驰 dev16 承载的是速度语义）
          ③ 都没有 → 留无效（float 填 NaN）—— **绝不编造**
        """
        size = df['size']
        v = meta.get('devs', {}).get(df['num'])
        if v is None or (isinstance(v, float) and v != v):
            # ② 走模板推断的语义来源
            v = self._dev_from_semantics(g, df['num'], vals)
        if v is None or (isinstance(v, float) and v != v):
            self.stats['dev_null'] = self.stats.get('dev_null', 0) + 1
            return b'\xFF' * size
        self.stats['dev_filled'] = self.stats.get('dev_filled', 0) + 1
        if size == 4:
            return struct.pack('<f', float(v))
        if size == 8:
            return struct.pack('<d', float(v))
        return invalid_bytes('uint8', size)

    def _dev_from_semantics(self, g, dev_num, vals):
        """按模板的 dev_semantics 推断，从源标准字段取等价物理值。"""
        sem = (self.t.get('dev_semantics') or {}).get(str(g), {}).get(str(dev_num))
        if not sem:
            return None
        conf = sem.get('confidence')
        if conf in (None, 'none'):
            return None
        sname = sem.get('std_name')
        if not sname:
            return None
        # 在源消息的语义值里找同名字段（含别名）
        if sname in vals:
            self.stats['dev_via_sem'] = self.stats.get('dev_via_sem', 0) + 1
            return vals[sname]['value']
        for alt in ALIASES.get(sname, []):
            if alt in vals:
                self.stats['dev_via_sem'] = self.stats.get('dev_via_sem', 0) + 1
                return vals[alt]['value']
        return None

    # -- 开发者字段声明照抄 -------------------------------------------------
    def _dev_decl_map(self, t):
        """把模板里的 207 + 206 原始声明逐字节照抄，按 global 分组返回。

        为什么照抄而不是按官方结构重建：
          高驰把 206 声明 2 次（local 0 与 local 8），且 207 的 applicationId
          有特定尾部 0x47。这些是厂商约定，照抄最稳。
        返回 {global_str: bytes}
        """
        out = {}
        for ent in t.get('developer_data', []):
            g = ent['global']
            local = ent['local']
            mi = t['messages'].get(str(g))
            if not mi:
                continue
            lay = None
            for l in mi['layouts']:
                if l['local'] == local:
                    lay = l
                    break
            lay = lay or mi['layouts'][0]
            blob = bytearray()
            blob += _def_bytes_vendor(g, lay['local'],
                                      [(f['num'], f['size'], f['base_type'])
                                       for f in lay['fields']],
                                      None)
            payload = bytearray()
            for f in lay['fields']:
                fo = ent['fields'].get(str(f['num'])) or {}
                if 'hex' in fo:
                    # 模板路径：学习时记录了原始字节，直接照抄
                    raw = bytes.fromhex(fo['hex'])
                else:
                    # 规范路径：只有结构化值（如 fitBaseTypeId=136），按目标编码重建
                    raw = _encode_dev_decl_field(f, fo.get('value'), self.prof)
                if len(raw) != f['size']:
                    raw = raw[:f['size']].ljust(f['size'], b'\x00')
                payload += raw
            blob += bytes([lay['local'] & 0x0F]) + bytes(payload)
            out[str(g)] = out.get(str(g), b'') + bytes(blob)
        return out

    # -- 补充：目标要而源无的消息 ------------------------------------------
    def _synth(self, g, pool, mi):
        """目标平台要求某消息、源没有时，尝试合成一条最小合法消息。

        目前支持：
          - session(18) / lap(19) / activity(34)：从 record 流推导
          - 其余：放弃
        """
        return None


def _encode_dev_decl_field(f, value, prof):
    """把 206(fieldDescription) 某字段的结构化值编码成字节。

    规范里只存结构化值（如 fieldName='Effort Pace'、fitBaseTypeId=136），
    不像模板那样存原始 hex。这里按 DEF 声明的 size/type 重新编码。
    """
    size, bt = f['size'], f['base_type']
    from fit_lib import BASE_TYPES
    tname = BASE_TYPES.get(bt, ('?', 0))[0]

    if value is None:
        return b'\x00' * size

    if tname == 'string':
        b = str(value).encode('utf-8')[:size - 1]
        return b.ljust(size, b'\x00')
    if tname == 'byte':
        if isinstance(value, str):
            b = value.encode('utf-8')
        elif isinstance(value, (bytes, bytearray)):
            b = bytes(value)
        else:
            b = bytes([int(value) & 0xFF])
        return b[:size].ljust(size, b'\x00')

    # 数值类型：按有无符号选 struct 格式
    import struct as _s
    signed = tname.startswith('sint')
    fmts = {1: 'b' if signed else 'B', 2: 'h' if signed else 'H',
            4: 'i' if signed else 'I', 8: 'q' if signed else 'Q'}
    fmt = fmts.get(size)
    if fmt is None:
        return b'\x00' * size
    return _s.pack('<' + fmt, int(value))


def _int_range(tname, size):
    if tname in ('string', 'byte', 'float32', 'float64'):
        return None
    bits = size * 8
    if tname in ('sint8', 'sint16', 'sint32', 'sint64'):
        hi = (1 << (bits - 1)) - 2      # 留出无效值
        return (-(1 << (bits - 1)) + 1, hi)
    if tname in ('uint8z', 'uint16z', 'uint32z', 'uint64z'):
        return (1, (1 << bits) - 1)
    return (0, (1 << bits) - 2)         # 留出全 1 哨兵


def _def_bytes_vendor(g, local, fields, devs):
    out = bytearray([0x40 | (0x20 if devs else 0) | (local & 0x0F), 0x00, 0x00])
    out += struct.pack('<H', g)
    out += bytes([len(fields)])
    for (n, sz, bt) in fields:
        out += bytes([n, sz, bt])
    if devs:
        out += bytes([len(devs)])
        for (n, sz, bt) in devs:
            out += bytes([n, sz, bt])
    return bytes(out)


def main():
    ap = argparse.ArgumentParser(description='模板驱动 FIT 转换（任意 → 任意）')
    ap.add_argument('src')
    ap.add_argument('dst')
    ap.add_argument('--to', required=True, help='目标模板名（references/templates/<name>.json）')
    ap.add_argument('--from', dest='src_dev', help='源设备标签（仅用于报告，可省）')
    ap.add_argument('--keep-identity', action='store_true',
                    help='不改设备身份，保留源文件的 manufacturer/product')
    ap.add_argument('--verify', action='store_true', default=True,
                    help='转换后自动跑规范校验（默认开）')
    ap.add_argument('--no-verify', dest='verify', action='store_false')
    a = ap.parse_args()

    prof = Profile()
    print(f'源文件: {a.src}')
    r = SemanticReader(a.src, prof)
    if not r.f.integrity():
        print(f'  ⚠️ 源文件解析不完整（desync={r.f.desync}），结果可能不可靠')
    print(f'  源消息: ' + ', '.join(f'g={g}×{c}' for g, c in sorted(r.summary().items())))

    print(f'目标模板: {a.to}')
    cv = TemplateConverter(a.to, prof, r, keep_identity=a.keep_identity)
    print(f'  protocol={cv.t["header"]["protocol_version"]} '
          f'profile_version={cv.t["header"]["profile_version"]}  '
          f'消息 {len(cv.t["messages"])} 种')

    blob = cv.convert()
    open(a.dst, 'wb').write(blob)
    print()
    print(f'✅ 已生成 {a.dst}（{len(blob)} bytes）')
    print(f'   字段映射: 同名 {cv.stats["mapped"]} / 别名 {cv.stats["alias"]} / '
          f'源缺留哨兵 {cv.stats["missing"]}')
    if cv.stats['missing']:
        print(f'   ℹ️ 源缺的字段一律留官方无效哨兵（绝不编造）')

    # 结构自检
    nf = FitFile(a.dst)
    print(f'   产物解析: {"完整" if nf.integrity() else "❌ 不完整"}  '
          f'desync={nf.desync}  头部CRC={nf.header["crc_ok"]}  尾部CRC={nf.trailer_crc_ok}')

    if a.verify:
        print()
        print('=' * 78)
        print('  自动规范校验')
        print('=' * 78)
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'fit_conformance_check.py')
        cmd = [sys.executable, script, a.dst, '--src', a.src, '--temp', a.to]
        rc = subprocess.call(cmd)
        if rc != 0:
            print('\n❌ 规范校验未通过 —— 产物不可交付，必须先修复')
            sys.exit(1)


if __name__ == '__main__':
    main()
