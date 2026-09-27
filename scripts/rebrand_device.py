#!/usr/bin/env python3
"""字节级替换 FIT 文件的设备身份（rebrand）。

把一个 FIT 文件的 file_id(global 0) + device_info(global 23) 两条消息，
替换成「参考文件」里的同名身份字节，同时：
  - 保留本活动自己的时间戳（file_id field 4 与 device_info field 253 改回本活动时间），
    使日期正确、压缩时间戳记录仍按同一时间线解码；
  - 其余所有字节（轨迹/计圈/session/事件/私有开发者字段）原样拼接；
  - 重算 header 的 data_size(偏移4) + header CRC(12-13) + 文件尾 CRC。

一个脚本覆盖两个方向（互逆）：
  → 高驰：参考文件用 COROS 设备导出的 .fit（如 APEX 4 42mm）
  → 佳明：参考文件用真实佳明设备导出的 .fit（如 fenix8）

解析统一用 fit_merge.walk（已验证正确，正确处理压缩时间戳 local 位与 dev 位 0x20），
不使用本文件早期自写、会漂移的 parse 实现。

用法：
  python rebrand_device.py <src.fit> <ref> <out.fit>
  ref 可为：设备名(apex4/fenix8) / 含 raw_identity 的 .json / 任意 .fit
"""
import struct, sys, datetime, os, json

# 正确的 FIT CRC-16（Garmin 半字节表，对应 Garmin SDK CrcCalculator）。
_TABLE = [0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,
          0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400]
def fit_crc16(data, crc=0):
    for value in data:
        tmp = _TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _TABLE[value & 0xF]
        tmp = _TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _TABLE[(value >> 4) & 0xF]
    return crc & 0xFFFF

# 复用 fit_merge.walk（正确的字节级帧遍历：压缩时间戳 local=(hb>>5)&3、dev 位 0x20 单字节索引）
import fit_merge as fm


def def_fields(raw_def):
    """从 definition 消息原始字节还原 (fnum,size,btype) 字段列表。

    raw_def 是完整 def 消息字节：hdr(0)/reserved(1)/arch(2)/gnum(3:5)/nf(5)/fields(6:)。
    字段从 raw[6] 起。
    """
    nf = raw_def[5]
    fields = []
    off = 6
    for _ in range(nf):
        fn = raw_def[off]; sz = raw_def[off+1]; bt = raw_def[off+2]
        fields.append((fn, sz, bt)); off += 3
    return fields


def field_offset(fields, fnum):
    """返回字段 fnum 在 data raw 内的偏移（含 1 字节 local 头）与 size。"""
    i = next(k for k, (fn, _, _) in enumerate(fields) if fn == fnum)
    p = 1 + sum(s for (fn, s, _) in fields[:i])
    sz = fields[i][1]
    return p, sz


def resolve_ref_identity(ref):
    """把 <ref> 解析成 (fid_def, fid_data, di_def, di_data) 四条原始字节。

    ref 支持三种形态：
      1) 设备名（如 apex4 / fenix8）→ 优先私人区 JSON 的 raw_identity，
         否则回退到已提交的 references/profiles/<name>_identity.json（仅无序列号设备）；
      2) .json 路径且含 raw_identity → 直接读取；
      3) .fit 路径 → 字节级解析（任意设备的一次性用法，不落盘）。
    Garmin 含序列号，raw_identity 只允许来自私人区 JSON，绝不进公开文件。
    """
    PROFILES = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            os.pardir, 'references', 'profiles')
    PRIVATE = os.path.expanduser("~/.workbuddy/private")
    def _as_bytes(d):
        return (bytes.fromhex(d['fid_def_hex'].replace(' ', '')),
                bytes.fromhex(d['fid_data_hex'].replace(' ', '')),
                bytes.fromhex(d['di_def_hex'].replace(' ', '')),
                bytes.fromhex(d['di_data_hex'].replace(' ', '')))
    # 1) 设备名
    if not ref.lower().endswith(('.fit', '.json')):
        for brand in ("coros", "garmin"):
            pj = os.path.join(PRIVATE, f"{brand}_devices.json")
            if os.path.exists(pj):
                store = json.load(open(pj, encoding='utf-8'))
                dev = store.get('devices', {}).get(ref)
                if dev and 'raw_identity' in dev:
                    return _as_bytes(dev['raw_identity'])
        # 已提交无序列号身份文件（命名兼容 <name>_identity.json / coros_<name>_identity.json / garmin_<name>_identity.json）
        for cand in (f"{ref}_identity.json", f"coros_{ref}_identity.json", f"garmin_{ref}_identity.json"):
            ij = os.path.join(PROFILES, cand)
            if os.path.exists(ij):
                d = json.load(open(ij, encoding='utf-8'))
                if 'raw_identity' in d:
                    return _as_bytes(d['raw_identity'])
        raise SystemExit(f"ERROR: 私人区/已提交区均无设备 {ref} 的 raw_identity")
    # 2) JSON
    if ref.lower().endswith('.json'):
        d = json.load(open(ref, encoding='utf-8'))
        if 'raw_identity' not in d:
            raise SystemExit(f"ERROR: {ref} 无 raw_identity")
        return _as_bytes(d['raw_identity'])
    # 3) .fit
    return extract_identity_from_fit(ref)


def identity_to_json(identity):
    """4 条原始字节 → raw_identity JSON（hex 空格分隔）。"""
    def hx(b):
        return " ".join(f"{x:02X}" for x in b)
    fid_def, fid_data, di_def, di_data = identity
    return {"fid_def_hex": hx(fid_def), "fid_data_hex": hx(fid_data),
            "di_def_hex": hx(di_def), "di_data_hex": hx(di_data)}


def extract_identity_from_fit(path):
    """从真实 .fit 抽取 file_id + device_info 的 def/data 原始字节。"""
    _, body = fm.read_body(path)
    frames = fm.walk(body)
    fd = next((f for f in frames if f['global'] == 0 and f['is_def']), None)
    fa = next((f for f in frames if f['global'] == 0 and not f['is_def']), None)
    dd = next((f for f in frames if f['global'] == 23 and f['is_def']), None)
    da = next((f for f in frames if f['global'] == 23 and not f['is_def']), None)
    if not all([fd, fa, dd, da]):
        raise SystemExit("ERROR: 参考 .fit 缺少 file_id/device_info")
    return fd['chunk'], fa['chunk'], dd['chunk'], da['chunk']


def build_identity(raw, src_time_created, src_fid_local, src_di_local):
    """从参考身份原始字节构造新 file_id / device_info def+data（local 用源文件，
    时间用本活动）。raw = (fid_def, fid_data, di_def, di_data)。"""
    new_fid_def = bytearray(raw[0])
    new_fid_def[0] = (new_fid_def[0] & 0xF0) | (src_fid_local & 0x0F)
    new_fid_data = bytearray(raw[1])
    new_fid_data[0] = src_fid_local & 0x0F
    fp, fsz = field_offset(def_fields(raw[0]), 4)
    new_fid_data[fp:fp+fsz] = struct.pack('<I', src_time_created)

    new_di_def = bytearray(raw[2])
    new_di_def[0] = (new_di_def[0] & 0xF0) | (src_di_local & 0x0F)
    new_di_data = bytearray(raw[3])
    new_di_data[0] = src_di_local & 0x0F
    dp, dsz = field_offset(def_fields(raw[2]), 253)
    new_di_data[dp:dp+dsz] = struct.pack('<I', src_time_created)

    return bytes(new_fid_def), bytes(new_fid_data), bytes(new_di_def), bytes(new_di_data)


def rebrand_core(d, hsize, frames, ref_identity, proto=None):
    """字节级拼接：替换 file_id + 第一条 device_info 为 ref 身份，其余原样。
    返回完整文件字节（含 header 与尾部 CRC）。proto=None 不改协议字节。"""
    fid_def, fid_data, di_def, di_data = ref_identity

    # 本活动自己的创建时间（file_id field 4）与源 local 号
    src_fid = next((f for f in frames if f['global'] == 0 and not f['is_def']), None)
    if src_fid is None:
        raise SystemExit("ERROR: 源文件缺少 file_id data 消息")
    src_fid_local = src_fid['hb'] & 0x0F
    raw_tc, _, _ = fm.read_field_raw(src_fid['chunk'], src_fid['dd'], 4,
                                     src_fid['compressed'], src_fid['dev'])
    src_time_created = struct.unpack('<I', raw_tc)[0]
    src_di = next((f for f in frames if f['global'] == 23), None)
    src_di_local = src_di['hb'] & 0x0F if src_di else src_fid_local

    nf_def, nf_data, nd_def, nd_data = build_identity(
        ref_identity, src_time_created, src_fid_local, src_di_local)

    body = bytearray()
    seen_fid = False
    di_count = 0
    for fr in frames:
        if fr['global'] == 0:                       # file_id：丢弃原始，替换为新身份
            if not seen_fid:
                body += nf_def
                body += nf_data
                seen_fid = True
            continue
        elif fr['global'] == 23:                    # device_info：只注入单条，其余丢弃
            if di_count == 0:
                body += nd_def
                body += nd_data
                di_count = 1
            continue
        else:
            body += fr['chunk']

    # 组装 header + body
    out = bytearray(d[:hsize])
    out += body
    # 修正 header data_size（偏移4）= header 之后、CRC 之前的字节数 = len(body)
    out[4:8] = struct.pack('<I', len(body))
    if proto is not None:
        out[1] = proto & 0xFF
    # 修正 header CRC（偏移12，覆盖字节 0..11）
    out[12:14] = struct.pack('<H', fit_crc16(bytes(out[0:12])))
    # 文件尾 CRC
    out += struct.pack('<H', fit_crc16(bytes(out)))
    return bytes(out), src_time_created


def main(src, ref, out):
    r_fid_def, r_fid_data, r_di_def, r_di_data = resolve_ref_identity(ref)
    d, hsize, frames = _load(src)
    out_b, tc = rebrand_core(d, hsize, frames, (r_fid_def, r_fid_data, r_di_def, r_di_data))

    open(out, 'wb').write(out_b)
    fc = struct.unpack('<H', out_b[-2:])[0]
    hc = struct.unpack('<H', out_b[12:14])[0]
    print(f"activity time_created = {tc} -> "
          f"{(datetime.datetime(1989,12,31)+datetime.timedelta(seconds=tc)).isoformat()}Z")
    print(f"wrote {out}: {len(out_b)} bytes (delta {len(out_b)-len(d):+d})")
    print(f"file CRC 0x{fc:04X} match={fc==fit_crc16(out_b[:-2])}; "
          f"header CRC 0x{hc:04X} match={hc==fit_crc16(out_b[0:12])}")


def _load(path):
    d, body = fm.read_body(path)
    return d, d[0], fm.walk(body)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
