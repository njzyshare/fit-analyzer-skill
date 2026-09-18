# -*- coding: utf-8 -*-
"""把学习到的模板精炼成「规范」——只保留可复用的格式规则，丢弃观测噪声。

模板（templates/*.json）是**学习过程的原始记录**：含逐点统计、present_count、
samples 等观测数据，体积大且大部分是一次性的。
规范（references/profiles/*.md + *.json）是**沉淀下来的格式规则**，
是跨设备可复用、可评审、可入库的东西。

用法：
    python fit_distill_spec.py coros_apex4          # 生成 references/profiles/coros_apex4.md
    python fit_distill_spec.py --all                # 精炼全部模板
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding='utf-8')

from fit_lib import Profile, TEMPLATE_DIR

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_DIR = os.path.join(BASE, 'references', 'profiles')


def distill(name, prof):
    """把一个模板精炼为规范对象（去掉观测噪声）。"""
    tp = os.path.join(TEMPLATE_DIR, f'{name}.json')
    if not os.path.exists(tp):
        raise SystemExit(f'模板不存在: {tp}')
    t = json.load(open(tp, encoding='utf-8'))

    spec = {
        'name': name,
        'device_note': t.get('_note', ''),
        # 文件头规范
        'header': {
            'protocol_version': t['header']['protocol_version'],
            'profile_version': t['header']['profile_version'],
            'header_size': t['header'].get('header_size', 14),
        },
        # 消息白名单与顺序
        'message_order': t.get('message_order'),
        'messages': {},
        # 开发者字段规范
        'developer_data': [],
        # 设备身份写法（不含序列号）
        'identity': {},
        'uses_compressed_timestamp': t.get('uses_compressed_timestamp', False),
    }

    # 消息：只保留布局（字段号/长度/类型码）+ 渐进节奏 + 名称
    for gs, mi in t['messages'].items():
        lays = []
        for lay in mi['layouts']:
            lays.append({
                'local': lay.get('local'),
                'fields': [[f['num'], f['size'], f['base_type']]
                           for f in lay['fields']],
                'dev_fields': [[d['num'], d['size'], d.get('ref_index')]
                               for d in lay.get('dev_fields', [])],
            })
        entry = {
            'name': mi.get('name'),
            'layouts': lays,
        }
        # ⚠️ 渐进节奏**必须始终保留**，即使只有一种布局：
        #    转换器靠它决定「第 i 条消息用哪个布局」，缺了会直接 KeyError。
        #    （曾为省体积省略单布局节奏 → 规范不自足，转换崩）
        rhythm = mi.get('layout_rhythm')
        if rhythm:
            entry['layout_rhythm'] = rhythm
        else:
            entry['layout_rhythm'] = [[0, 1 << 30]]   # 始终用 LAY0
        # 字段官方名对照（便于人工审阅）
        names = {}
        for lay in mi['layouts']:
            for f in lay['fields']:
                if f.get('official_name'):
                    names[str(f['num'])] = f['official_name']
        if names:
            entry['field_names'] = names
        spec['messages'][gs] = entry

    # 开发者字段：只留声明本身（字段号/类型/名称/单位）
    for d in t.get('developer_data', []):
        if d.get('global') not in (206, 207):
            continue
        flds = d.get('fields', {})

        def fv(k):
            """字段值统一存在 value 键下（学习器写入格式）。"""
            return (flds.get(str(k)) or {}).get('value')

        if d.get('global') == 207:
            # ⚠️ 207(developerDataId) 必须保留：DEF 里开发字段的第三字节
            #    引用它的 index，缺了整条 dev 链就断（曾漏采 → 门禁 FAIL）。
            #    applicationId 是 16 字节 byte 数组，**必须留 hex**：
            #    用 int 表示会丢掉前导零（0x47 那一位是厂商约定）。
            def hx(k):
                return (flds.get(str(k)) or {}).get('hex')

            spec.setdefault('developer_data_id', []).append({
                'local': d.get('local'),
                'applicationId_hex': hx(1),
                'manufacturerId': (flds.get('2') or {}).get('int'),
                'developerDataIndex': (flds.get('3') or {}).get('int'),
            })
            continue

        spec['developer_data'].append({
            'local': d.get('local'),
            'developerDataIndex': fv(0),
            'fieldDefinitionNumber': fv(1),
            'fitBaseTypeId': fv(2),
            'fieldName': fv(3),
            'units': fv(8),
        })

    # 身份：只要 manufacturer/product/productName（序列号从来不在模板里）
    idn = t.get('identity', {})
    for k in ('type', 'manufacturer', 'product', 'productName',
              'device_info_count'):
        if k in idn:
            spec['identity'][k] = idn[k]

    # dev 语义（去掉 samples / q75 这类观测细节，保留结论与置信度）
    ds = t.get('dev_semantics') or {}
    if ds:
        spec['dev_semantics'] = {}
        for gs, m in ds.items():
            spec['dev_semantics'][gs] = {}
            for dn, info in m.items():
                spec['dev_semantics'][gs][dn] = {
                    'std_field': info.get('std_field'),
                    'std_name': info.get('std_name'),
                    'confidence': info.get('confidence'),
                    'median_diff': info.get('median_diff'),
                }
    return spec


def write_md(spec, out_path):
    """把规范对象渲染成可读的 Markdown。"""
    L = []
    h = spec['header']
    L.append(f"# {spec['name']} 格式规范")
    L.append('')
    L.append(f"> {spec['device_note']}")
    L.append('>')
    L.append('> 本文件由 `fit_distill_spec.py` 从真机文件学习后精炼而成，'
             '**只保留可复用的格式规则**（已剔除学习过程的观测噪声）。')
    L.append('')
    L.append('## 一、文件头')
    L.append('')
    L.append('| 项 | 值 |')
    L.append('|---|---|')
    L.append(f"| protocol_version | **{h['protocol_version']}** |")
    L.append(f"| profile_version | **{h['profile_version']}** |")
    L.append(f"| header_size | {h['header_size']} |")
    L.append(f"| 压缩时间戳消息 | {'有' if spec['uses_compressed_timestamp'] else '无'} |")
    L.append('')

    L.append('## 二、消息白名单与出现顺序')
    L.append('')
    L.append(f"共 **{len(spec['messages'])}** 种消息。顺序（首现）：")
    L.append('')
    order = spec.get('message_order') or list(spec['messages'].keys())
    order = [int(x) for x in order]
    L.append('```')
    L.append(' → '.join(
        f"{g}({spec['messages'].get(str(g), {}).get('name', '?')})" for g in order))
    L.append('```')
    L.append('')
    L.append('> 其余消息一律**省略**（不填哨兵占位）—— 语义是「这类数据不存在」。')
    L.append('')

    L.append('## 三、各消息布局（字段号 / 字节长 / 类型码）')
    L.append('')
    for gs in order:
        key = str(gs)
        if key not in spec['messages']:
            continue
        mi = spec['messages'][key]
        L.append(f"### g={gs} {mi.get('name', '?')}")
        L.append('')
        if mi.get('layout_rhythm'):
            L.append(f"**渐进节奏**（`[布局下标, 连续条数]`）：`{mi['layout_rhythm']}`")
            L.append('')
        for i, lay in enumerate(mi['layouts']):
            nums = [f[0] for f in lay['fields']]
            L.append(f"- **LAY{i}**（{len(nums)} 字段"
                     f"{'，local=' + str(lay['local']) if lay.get('local') is not None else ''}）："
                     f"`{nums}`")
            if lay.get('dev_fields'):
                L.append(f"  - dev: `{lay['dev_fields']}`")
        L.append('')

    if spec.get('developer_data_id') or spec.get('developer_data'):
        L.append('## 四、开发者字段声明')
        L.append('')
        if spec.get('developer_data_id'):
            L.append('**207 developerDataId**（DEF 里开发字段第三字节引用它的 index）：')
            L.append('')
            L.append('| local | manufacturerId | developerDataIndex | applicationId (hex) |')
            L.append('|---|---|---|---|')
            for d in spec['developer_data_id']:
                L.append(f"| {d.get('local')} | {d.get('manufacturerId')} | "
                         f"{d.get('developerDataIndex')} | `{d.get('applicationId_hex')}` |")
            L.append('')
        if spec.get('developer_data'):
            L.append('**206 fieldDescription**：')
            L.append('')
            L.append('| developerDataIndex | fieldDefinitionNumber | fitBaseTypeId | 名称 | 单位 |')
            L.append('|---|---|---|---|---|')
            for d in spec['developer_data']:
                L.append(f"| {d['developerDataIndex']} | {d['fieldDefinitionNumber']} | "
                         f"{d['fitBaseTypeId']} | {d['fieldName']} | {d['units']} |")
            L.append('')
            locs = [str(d.get('local')) for d in spec['developer_data']
                    if d.get('local') is not None]
            if locs:
                L.append(f"> 206 声明位置：local = {', '.join(locs)}"
                         f"（真机在同份文件里会重复声明，照抄）")
                L.append('')
            if spec.get('dev_semantics'):
                L.append('**语义推断**（faithful 可直接搬 / approx 走势一致 / weak 仅参考）：')
                L.append('')
                for gs, m in spec['dev_semantics'].items():
                    for dn, info in m.items():
                        L.append(f"- g={gs} dev{dn} ≈ `{info['std_name']}`"
                                 f"(f{info['std_field']})，置信度 **{info['confidence']}**"
                                 f"，中位差 {info.get('median_diff')}")
                L.append('')

    L.append('## 五、设备身份写法')
    L.append('')
    L.append('| 项 | 值 |')
    L.append('|---|---|')
    for k, v in spec['identity'].items():
        L.append(f'| {k} | {v} |')
    L.append('')
    L.append('> ⚠️ **serialNumber / Unit ID 不在本文件、也不在任何模板里**，'
             '一律存私有区 `~/.workbuddy/private/fit_devices.json`。')
    L.append('')

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(L))
    return len(L)


def node_safe(x):
    return str(x)


def main():
    ap = argparse.ArgumentParser(description='把模板精炼成可读规范')
    ap.add_argument('name', nargs='?', help='模板名')
    ap.add_argument('--all', action='store_true', help='精炼全部模板')
    ap.add_argument('--json-only', action='store_true', help='只输出 JSON 规范')
    a = ap.parse_args()

    prof = Profile(os.path.join(BASE, 'references', 'fit_profile_official.json'))
    os.makedirs(SPEC_DIR, exist_ok=True)

    if a.all:
        names = [f[:-5] for f in os.listdir(TEMPLATE_DIR) if f.endswith('.json')]
    elif a.name:
        names = [a.name]
    else:
        ap.error('请给出模板名，或用 --all')

    for n in sorted(names):
        spec = distill(n, prof)
        jp = os.path.join(SPEC_DIR, f'{n}.json')
        json.dump(spec, open(jp, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=1)
        jsz = os.path.getsize(jp)
        msg = f'✅ {n}: 规范 JSON {jsz} bytes'
        if not a.json_only:
            mp = os.path.join(SPEC_DIR, f'{n}.md')
            lines = write_md(spec, mp)
            msg += f' / Markdown {os.path.getsize(mp)} bytes（{lines} 行）'
        tsz = os.path.getsize(os.path.join(TEMPLATE_DIR, f'{n}.json'))
        msg += f'  ←  模板 {tsz} bytes（体积 {100 - round(jsz / tsz * 100)}% 是观测噪声）'
        print(msg)


if __name__ == '__main__':
    main()
