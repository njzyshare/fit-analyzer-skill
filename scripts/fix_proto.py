import sys, datetime

# FIT 协议版本字节（header 第 2 字节）修复工具。
#
# 背景（2026-08-02 实测根因）：
#   - 高驰(COROS) 原生文件协议字节 = 0x20（COROS 私有取值，非标准 2.0）。
#   - 经 Garmin FIT SDK 重编码的文件协议字节 = 0x02（标准 protocol 2.0）。
#   - 若把 0x02 的文件交给 COROS app 读，COROS 会按私有规则解读 header，
#     导致开始时间等严重错乱（用户实测看到「凌晨 04:06」而非真实 09:36）。
#   - 传给 Garmin Connect 时则必须用标准 0x02，佳明按 UTC 时间戳正确解析。
# 所以：保留给 COROS 看的文件，协议字节必须是 0x20；传给佳明则是 0x02。
#
# 本工具只改协议字节这一处，并重算「header CRC（字节 0..11 → 12..13）」与
# 「file CRC（字节 0..len-2 → 末尾 2 字节）」两道校验——改协议字节会同时
# 让两道 CRC 失效，必须都重算，否则 checkIntegrity()=false。
#
# 使用 Garmin 自定义半字节查表 CRC（与 @garmin/fitsdk/src/crc-calculator.js 完全一致）。
# 用法：
#   python fix_proto.py <输入.fit> <输出.fit> [目标协议字节, 默认 0x20]
# 例：
#   python fix_proto.py merged.fit merged20.fit            # -> 0x20 (COROS 原生)
#   python fix_proto.py coros.fit coros_02.fit 0x02       # -> 0x02 (标准/佳明)

crcTable = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
            0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]

def update_crc(crc, value):
    # 低 4 位
    tmp = crcTable[crc & 0xF]
    crc = (crc >> 4) & 0x0FFF
    crc = crc ^ tmp ^ crcTable[value & 0xF]
    # 高 4 位
    tmp = crcTable[crc & 0xF]
    crc = (crc >> 4) & 0x0FFF
    crc = crc ^ tmp ^ crcTable[(value >> 4) & 0xF]
    return crc

def calc_crc(buf, start, end):
    crc = 0
    for i in range(start, end):
        crc = update_crc(crc, buf[i])
    return crc & 0xFFFF

def main(src, dst, target=0x20):
    with open(src, 'rb') as f:
        buf = bytearray(f.read())
    cur = buf[1]
    if cur == target:
        print(f"协议字节已是 {target:#04x}，无需修改，仅复制")
    else:
        old = cur
        buf[1] = target
        hcrc = calc_crc(buf, 0, 12)
        buf[12] = hcrc & 0xFF
        buf[13] = (hcrc >> 8) & 0xFF
        fcrc = calc_crc(buf, 0, len(buf) - 2)
        buf[len(buf) - 2] = fcrc & 0xFF
        buf[len(buf) - 1] = (fcrc >> 8) & 0xFF
        print(f"协议字节 {old:#04x} -> {target:#04x}；重算 headerCRC={hcrc:#06x} fileCRC={fcrc:#06x}")
    with open(dst, 'wb') as f:
        f.write(buf)
    print("已写出:", dst, len(buf), "bytes")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("用法: python fix_proto.py <输入.fit> <输出.fit> [目标协议字节, 默认 0x20]")
        sys.exit(1)
    t = 0x20
    if len(sys.argv) >= 4:
        t = int(sys.argv[3], 0)
    main(sys.argv[1], sys.argv[2], t)
