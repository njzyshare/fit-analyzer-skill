#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_shift_time.py — FIT 活动「整体平移时间戳」工具
==================================================

把一次运动的所有时间戳字段统一平移 delta 秒，从而改变开始时间、但**保持时长不变**。
典型用途：用户把运动记录传了某平台后又删除，平台按"已上传"去重导致无法重传，
于是把开始时间从 17:28 改成 05:28 规避（平移 -12h）。

为什么用字节级定点修补，而不是重新编码：
  - garmin-fit-sdk Encoder 拒写私有设备消息（如 fenix8 的 mesg_num 233），
    重新编码会丢私有消息流；
  - fitparse 没有写方法。
  字节级只改时间戳字段的 4 字节小端值，其余字节原样保留，文件最"原汁原味"。

平移哪些字段（绝对时间，base type=date_time=uint32，4 字节）：
  - 所有消息的 field 253（timestamp，消息时间戳）—— 一律平移；
  - file_id 的 field 4（time_created）—— 平移；
  - session 的 field 2（start_time）—— 平移；
  - lap 的 field 2（start_time）—— 平移。
  其余字段（距离/心率/坐标/本地时间戳 field1 等）一律不动。
  压缩时间戳消息（header bit7）不存绝对时间，跟着参考时间戳走，无需处理。

CRC：必须用 fitdecode.utils.compute_crc，手搓 CRC 算出来和文件读到的对不上
（实战踩坑，详见 SKILL.md）。

用法：
  python fit_shift_time.py input.fit --delta-hours -12 -o output.fit
  python fit_shift_time.py input.fit --delta-seconds -43200        # 等价
  python fit_shift_time.py input.fit --set-start "2026-07-18 05:28:00"  # 指定新本地开始时间(UTC+8)
"""
import sys
import os
import struct
import argparse
import datetime

try:
    from fitdecode.utils import compute_crc
except Exception as e:  # pragma: no cover
    sys.stderr.write("缺少 fitdecode，请先安装：pip install fitdecode\n")
    raise

# FIT 全局消息号
MESG_FILE_ID = 0
MESG_SESSION = 18
MESG_LAP = 19

# base type = uint32 (date_time) 的大小
UINT32 = 4

# 需要平移的字段规则：(field_num, 仅限的 global mesg_num 集合 或 None 表示任意)
# field 253 = timestamp，任意消息都平移
# file_id(0) field 4 = time_created
# session(18)/lap(19) field 2 = start_time
SHIFT_RULES = [
    (253, None),
    (4, {MESG_FILE_ID}),
    (2, {MESG_SESSION, MESG_LAP}),
]


def _should_shift(field_num, global_mesg):
    for fn, allowed in SHIFT_RULES:
        if fn == field_num and (allowed is None or global_mesg in allowed):
            return True
    return False


def shift_fit(in_path, out_path, delta_seconds, verbose=False):
    with open(in_path, "rb") as f:
        data = bytearray(f.read())

    hdr_size = data[0]
    # 数据区起点 = 头大小（12 或 14，14 时 [12:14] 是头 CRC，保留不动）
    off_start = hdr_size
    end = len(data) - 2  # 末尾 2 字节是文件 CRC

    local_defs = {}  # local_type(0..31) -> dict(arch, global, fields[(fnum,size,bt)], size)

    p = off_start
    n_shifted = 0
    n_data = 0
    n_def = 0

    while p < end:
        hdr = data[p]
        if hdr & 0x80:
            # 压缩时间戳数据消息：1 头 + 1 压缩时间字节 + 字段
            lmt = hdr & 0x1F
            dev = (hdr & 0x20) != 0
            if lmt not in local_defs:
                raise ValueError("压缩数据消息在 %d 处缺少定义" % p)
            d = local_defs[lmt]
            p += 1  # header
            p += 1  # compressed timestamp byte
            p += d["size"]
            if dev:
                ndf = data[p]
                p += 1
                for _ in range(ndf):
                    dsize = data[p + 1]
                    p += 3 + dsize
            n_data += 1
            continue

        is_def = (hdr & 0x40) != 0
        dev_flag = (hdr & 0x20) != 0
        lmt = hdr & 0x1F

        if is_def:
            arch = data[p + 2]
            if arch not in (0, 1):
                raise ValueError("定义消息在 %d 处 arch=%d 非法" % (p, arch))
            glob = struct.unpack("<H" if arch == 0 else ">H", data[p + 3:p + 5])[0]
            nf = data[p + 5]
            fields = []
            q = p + 6
            for _ in range(nf):
                fnum = data[q]
                fsize = data[q + 1]
                fbt = data[q + 2]
                fields.append((fnum, fsize, fbt))
                q += 3
            if dev_flag:
                ndf = data[q]
                q += 1
                for _ in range(ndf):
                    q += 3  # dev field def: num,size,dev_index
            size = sum(f[1] for f in fields)
            local_defs[lmt] = {"arch": arch, "global": glob, "fields": fields, "size": size}
            p = q
            n_def += 1
        else:
            # 数据消息
            d = local_defs.get(lmt)
            if d is None:
                raise ValueError("数据消息在 %d 处缺少定义 (local=%d)" % (p, lmt))
            q = p + 1  # 跳过 header
            body = q
            shifted_here = []
            for (fnum, fsize, fbt) in d["fields"]:
                if _should_shift(fnum, d["global"]) and fsize == UINT32:
                    raw = bytes(data[q:q + UINT32])
                    val = struct.unpack("<I", raw)[0]
                    new_val = (val + delta_seconds) & 0xFFFFFFFF
                    data[q:q + UINT32] = struct.pack("<I", new_val)
                    n_shifted += 1
                    shifted_here.append((fnum, val, new_val))
                q += fsize
            if dev_flag:
                ndf = data[q]
                q += 1
                for _ in range(ndf):
                    dsize = data[q + 1]
                    q += 3 + dsize
            p = q
            n_data += 1
            if verbose and shifted_here:
                for fnum, old, new in shifted_here:
                    sys.stderr.write(
                        "  shifted mesg=%d field=%d: %d -> %d\n"
                        % (d["global"], fnum, old, new)
                    )

    if p != end:
        raise ValueError("解析异常：停在 %d，预期 %d（文件可能含未支持的编码）" % (p, end))

    # 重算 CRC（覆盖 header+data，不含末尾 2 字节）
    new_crc = compute_crc(bytes(data[:-2]))
    data[-2:] = struct.pack("<H", new_crc)

    with open(out_path, "wb") as f:
        f.write(data)

    return {"n_def": n_def, "n_data": n_data, "n_shifted": n_shifted, "crc": new_crc}


def _local_str(utc_dt):
    # 假定时间戳是 UTC，转中国时区(UTC+8)展示
    return (utc_dt + datetime.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M:%S")


def main():
    ap = argparse.ArgumentParser(description="FIT 时间戳整体平移（改开始时间，保持时长）")
    ap.add_argument("input", help="输入 .fit 路径")
    ap.add_argument("-o", "--output", default=None, help="输出 .fit 路径（默认 <原名>_shifted.fit）")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--delta-seconds", type=int, help="平移秒数（负=往前，如 -43200 即 -12h）")
    g.add_argument("--delta-hours", type=float, help="平移小时数（负=往前，如 -12）")
    g.add_argument("--set-start", help="指定新的本地开始时间(UTC+8)，格式 'YYYY-MM-DD HH:MM:SS'，自动反推 delta")
    ap.add_argument("-v", "--verbose", action="store_true", help="打印每条被平移的字段")
    args = ap.parse_args()

    if args.delta_hours is not None:
        delta = int(round(args.delta_hours * 3600))
    elif args.delta_seconds is not None:
        delta = args.delta_seconds
    else:
        # --set-start：先读原 session.start_time，反推 delta
        import fitdecode
        target = datetime.datetime.strptime(args.set_start, "%Y-%m-%d %H:%M:%S")
        target_utc = target.replace(tzinfo=datetime.timezone.utc) - datetime.timedelta(hours=8)
        orig_start = None
        with fitdecode.FitReader(args.input) as r:
            for m in r:
                if isinstance(m, fitdecode.FitDataMessage) and m.name == "session":
                    orig_start = m.get_value("start_time")
                    break
        if orig_start is None:
            sys.stderr.write("未在文件中找到 session.start_time，无法用 --set-start\n")
            sys.exit(2)
        delta = int((target_utc - orig_start).total_seconds())

    out = args.output or (os.path.splitext(args.input)[0] + "_shifted.fit")

    info = shift_fit(args.input, out, delta, verbose=args.verbose)
    sys.stderr.write(
        "完成：定义消息 %d，数据消息 %d，平移时间戳字段 %d 处，delta=%+d 秒，新 CRC=0x%04X\n"
        % (info["n_def"], info["n_data"], info["n_shifted"], delta, info["crc"])
    )
    sys.stderr.write("输出：%s\n" % out)

    # 轻量自检：用 fitdecode 重算 CRC 并读新开始时间
    try:
        import fitdecode
        with open(out, "rb") as f:
            raw = f.read()
        stored = struct.unpack("<H", raw[-2:])[0]
        calc = compute_crc(raw[:-2])
        crc_ok = stored == calc
        new_start = None
        with fitdecode.FitReader(out) as r:
            for m in r:
                if isinstance(m, fitdecode.FitDataMessage) and m.name == "session":
                    new_start = m.get_value("start_time")
                    break
        sys.stderr.write("校验：CRC %s（0x%04X）\n" % ("OK" if crc_ok else "FAIL", stored))
        if new_start is not None:
            sys.stderr.write("新 session.start_time（本地 UTC+8）：%s\n" % _local_str(new_start))
    except Exception as e:
        sys.stderr.write("自检跳过：%s\n" % e)


if __name__ == "__main__":
    main()
