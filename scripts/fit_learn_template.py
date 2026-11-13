# -*- coding: utf-8 -*-
"""从真机 FIT 文件学习「设备模板画像」。

这是「照抄目标平台真机写法」这条原则的自动化实现。
不再靠人眼逐字节比对——本脚本把真机文件的一切结构性特征提取成 JSON，
供 `fit_convert_by_template.py` 在重建时逐条复刻。

学到的内容
----------
1. **header 参数**：protocol_version / profile_version
2. **消息白名单**：用了哪些 global、各自条数、首次出现顺序
3. **每个消息的全部 DEF 布局**：字段号 / 大小 / 类型码 / 顺序 / local 号
4. **渐进式布局节奏**：同消息多布局时，每条 MSG 用哪个布局的 run-length 序列
5. **开发者字段完整声明**：207（应用）+ 206（字段）的原始字节与解析值
6. **字段级偏离清单**：实测类型码 vs 官方定义，自动列出「私有写法」
7. **压缩时间戳使用情况**：真机是否用压缩时间戳头

用法
----
    python fit_learn_template.py <真机.fit> --name coros_apex4
    python fit_learn_template.py <真机.fit> --name garmin_fenix8 --note "fenix 8 跑步"
    python fit_learn_template.py --list          # 列出已学模板
"""

import argparse
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fit_lib import (BASE_TYPES, FitFile, Profile, TEMPLATE_DIR,
                     HDR_COMPRESSED, invalid_bytes)

# 结构模板里不需要携带数据的消息（真机里可能几千条，我们只学"布局"）
STRUCT_ONLY = True


def run_length(seq):
    """[(x), (x), (y)] -> [[x, 2], [y, 1]]（紧凑表示布局使用节奏）。"""
    out = []
    for x in seq:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return out


def learn(path, name, prof, note=''):
    f = FitFile(path)
    if not f.integrity():
        print(f'⚠️  源文件自身解析不完整（desync={f.desync}, end={f.end}, '
              f'data_end={f.data_end}），模板可能不可靠', file=sys.stderr)

    result = {
        '_name': name,
        '_note': note,
        '_learned_from': os.path.basename(path),
        '_source_size': len(f.data),
        '_profile_ref': {'source': prof.source, 'version': prof.version},
        'header': {
            'protocol_version': f.header['protocol'],
            'profile_version': f.header['profile_version'],
            'header_size': f.header['size'],
        },
        'messages': {},          # global(str) -> 消息画像
        'message_order': [],     # 各 global 首次出现的消息序号
        'developer_data': [],    # 207 + 206 原始真相
        'uses_compressed_timestamp': False,
        'deviations_from_spec': [],   # 自动挖掘的私有写法
    }

    # ---- 1) 消息骨架 ------------------------------------------------------
    order = []
    for idx, m in enumerate(f.msgs):
        if m.g not in order:
            order.append(m.g)
    result['message_order'] = order

    # ---- 2) 逐消息学习 ----------------------------------------------------
    for g in order:
        msgs = f.by_global(g)
        layouts = f.layouts(g)

        # 布局索引：按在文件中首次声明的顺序
        lay_list = []
        for dd in layouts:
            fnums = [(fd.num, fd.size, fd.base_type) for fd in dd.fields]
            dnums = [(fd.num, fd.size, fd.base_type) for fd in dd.devs]
            lay = {
                'local': dd.local,
                'endian': 'little' if dd.endian == '<' else 'big',
                'n_fields': len(dd.fields),
                'fields': [
                    {
                        'num': n, 'size': sz, 'base_type': bt,
                        'base_type_name': BASE_TYPES.get(bt, (f'?0x{bt:02X}', sz))[0],
                        'official_name': prof.fname(g, n),
                        'official_type': prof.type_name(g, n),
                        'official_type_id': prof.type_id(g, n),
                        'scale': prof.scale_offset(g, n)[0],
                        'offset': prof.scale_offset(g, n)[1],
                        'units': (prof.field(g, n) or {}).get('units'),
                    }
                    for (n, sz, bt) in fnums
                ],
                'dev_fields': [
                    {'num': n, 'size': sz, 'ref_index': bt}
                    for (n, sz, bt) in dnums
                ],
                'has_dev': dd.has_dev,
            }
            lay_list.append(lay)

        # 布局使用节奏：每条 MSG 对应哪个布局
        sig2idx = {}
        for i, dd in enumerate(layouts):
            sig2idx[dd.signature()] = i
        use_seq = []
        for m in msgs:
            use_seq.append(sig2idx.get(m.def_.signature(), -1))
        rhythm = run_length(use_seq)

        # 压缩时间戳使用情况（在解析阶段已记录，无需重扫）
        uses_comp = any(m.compressed for m in msgs)
        if uses_comp:
            result['uses_compressed_timestamp'] = True

        # 字段实际有值率（帮助判断哪些字段真机确实在写）
        present_nums = []
        for lay in lay_list:
            for fdf in lay['fields']:
                if fdf['num'] not in present_nums:
                    present_nums.append(fdf['num'])
        field_stats = []
        for n in present_nums:
            total = 0
            valid = 0
            for m in msgs:
                raw = m.raw.get(n)
                if raw is None:
                    continue
                total += 1
                fdef = prof.field(g, n)
                tn = fdef['type'] if fdef else None
                if tn and _raw_valid(raw, tn):
                    valid += 1
                elif tn is None:
                    valid += 1
            field_stats.append({
                'num': n,
                'official_name': prof.fname(g, n),
                'present_count': total,
                'valid_count': valid,
                'always_invalid': total > 0 and valid == 0,
            })

        result['messages'][str(g)] = {
            'name': prof.msg_name(g),
            'count': len(msgs),
            'n_layouts': len(lay_list),
            'layouts': lay_list,
            'layout_rhythm': rhythm,          # [[布局索引, 连续条数], ...]
            'field_stats': field_stats,
            'uses_compressed_timestamp': uses_comp,
        }

    # ---- 3) 设备身份（公开值写模板；序列号一律脱敏 + 存私有区）------------
    # ⚠️ serialNumber(Unit ID) 属私人数据，**绝不写进模板 JSON**（模板会进 GitHub）。
    #    公开的 manufacturer / product / productName / 版本号可以学。
    #    真正注入身份时从 ~/.workbuddy/private/fit_devices.json 读序列号。
    #    这里顺便把学到的身份**合并进私有设备库**（幂等，不覆盖已有序列号）。
    idn = {}
    fid = f.one(0)
    if fid:
        for num in fid.raw:
            nm = prof.fname(0, num)
            v = f.value(fid, num, prof)
            if nm == 'serialNumber':
                continue                     # 🔒 脱敏，不放模板
            if nm in ('manufacturer', 'product', 'type') and v is not None:
                idn[nm] = int(v)
            elif nm in ('productName', 'timeCreated') and v is not None:
                idn[nm] = v
    dinfos = f.by_global(23)
    if len(dinfos) == 1:
        d = dinfos[0]
        for num in d.raw:
            nm = prof.fname(23, num)
            v = f.value(d, num, prof)
            if nm == 'productName' and v not in (None, ''):
                idn.setdefault('productName', v)
            if nm == 'manufacturer' and v is not None:
                idn.setdefault('manufacturer', int(v))
            if nm == 'product' and v is not None:
                idn.setdefault('product', int(v))
    idn['device_info_count'] = len(dinfos)
    result['identity'] = idn

    # ---- 3.5) 单条消息的「有值字段」快照 ----------------------------------
    # 用途：布局一致 ≠ 值完整。真机 fileId 的 f8(productName) 有值，
    # 若转换时漏填会变成哨兵，而布局比对完全抓不到（2026-09-18 实际踩到）。
    # 这里把「整份文件只出现一次、且属于身份/元信息类」的消息里，
    # 有值的字段记下来，供门禁做值级核对。
    SINGLE_MSG_WHITELIST = {
        0: 'fileId',
        34: 'activity',
        18: 'session',
        23: 'deviceInfo',
    }
    snap = {}
    for g in SINGLE_MSG_WHITELIST:
        msgs = f.by_global(g)
        if len(msgs) != 1:
            continue
        m = msgs[0]
        vals = {}
        for num in sorted(m.raw):
            nm = prof.fname(g, num)
            if nm is None:
                continue
            v = f.value(m, num, prof)
            if v is None:
                continue
            # 只记少数"身份/名称类"关键字段，避免把随活动变化的时间/统计量写进模板
            if nm in ('manufacturer', 'product', 'productName', 'type',
                      'serialNumber', 'garminProduct', 'sport',
                      'timeCreated', 'localTimestamp'):
                if isinstance(v, (bytes, bytearray)):
                    continue
                vals[str(num)] = v
        if vals:
            snap[str(g)] = vals
    if snap:
        result['single_message_values'] = snap

    # ---- 4) 开发者字段原始真相 --------------------------------------------
    for m in f.msgs:
        if m.g == 207:
            ent = {'global': 207, 'local': m.local, 'fields': {}}
            for n, raw in m.raw.items():
                ent['fields'][str(n)] = {
                    'official_name': prof.fname(207, n),
                    'hex': raw.hex(' '),
                    'int': int.from_bytes(raw, 'little'),
                }
            result['developer_data'].append(ent)
        if m.g == 206:
            ent = {'global': 206, 'local': m.local, 'fields': {}}
            for n, raw in m.raw.items():
                tn = prof.type_name(206, n)
                if tn == 'string':
                    v = raw.rstrip(b'\x00').decode('utf-8', 'replace')
                else:
                    v = int.from_bytes(raw, 'little')
                ent['fields'][str(n)] = {
                    'official_name': prof.fname(206, n),
                    'value': v,
                    'hex': raw.hex(' '),
                }
            result['developer_data'].append(ent)

    # ---- 4) 自动挖掘「偏离官方定义的写法」 --------------------------------
    dev = []
    for gs, mi in result['messages'].items():
        g = int(gs)
        for li, lay in enumerate(mi['layouts']):
            for fdf in lay['fields']:
                off_t = fdf['official_type_id']
                if off_t is None:
                    dev.append({
                        'global': g, 'msg': mi['name'], 'field': fdf['num'],
                        'official_name': None, 'kind': 'not_in_official_profile',
                        'actual': f'0x{fdf["base_type"]:02X}',
                        'detail': '官方 profile 无此消息/字段（私有字段）',
                    })
                elif fdf['base_type'] != off_t:
                    dev.append({
                        'global': g, 'msg': mi['name'], 'field': fdf['num'],
                        'official_name': fdf['official_name'],
                        'kind': 'base_type_mismatch',
                        'official': f'0x{off_t:02X}({fdf["official_type"]})',
                        'actual': f'0x{fdf["base_type"]:02X}({fdf["base_type_name"]})',
                        'detail': '类型码与官方定义不一致 → 转换到本平台时必须照抄实际值',
                    })
    result['deviations_from_spec'] = dev

    # ---- 5) 开发字段的语义来源自动推断 ------------------------------------
    # 真机的开发者字段（如高驰 dev16 "Effort Pace"）承载的其实是某个标准物理量。
    # 与其靠人猜，不如让真机自己回答：逐点比对它与所有标准字段，
    # 找出**完全一致**的那个 → 记为 semantic_source。
    # 转换时源没有该 dev 字段，就按这个语义从源的对应字段取，避免留 NULL。
    result['dev_semantics'] = infer_dev_semantics(f, prof)

    # ---- 6) 开发字段语义：跨消息回补 ---------------------------------------
    # session/lap 往往只有 1~30 条，样本不足以自行推断 dev 字段语义。
    # 但它们的 dev 字段号（如 16）与 record 的一致 —— 直接把 record 上
    # 推断出的结论**按字段号复用到样本不足的消息**，并换用目标消息里的
    # 同义标准字段名（如 record.speed 的语义在 lap/session 里对应 avgSpeed）。
    _propagate_dev_semantics(result, prof)

    return result, f


# 标准字段名在不同消息间的语义对应（用于 dev 语义跨消息回补）
_MSG_LEVEL_EQUIV = {
    'speed': ['avgSpeed', 'enhancedAvgSpeed'],
    'enhancedSpeed': ['avgSpeed', 'enhancedAvgSpeed'],
    'avgSpeed': ['avgSpeed', 'enhancedAvgSpeed'],
    'heartRate': ['avgHeartRate'],
    'cadence': ['avgCadence', 'avgRunningCadence'],
    'power': ['avgPower'],
    'altitude': ['avgAltitude', 'enhancedAvgAltitude'],
    'stanceTime': ['avgStanceTime'],
    'verticalOscillation': ['avgVerticalOscillation'],
    'verticalRatio': ['avgVerticalRatio'],
    'stepLength': ['avgStepLength'],
    'temperature': ['avgTemperature'],
}


def _propagate_dev_semantics(result, prof):
    """把样本充足的语义结论按 dev 字段号复用到样本不足的消息。"""
    sem = result.get('dev_semantics') or {}
    # 收集「字段号 -> 最佳语义结论」
    by_num = {}
    for g, m in sem.items():
        for dn, info in m.items():
            cur = by_num.get(dn)
            if cur is None or _conf_rank(info['confidence']) < _conf_rank(cur['confidence']):
                by_num[dn] = dict(info)
    for g in result['messages']:
        msg = result['messages'][g]
        nums = set()
        for lay in msg['layouts']:
            for df in lay['dev_fields']:
                nums.add(str(df['num']))
        for dn in nums:
            if dn in sem.get(g, {}):
                continue
            src = by_num.get(dn)
            if not src:
                continue
            # 找该消息里对应的标准字段名
            target_name = None
            for cand in _MSG_LEVEL_EQUIV.get(src['std_name'], []):
                n = prof.field_num(int(g), cand)
                if n is not None:
                    target_name = cand
                    break
            info = dict(src)
            info['confidence'] = 'weak' if src['confidence'] != 'faithful' else 'approx'
            info['std_name'] = target_name or src['std_name']
            info['std_field'] = (prof.field_num(int(g), info['std_name'])
                                 if info['std_name'] else None)
            info['_note'] += '（由样本充足的消息按字段号回补，置信度下调一级）'
            sem.setdefault(g, {})[dn] = info
    result['dev_semantics'] = sem


def _conf_rank(c):
    return {'faithful': 0, 'approx': 1, 'weak': 2, 'none': 3}.get(c, 4)


def infer_dev_semantics(f, prof):
    """推断各消息里每个开发字段最接近哪个标准字段（分级置信度）。

    背景（实测发现）
    ----------------
    开发者字段常是**厂商私有算法的产物**，与标准字段**走势一致但不逐点相等**。
    例如高驰 dev16 "Effort Pace"（float32）vs record.f6 speed（uint16 分辨率 0.001）：
      - 中位绝对差 0.154 m/s、75 分位差 0.514 m/s
      - 精确命中（<0.0025）仅 33.6%
      - 走时移相关峰值在 k=0 → 两者同相位但 dev16 更灵敏
    因此**不能**宣称"dev16 == speed"。这里只给出**最接近的候选 + 置信度分级**，
    供转换时决定：✅faithful（可靠等价）/ ⚠️approx（近似，需注明）/ ❌none（无对应）。

    分级标准
    --------
      faithful : 中位差 < 0.01 且 精确命中 > 80%   → 可视为等价，直接搬
      approx   : 中位差 < 0.5  且 精确命中 > 10%   → 近似，转换时采用但需注明
      weak     : 中位差 < 2.0                      → 仅作兜底参考
      none     : 都不满足 → 源无对应数据，转换时留无效值（绝不编造）
    """
    out = {}
    for g in sorted({m.g for m in f.msgs}):
        msgs = f.by_global(g)
        dev_nums = sorted({n for m in msgs for n in m.dev_raw})
        if not dev_nums:
            continue
        for dn in dev_nums:
            dvals = []
            for m in msgs:
                raw = m.dev_raw.get(dn)
                if raw is None:
                    dvals.append(None)
                elif len(raw) == 4:
                    dvals.append(float(struct.unpack('<f', raw)[0]))
                elif len(raw) == 8:
                    dvals.append(float(struct.unpack('<d', raw)[0]))
                else:
                    dvals.append(None)
            std_nums = sorted({n for m in msgs for n in m.raw})
            cands = []
            for sn in std_nums:
                if sn == 253:           # timestamp 不参与
                    continue
                diffs, exact = [], 0
                for m, dv in zip(msgs, dvals):
                    if dv is None or dv != dv or sn not in m.raw:
                        continue
                    sv = f.value(m, sn, prof)
                    if sv is None or not isinstance(sv, (int, float)):
                        continue
                    dd = abs(float(dv) - float(sv))
                    diffs.append(dd)
                    if dd < 0.0025:
                        exact += 1
                if len(diffs) < 5:
                    continue
                diffs.sort()
                med = diffs[len(diffs) // 2]
                q75 = diffs[int(len(diffs) * 0.75)]
                ex_rate = exact / len(diffs)
                if med < 0.01 and ex_rate > 0.80:
                    level = 'faithful'
                elif med < 0.5 and ex_rate > 0.10:
                    level = 'approx'
                elif med < 2.0:
                    level = 'weak'
                else:
                    continue
                rank = {'faithful': 0, 'approx': 1, 'weak': 2}[level]
                cands.append((rank, med, -ex_rate, sn, len(diffs), ex_rate, q75, level))
            if cands:
                cands.sort()
                rank, med, neg, sn, n, ex, q75, level = cands[0]
                out.setdefault(str(g), {})[str(dn)] = {
                    'std_field': sn if level != 'none' else None,
                    'std_name': prof.fname(g, sn) if level != 'none' else None,
                    'confidence': level,
                    'median_diff': round(med, 5),
                    'q75_diff': round(q75, 5),
                    'exact_match_ratio': round(ex, 4),
                    'samples': n,
                    '_note': ('faithful=可靠等价，可直接搬；approx=走势一致但非逐点相等，'
                              '采用时须注明为推断；weak=仅兜底参考'),
                }
    return out


def _raw_valid(raw, type_name):
    return bytes(raw) != invalid_bytes(type_name, len(raw))


def save(result, name):
    os.makedirs(TEMPLATE_DIR, exist_ok=True)
    p = os.path.join(TEMPLATE_DIR, f'{name}.json')
    json.dump(result, open(p, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    return p


# 私有设备库（序列号等敏感值只在这里）
PRIVATE_STORE = os.path.join(os.path.expanduser('~'), '.workbuddy',
                             'private', 'fit_devices.json')


def update_private_identity(path, name, prof):
    """把真机的完整身份（含序列号）写入私有设备库。"""
    try:
        f = FitFile(path)
        fid = f.one(0)
        if not fid:
            return None
        rec = {'brand': name.split('_')[0]}
        for num in fid.raw:
            nm = prof.fname(0, num)
            v = f.value(fid, num, prof)
            if v is None:
                continue
            m = {'manufacturer': 'manufacturer', 'product': 'product',
                 'serialNumber': 'serial_number', 'productName': 'product_name',
                 'timeCreated': 'time_created'}
            if nm in m:
                rec[m[nm]] = v
        dinfos = f.by_global(23)
        rec['device_info_count'] = len(dinfos)
        if len(dinfos) == 1:
            d = dinfos[0]
            for num in d.raw:
                nm = prof.fname(23, num)
                v = f.value(d, num, prof)
                if nm == 'productName' and v:
                    rec.setdefault('product_name', v)
                if nm == 'softwareVersion' and v is not None:
                    rec['sw_version'] = v
                if nm == 'hardwareVersion' and v is not None:
                    rec['hw_version'] = v
        rec['_source_file'] = path
        rec['_note'] = f'{name} 模板学习时自动记录'
        os.makedirs(os.path.dirname(PRIVATE_STORE), exist_ok=True)
        if os.path.exists(PRIVATE_STORE):
            db = json.load(open(PRIVATE_STORE, encoding='utf-8'))
        else:
            db = {'_说明': 'FIT 设备身份信息（私有），不随 GitHub 更新变动。',
                  'devices': {}}
        db.setdefault('devices', {})[name] = rec
        json.dump(db, open(PRIVATE_STORE, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        return rec
    except Exception as e:
        print(f'  ⚠️ 写私有设备库失败: {e}', file=sys.stderr)
        return None


def main():
    ap = argparse.ArgumentParser(description='从真机 FIT 学习设备模板画像')
    ap.add_argument('fit', nargs='?', help='真机 .fit 文件')
    ap.add_argument('--name', help='模板名（保存为 references/templates/<name>.json）')
    ap.add_argument('--note', default='', help='备注（设备型号等）')
    ap.add_argument('--list', action='store_true', help='列出已学模板')
    ap.add_argument('--print', action='store_true', help='打印学习结果')
    a = ap.parse_args()

    if a.list:
        if not os.path.isdir(TEMPLATE_DIR):
            print('尚无模板'); return
        for fn in sorted(os.listdir(TEMPLATE_DIR)):
            if not fn.endswith('.json'):
                continue
            d = json.load(open(os.path.join(TEMPLATE_DIR, fn), encoding='utf-8'))
            gs = len(d.get('messages', {}))
            print(f'  {fn:<28} {d.get("_note","")}  消息{gs}种  '
                  f'proto={d["header"]["protocol_version"]}')
        return

    if not a.fit or not a.name:
        ap.error('需要 <真机.fit> 与 --name')

    prof = Profile()
    res, f = learn(a.fit, a.name, prof, a.note)

    p = save(res, a.name)
    priv = update_private_identity(a.fit, a.name, prof)
    print(f'✅ 模板已保存: {p}')
    if priv:
        print(f'   设备身份已记入私有库（含序列号，不进仓库）: '
              f'manufacturer={priv.get("manufacturer")} '
              f'product={priv.get("product")} '
              f'name={priv.get("product_name")}')
    print(f'   来源: {os.path.basename(a.fit)}  ({len(f.data)} bytes)')
    print(f'   protocol={res["header"]["protocol_version"]} '
          f'profile_version={res["header"]["profile_version"]}')
    print(f'   消息 {len(res["messages"])} 种')
    print()
    print('   逐消息布局:')
    for gs, mi in res['messages'].items():
        n_lay = mi['n_layouts']
        flag = f'  ← 渐进式 {n_lay} 种布局' if n_lay > 1 else ''
        print(f'     g={gs:<4} {mi["name"]:<20} 条数={mi["count"]:<7} '
              f'布局={n_lay}{flag}')
        if n_lay > 1:
            for i, lay in enumerate(mi['layouts']):
                nums = [x['num'] for x in lay['fields']]
                print(f'         [{i}] local={lay["local"]:<3} '
                      f'字段{nums}'
                      + (f' + dev{[x["num"] for x in lay["dev_fields"]]}' if lay['dev_fields'] else ''))
            print(f'         节奏: {mi["layout_rhythm"]}')

    if res['developer_data']:
        print()
        print('   开发者字段:')
        for ent in res['developer_data']:
            parts = []
            for k, v in ent['fields'].items():
                val = v.get('value', v.get('hex'))
                parts.append(f'{v["official_name"]}={val}')
            print(f'     g={ent["global"]} local={ent["local"]}: ' + ', '.join(parts))

    ds = res.get('dev_semantics') or {}
    if ds:
        print()
        print('   开发字段语义来源（自动推断，转换时源无此字段则按此取值）:')
        for g, m in ds.items():
            for dn, info in m.items():
                print(f'     g={g} dev{dn} ≈ {info["std_name"]}(f{info["std_field"]}) '
                      f'中位差 {info["median_diff"]:.4f} / 精确命中 '
                      f'{info["exact_match_ratio"]*100:.1f}% （{info["samples"]} 点）')

    if res['deviations_from_spec']:
        print()
        print(f'   ⚠️ 偏离官方定义的写法 {len(res["deviations_from_spec"])} 处'
              f'（转换时必须照抄实际值）:')
        for d in res['deviations_from_spec'][:12]:
            print(f'     g={d["global"]} f{d["field"]} {d.get("official_name") or "(私有)"}: '
                  f'{d.get("official") or "-"} → {d["actual"]}')
        if len(res['deviations_from_spec']) > 12:
            print(f'     … 其余 {len(res["deviations_from_spec"]) - 12} 处见 JSON')

    if a.print:
        print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
