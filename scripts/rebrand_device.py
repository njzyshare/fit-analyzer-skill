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
用法：
  python rebrand_device.py <src.fit> <ref.fit> <out.fit>

为什么用字节级而不是 SDK 重编码：
  - 字节级能 100% 保留私有/开发者字段与压缩时间戳消息布局；SDK 重编码会丢私有消息类型、且对压缩时间戳记录 desync。
  - 高驰 device_info 是非标准布局（product 字段=厂商码294、无 manufacturer 字段），
    Garmin SDK 的 Encoder 编不出这种布局（会把 294 放到错误字段，高驰直接拒收）。
  - 因此「复制参考身份字节 + 改本活动时间戳」是唯一可靠做法。
"""
import struct, sys, datetime

# 正确的 FIT CRC-16（Garmin 半字节表，对应 Garmin SDK CrcCalculator）。
# 注意：网上常见的 CCITT 表是错的；必须用下面这组与 Garmin SDK 一致的表。
_TABLE = [0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,
          0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400]
def fit_crc16(data, crc=0):
    for value in data:
        tmp = _TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _TABLE[value & 0xF]
        tmp = _TABLE[crc & 0xF]; crc = (crc >> 4) & 0x0FFF; crc ^= tmp ^ _TABLE[(value >> 4) & 0xF]
    return crc & 0xFFFF

def parse(path):
    data = open(path,'rb').read()
    hsize = data[0]; off = hsize; end = len(data) - 2
    records = []; defs = {}
    while off < end:
        start = off; hdr = data[off]; off += 1
        if hdr & 0x80:    # 压缩时间戳数据消息
            local = hdr & 0x0F
            if local not in defs:
                break
            gnum, fields = defs[local]
            ts_size = sum(s for (fn,s,bt) in fields if fn == 253)
            total = sum(s for (fn,s,bt) in fields) - ts_size
            raw = data[start:start+1+total]; off = start+1+total
            records.append({'kind':'data','local':local,'global':gnum,'fields':fields,'raw':raw,'start':start,'end':off})
            continue
        is_def = bool(hdr & 0x40); local = hdr & 0x0F
        if is_def:
            off += 1; arch = data[off]; off += 1
            gnum = struct.unpack('<H' if arch==0 else '>H', data[off:off+2])[0]; off += 2
            nf = data[off]; off += 1; fields = []
            for _ in range(nf):
                fnum=data[off]; size=data[off+1]; btype=data[off+2]; off += 3
                fields.append((fnum,size,btype))
            defs[local] = (gnum, fields)
            raw = data[start:off]
            records.append({'kind':'def','local':local,'global':gnum,'fields':fields,'raw':raw,'start':start,'end':off})
        else:
            if local not in defs:
                break
            gnum, fields = defs[local]
            total = sum(s for (fn,s,bt) in fields)
            raw = data[start:off+total]; off += total
            records.append({'kind':'data','local':local,'global':gnum,'fields':fields,'raw':raw,'start':start,'end':off})
    return data, hsize, records

def find_pair(records, global_num):
    d = next((r for r in records if r['global']==global_num and r['kind']=='def'), None)
    a = next((r for r in records if r['global']==global_num and r['kind']=='data'), None)
    return d, a

def field_offset(defn, fnum):
    """返回字段 fnum 在 data raw 内的偏移（含 1 字节 local 头）与 size。"""
    i = next(k for k,(fn,_,_) in enumerate(defn['fields']) if fn==fnum)
    p = 1 + sum(s for (fn,s,_) in defn['fields'][:i])
    sz = defn['fields'][i][1]
    return p, sz

def main(src, ref, out):
    tdata, thsize, trecs = parse(src)
    rdata, _, rrecs = parse(ref)

    t_fid_def, t_fid_data = find_pair(trecs, 0)
    t_di_def,  t_di_data  = find_pair(trecs, 23)
    r_fid_def, r_fid_data = find_pair(rrecs, 0)
    r_di_def,  r_di_data  = find_pair(rrecs, 23)
    if not all([t_fid_def,t_fid_data,t_di_def,t_di_data,r_fid_def,r_fid_data,r_di_def,r_di_data]):
        print("ERROR: 源文件或参考文件缺少 file_id/device_info"); sys.exit(1)

    # 本活动自己的创建时间（file_id field 4）
    tp, tsz = field_offset(t_fid_def, 4)
    time_created = struct.unpack('<I', t_fid_data['raw'][tp:tp+tsz])[0]
    print(f"activity time_created = {time_created} -> "
          f"{(datetime.datetime(1989,12,31)+datetime.timedelta(seconds=time_created)).isoformat()}Z")

    # 新 file_id：复制参考 def/data，local 用源文件自己的，时间改成本活动
    new_fid_def = bytearray(r_fid_def['raw'])
    new_fid_def[0] = (new_fid_def[0] & 0xF0) | (t_fid_def['local'] & 0x0F)
    new_fid_data = bytearray(r_fid_data['raw'])
    new_fid_data[0] = t_fid_def['local'] & 0x0F
    fp, fsz = field_offset(r_fid_def, 4)
    new_fid_data[fp:fp+fsz] = struct.pack('<I', time_created)

    # 新 device_info：复制参考 def/data，local 用源文件自己的，timestamp(253) 改成本活动
    new_di_def = bytearray(r_di_def['raw'])
    new_di_def[0] = (new_di_def[0] & 0xF0) | (t_di_def['local'] & 0x0F)
    new_di_data = bytearray(r_di_data['raw'])
    new_di_data[0] = t_di_def['local'] & 0x0F
    dp, dsz = field_offset(r_di_def, 253)
    new_di_data[dp:dp+dsz] = struct.pack('<I', time_created)

    # 拼接：身份两条消息用新的，其余按源文件原偏移原样保留
    out_b = bytearray()
    out_b += tdata[:t_fid_def['start']]
    out_b += new_fid_def
    out_b += new_fid_data
    out_b += tdata[t_fid_data['end']:t_di_def['start']]
    out_b += new_di_def
    out_b += new_di_data
    out_b += tdata[t_di_data['end']:-2]   # 去掉旧尾部 CRC

    # 修正 header data_size（偏移4）= header 之后、CRC 之前的字节数 = len(out_b)-hsize
    out_b[4:8] = struct.pack('<I', len(out_b) - thsize)
    # 修正 header CRC（偏移12，覆盖字节 0..11）
    out_b[12:14] = struct.pack('<H', fit_crc16(bytes(out_b[0:12])))
    # 文件尾 CRC
    out_b += struct.pack('<H', fit_crc16(bytes(out_b)))

    open(out,'wb').write(out_b)
    fc = struct.unpack('<H', bytes(out_b[-2:]))[0]
    hc = struct.unpack('<H', bytes(out_b[12:14]))[0]
    print(f"wrote {out}: {len(out_b)} bytes (delta {len(out_b)-len(tdata):+d})")
    print(f"file CRC 0x{fc:04X} match={fc==fit_crc16(bytes(out_b[:-2]))}; "
          f"header CRC 0x{hc:04X} match={hc==fit_crc16(bytes(out_b[0:12]))}")

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
