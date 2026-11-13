#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高驰(COROS) 设备身份注入 —— 字节级，保真保留全部运动数据。

类比 `inject_garmin_device.mjs`，但走「字节级 rebrand」而非 SDK 重编码：
因为高驰 device_info 是标准精简布局（field 2=manufacturer=coros、无 product/serial，
product 在 file_id=814），但 Garmin SDK 的 Encoder 编不出这种布局（会把 294 错放字段 →
高驰拒收）。唯一可靠做法 = 复制参考高驰文件的 file_id + device_info 原始字节，其余按源文件拼接。

与 rebrand_device.py 的关系：
  - rebrand_device.py 只替换「第一条」device_info，源文件其余 device_info 原样保留。
    但佳明源文件常带 10+ 条 device_info（手表+传感器），只换第一条会留下一堆佳明设备，
    变成「四不像」。本脚本**删除源文件全部 device_info，只注入单条高驰 device_info**，
    结构等同于一份纯高驰原生文件（1 个 file_id + 1 个 device_info）。
  - 因此本脚本是 rebrand_device.rebrand_core 的薄封装：ref 恒为高驰身份、协议字节翻回 0x20。
  - 解析统一走 fit_merge.walk（正确实现），不再依赖会漂移的自写 parse。

身份字节来源（绝不存 .fit 样本做参考，遵循 skill 铁律）：
  - 私人区 `~/.workbuddy/private/coros_devices.json` 的 `raw_identity`（extract 一次性抽取）。
  - 回退：已提交的 `references/profiles/coros_<name>_identity.json`（仅无序列号设备）。

用法：
  # 0) 首次：从真实高驰活动抽取设备身份（含原始字节）入私人区域（不再复制 .fit）
  python inject_coros.py extract 真实高驰活动.fit --name apex4

  # 1) 把私人区域/已提交的身份注入任意 FIT（运动数据 100% 保留，只换设备身份）
  python inject_coros.py apply 源.fit --device apex4 --out 源_coros.fit
      # 不写 --device 时取私人文件里的 default 项
      # 不写 --out 时默认 <原名>_coros.fit
      # --proto 0x02 可改为标准协议（传 Garmin Connect 时用）；默认 0x20（传 COROS）
"""
import sys, os, json, argparse, datetime, struct
import rebrand_device as rb
import fit_merge as fm

PRIVATE = os.path.expanduser("~/.workbuddy/private")
JSON_PATH = os.path.join(PRIVATE, "coros_devices.json")
PROFILES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        os.pardir, "references", "profiles")
DEFAULT_PROTO = 0x20  # COROS 原生协议字节


def get_identity(fit):
    """从真实高驰活动抽取可读身份字段（不含原始字节，原始字节由 rb.extract 负责）。"""
    d, body = fm.read_body(fit)
    frames = fm.walk(body)
    man = prod = pname = serial = None
    tc = None
    for fr in frames:
        if fr['global'] == 0 and not fr['is_def']:
            for (dn, _, _) in fr['dd']['fields']:
                if dn == 2:
                    man = fm.read_field_raw(fr['chunk'], fr['dd'], 2, fr['compressed'], fr['dev'])[0]
                if dn == 4:
                    raw = fm.read_field_raw(fr['chunk'], fr['dd'], 4, fr['compressed'], fr['dev'])[0]
                    tc = datetime.datetime(1989, 12, 31) + datetime.timedelta(seconds=int.from_bytes(raw, 'little'))
    # product / product_name 在 device_info
    for fr in frames:
        if fr['global'] == 23 and not fr['is_def']:
            for (dn, _, _) in fr['dd']['fields']:
                if dn == 2:
                    pname = fm.read_field_raw(fr['chunk'], fr['dd'], 2, fr['compressed'], fr['dev'])[0]
    return {
        "manufacturer": man.decode('ascii', 'replace') if isinstance(man, bytes) else man,
        "product": prod,
        "productName": pname.decode('ascii', 'replace') if isinstance(pname, bytes) else pname,
        "serialNumber": serial,
        "time_created": tc.isoformat() if tc else None,
    }


def load_json():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"default": None, "devices": {}}


def load_raw_identity(name):
    """私人区优先，回退已提交 identity 文件（仅无序列号设备）。返回 4 条原始字节。"""
    store = load_json()
    dev = store.get("devices", {}).get(name)
    if dev and "raw_identity" in dev:
        return _as_bytes(dev["raw_identity"])
    ij = os.path.join(PROFILES, f"coros_{name}_identity.json")
    if os.path.exists(ij):
        d = json.load(open(ij, encoding="utf-8"))
        if "raw_identity" in d:
            return _as_bytes(d["raw_identity"])
    print("ERROR: 私人库/已提交区均无设备", name, "的 raw_identity")
    sys.exit(1)


def _as_bytes(ri):
    return (bytes.fromhex(ri["fid_def_hex"].replace(" ", "")),
            bytes.fromhex(ri["fid_data_hex"].replace(" ", "")),
            bytes.fromhex(ri["di_def_hex"].replace(" ", "")),
            bytes.fromhex(ri["di_data_hex"].replace(" ", "")))


def cmd_extract(args):
    ident = get_identity(args.fit)
    ident["source"] = os.path.basename(args.fit)
    ident["raw_identity"] = rb.identity_to_json(rb.extract_identity_from_fit(args.fit))
    store = load_json()
    store["devices"][args.name] = ident
    if not store.get("default"):
        store["default"] = args.name
    os.makedirs(PRIVATE, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
    print(f"已抽取 {ident['manufacturer']} {ident['productName']} -> 私人库 [{args.name}]")
    print(f"  身份库: {JSON_PATH}（含 raw_identity 原始字节，已不依赖 .fit 样本）")


def cmd_apply(args):
    store = load_json()
    name = args.device or store.get("default")
    if not name or name not in store.get("devices", {}):
        print("ERROR: 私人库无此设备:", name)
        sys.exit(1)
    raw = load_raw_identity(name)
    d, hsize, frames = rb._load(args.fit)
    proto = args.proto if args.proto is not None else DEFAULT_PROTO
    out_b, tc = rb.rebrand_core(d, hsize, frames, raw, proto=proto)
    out_path = args.out or (os.path.splitext(args.fit)[0] + "_coros.fit")
    open(out_path, "wb").write(out_b)
    fc = struct.unpack('<H', out_b[-2:])[0]
    hc = struct.unpack('<H', out_b[12:14])[0]
    print(f"wrote {out_path}: {len(out_b)} bytes (delta {len(out_b)-len(d):+d})")
    print(f"file CRC 0x{fc:04X} match={fc==rb.fit_crc16(out_b[:-2])}; "
          f"header CRC 0x{hc:04X} match={hc==rb.fit_crc16(out_b[0:12])}; "
          f"proto=0x{out_b[1]:02X}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="COROS 设备身份字节级注入")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="从真实高驰活动抽取设备身份(含原始字节)存入私人区域")
    pe.add_argument("fit", help="真实高驰活动 .fit")
    pe.add_argument("--name", default="apex4", help="设备名（默认 apex4）")

    pa = sub.add_parser("apply", help="把高驰身份(原始字节)注入源 FIT")
    pa.add_argument("fit", help="源 .fit（任意设备产出均可）")
    pa.add_argument("--device", default=None, help="私人库设备名（默认 default）")
    pa.add_argument("--out", default=None, help="输出路径（默认 <原名>_coros.fit）")
    pa.add_argument("--proto", type=lambda x: int(x, 0), default=None,
                    help="协议字节（默认 0x20；传 Garmin Connect 用 0x02）")

    args = ap.parse_args()
    {"extract": cmd_extract, "apply": cmd_apply}[args.cmd](args)
