# -*- coding: utf-8 -*-
"""佳明 FIT → 高驰原生 FIT（严格按高驰字段布局重建）。

与 inject_coros_device.mjs 的区别：
  - inject_*  用 @garmin/fitsdk 重编码 -> 字段布局跟随佳明 profile（不符合高驰规范）
  - 本脚本    直接用高驰的字段定义自己拼字节 -> lap/session/device_info 严格 24/24/3 字段

数据来源：源 FIT 的 record / lap / session / event（按字段号读取）。
字段映射：见 references/format_spec_garmin_vs_coros.md。

用法：
  python fit_to_coros_mapped.py 输入.fit 输出.fit
  python fit_to_coros_mapped.py 输入.fit 输出.fit --ref 高驰真机.fit
"""
import argparse
import json
import os
import struct
import sys

sys.stdout.reconfigure(encoding='utf-8')

STORE = os.path.join(os.path.expanduser('~'), '.workbuddy', 'private', 'fit_devices.json')

# ---------- 基本类型 ----------
ENUM, U8, U16, U32, S8, S16, S32, F32, STR, BYTE = (
    0x00, 0x02, 0x84, 0x86, 0x01, 0x83, 0x85, 0x88, 0x07, 0x0D)
INV = {1: 0xFF, 2: 0xFFFF, 4: 0xFFFFFFFF}

# ---------- 高驰字段布局（照抄真机，勿改）----------
# ---------- 高驰字段布局（照抄真机，勿改）----------
# 开发字段的第三个字节不是类型码，而是「引用 206 field_description 的索引」，
# 真机里恒为 0。写成 136(0x88) 会让解析器读成 4 元组。
DEV16 = [(16, 4, 0)]

COROS_DEFS = {
    # (global, 普通字段, 开发字段, local)
    # local 号照抄真机首次出现的值：
    #   0=0, 207=3, 23=4, 34=1, 21=10, 206=0, 20=9, 19=7, 18=2
    0:   ([(0, 1, ENUM), (1, 2, U16), (4, 4, U32), (2, 2, U16), (8, 18, STR)], [], 0),
    207: ([(2, 2, U16), (3, 1, U8), (1, 16, BYTE)], [], 3),
    23:  ([(253, 4, U32), (2, 2, U16), (27, 18, STR)], [], 4),
    34:  ([(253, 4, U32), (0, 4, U32), (5, 4, U32), (1, 2, U16),
           (2, 1, ENUM), (3, 1, ENUM), (4, 1, ENUM)], [], 1),
    21:  ([(253, 4, U32), (0, 1, ENUM), (1, 1, ENUM), (4, 1, U8)], [], 10),
    206: ([(0, 1, U8), (1, 1, U8), (2, 1, U8), (3, 12, STR), (8, 4, STR)], [], 0),
    # record 用真机的「变体 5」（15 字段 + dev16），字段顺序严格照抄：
    #   [42, 253, 0, 1, 5, 3, 2, 6, 4, 7, 29, 41, 39, 83, 85] + dev16(local 9)
    20:  ([(42, 1, ENUM), (253, 4, U32), (0, 4, S32), (1, 4, S32),
           (5, 4, U32), (3, 1, U8), (2, 2, U16), (6, 2, U16), (4, 1, U8),
           (7, 2, U16), (29, 4, U32), (41, 2, U16), (39, 2, U16),
           (83, 2, U16), (85, 2, U16)],
          DEV16, 9),
    19:  ([(254, 2, U16), (253, 4, U32), (2, 4, U32), (8, 4, U32), (7, 4, U32),
           (9, 4, U32), (11, 2, U16), (25, 1, ENUM), (16, 1, U8), (63, 1, U8),
           (15, 1, U8), (50, 1, S8), (14, 2, U16), (13, 2, U16), (17, 1, U8),
           (120, 2, U16), (18, 1, U8), (22, 2, U16), (21, 2, U16), (19, 2, U16),
           (79, 2, U16), (78, 2, U16), (77, 2, U16), (118, 2, U16)],
          DEV16, 7),
    18:  ([(5, 1, ENUM), (2, 4, U32), (253, 4, U32), (7, 4, U32), (8, 4, U32),
           (9, 4, U32), (11, 2, U16), (17, 1, U8), (64, 1, U8), (16, 1, U8),
           (57, 1, S8), (22, 2, U16), (23, 2, U16), (10, 4, U32), (19, 1, U8),
           (18, 1, U8), (134, 2, U16), (15, 2, U16), (14, 2, U16), (20, 2, U16),
           (91, 2, U16), (133, 2, U16), (89, 2, U16), (132, 2, U16)],
          DEV16, 2),
}


# ---------- 读取源 FIT ----------
def read_fit(path):
    d = open(path, 'rb').read()
    hs = d[0]
    be = hs + struct.unpack_from('<I', d, 4)[0]
    i = hs
    defs = {}
    msgs = []
    while i + 1 < be:
        st = i
        hdr = d[i]; i += 1
        if (hdr & 0x40) == 0x40:
            hdev = bool(hdr & 0x20); loc = hdr & 0x0F; i += 1
            if i >= be: break
            en = '<' if d[i] == 0 else '>'; i += 1
            g = struct.unpack_from(en + 'H', d, i)[0]; i += 2
            nf = d[i]; i += 1
            fs = []
            for _ in range(nf):
                fs.append((d[i], d[i+1], d[i+2])); i += 3
            dv = []
            if hdev:
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
        ok = True
        for (n, sz, bt) in pf:
            if o + sz > be:
                ok = False; break
            raw = d[o:o+sz]
            if bt == STR:
                vals[n] = raw.rstrip(b'\x00').decode('utf-8', 'replace')
            elif sz == 1:
                vals[n] = raw[0]
            elif sz == 2:
                vals[n] = struct.unpack('<h' if bt == S16 else '<H', raw)[0]
            elif sz == 4:
                if bt == S32:
                    vals[n] = struct.unpack('<i', raw)[0]
                elif bt == F32:
                    vals[n] = struct.unpack('<f', raw)[0]
                else:
                    vals[n] = struct.unpack('<I', raw)[0]
            else:
                vals[n] = raw
            o += sz
        if not ok:
            break
        for (n, sz, bt) in dv:
            if o + sz > be:
                break
            raw = d[o:o+sz]
            vals[f'dev{n}'] = struct.unpack('<f', raw)[0] if (sz == 4 and bt == F32) else raw
            o += sz
        msgs.append((g, vals))
        i += sum(f[1] for f in pf) + sum(f[1] for f in dv)
    return msgs


# ---------- 写入 ----------
def enc_val(width, bt, v):
    """按宽度和类型编码；None/无效 -> 哨兵。

    ⚠️ 哨兵必须「按类型码」选，不能一律填 0xFF：
      - 无符号类型（U8/U16/U32）的无效值 = 全 1（0xFF / 0xFFFF / 0xFFFFFFFF）
      - 有符号类型（S8/S16/S32）的无效值 = 最小值 bits 全 1 后右移一位，
        即 S8=0x7F(127)、S16=0x7FFF、S32=0x7FFFFFFF
    我之前对 S8 的 f50(avgTemperature) 填了 0xFF，被解析成 -1/255，
    高驰页面就显示成 255℃。踩过，别再犯。
    """
    if v is None:
        if width == 1:
            return b'\x7F' if bt == S8 else b'\xFF'
        if width == 2:
            return struct.pack('<h', 0x7FFF) if bt == S16 else b'\xFF\xFF'
        if width == 4:
            if bt == S32:
                return struct.pack('<i', 0x7FFFFFFF)
            return b'\xFF' * 4
        return b'\xFF' * width
    # byte 数组（如 developer_data_id 的 application_id）：原样填充，缺位补 0x00
    if bt == BYTE or isinstance(v, (bytes, bytearray)):
        b = bytes(v)
        return b[:width].ljust(width, b'\x00')
    if bt == STR:
        b = v.encode('utf-8') if isinstance(v, str) else bytes(v)
        return b[:width].ljust(width, b'\x00')
    if bt == F32:
        try:
            if v != v:  # NaN
                return struct.pack('<f', float('nan'))
        except TypeError:
            pass
        return struct.pack('<f', float(v))
    if isinstance(v, float):
        v = int(round(v))
    if width == 1:
        return bytes([v & 0xFF])
    if width == 2:
        return struct.pack('<h' if bt == S16 else '<H', v & 0xFFFF)
    if width == 4:
        if bt == S32:
            return struct.pack('<i', v)
        return struct.pack('<I', v & 0xFFFFFFFF)
    return b'\xFF' * width


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def def_bytes(self, gnum):
        return self.def_bytes_alt_local(gnum, None)

    def def_bytes_alt_local(self, gnum, local_override):
        """同 def_bytes，但可覆盖 local 号（用于复刻高驰重复声明 206 的写法）。"""
        fields, devs, local = COROS_DEFS[gnum]
        if local_override is not None:
            local = local_override
        hdr = 0x40 | (0x20 if devs else 0x00) | (local & 0x0F)
        out = bytearray([hdr, 0x00, 0x00])
        out += struct.pack('<H', gnum)
        out += bytes([len(fields)])
        for (n, sz, bt) in fields:
            out += bytes([n, sz, bt])
        if devs:
            out += bytes([len(devs)])
            for (n, sz, bt) in devs:
                out += bytes([n, sz, bt])
        return bytes(out)

    def data_bytes_alt_local(self, gnum, local_override, vals):
        fields, devs, local = COROS_DEFS[gnum]
        if local_override is not None:
            local = local_override
        out = bytearray([local])
        for (n, sz, bt) in fields:
            out += enc_val(sz, bt, vals.get(n))
        for (n, sz, bt) in devs:
            dev_val = vals.get(f'dev{n}')
            if sz == 4:
                out += enc_val(sz, F32, dev_val)
            else:
                out += enc_val(sz, bt, dev_val)
        return bytes(out)

    def data_bytes(self, gnum, vals):
        fields, devs, local = COROS_DEFS[gnum]
        out = bytearray([local])
        for (n, sz, bt) in fields:
            out += enc_val(sz, bt, vals.get(n))
        for (n, sz, bt) in devs:
            # 开发字段的第三个字节 0 是「206 声明索引」而非类型码；
            # 实际类型由 field_description 决定（本项目恒为 float32）。
            dev_val = vals.get(f'dev{n}')
            if sz == 4:
                out += enc_val(sz, F32, dev_val)
            else:
                out += enc_val(sz, bt, dev_val)
        return bytes(out)

    # ---- 渐进式布局支持（供 record 用）----
    def def_bytes_subset(self, gnum, field_nums=None, dev_nums=None):
        """按字段子集生成 DEF，用于复刻高驰的「渐进式布局」。"""
        fields, devs, local = COROS_DEFS[gnum]
        if field_nums is not None:
            fields = [f for f in fields if f[0] in field_nums]
        if dev_nums is not None:
            devs = [f for f in devs if f[0] in dev_nums]
        hdr = 0x40 | (0x20 if devs else 0x00) | (local & 0x0F)
        out = bytearray([hdr, 0x00, 0x00])      # reserved + endian(小端)
        out += struct.pack('<H', gnum)
        out += bytes([len(fields)])
        for (n, sz, bt) in fields:
            out += bytes([n, sz, bt])
        if devs:
            out += bytes([len(devs)])
            for (n, sz, bt) in devs:
                out += bytes([n, sz, bt])
        return bytes(out)

    def data_bytes_subset(self, gnum, vals, field_nums=None, dev_nums=None):
        """按字段子集生成 MSG，与 def_bytes_subset 配套使用。"""
        fields, devs, local = COROS_DEFS[gnum]
        if field_nums is not None:
            fields = [f for f in fields if f[0] in field_nums]
        if dev_nums is not None:
            devs = [f for f in devs if f[0] in dev_nums]
        out = bytearray([local])
        for (n, sz, bt) in fields:
            out += enc_val(sz, bt, vals.get(n))
        for (n, sz, bt) in devs:
            dev_val = vals.get(f'dev{n}')
            if sz == 4:
                out += enc_val(sz, F32, dev_val)
            else:
                out += enc_val(sz, bt, dev_val)
        return bytes(out)


def load_device(key='coros_apex4'):
    if not os.path.exists(STORE):
        raise SystemExit(f'私有设备库不存在: {STORE}，先运行 extract_devices.py')
    d = json.load(open(STORE, encoding='utf-8'))
    return d['devices'][key]


def crc16(data):
    table = [0x0000, 0xCC01, 0xD801, 0x1400, 0xF001, 0x3C00, 0x2800, 0xE401,
             0xA001, 0x6C00, 0x7800, 0xB401, 0x5000, 0x9C01, 0x8801, 0x4400]
    crc = 0
    for b in data:
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ table[b & 0xF]
        tmp = table[crc & 0xF]
        crc = (crc >> 4) & 0x0FFF
        crc = crc ^ tmp ^ table[(b >> 4) & 0xF]
    return crc


def main():
    ap = argparse.ArgumentParser(description='佳明 FIT → 高驰原生 FIT（严格字段布局）')
    ap.add_argument('input')
    ap.add_argument('output')
    ap.add_argument('--device', default='coros_apex4')
    a = ap.parse_args()

    dev = load_device(a.device)
    msgs = read_fit(a.input)
    print(f'源文件: {len(msgs)} 条消息')

    recs = [v for (g, v) in msgs if g == 20]
    laps = [v for (g, v) in msgs if g == 19]
    sess = [v for (g, v) in msgs if g == 18][0]
    evs = [v for (g, v) in msgs if g == 21]
    print(f'  record {len(recs)}  lap {len(laps)}  event {len(evs)}')

    start = sess.get(2) or 0
    elapsed = sess.get(7) or 0
    timer = sess.get(8) or 0
    dist = sess.get(9) or 0

    w = Writer()
    # ---- file_id ----
    w.buf += w.def_bytes(0)
    w.buf += w.data_bytes(0, {
        0: 4,                       # type = activity
        1: dev['manufacturer'],     # 294
        4: start,                   # time_created
        2: dev['product'],          # 814
        8: dev['product_name'],     # COROS APEX 4 42mm
    })

    # ---- developer_data_id (207) ----
    w.buf += w.def_bytes(207)
    w.buf += w.data_bytes(207, {
        2: dev['manufacturer'],
        3: 0,
        1: bytes([0] * 15 + [0x47]),
    })

    # ---- device_info (23) ----
    w.buf += w.def_bytes(23)
    w.buf += w.data_bytes(23, {
        253: start,
        2: dev['manufacturer'],
        27: dev['product_name'],
    })

    # ---- activity (34) ----
    # 参考真机: f0=总计时(ms) f5=活动结束时间 f1=1 f3=圈数 f4=1
    w.buf += w.def_bytes(34)
    w.buf += w.data_bytes(34, {
        253: start,
        0: timer,                 # total_timer_time (ms)
        5: start + (elapsed // 1000),   # 活动结束时间
        1: 1,                     # num_sessions
        2: 0,                     # type = manual
        3: len(laps),             # num_laps
        4: 1,                     # event = activity
    })

    # ---- event (21) ----
    w.buf += w.def_bytes(21)
    for e in evs:
        w.buf += w.data_bytes(21, {
            253: e.get(253),
            0: e.get(0),
            1: e.get(1),
            4: e.get(4),
        })

    # ---- field_description (206) ----
    # 高驰真机会用「两个不同 local」重复声明同一条开发者字段（local 0 与 local 8），
    # 内容完全一样。这里照抄，避免解析器按 local 号区分时出岔。
    # （206 的 COROS_DEFS local 固定为 0；这里额外写一个 local 8 的副本。）
    _fd_vals = {0: 0, 1: 16, 2: 136, 3: 'Effort Pace', 8: 'm/s'}
    w.buf += w.def_bytes(206)
    w.buf += w.data_bytes(206, _fd_vals)
    w.buf += w.def_bytes_alt_local(206, 8)
    w.buf += w.data_bytes_alt_local(206, 8, _fd_vals)

    # ---- record (20) ----
    # 全部字段按【FIT 官方定义 scale/offset】处理（见 references/fit_profile_official.json）。
    #
    # 🔴 「渐进式布局」：高驰真机的 record 不是一上来就用全字段布局，而是
    #    前 9 条从少到多逐步声明（见 PROGRESSIVE_RECORD_SCHEDULE 注释）。
    #    这很可能是 FIT 解析器的「字段可用起点」声明机制，影响高驰对
    #    「数据从哪一秒开始有效」的判断（进而影响最快 1KM 等派生指标）。
    #    因此下面按真机的节奏分段写 DEF + MSG，而不是全程单一布局。
    #
    # 佳明源   → 高驰    官方名称            换算
    #  f78     →  f2     enhancedAltitude   (v/5-500) 米 → 回写 (米+500)*5
    #  f73     →  f6     enhancedSpeed      v/1000 = m/s → 回写 m/s*1000
    #  f3      →  f3     heartRate          直搬
    #  f4      →  f4     cadence            直搬
    #  f5      →  f5     distance           cm，直搬
    #  f0/f1   →  f0/f1  positionLat/Long   直搬
    #  f7      →  f7     power              W，直搬
    #  f29     →  f29    accumulatedPower   W，直搬
    #  f39     →  f39    verticalOscillation mm（scale 10），直搬
    #  f41     →  f41    stanceTime         ms（scale 10），直搬
    #  f83     →  f83    verticalRatio      %（scale 100），直搬
    #  f85     →  f85    stepLength         mm（scale 10），直搬
    # ⚠️ 千万注意：f73 是 enhancedSpeed，f78 才是 enhancedAltitude —— 我一度搞反，
    #    把速度当海拔算，导致 6000 米的假海拔。

    # 速度：源 f73（enhancedSpeed, raw/1000 = m/s）。
    # 另外用「距离差分」交叉校验；两者差异大时以差分为准，再做中值平滑。
    #
    # 🔴🔴 铁律：速度 0 是「有效值」，绝不能过滤、更不能被平滑抹掉！
    #   高驰靠「speed==0」识别暂停/静止段，进而算移动时间；
    #   移动时间算不出来 → 最快 1KM / 最佳配速整块空白。
    #   我最初写成 `if 0 < cand < 20`，把暂停点的 0 排掉，
    #   再用滑动中值拿邻居正值顶上 → 高驰看到的是「一路匀速、从不暂停」，
    #   于是既算不出区间成绩，距离还出现 29s 不前进的断裂。踩过，别再犯。
    # 速度优先级（血泪教训后的定稿）：
    #   ① 源 enhancedSpeed(f73) 有效  → 一律采用（它是设备融合后的结果，已做过平滑）
    #   ② 源无效                     → 退回「距离差分」
    # 早期版本反过来（差分优先），结果：
    #   - 起跑段 GPS 冷启动漂移 → 差分算出 4.03 m/s，源实际只有 1.60 m/s，起步被抬高；
    #   - 暂停段距离漂移        → 差分把 0 抬成正值，高驰认不出暂停。
    # 两个 bug 的根因是同一个：不该拿粗糙的差分去覆盖设备已经算好的速率。
    raw_spd = []
    prev = None
    for r in recs:
        ts = r.get(253)
        dist_cm = r.get(5)
        v = None
        src_spd = r.get(73)                  # enhancedSpeed
        if src_spd not in (None, 0xFFFFFFFF):
            cand = src_spd / 1000.0
            if 0 <= cand < 20:               # ← 含 0（暂停）
                v = cand
        # 仅当源无有效速度时，才用距离差分兜底
        if v is None and prev and ts is not None and prev[0] is not None \
                and dist_cm is not None and prev[1] is not None:
            dt = ts - prev[0]
            dd = dist_cm - prev[1]
            if dt > 0 and dd >= 0:
                diff = (dd / 100.0) / dt
                if 0 <= diff < 20:
                    v = diff
        if ts is not None and dist_cm is not None:
            prev = (ts, dist_cm)
        raw_spd.append(v)

    # ⚠️ 不再做中值平滑！
    #   源 enhancedSpeed 是设备（气压/加速度/GPS 融合）已经平滑过的结果，
    #   我再平滑一次会破坏两处真实形态：
    #     ① 暂停段的 0 会被邻居正值抬高 → 高驰认不出暂停；
    #     ② 起跑/冲刺的快速变化被抹平 → 最快 1km 不真实。
    #   源缺值时用差分补的点占极少数，不值得为它牺牲全局真实性。
    #   仅对「源缺值、靠差分补出」的点做一次轻量校验（剔除 >12 m/s 的荒谬值）。
    speed_seq = [
        (v if (v is None or v < 12) else None)
        for v in raw_spd
    ]

    n_zero = sum(1 for x in raw_spd if x == 0)
    n_derived = sum(1 for r, v in zip(recs, raw_spd)
                    if v is not None and r.get(73) in (None, 0xFFFFFFFF))
    if n_zero:
        print(f'  识别到 {n_zero} 个静止/暂停点（速度 0，高驰据此划分移动段）')
    if n_derived:
        print(f'  {n_derived} 个点源无速率、由距离差分兜底')

    # ---- 温度：源有就搬，源没有就留无效值 ----
    # 🔴 绝不编造！我曾写过「按月份给气候中位数」（8月=31℃、9月=28℃）这种兜底，
    #    那是凭空造数：产物里的温度会被当成实测值，比留空更糟。
    #    铁律：没有数据来源的字段，宁可留无效哨兵，也不填推测值。
    #    实测本佳明文件 record 无 temperature（f13）通道（fenix 8 需外接温度计），
    #    因此这里必然为 None → 写 S8 无效值 127。
    src_temp = None
    for r in recs:
        # record 的温度是 f13（sint8）。⚠️ 不是 f53（那是 fractionalCadence）。
        t = r.get(13)
        if t not in (None, 0x7F, 0xFF):
            sv = t if t < 0x80 else t - 256
            if -40 <= sv <= 60:
                src_temp = sv
                break
    if src_temp is None:
        for cand in (sess.get(57), laps[0].get(50) if laps else None):
            if cand not in (None, 0x7F, 0xFF):
                src_temp = cand if cand < 0x80 else cand - 256
                break
    if src_temp is None:
        print('  源无温度通道 → 留无效值（不编造）')
    temp_default = src_temp

    # 海拔：源 f78（enhancedAltitude, (米+500)*5）。实测本文件 6.6~16.2 米，
    # 与「福建平原海拔个位数」吻合，是可信数据。
    raw_alt_m = []
    for r in recs:
        v78 = r.get(78)                       # enhancedAltitude
        if v78 not in (None, 0, 0xFFFFFFFF):
            raw_alt_m.append(v78 / 5.0 - 500.0)
            continue
        v2 = r.get(2)                          # 退化到 altitude
        if v2 not in (None, 0, 0xFFFF):
            raw_alt_m.append(v2 / 5.0 - 500.0)
        else:
            raw_alt_m.append(None)

    # 渐进式布局方案（复刻高驰真机记录的前 9 条声明节奏）
    # 结构: (字段号集合, 开发字段号集合, 条数)
    PROG = [
        ([42, 253, 5], [], 1),
        ([42, 253, 0, 1, 5, 3], [], 2),
        ([42, 253, 0, 1, 5, 3, 6, 41, 39, 83], [16], 2),
        ([42, 253, 0, 1, 5, 3, 2, 6, 41, 39, 83], [16], 2),
        ([42, 253, 0, 1, 5, 3, 2, 6, 7, 29, 41, 39, 83, 85], [16], 2),
    ]
    FULL_F = [42, 253, 0, 1, 5, 3, 2, 6, 4, 7, 29, 41, 39, 83, 85]
    FULL_D = [16]

    _prog_idx = 0
    _prog_rest = PROG[0][2] if PROG else 0
    _cur_key = None

    for idx, r in enumerate(recs):
        ts = r.get(253)
        dist_cm = r.get(5)
        spd_ms = speed_seq[idx] if idx < len(speed_seq) else None
        # ⚠️ 不能用 `if spd_ms`：0 是合法速度（暂停），会被当成假值丢掉。
        #    必须显式判 None。
        speed_mm = int(round(spd_ms * 1000)) if spd_ms is not None else None

        # 海拔：回写成 FIT 标准 (米+500)*5（u16），绝不能超出 0..65534
        am = raw_alt_m[idx] if idx < len(raw_alt_m) else None
        alt_raw = None
        if am is not None:
            alt_raw = int(round((am + 500.0) * 5))
            if not (0 <= alt_raw <= 65534):
                alt_raw = None

        vals = {42: 1, 253: ts, 5: dist_cm, 0: r.get(0), 1: r.get(1),
                3: r.get(3), 2: alt_raw, 6: speed_mm, 4: r.get(4),
                7: r.get(7), 29: r.get(29), 41: r.get(41), 39: r.get(39),
                83: r.get(83), 85: r.get(85),
                'dev16': spd_ms if spd_ms is not None else float('nan')}

        # 选本次用的字段子集
        if _prog_idx < len(PROG):
            fset, dset, _ = PROG[_prog_idx]
            if _prog_rest <= 0:
                _prog_idx += 1
                if _prog_idx < len(PROG):
                    fset, dset, _ = PROG[_prog_idx]
                    _prog_rest = PROG[_prog_idx][2]
                else:
                    fset, dset = FULL_F, FULL_D
            _prog_rest -= 1
        else:
            fset, dset = FULL_F, FULL_D

        key = (tuple(fset), tuple(dset))
        if key != _cur_key:
            w.buf += w.def_bytes_subset(20, fset, dset)
            _cur_key = key
        w.buf += w.data_bytes_subset(20, vals, fset, dset)

    # ---- lap (19) ----
    w.buf += w.def_bytes(19)
    for l in laps:
        di = l.get(9) or 0
        ti = l.get(8) or 0
        st = l.get(2) or start
        el = l.get(7) or 0
        # f13 平均速度 = 距离÷计时（与真机规律一致，逐圈精确）
        avg_spd = (di / 100.0) / (ti / 1000.0) if (ti and di) else None
        # f63 最小心率 / f14 最大速度 / f78 触地占比：源无 -> 从 record 流按圈时间窗推导
        win_hr, win_spd = [], []
        t0, t1 = st, st + (el // 1000)
        for r in recs:
            t = r.get(253)
            if t is None or not (t0 <= t <= t1):
                continue
            h = r.get(3)
            if h not in (None, 0xFF):
                win_hr.append(h)
        # 用同一时间窗内的逐点速度（speed_seq 与 recs 一一对应，用 enumerate 保证对齐）
        for idx, r in enumerate(recs):
            t = r.get(253)
            if t is None or not (t0 <= t <= t1):
                continue
            s = speed_seq[idx] if idx < len(speed_seq) else None
            if s:
                win_spd.append(s)
        min_hr = min(win_hr) if win_hr else None
        max_spd = max(win_spd) if win_spd else avg_spd

        # 过滤无效值：s8 的 127、u8 的 255 都不是真实读数
        def ok8(v, upper=126):
            return v if (v is not None and 0 < v <= upper) else None

        # 速度：官方定义下佳明 lap 的 f13/f14 常为无效，
        # 真实速度在 f110(enhancedAvgSpeed)/f111(enhancedMaxSpeed)，scale 1000。
        src_avg = l.get(110)
        src_max = l.get(111)
        if src_avg not in (None, 0xFFFFFFFF) and src_avg > 0:
            avg_spd = src_avg / 1000.0
        src_avg2, src_max2 = avg_spd, None
        if src_max not in (None, 0xFFFFFFFF) and src_max > 0:
            src_max2 = src_max / 1000.0
        max_spd = max([x for x in (src_max2, max_spd) if x], default=None)

        w.buf += w.data_bytes(19, {
            254: l.get(254),
            253: l.get(253),
            2: st,
            8: ti,
            7: el,
            9: di,
            11: l.get(11),
            25: 1,
            16: l.get(16),
            63: min_hr,                     # minHeartRate（源缺则从 record 推导）
            15: l.get(15),                  # avgHeartRate
            50: l.get(50) if l.get(50) not in (None, 0x7F) else temp_default,  # avgTemperature（S8）
            78: 0,                         # avgStanceTimePercent：高驰真机恒为 0（未测填 0，不是无效值）
            14: int(round(max_spd * 1000)) if max_spd else None,   # maxSpeed
            13: int(round(avg_spd * 1000)) if avg_spd else None,   # avgSpeed
            17: l.get(17),                  # avgCadence
            120: l.get(120),                # avgStepLength
            18: l.get(18),                  # maxCadence
            22: l.get(22),                  # totalDescent
            21: l.get(21),                  # totalAscent
            19: l.get(19),                  # avgPower（不是垂直振幅）
            79: l.get(79),                  # avgStanceTime
            78: l.get(78),                  # avgStanceTimePercent（源无则留无效，不编造）
            77: l.get(77),                  # avgVerticalOscillation
            118: l.get(118),                # avgVerticalRatio
            'dev16': avg_spd if avg_spd else float('nan'),
        })

    # ---- session (18) ----
    # 速度：官方定义下佳明 session 的 f14/f15 常无效，
    # 真实速度在 f124(enhancedAvgSpeed)/f125(enhancedMaxSpeed)，scale 1000。
    w.buf += w.def_bytes(18)
    s_avg_spd = None
    s_max_spd = None
    v124 = sess.get(124)
    if v124 not in (None, 0xFFFFFFFF) and v124 > 0:
        s_avg_spd = v124 / 1000.0
    v125 = sess.get(125)
    if v125 not in (None, 0xFFFFFFFF) and v125 > 0:
        s_max_spd = v125 / 1000.0
    if s_avg_spd is None:
        s_avg_spd = (dist / 100.0) / (timer / 1000.0) if (timer and dist) else None

    w.buf += w.data_bytes(18, {
        5: sess.get(5) or 1,
        2: start,
        253: start + (elapsed // 1000),
        7: elapsed,
        8: timer,
        9: dist,
        11: sess.get(11),
        17: sess.get(17),
        64: sess.get(64),
        16: sess.get(16),
        57: sess.get(57) if sess.get(57) not in (None, 0x7F) else temp_default,   # avgTemperature（S8）
        22: sess.get(22),
        23: sess.get(23),
        10: sess.get(10),
        19: sess.get(19),
        18: sess.get(18),
        134: sess.get(134),
        15: int(round(s_max_spd * 1000)) if s_max_spd else None,
        14: int(round(s_avg_spd * 1000)) if s_avg_spd else None,
        20: sess.get(20),
        91: sess.get(91),
        133: sess.get(133),             # avgStanceTimeBalance（源无则留无效，不编造）
        89: sess.get(89),
        132: sess.get(132),
        'dev16': s_avg_spd if s_avg_spd else float('nan'),
    })

    body = bytes(w.buf)
    header = bytearray([14, 32])            # 高驰 protocol_version = 32
    header += struct.pack('<H', 21158)
    header += struct.pack('<I', len(body))
    header += b'.FIT'
    header += struct.pack('<H', crc16(bytes(header[:12])))

    out = bytes(header) + body
    out += struct.pack('<H', crc16(out))
    open(a.output, 'wb').write(out)
    print(f'已生成 {a.output} ({len(out)} bytes)')


if __name__ == '__main__':
    main()
