# -*- coding: utf-8 -*-
"""从真实设备文件抽取身份信息，写入私有区域。

私有区域：~/.workbuddy/private/fit_devices.json
（不随 skill 的 GitHub 更新变动，不进任何公开仓库）

用法：
  python extract_devices.py <高驰.fit> <佳明.fit>      # 指定真机文件（推荐）
  python extract_devices.py --coros X.fit             # 只更新高驰
  python extract_devices.py --garmin Y.fit            # 只更新佳明
  python extract_devices.py --show                    # 只显示现有内容

⚠️ 路径不写死在本文件里（避免泄露个人目录结构）。
   若需固定默认路径，用环境变量指定：
     FIT_COROS_SRC / FIT_GARMIN_SRC
   或放到私有配置 ~/.workbuddy/private/fit_sources.json：
     {"coros": "...", "garmin": "..."}
"""
import json, os, struct, sys

sys.stdout.reconfigure(encoding='utf-8')

STORE = os.path.join(os.path.expanduser('~'), '.workbuddy', 'private', 'fit_devices.json')
SOURCE_CFG = os.path.join(os.path.expanduser('~'), '.workbuddy', 'private',
                          'fit_sources.json')


def _load_sources():
    """读取默认真机文件路径：环境变量优先，其次私有配置文件，都没有则返回空。"""
    cfg = {}
    if os.path.exists(SOURCE_CFG):
        try:
            cfg = json.load(open(SOURCE_CFG, encoding='utf-8'))
        except Exception:
            cfg = {}
    return (
        os.environ.get('FIT_COROS_SRC') or cfg.get('coros'),
        os.environ.get('FIT_GARMIN_SRC') or cfg.get('garmin'),
    )


COROS_SRC, GARMIN_SRC = _load_sources()


def read_identity(path, brand):
    """读取 file_id + device_info 主设备信息。"""
    d = open(path, 'rb').read()
    hs = d[0]
    be = hs + struct.unpack_from('<I', d, 4)[0]
    i = hs
    defs = {}
    fid = None
    devs = []
    while i + 1 < be:
        st = i
        hdr = d[i]; i += 1
        if (hdr & 0x40) == 0x40:
            hd = bool(hdr & 0x20); loc = hdr & 0x0F; i += 1
            en = '<' if d[i] == 0 else '>'; i += 1
            g = struct.unpack_from(en + 'H', d, i)[0]; i += 2
            nf = d[i]; i += 1
            fs = []
            for _ in range(nf):
                fs.append((d[i], d[i+1], d[i+2])); i += 3
            dv = []
            if hd:
                nd = d[i]; i += 1
                for _ in range(nd):
                    dv.append((d[i], d[i+1], d[i+2])); i += 3
            defs[loc] = (g, fs, dv)
            continue
        loc = (hdr >> 5) & 3 if (hdr & 0x80) == 0x80 else hdr & 0x0F
        if loc not in defs:
            break
        g, pf, dv = defs[loc]
        vals = {}
        o = st + 1
        for (n, sz, bt) in pf:
            raw = d[o:o+sz]
            if bt == 0x07:
                v = raw.rstrip(b'\x00').decode('utf-8', 'replace')
            elif sz == 1:
                v = raw[0]
            elif sz == 2:
                v = struct.unpack('<H', raw)[0]
            elif sz == 4:
                v = struct.unpack('<I', raw)[0]
            else:
                v = raw.hex(' ')
            vals[n] = v
            o += sz
        if g == 0:
            fid = vals
        elif g == 23:
            devs.append(vals)
        i += sum(f[1] for f in pf) + sum(f[1] for f in dv)

    # 找手表本体：
    #   佳明 device_info 有 29 字段，主设备 = device_index(0)==0 且带 serial(3)/product(4)
    #   高驰只有 3 字段（253 timestamp / 2 manufacturer / 27 product_name），无 device_index
    main = None
    if brand == 'garmin':
        for v in devs:
            if v.get(0, 0) == 0 and (v.get(3) or v.get(4)):
                main = v
                break
    if main is None and devs:
        main = devs[0]

    out = {
        'brand': brand,
        'source_file': path,
        # file_id 层（双方共有）
        'manufacturer': fid.get(1),          # 1=garmin, 294=coros
        'product': fid.get(2),
        'serial_number': fid.get(3),         # 高驰为 None（不存序列号）
        'time_created': fid.get(4),
        'product_name': fid.get(8),          # 高驰有；佳明 file_id 无此字段
        # device_info 主设备层
        'device_index': main.get(0) if main else None,
        'sw_version': main.get(5) if main else None,
        'hw_version': main.get(6) if main else None,
        'battery_status': main.get(11) if main else None,
        'source_type': main.get(25) if main else None,
        'device_info_count': len(devs),
    }
    # 高驰 device_info 的名称在字段 27；佳明用固定名称（file_id 无 product_name）
    if brand == 'coros' and main and not out['product_name']:
        out['product_name'] = main.get(27)
    if brand == 'garmin' and not out['product_name']:
        # 佳明 device_info 的字段 27 是 24 字节 product_name，本例全 0xFF（空）
        out['product_name'] = 'fenix 8'
    return out, devs


def main():
    args = sys.argv[1:]
    if '--show' in args:
        if os.path.exists(STORE):
            print(open(STORE, encoding='utf-8').read())
        else:
            print(f'{STORE} 不存在')
        return

    def optval(name):
        if name in args:
            i = args.index(name)
            if i + 1 < len(args):
                return args[i + 1]
        return None

    c_opt = optval('--coros')
    g_opt = optval('--garmin')
    # 位置参数：第 1 个 = 高驰模板，第 2 个 = 佳明模板
    pos = [a for a in args if not a.startswith('--') and a not in (c_opt, g_opt)]
    if len(pos) >= 1 and c_opt is None:
        c_opt = pos[0]
    if len(pos) >= 2 and g_opt is None:
        g_opt = pos[1]

    # 更新范围：给了哪个就更新哪个；什么都没给则两个都更新
    explicit = c_opt is not None or g_opt is not None
    want_coros = (c_opt is not None) if explicit else True
    want_garmin = (g_opt is not None) if explicit else True

    coros_src = c_opt or COROS_SRC
    garmin_src = g_opt or GARMIN_SRC

    # 载入已有内容（保留未更新的设备）
    if os.path.exists(STORE):
        with open(STORE, encoding='utf-8') as f:
            store = json.load(f)
    else:
        store = {
            '_说明': 'FIT 设备身份信息（私有）。由 fit-analyzer-skill 的脚本读取，不随 GitHub 更新变动。',
            'devices': {},
        }
    store.setdefault('devices', {})

    if want_coros:
        if os.path.exists(coros_src):
            coros, _ = read_identity(coros_src, 'coros')
            store['devices']['coros_apex4'] = {
                **coros,
                '_备注': '高驰 APEX 4 42mm 真机记录，作为「改成高驰设备」的唯一权威来源',
            }
            print(f'高驰身份已更新（{coros_src}）')
        else:
            print(f'跳过高驰：文件不存在 {coros_src}')

    if want_garmin:
        if os.path.exists(garmin_src):
            garmin, _ = read_identity(garmin_src, 'garmin')
            store['devices']['garmin_fenix8'] = {
                **garmin,
                '_备注': '佳明 fenix 8 官方导出，作为「改成佳明设备」的唯一权威来源',
            }
            print(f'佳明身份已更新（{garmin_src}）')
        else:
            print(f'跳过佳明：文件不存在 {garmin_src}')

    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, 'w', encoding='utf-8') as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    print(f'\n已写入 {STORE}')
    print()
    print(json.dumps(store, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
