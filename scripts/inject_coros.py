#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高驰(COROS) 设备身份注入 —— 字节级，保真保留全部运动数据。
=============================================================

类比 `inject_garmin_device.mjs`，但走「字节级 rebrand」而非 SDK 重编码：
因为高驰 device_info 是非标准布局（product 字段=厂商码 294、无 manufacturer 字段），
Garmin SDK 的 Encoder 编不出这种布局（会把 294 错放字段 → 高驰拒收）。
唯一可靠做法 = 复制参考高驰文件的 file_id + device_info 原始字节，其余按源文件拼接。

与 rebrand_device.py 的区别：
  - rebrand_device.py 只替换「第一条」device_info，源文件其余 device_info 原样保留。
    但佳明源文件常带 10+ 条 device_info（手表+传感器），只换第一条会留下一堆佳明设备，
    变成「四不像」。本脚本**删除源文件全部 device_info，只注入单条高驰 device_info**，
    结构等同于一份纯高驰原生文件（1 个 file_id + 1 个 device_info）。
  - 协议字节默认翻回高驰原生 0x20（回传 COROS app 必须；否则时间会被 COROS 误读成凌晨）。
  - 提供 extract / apply 子命令 + 私人区域存储（类比佳明）。

私人区域：
  ~/.workbuddy/private/coros_devices.json   设备身份元数据（mirror garmin_devices.json）
  ~/.workbuddy/private/coros_<name>.fit     参考高驰活动（字节级注入的身份字节来源，不可省略）

用法：
  # 0) 首次：从真实高驰活动抽取设备身份入私人区域（同时保存参考 .fit 字节）
  python inject_coros.py extract 高驰活动.fit --name apex4

  # 1) 把私人区域里的身份注入任意 FIT（运动数据 100% 保留，只换设备身份）
  python inject_coros.py apply 源.fit --device apex4 --out 源_coros.fit
      # 不写 --device 时取私人文件里的 default 项
      # 不写 --out 时默认 <原名>_coros.fit
      # --proto 0x02 可改为标准协议（传 Garmin Connect 时用）；默认 0x20（传 COROS）
"""
import sys, os, json, shutil, struct, argparse, datetime
import rebrand_device as rb

PRIVATE = os.path.expanduser("~/.workbuddy/private")
JSON_PATH = os.path.join(PRIVATE, "coros_devices.json")
DEFAULT_PROTO = 0x20  # COROS 原生协议字节


def _safe(m, f):
    try:
        return m.get_value(f)
    except Exception:
        return None


def get_identity(fit):
    import fitdecode
    man = prod = pname = serial = None
    tc = None
    with fitdecode.FitReader(fit) as r:
        for m in r:
            if not isinstance(m, fitdecode.FitDataMessage):
                continue
            if m.name == "file_id":
                man = _safe(m, "manufacturer")
                prod = _safe(m, "product")
                pname = _safe(m, "product_name")
                serial = _safe(m, "serial_number")
                tc = _safe(m, "time_created")
            if m.name == "device_info" and pname is None:
                pname = _safe(m, "product_name") or pname
    return {
        "manufacturer": man,
        "product": prod,
        "productName": pname,
        "serialNumber": serial,
        "time_created": tc.isoformat() if tc else None,
    }


def load_json():
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"default": None, "devices": {}}


def cmd_extract(args):
    ident = get_identity(args.fit)
    ident["source"] = os.path.basename(args.fit)
    name = args.name
    store = load_json()
    store["devices"][name] = ident
    if not store.get("default"):
        store["default"] = name
    os.makedirs(PRIVATE, exist_ok=True)
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, indent=2, ensure_ascii=False)
    ref_path = os.path.join(PRIVATE, f"coros_{name}.fit")
    shutil.copyfile(args.fit, ref_path)
    print(f"已抽取 {ident['manufacturer']} {ident['productName']} -> 私人库 [{name}]")
    print(f"  身份库:  {JSON_PATH}")
    print(f"  参考字节: {ref_path}")


def build_identity(ref, src_time_created, src_fid_local, src_di_local):
    """从参考文件构造新的 file_id / device_info def+data 字节（local 用源文件的，时间用源活动的）。"""
    rdata, _, rrecs = rb.parse(ref)
    r_fid_def, r_fid_data = rb.find_pair(rrecs, 0)
    r_di_def, r_di_data = rb.find_pair(rrecs, 23)
    if not all([r_fid_def, r_fid_data, r_di_def, r_di_data]):
        print("ERROR: 参考文件缺少 file_id/device_info")
        sys.exit(1)

    # file_id
    new_fid_def = bytearray(r_fid_def["raw"])
    new_fid_def[0] = (new_fid_def[0] & 0xF0) | (src_fid_local & 0x0F)
    new_fid_data = bytearray(r_fid_data["raw"])
    new_fid_data[0] = src_fid_local & 0x0F
    fp, fsz = rb.field_offset(r_fid_def, 4)
    new_fid_data[fp : fp + fsz] = struct.pack("<I", src_time_created)

    # device_info（单条）
    new_di_def = bytearray(r_di_def["raw"])
    new_di_def[0] = (new_di_def[0] & 0xF0) | (src_di_local & 0x0F)
    new_di_data = bytearray(r_di_data["raw"])
    new_di_data[0] = src_di_local & 0x0F
    dp, dsz = rb.field_offset(r_di_def, 253)
    new_di_data[dp : dp + dsz] = struct.pack("<I", src_time_created)

    return bytes(new_fid_def), bytes(new_fid_data), bytes(new_di_def), bytes(new_di_data)


def cmd_apply(args):
    store = load_json()
    name = args.device or store.get("default")
    if not name or name not in store["devices"]:
        print("ERROR: 私人库无此设备:", name)
        sys.exit(1)
    ref = os.path.join(PRIVATE, f"coros_{name}.fit")
    if not os.path.exists(ref):
        print("ERROR: 缺少参考字节", ref)
        sys.exit(1)

    tdata, thsize, trecs = rb.parse(args.fit)
    t_fid_def, t_fid_data = rb.find_pair(trecs, 0)
    if not (t_fid_def and t_fid_data):
        print("ERROR: 源文件缺少 file_id")
        sys.exit(1)
    # 本活动自己的创建时间（file_id field 4）
    tp, tsz = rb.field_offset(t_fid_def, 4)
    src_time_created = struct.unpack("<I", t_fid_data["raw"][tp : tp + tsz])[0]

    # 源 file_id / 第一条 device_info 的 local 号（用于新身份，避免与文件内其它 def 冲突）
    src_fid_local = t_fid_def["local"]
    first_di = next((r for r in trecs if r["global"] == 23), None)
    src_di_local = first_di["local"] if first_di else src_fid_local

    nf_def, nf_data, nd_def, nd_data = build_identity(ref, src_time_created, src_fid_local, src_di_local)

    # 拼接：先放原始 header（后面再改 data_size/proto/header CRC），再按源文件顺序遍历消息
    out = bytearray(tdata[:thsize])
    di_emitted = False
    fid_emitted = False
    for r in trecs:
        if r["global"] == 0:  # file_id：替换（只输出一次，避免 def+data 各触发一次造成重复）
            if not fid_emitted:
                out += nf_def
                out += nf_data
                fid_emitted = True
        elif r["global"] == 23:  # device_info：只注入单条，其余丢弃
            if not di_emitted:
                out += nd_def
                out += nd_data
                di_emitted = True
            # 其余源 device_info（def+data）直接跳过
        else:
            out += r["raw"]

    # 修正 header data_size（偏移4）= header 之后、CRC 之前的字节数
    out[4:8] = struct.pack("<I", len(out) - thsize)
    # 协议字节翻回高驰原生（默认 0x20）
    proto = args.proto if args.proto is not None else DEFAULT_PROTO
    out[1] = proto & 0xFF
    # 修正 header CRC（偏移12，覆盖字节 0..11）
    out[12:14] = struct.pack("<H", rb.fit_crc16(bytes(out[0:12])))
    # 文件尾 CRC
    out += struct.pack("<H", rb.fit_crc16(bytes(out)))

    out_path = args.out or (os.path.splitext(args.fit)[0] + "_coros.fit")
    open(out_path, "wb").write(out)

    fc = struct.unpack("<H", bytes(out[-2:]))[0]
    hc = struct.unpack("<H", bytes(out[12:14]))[0]
    print(f"wrote {out_path}: {len(out)} bytes (delta {len(out)-len(tdata):+d})")
    print(
        f"file CRC 0x{fc:04X} match={fc==rb.fit_crc16(bytes(out[:-2]))}; "
        f"header CRC 0x{hc:04X} match={hc==rb.fit_crc16(bytes(out[0:12]))}; "
        f"proto=0x{out[1]:02X}"
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="COROS 设备身份字节级注入")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pe = sub.add_parser("extract", help="从真实高驰活动抽取设备身份存入私人区域")
    pe.add_argument("fit", help="真实高驰活动 .fit")
    pe.add_argument("--name", default="apex4", help="设备名（默认 apex4）")

    pa = sub.add_parser("apply", help="把私人区域的高驰身份注入源 FIT")
    pa.add_argument("fit", help="源 .fit（任意设备产出均可）")
    pa.add_argument("--device", default=None, help="私人库设备名（默认 default）")
    pa.add_argument("--out", default=None, help="输出路径（默认 <原名>_coros.fit）")
    pa.add_argument("--proto", type=lambda x: int(x, 0), default=None,
                    help="协议字节（默认 0x20；传 Garmin Connect 用 0x02）")

    args = ap.parse_args()
    {"extract": cmd_extract, "apply": cmd_apply}[args.cmd](args)
