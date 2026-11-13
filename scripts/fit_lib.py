# -*- coding: utf-8 -*-
"""FIT 协议通用核心库（解析 / 写入 / 官方定义索引 / 哨兵规则 / CRC）。

设计原则
--------
本库是 fit-analyzer-skill 所有脚本的**单一事实来源**，任何脚本都不许再自己
手抄类型码、哨兵值、scale/offset。全部从 `references/fit_profile_official.json`
（由 @garmin/fitsdk v21.214 导出）查。

三条铁律（写进代码，不靠人记）：
  1. 字段号 ↔ 官方名、scale、offset、类型码 —— 一律查 profile，绝不硬编码数字。
  2. 无效哨兵**按类型族**选：有符号=最大值右移一位，无符号=全 1，z 系列=全 0。
  3. 解析必须能定位 desync（解析终点 != 数据区终点 即结构错误）。
"""

import json
import os
import struct

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# FIT epoch = 1989-12-31 00:00:00 UTC
FIT_EPOCH_UNIX = 631065600
# 压缩时间戳的偏移量模数
COMPRESSED_TS_MOD = 32

# fitBaseTypeId 全枚举: id -> (类型名, 字节数)
BASE_TYPES = {
    0x00: ('enum', 1),
    0x01: ('sint8', 1),
    0x02: ('uint8', 1),
    0x07: ('string', 1),
    0x0A: ('uint8z', 1),
    0x0D: ('byte', 1),
    0x83: ('sint16', 2),
    0x84: ('uint16', 2),
    0x85: ('sint32', 4),
    0x86: ('uint32', 4),
    0x88: ('float32', 4),
    0x89: ('float64', 8),
    0x8B: ('uint16z', 2),
    0x8C: ('uint32z', 4),
    0x8E: ('sint64', 8),
    0x8F: ('uint64', 8),
    0x90: ('uint64z', 8),
}
# 类型名 -> id
TYPE_IDS = {v[0]: k for k, v in BASE_TYPES.items()}

# 有无符号族
SIGNED_TYPES = {'sint8', 'sint16', 'sint32', 'sint64'}
ZERO_INVALID_TYPES = {'uint8z', 'uint16z', 'uint32z', 'uint64z'}
FLOAT_TYPES = {'float32', 'float64'}

# 记录头掩码
HDR_COMPRESSED = 0x80
HDR_DEFINITION = 0x40
HDR_DEV_FIELDS = 0x20

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROFILE_PATH = os.path.join(_SKILL_DIR, 'references', 'fit_profile_official.json')
TEMPLATE_DIR = os.path.join(_SKILL_DIR, 'references', 'templates')


# ---------------------------------------------------------------------------
# 哨兵（无效值）—— 按类型族，不按字节数
# ---------------------------------------------------------------------------

def invalid_bytes(type_name, size=None):
    """返回该类型的无效值字节串。

    ⚠️ 这是踩过坑的地方：曾对 S8 的 avgTemperature 无脑填 0xFF，
       被解析成 -1/255，高驰页面显示 255℃。
    """
    if isinstance(type_name, int):          # 允许直接传 type id
        type_name = BASE_TYPES[type_name][0]
    if size is None:
        size = BASE_TYPES[TYPE_IDS[type_name]][1]
    if type_name in SIGNED_TYPES:
        # 最大值右移一位：S8=0x7F, S16=0x7FFF, S32=0x7FFFFFFF, S64=0x7FFF...
        v = (1 << (size * 8 - 1)) - 1
        return v.to_bytes(size, 'little', signed=True)
    if type_name in ZERO_INVALID_TYPES:
        return b'\x00' * size            # 0 也无效
    if type_name == 'string':
        return b'\x00' * size
    # 无符号 + 浮点：全 1
    return b'\xFF' * size


def invalid_int(type_name, size=None):
    """无效值的整数表示（用于比较）。"""
    return int.from_bytes(invalid_bytes(type_name, size), 'little')


def is_invalid(raw, type_name, size=None):
    """判断原始字节是否为无效哨兵。"""
    if raw is None:
        return True
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw) == invalid_bytes(type_name, len(raw) if size is None else size)
    return False


# ---------------------------------------------------------------------------
# profile 索引（官方定义的唯一入口）
# ---------------------------------------------------------------------------

class Profile:
    """FIT 官方 profile 索引。

    - `field(g, num)`      -> 字段定义 dict（含 name/type/scale/offset/units）
    - `field_num(g, name)` -> 字段号
    - `msg_name(g)` / `msg_num(name)`
    - `scale_offset(g, num)` -> (scale, offset)（数组取首元素）
    """

    def __init__(self, path=PROFILE_PATH):
        d = json.load(open(path, encoding='utf-8'))
        self.raw = d
        self.version = d.get('_version')
        self.source = d.get('_source')
        self.messages = d['messages']            # str(num) -> {name, fields}
        self.types = d['types']                  # 枚举名 -> {值: 名}
        self.base_type_ids = d.get('base_type_ids', {})
        self._msg_by_num = {}
        self._msg_by_name = {}
        self._field_cache = {}
        for num_s, m in self.messages.items():
            num = int(num_s)
            self._msg_by_num[num] = m['name']
            self._msg_by_name[m['name']] = num
        self._enum_rev = {}
        for tname, tv in self.types.items():
            rev = {}
            for k, v in tv.items():
                rev[v] = int(k)
            self._enum_rev[tname] = rev

    # -- 消息 ---------------------------------------------------------------
    def msg_name(self, g):
        return self._msg_by_num.get(g, f'unknown_{g}')

    def msg_num(self, name):
        return self._msg_by_name.get(name)

    def msg_fields(self, g):
        m = self.messages.get(str(g))
        return m['fields'] if m else {}

    # -- 字段 ---------------------------------------------------------------
    def field(self, g, num):
        """字段定义 dict；查不到返回 None（说明是开发字段或私有字段）。"""
        m = self.messages.get(str(g))
        if not m:
            return None
        return m['fields'].get(str(num))

    def field_num(self, g, name):
        m = self.messages.get(str(g))
        if not m:
            return None
        for num_s, f in m['fields'].items():
            if f['name'] == name:
                return int(num_s)
        return None

    def fname(self, g, num):
        f = self.field(g, num)
        return f['name'] if f else f'f{num}(?{g})'

    def scale_offset(self, g, num):
        """返回 (scale, offset)，默认 (1, 0)。profile 里可能是数组。"""
        f = self.field(g, num)
        if not f:
            return 1, 0
        sc, of = f.get('scale'), f.get('offset')
        if isinstance(sc, list):
            sc = sc[0] if sc else 1
        if isinstance(of, list):
            of = of[0] if of else 0
        return (sc or 1), (of or 0)

    def type_name(self, g, num):
        """真正的 fitBaseType 名（enum/uint16/sint32...）。

        ⚠️ 不是 profile 里的 `type`（那是逻辑类型名，如 file/manufacturer/date_time）。
           `type` 只用于查枚举值，`base_type` 才是编码类型。
        """
        f = self.field(g, num)
        if not f:
            return None
        return f.get('base_type') or f.get('type')

    def type_id(self, g, num):
        """该字段在官方定义里的 fitBaseTypeId（用于比对真机是否偏离标准）。"""
        f = self.field(g, num)
        if not f:
            return None
        if f.get('base_type_id') is not None:
            return f['base_type_id']
        tn = self.type_name(g, num)
        return TYPE_IDS.get(tn) if tn else None

    def logic_type(self, g, num):
        """逻辑类型名（file / manufacturer / date_time ...），用于查枚举。"""
        f = self.field(g, num)
        return f.get('type') if f else None

    def enum_name(self, enum_type, value):
        return self.types.get(enum_type, {}).get(str(value))

    def enum_value(self, enum_type, name):
        return self._enum_rev.get(enum_type, {}).get(name)

    # -- 物理量换算 ---------------------------------------------------------
    def to_phys(self, g, num, raw):
        sc, of = self.scale_offset(g, num)
        if raw is None:
            return None
        return raw / sc - of

    def to_raw(self, g, num, phys):
        sc, of = self.scale_offset(g, num)
        if phys is None:
            return None
        return int(round((phys + of) * sc))


# ---------------------------------------------------------------------------
# 解析器
# ---------------------------------------------------------------------------

class FieldDef:
    """DEF 里的一条字段定义。"""
    __slots__ = ('num', 'size', 'base_type', 'is_dev')

    def __init__(self, num, size, base_type, is_dev=False):
        self.num, self.size, self.base_type, self.is_dev = num, size, base_type, is_dev

    def __repr__(self):
        return f'<F f{self.num} sz{self.size} bt0x{self.base_type:02X}{" dev" if self.is_dev else ""}>'


class Definition:
    """一条定义消息（DEF）。"""

    def __init__(self, local, g, fields, devs, endian, has_dev, offset_in_file):
        self.local = local
        self.g = g
        self.fields = fields
        self.devs = devs
        self.endian = endian
        self.has_dev = has_dev
        self.offset = offset_in_file          # 在文件中的字节偏移（用于复用判断）

    @property
    def payload_size(self):
        return sum(f.size for f in self.fields) + sum(f.size for f in self.devs)

    def signature(self):
        """布局签名（字段号+大小+类型码），用于判断"同一布局"。"""
        return (tuple((f.num, f.size, f.base_type) for f in self.fields),
                tuple((f.num, f.size, f.base_type) for f in self.devs))

    def __repr__(self):
        return (f'<DEF g={self.g}({Profile.__name__}) local={self.local} '
                f'nfields={len(self.fields)} ndev={len(self.devs)}>')


class RawMsg:
    """一条数据消息（MSG）。"""
    __slots__ = ('g', 'local', 'def_', 'raw', 'dev_raw', 'ts', 'compressed', 'offset')

    def __init__(self, g, local, def_, raw, dev_raw, compressed=False, offset=0):
        self.g = g
        self.local = local
        self.def_ = def_
        self.raw = raw            # {field_num: bytes}
        self.dev_raw = dev_raw    # {dev_field_num: bytes}
        self.ts = None            # 压缩时间戳还原值
        self.compressed = compressed   # 是否使用压缩时间戳头
        self.offset = offset           # 在文件中的字节偏移

    def __repr__(self):
        return f'<MSG g={self.g} local={self.local} fields={len(self.raw)}>'


class ParseError(Exception):
    pass


def crc16(data):
    """FIT 专用 CRC16。"""
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


class FitFile:
    """一个解析后的 FIT 文件。

    属性
    ----
    - header: dict（size/protocol/profile_version/data_size/data_type/crc/crc_ok）
    - defs:   list[Definition]（按文件中出现顺序，含重复声明）
    - msgs:   list[RawMsg]（按文件顺序）
    - desync: None 或发生错位的字节偏移
    - end:    解析终点
    - data_end: header_size + data_size（应为 end）
    """

    def __init__(self, path=None, data=None):
        self.path = path
        self.data = data if data is not None else open(path, 'rb').read()
        self.defs = []
        self.msgs = []
        self.desync = None
        self.end = 0
        self._parse()

    # -- 头部 ---------------------------------------------------------------
    def _parse_header(self):
        d = self.data
        if len(d) < 12:
            raise ParseError('文件过短')
        size = d[0]
        self.header = {
            'size': size,
            'protocol': d[1],
            'profile_version': struct.unpack_from('<H', d, 2)[0],
            'data_size': struct.unpack_from('<I', d, 4)[0],
            'data_type': d[8:12],
        }
        if size >= 14 and len(d) >= 14:
            self.header['crc'] = struct.unpack_from('<H', d, 12)[0]
            self.header['crc_ok'] = (self.header['crc'] == crc16(d[0:12]))
        else:
            self.header['crc'] = None
            self.header['crc_ok'] = True
        self.data_end = size + self.header['data_size']
        self.trailer_crc_ok = None
        if len(d) >= self.data_end + 2:
            tc = struct.unpack_from('<H', d, self.data_end)[0]
            self.header['trailer_crc'] = tc
            self.trailer_crc_ok = (tc == crc16(d[0:self.data_end]))
            self.header['trailer_crc_ok'] = self.trailer_crc_ok

    # -- 记录流 -------------------------------------------------------------
    def _parse(self):
        self._parse_header()
        d = self.data
        i = self.header['size']
        be = self.data_end
        defs = {}
        last_ts = None          # 压缩时间戳基准
        last_offset = None
        while i < be:
            st = i
            if i + 1 > be:
                self.desync = i
                break
            hdr = d[i]
            i += 1

            # ---- DEF ----
            if hdr & HDR_DEFINITION:
                has_dev = bool(hdr & HDR_DEV_FIELDS)
                local = hdr & 0x0F
                if i + 5 > be:
                    self.desync = st
                    break
                i += 1                                    # reserved
                endian = '<' if d[i] == 0 else '>'
                i += 1
                g = struct.unpack_from(endian + 'H', d, i)[0]
                i += 2
                nf = d[i]
                i += 1
                fields = []
                for _ in range(nf):
                    if i + 3 > be:
                        self.desync = st
                        break
                    fields.append(FieldDef(d[i], d[i + 1], d[i + 2]))
                    i += 3
                devs = []
                if has_dev:
                    if i + 1 > be:
                        self.desync = st
                        break
                    nd = d[i]
                    i += 1
                    for _ in range(nd):
                        if i + 3 > be:
                            self.desync = st
                            break
                        devs.append(FieldDef(d[i], d[i + 1], d[i + 2], True))
                        i += 3
                dd = Definition(local, g, fields, devs, endian, has_dev, st)
                self.defs.append(dd)
                defs[local] = dd
                continue

            # ---- MSG ----
            compressed = bool(hdr & HDR_COMPRESSED)
            if compressed:
                local = (hdr >> 5) & 0x03
            else:
                local = hdr & 0x0F
            dd = defs.get(local)
            if dd is None:
                self.desync = st
                break
            o = i
            raw, dev_raw = {}, {}
            ok = True
            for f in dd.fields:
                if o + f.size > be:
                    ok = False
                    break
                raw[f.num] = d[o:o + f.size]
                o += f.size
            if ok:
                for f in dd.devs:
                    if o + f.size > be:
                        ok = False
                        break
                    dev_raw[f.num] = d[o:o + f.size]
                    o += f.size
            if not ok:
                self.desync = st
                break
            m = RawMsg(dd.g, local, dd, raw, dev_raw, compressed, st)

            # 压缩时间戳还原（Garmin SDK 语义：32 秒窗口回绕）
            if compressed:
                off = hdr & 0x1F
                if last_ts is None:
                    m.ts = off
                else:
                    if off >= last_offset:
                        m.ts = last_ts + (off - last_offset)
                    else:
                        m.ts = last_ts + (off + COMPRESSED_TS_MOD - last_offset)
                last_offset = off
                last_ts = m.ts
            else:
                ts_f = dd.g and _find_ts_field(dd)
                if ts_f is not None and ts_f in raw:
                    v = int.from_bytes(raw[ts_f], 'little')
                    if v != 0xFFFFFFFF:
                        last_ts = v
                        last_offset = v % COMPRESSED_TS_MOD
            self.msgs.append(m)
            i = st + 1 + sum(f.size for f in dd.fields) + sum(f.size for f in dd.devs)

        self.end = i

    # -- 便捷访问 -----------------------------------------------------------
    def by_global(self, g):
        return [m for m in self.msgs if m.g == g]

    def one(self, g):
        r = self.by_global(g)
        return r[0] if r else None

    def global_counts(self):
        c = {}
        for m in self.msgs:
            c[m.g] = c.get(m.g, 0) + 1
        return c

    def layouts(self, g):
        """该消息在文件中出现过的所有 DEF 布局（去重，保持顺序）。"""
        seen, out = set(), []
        for dd in self.defs:
            if dd.g != g:
                continue
            sig = dd.signature()
            if sig in seen:
                continue
            seen.add(sig)
            out.append(dd)
        return out

    def layout_sequence(self, g):
        """该消息的 DEF 出现序列（含重复），每条 = (signature, 第几次声明偏移)。"""
        return [(dd.signature(), dd.local, dd.offset) for dd in self.defs if dd.g == g]

    def integrity(self):
        """结构完整性：解析终点 == 数据区终点 且无 desync。"""
        return self.desync is None and self.end == self.data_end

    # -- 数值读取（配合 Profile 换算）--------------------------------------
    def value(self, msg, num, prof=None, g=None):
        """取字段的**物理值**。需要 prof 才能换算 scale/offset。"""
        raw = msg.raw.get(num)
        if raw is None:
            return None
        g = g if g is not None else msg.g
        f = (prof.field(g, num) if prof else None)
        tn = (f.get('base_type') or f.get('type')) if f else None
        if tn is None:
            # 无官方定义：按长度猜（可能是开发字段/私有字段）
            return int.from_bytes(raw, 'little')
        if is_invalid(raw, tn):
            return None
        v = _decode(raw, tn, msg.def_.endian)
        # byte / string 不参与 scale/offset 换算（它们是二进制/文本，不是物理量）
        if isinstance(v, (str, bytes, bytearray)):
            return v
        if prof:
            sc, of = prof.scale_offset(g, num)
            return v / sc - of
        return v

    def value_enum(self, msg, num, prof, g=None):
        """取枚举名（如 event=f26 -> "activity"、eventType=f1 -> "stop"）。"""
        g = g if g is not None else msg.g
        v = self.value(msg, num, prof, g)
        if v is None:
            return None
        lt = prof.logic_type(g, num)
        if not lt:
            return None
        return prof.enum_name(lt, int(v))

    def raw_int(self, msg, num):
        raw = msg.raw.get(num)
        if raw is None:
            return None
        return int.from_bytes(raw, 'little')

    def dev_value(self, msg, num):
        raw = msg.dev_raw.get(num)
        if raw is None:
            return None
        return struct.unpack('<f', raw)[0] if len(raw) == 4 else raw


def _find_ts_field(dd):
    for f in dd.fields:
        if f.num == 253:
            return 253
    return None


def _decode(raw, type_name, endian='<'):
    """按官方类型名解码原始字节（不做 scale/offset）。"""
    if type_name == 'string':
        return raw.rstrip(b'\x00').decode('utf-8', 'replace')
    if type_name == 'byte':
        return raw
    if type_name == 'float32':
        return struct.unpack('<f', raw)[0]
    if type_name == 'float64':
        return struct.unpack('<d', raw)[0]
    signed = type_name in SIGNED_TYPES
    if endian == '>':
        return int.from_bytes(raw, 'big', signed=signed)
    return int.from_bytes(raw, 'little', signed=signed)


def encode_value(phys, type_name, size=None, endian='<'):
    """物理值 -> 字节串（含 scale/offset 已由调用方处理与否的区分见 encode_field）。

    ⚠️ 本函数**只做类型编码 + 哨兵**，不做 scale/offset（那是 Profile 的职责）。
    """
    if isinstance(type_name, int):
        type_name, dsz = BASE_TYPES[type_name]
        size = size or dsz
    if size is None:
        size = BASE_TYPES[TYPE_IDS[type_name]][1]

    if phys is None:
        return invalid_bytes(type_name, size)

    if type_name == 'string':
        b = phys.encode('utf-8') if isinstance(phys, str) else bytes(phys)
        return b[:size].ljust(size, b'\x00')
    if type_name == 'byte':
        return bytes(phys)[:size].ljust(size, b'\x00')
    if type_name == 'float32':
        try:
            if phys != phys:
                return b'\xFF\xFF\xFF\xFF'
        except TypeError:
            pass
        return struct.pack('<f', float(phys))
    if type_name == 'float64':
        return struct.pack('<d', float(phys))

    v = int(round(phys)) if isinstance(phys, float) else int(phys)
    signed = type_name in SIGNED_TYPES
    try:
        return v.to_bytes(size, 'little' if endian == '<' else 'big', signed=signed)
    except OverflowError:
        return invalid_bytes(type_name, size)


# ---------------------------------------------------------------------------
# 写入器
# ---------------------------------------------------------------------------

class FitWriter:
    """按 DEF 拼字节。所有字段值由调用方以**物理值 + 官方类型名**给出。"""

    def __init__(self):
        self.buf = bytearray()

    # -- DEF ---------------------------------------------------------------
    def def_bytes(self, g, local, fields, devs=None, endian=0):
        """fields/devs: list[(num, size, base_type_id)]"""
        devs = devs or []
        hdr = HDR_DEFINITION | (HDR_DEV_FIELDS if devs else 0) | (local & 0x0F)
        out = bytearray([hdr, 0x00, endian])
        out += struct.pack('<H' if endian == 0 else '>H', g)
        out += bytes([len(fields)])
        for (n, sz, bt) in fields:
            out += bytes([n, sz, bt])
        if devs:
            out += bytes([len(devs)])
            for (n, sz, bt) in devs:
                out += bytes([n, sz, bt])
        return bytes(out)

    # -- MSG ---------------------------------------------------------------
    def msg_bytes(self, local, payloads):
        """payloads: list[bytes]（已编码好的字段字节，顺序与 DEF 一致）"""
        out = bytearray([local & 0x0F])
        for p in payloads:
            out += p
        return bytes(out)

    def add_def(self, g, local, fields, devs=None, endian=0):
        self.buf += self.def_bytes(g, local, fields, devs, endian)

    def add_msg(self, local, payloads):
        self.buf += self.msg_bytes(local, payloads)

    # -- 组装 ---------------------------------------------------------------
    def finish(self, protocol, profile_version, data_type=b'.FIT'):
        body = bytes(self.buf)
        header = bytearray([14, protocol])
        header += struct.pack('<H', profile_version)
        header += struct.pack('<I', len(body))
        header += data_type
        header += struct.pack('<H', crc16(bytes(header[:12])))
        out = bytes(header) + body
        out += struct.pack('<H', crc16(out))
        return out


def write_fit(path, blob):
    open(path, 'wb').write(blob)
    return len(blob)


# ---------------------------------------------------------------------------
# 快速自检
# ---------------------------------------------------------------------------

def summary(path, prof=None):
    """打印一个 FIT 的概览（调试用）。"""
    prof = prof or Profile()
    f = FitFile(path)
    print(f'文件: {path}')
    print(f'  header_size={f.header["size"]} protocol={f.header["protocol"]} '
          f'profile_version={f.header["profile_version"]} data_size={f.header["data_size"]}')
    print(f'  header_crc_ok={f.header["crc_ok"]} trailer_crc_ok={f.trailer_crc_ok}')
    print(f'  完整解析={f.integrity()} end={f.end} data_end={f.data_end} desync={f.desync}')
    print(f'  消息 {len(f.msgs)} 条 / DEF {len(f.defs)} 条')
    for g, c in sorted(f.global_counts().items()):
        nl = len(f.layouts(g))
        print(f'    g={g:<4} {prof.msg_name(g):<20} 条数={c:<7} 布局数={nl}')
    return f


if __name__ == '__main__':
    import sys
    sys.stdout.reconfigure(encoding='utf-8')
    Profile()   # 校验 profile 可加载
    for p in sys.argv[1:]:
        summary(p)
        print()
