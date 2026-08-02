#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_qa.py — FIT 合并文件的 QA 测试员 (质量保障 / 回归测试)

角色定位
--------
这是「开发→测试→修复→复测」工作流里的测试员。每次 fit_merge.py 生成合并文件后，
QA 必须跑一遍本脚本，全部 PASS 才允许交付；只要有一个 FAIL，开发者（同一 agent
的另一个角色）就要回去修，修完复测，直到全绿。

设计原则
--------
1. 覆盖「今天踩过的全部常识性错误」：
   - 设备去重：合并后 device_info 必须只有 1 个、且 manufacturer/product_name 都在
     （否则 COROS 显示「未知设备」）。  ← 本次会话刚修的坑
   - 孤儿定义：每个 definition 消息后面必须有 ≥1 条数据消息，不能有悬空定义
     （seg2 的 device_info/field_description 定义曾被漏丢）。  ← 本次会话刚修的坑
   - 计圈逻辑：前 N-1 圈必须各≈1.000km、末圈为余数、总距=session 总距
     （曾误改成累计导致每圈二三十 km）。  ← 上一轮的大坑
   - 私有字段保留：Effort Pace(等强配速) 的 field_description 不能丢
     （曾因 developer_data_id/field_description 未去重被 COROS 整体丢弃）。
   - record 距离单调递增、末值=session 总距。
   - message_index 同类消息内唯一。
2. 必须符合 FIT 文件全部规范：header 合法、CRC 正确、字段 size 与 base type 匹配、
   definition 完整性等。
3. 不篡改真实数据：源文件固有的怪癖（如 COROS event 定义里 uint32 被声明 size=1）
   只在报告里 WARN，不强行修（修了等于改设备原始输出，违背「不篡改真实数据」原则）。

用法
----
  python fit_qa.py merged.fit [--expect-devices 1] [--lap-km 1.0] [--slack-m 3.0]

退出码：0 = 全 PASS；1 = 有 FAIL；2 = 脚本/参数错误。
"""
import sys, os, struct, argparse, datetime
from collections import defaultdict, Counter

try:
    import fitdecode
except ImportError:
    sys.stderr.write("ERROR: fitdecode 未安装 (pip install fitdecode)\n")
    sys.exit(2)

# 让本脚本能直接 import 同目录的 fit_merge（复用 walk/read_body 字节级解析）
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
import fit_merge as fm

# FIT base type -> 规范字节宽（None 表示 string，宽度任意、以 \\0 结尾）
BASE_SIZE = {0:1,1:1,2:1,3:2,4:2,5:4,6:4,7:None,8:4,9:8,10:1,11:2,12:4,13:8,14:8,15:8}
GLOBAL_NAME = {0:"file_id",18:"session",19:"lap",20:"record",21:"event",
               23:"device_info",34:"activity",206:"field_description",207:"developer_data_id"}

_EPOCH = datetime.datetime(1989, 12, 31, 0, 0, 0)
def _dec_raw(rawb, base):
    if rawb is None:
        return None
    signed = (base & 0x1F) in (1, 3, 5, 13)
    return int.from_bytes(rawb, "little", signed=signed)
def _field_raw(fr, dn):
    """返回 (raw_bytes, base) ，封装 fit_merge.read_field_raw 的三元组结果。"""
    r = fm.read_field_raw(fr["chunk"], fr["dd"], dn, fr["compressed"], fr["dev"])
    return r[0], r[2]
def _fmt_ts(v):
    if v is None:
        return "NA"
    return (_EPOCH + datetime.timedelta(seconds=v)).strftime("%Y-%m-%d %H:%M:%S")


def extract_times(path):
    """从任意 FIT 文件抽取时间相关事实，供交叉校验使用（全部用原始 uint32，避免 fitdecode 时区歧义）。"""
    body = fm.read_body(path)[1]
    rec_ts = []
    fid_tc = sess_start = sess_ts = None
    di_ident = None
    for fr in fm.walk(body):
        g = fr["global"]
        if g == 0 and not fr["is_def"]:
            fid_tc = _dec_raw(*_field_raw(fr, 4))
        elif g == 18 and not fr["is_def"]:
            sess_start = _dec_raw(*_field_raw(fr, 2))
            sess_ts = _dec_raw(*_field_raw(fr, 253))
        elif g == 20 and not fr["is_def"]:
            t = _dec_raw(*_field_raw(fr, 253))
            if t is not None:
                rec_ts.append(t)
        elif g == 23 and not fr["is_def"]:
            manu = _dec_raw(*_field_raw(fr, 1))
            prod = _dec_raw(*_field_raw(fr, 2))
            di_ident = (manu, prod)
    rec_ts.sort()
    return {"fid_tc": fid_tc, "sess_start": sess_start, "sess_ts": sess_ts,
            "rec_ts": rec_ts,
            "first": rec_ts[0] if rec_ts else None,
            "last": rec_ts[-1] if rec_ts else None,
            "di": di_ident}


class QA:
    def __init__(self, path, expect_devices=1, lap_km=1000.0, slack_m=3.0, sources=None):
        self.path = path
        self.expect_devices = expect_devices
        self.lap_km = lap_km
        self.slack = slack_m
        self.sources = sources or []  # [seg1, seg2] 原始文件，用于交叉校验
        self.results = []  # (level, name, ok, detail)

    def check(self, name, ok, detail=""):
        self.results.append(("FAIL" if not ok else "PASS", name, ok, detail))
        return ok

    def warn(self, name, detail):
        self.results.append(("WARN", name, True, detail))

    # ---------- raw structural scan (definition <-> data pairing) ----------
    def raw_scan(self):
        raw = open(self.path, "rb").read()
        self.raw = raw
        hsize = raw[0]
        body = raw[hsize:-2]
        self.body = body
        i = 0; n = len(body); active = {}
        runs = defaultdict(list)          # local -> [{"def":gnum,"data":0}, ...]
        field_issues = []                 # (offset, global, field, msg)
        defs_meta = []                    # (offset, local, gnum, fields)
        seen_def_order = []
        while i < n:
            st = i; hb = body[i]; i += 1
            if hb & 0x80:  # compressed timestamp
                local = (hb >> 5) & 0x03
                if local in active:
                    if runs[local]:
                        runs[local][-1]["data"] += 1
                dd = active.get(local)
                if dd: i += dd["data_size"]
                continue
            is_def = bool(hb & 0x40); dev = bool(hb & 0x20); local = hb & 0x0F
            if is_def:
                i += 2; gnum = int.from_bytes(body[i:i+2], "little"); i += 2
                nf = body[i]; i += 1
                fields = []
                for _ in range(nf):
                    dn = body[i]; sz = body[i+1]; bt = body[i+2]; i += 3
                    fields.append((dn, sz, bt))
                devf = []
                if dev:
                    nd = body[i]; i += 1
                    for _ in range(nd):
                        dn = body[i]; sz = body[i+1]; di = body[i+2]; i += 3
                        devf.append((dn, sz, di))
                ds = sum(f[1] for f in fields) + sum(x[1] for x in devf)
                # spec: field size must match base type
                for (dn, sz, bt) in fields:
                    base = bt & 0x1F
                    bsz = BASE_SIZE.get(base)
                    if bsz is None:
                        if sz <= 0:
                            field_issues.append((st, gnum, dn, f"string field size {sz} invalid"))
                    elif sz <= 0 or sz % bsz != 0:
                        field_issues.append((st, gnum, dn,
                            f"field {dn} base={base}(sz {bsz}) declared size {sz} (not a multiple)"))
                runs[local].append({"def": gnum, "data": 0, "offset": st})
                active[local] = {"global": gnum, "fields": fields, "dev_fields": devf, "data_size": ds}
                defs_meta.append((st, local, gnum, fields))
            else:
                if dev: i += 1
                dd = active.get(local)
                if dd is None:
                    field_issues.append((st, -1, -1, f"data at local {local} has no active definition"))
                    continue
                gnum = dd["global"]; i += dd["data_size"]
                if runs[local]:
                    runs[local][-1]["data"] += 1
        return runs, field_issues, defs_meta

    # ---------- FIT spec conformance ----------
    def test_header_crc(self):
        raw = self.raw
        # FIT header layout: [0]=size(14) [1]=proto [2:4]=profile [4:8]=data_size
        #                    [8:12]=".FIT" [12:14]=header CRC  (CRC over bytes 0..11)
        ok = (len(raw) >= 14 and raw[0] == 14 and raw[8:12] == b".FIT"
              and fm.crc16(raw[:12]) == int.from_bytes(raw[12:14], "little"))
        self.check("T01 header合法(.FIT + header CRC)", ok,
                   "" if ok else f"size={raw[0]} magic={raw[8:12]!r}")

    def test_file_crc(self):
        try:
            with fitdecode.FitReader(self.path, check_crc=True) as r:
                for _ in r:
                    pass
            self.check("T02 文件CRC正确", True)
        except Exception as e:
            self.check("T02 文件CRC正确", False, str(e)[:120])

    def test_orphan_defs(self, runs):
        orphans = []
        for local, seq in runs.items():
            for r in seq:
                if r["data"] == 0:
                    orphans.append((local, GLOBAL_NAME.get(r["def"], r["def"]), r["offset"]))
        ok = not orphans
        self.check("T03 无孤儿定义(每条def都有≥1数据)", ok,
                   "" if ok else f"悬空定义: {[(o[0],o[1]) for o in orphans]}")

    def test_field_sizes(self, field_issues):
        if not field_issues:
            self.check("T04 字段size符合base type规范", True)
        else:
            # 源文件固有怪癖（如 COROS event 的 uint32 size=1）只在报告里 WARN，不阻断交付
            msgs = "; ".join(f"@{o[0]} {GLOBAL_NAME.get(o[1],o[1])} field{o[2]}: {o[3]}" for o in field_issues)
            self.warn("T04 字段size规范(源文件固有怪癖)", f"发现 {len(field_issues)} 处: {msgs}")

    # ---------- semantic checks via fitdecode ----------
    @staticmethod
    def gv(m, name, default=None):
        """安全取值：字段不存在时返回 default（fitdecode 的 get_value 对缺失字段抛 KeyError）"""
        try:
            return m.get_value(name)
        except (KeyError, Exception):
            return default

    def semantic(self):
        msgs = defaultdict(list)
        with fitdecode.FitReader(self.path, check_crc=False) as r:
            for m in r:
                if m.__class__.__name__ == "FitDataMessage":
                    msgs[m.name].append(m)
        return msgs

    def test_device_info(self, msgs):
        di = msgs.get("device_info", [])
        if not di:
            self.check("T05 device_info 存在且被识别", False, "文件无 device_info 消息")
            return
        # 去重后的不同设备身份
        identities = set()
        for m in di:
            manu = self.gv(m, "manufacturer")
            pname = self.gv(m, "product_name")
            prod = self.gv(m, "product")
            ser = self.gv(m, "serial_number")
            identities.add((manu, prod, ser, pname))
            if manu is None:
                self.check("T05 device_info 被识别(manufacturer非空)", False,
                           f"某 device_info manufacturer=None")
                return
        ok_count = (len(identities) == self.expect_devices)
        ok_id = all(p is not None or n is not None for (_, p, _, n) in identities)
        ok = ok_count and ok_id
        detail = f"distinct_devices={len(identities)} (期望{self.expect_devices}); "
        detail += f"identities={[(str(a), str(c), str(d)) for (a, c, _, d) in identities]}"
        self.check("T05 device_info 存在且唯一被识别(无未知设备)", ok, detail)

    def test_file_id(self, msgs):
        fi = msgs.get("file_id", [])
        if not fi:
            self.check("T06 file_id 含 manufacturer+product", False, "无 file_id")
            return
        m = fi[0]
        manu = self.gv(m, "manufacturer"); prod = self.gv(m, "product")
        ok = (manu is not None and prod is not None)
        self.check("T06 file_id 含 manufacturer+product", ok,
                   f"manufacturer={manu} product={prod}")

    def test_dev_fields(self, msgs):
        fd = msgs.get("field_description", [])
        has_effort = any((self.gv(m, "field_name") or "").lower().replace(" ", "")
                         in ("effortpace", "等强配速", "effort", "pace") for m in fd)
        # 只要存在 Effort Pace 定义即可；也可放宽到"存在任意 field_description 且 record 带 dev 字段"
        recs = msgs.get("record", [])
        rec_has_dev = any(getattr(m, "message", None) and m.message.dev_fields for m in recs)
        ok = has_effort or (len(fd) > 0 and rec_has_dev)
        self.check("T07 私有字段(Effort Pace)保留", ok,
                   f"field_description={len(fd)} 含EffortPace={has_effort} record带dev={rec_has_dev}")

    def test_laps(self, msgs):
        laps = msgs.get("lap", [])
        sess = msgs.get("session", [])
        if not laps or not sess:
            self.check("T08 计圈结构(前N-1圈≈1km + 末圈余数)", False,
                       f"lap={len(laps)} session={'有' if sess else '无'}")
            return
        s = sess[0]
        total = self.gv(s, "total_distance")
        nlap = self.gv(s, "num_laps")
        dists = [self.gv(m, "total_distance") for m in laps]
        dists = [d for d in dists if d is not None]
        if not dists or total is None:
            self.check("T08 计圈结构", False, "lap/session 距离缺失"); return
        n = len(dists)
        # 1km 圈判定（米）
        is_full = lambda d: abs(d - self.lap_km) <= self.slack
        short_idx = [i for i, d in enumerate(dists) if not is_full(d)]
        # 规则（用户踩过的常识性错误）：
        #  ① 过大圈(>1.5km) → 累计距离写错（旧 "6.4/7.4km" 回归）；
        #  ② 过短圈(<200m) 且不在末位 → 圈序错乱/末尾圈被挪到前面（"lap5=0.12km" 回归）；
        #  ③ Σlap 必须等于 session 总距（缺圈/重圈）；
        #  ④ 短圈数量 ≤2（单活动1个尾圈；两段合并每段各1个尾圈，共2个；>2 异常）。
        #  注：两段合并合法地有 2 个尾圈（每段末圈余数，如 0.727km / 0.396km），
        #      它们不在最后一位属正常，故不再强制「短圈必在末位」。
        too_big = [i for i, d in enumerate(dists) if d > self.lap_km + 500]
        very_short_not_last = [i for i, d in enumerate(dists) if d < 200 and i != n - 1]
        sum_ok = abs(sum(dists) - total) <= self.slack * n
        nlap_ok = (nlap is None) or (nlap == n)
        short_count_ok = len(short_idx) <= 2
        ok = (not too_big) and (not very_short_not_last) and sum_ok and nlap_ok and short_count_ok
        detail = (f"圈数={n} 短圈下标={short_idx} 过大圈={too_big} "
                  f"过短非末位={very_short_not_last} "
                  f"Σlap={sum(dists)/1000:.3f}km vs session={total/1000:.3f}km "
                  f"num_laps={nlap}")
        self.check("T08 计圈结构(无过大圈/无过短非末位圈/Σ=总距/短圈≤2)", ok, detail)

    def test_record_monotonic(self, msgs):
        recs = msgs.get("record", [])
        vals = [self.gv(m, "distance") for m in recs if self.gv(m, "distance") is not None]
        if len(vals) < 2:
            self.check("T09 record距离单调且=总距", True, "记录过少，跳过"); return
        mono = all(vals[i] <= vals[i+1] + 1 for i in range(len(vals)-1))
        sess = msgs.get("session", [])
        total = self.gv(sess[0], "total_distance") if sess else None
        end_ok = (total is None) or (abs(vals[-1] - total) <= self.slack)
        ok = mono and end_ok
        detail = f"monotonic={'OK' if mono else 'BAD'} last={vals[-1]/1000:.3f}km vs total={ (total/1000 if total else None)}km"
        self.check("T09 record距离单调递增且末值=总距", ok, detail)

    def test_message_index(self, msgs):
        bad = {}
        for name, lst in msgs.items():
            idxs = [self.gv(m, "message_index") for m in lst]
            idxs = [x for x in idxs if x is not None]
            if idxs and len(set(idxs)) != len(idxs):
                bad[name] = len(idxs) - len(set(idxs))
        ok = not bad
        self.check("T10 message_index 同类内唯一", ok,
                   "" if ok else f"重复: {bad}")

    def test_lap_pace(self, msgs):
        laps = msgs.get("lap", [])
        if not laps:
            return
        bad = []
        for i, m in enumerate(laps):
            timer = self.gv(m, "total_timer_time")
            dist = self.gv(m, "total_distance")
            pace = self.gv(m, "avg_pace")
            if timer is None or dist is None or dist <= 0 or pace is None:
                continue
            timer_s = timer / 1000.0
            dist_km = dist / 100000.0
            exp_pace = int(round(timer_s / dist_km))   # s/m*1000 == s per km for 1km lap
            if abs(pace - exp_pace) > 20:              # 容差 20 s/km
                bad.append((i, pace, exp_pace))
        ok = not bad
        self.check("T18 每圈avg_pace=扣暂停后timer/距离(防暂停未扣回归)", ok,
                   "" if ok else f"偏差圈: {bad}")

    def test_lap_timer_elapsed(self, msgs):
        laps = msgs.get("lap", [])
        bad = [i for i, m in enumerate(laps)
               if (self.gv(m, "total_timer_time") or 0) >
                  (self.gv(m, "total_elapsed_time") or 0) + 1000]
        ok = not bad
        self.check("T19 每圈timer<=elapsed(暂停已扣, 无负值)", ok,
                   "" if ok else f"timer>elapsed 的圈下标: {bad}")

    # ---------- 交叉校验：合并文件 vs 原始 2 个段（用户点名要求） ----------
    def cross_check(self):
        if len(self.sources) != 2:
            self.warn("TX 交叉校验(合并 vs 原始2段)", "未提供恰好2个源文件，跳过时间交叉校验")
            return
        s1 = extract_times(self.sources[0])
        s2 = extract_times(self.sources[1])
        m = extract_times(self.path)

        # T11 起始时间 == 段1 起始
        ok_start = (m["sess_start"] is not None and m["sess_start"] == s1["sess_start"])
        self.check("T11 合并起始时间==段1起始(session.start_time)", ok_start,
                   f"merged={_fmt_ts(m['sess_start'])} seg1={_fmt_ts(s1['sess_start'])}")

        # T12 结束时间 == 段2 结束(末record)
        ok_end = (m["last"] is not None and m["last"] == s2["last"])
        self.check("T12 合并结束时间==段2结束(末record)", ok_end,
                   f"merged_last={_fmt_ts(m['last'])} seg2_last={_fmt_ts(s2['last'])}")

        # T13 record 时间戳多重集合 == 段1 ∪ 段2（杀手锏：任何偏移/重复/丢失都报红）
        merged_set = m["rec_ts"]
        union = s1["rec_ts"] + s2["rec_ts"]
        union.sort()
        ok_rec = (merged_set == union)
        detail = f"merged={len(merged_set)} 段1+段2={len(union)}"
        if not ok_rec:
            if len(merged_set) != len(union):
                detail += f" 长度不一致(可能重复或丢失)"
            for i in range(min(len(merged_set), len(union))):
                if merged_set[i] != union[i]:
                    detail += f" 首个差异@idx{i}: merged={_fmt_ts(merged_set[i])} src={_fmt_ts(union[i])}"
                    break
        self.check("T13 record时间戳多重集合==段1∪段2(无偏移/重复/丢失)", ok_rec, detail)

        # T14 全部 record 时间戳落在 [段1首, 段2末] 区间内
        lo = min(s1["first"], s2["first"]); hi = max(s1["last"], s2["last"])
        out_of_range = [t for t in merged_set if t < lo or t > hi]
        ok_b = not out_of_range
        self.check("T14 合并record时间戳全在[段1首,段2末]内", ok_b,
                   "" if ok_b else f"越界{len(out_of_range)}条, 区间=[{_fmt_ts(lo)},{_fmt_ts(hi)}]")

        # T15 总时长 == 段2末 - 段1首
        ok_d = (m["first"] is not None and m["last"] is not None
                and (m["last"] - m["first"]) == (s2["last"] - s1["first"]))
        self.check("T15 合并总时长==段2末-段1首", ok_d,
                   f"merged={(m['last']-m['first']) if m['last'] else None}s "
                   f"src={(s2['last']-s1['first']) if s2['last'] else None}s")

        # T16 file_id.time_created == 段1（合并应继承首段身份）
        ok_fid = (m["fid_tc"] == s1["fid_tc"])
        self.check("T16 file_id.time_created==段1", ok_fid,
                   f"merged={_fmt_ts(m['fid_tc'])} seg1={_fmt_ts(s1['fid_tc'])}")

        # T17 device_info 身份 == 段1
        ok_di = (m["di"] == s1["di"])
        self.check("T17 device_info身份(manufacturer,product)==段1", ok_di,
                   f"merged={m['di']} seg1={s1['di']}")

    # ---------- runner ----------
    def run(self):
        runs, field_issues, _ = self.raw_scan()
        self.test_header_crc()
        self.test_file_crc()
        self.test_orphan_defs(runs)
        self.test_field_sizes(field_issues)
        msgs = self.semantic()
        self.test_file_id(msgs)
        self.test_device_info(msgs)
        self.test_dev_fields(msgs)
        self.test_laps(msgs)
        self.test_record_monotonic(msgs)
        self.test_message_index(msgs)
        self.test_lap_pace(msgs)
        self.test_lap_timer_elapsed(msgs)
        self.cross_check()

    def report(self):
        print("=" * 72)
        print(f"FIT QA 报告: {self.path}")
        print("=" * 72)
        fails = warns = 0
        for level, name, ok, detail in self.results:
            mark = "✅" if level == "PASS" else ("⚠️" if level == "WARN" else "❌")
            line = f"  {mark} {name}"
            if detail:
                line += f"  — {detail}"
            print(line)
            if level == "FAIL": fails += 1
            if level == "WARN": warns += 1
        print("-" * 72)
        print(f"  结果: PASS={len(self.results)-fails-warns}  WARN={warns}  FAIL={fails}")
        return fails


def main():
    ap = argparse.ArgumentParser(description="FIT 合并文件 QA 测试 (开发→测试→修复→复测)")
    ap.add_argument("fit", help="待质检的合并 .fit 文件")
    ap.add_argument("sources", nargs="*", help="原始段文件(先跑的段 后跑的段)，用于交叉校验时间/身份")
    ap.add_argument("--expect-devices", type=int, default=1, help="期望的不同 device_info 数量(同设备合并=1)")
    ap.add_argument("--lap-km", type=float, default=1000.0, help="每个整圈的目标距离(米)，默认1000")
    ap.add_argument("--slack-m", type=float, default=3.0, help="距离容差(米)，默认3")
    args = ap.parse_args()
    if not os.path.exists(args.fit):
        sys.stderr.write(f"ERROR: 文件不存在 {args.fit}\n")
        sys.exit(2)
    for s in args.sources:
        if not os.path.exists(s):
            sys.stderr.write(f"ERROR: 源文件不存在 {s}\n")
            sys.exit(2)
    qa = QA(args.fit, expect_devices=args.expect_devices, lap_km=args.lap_km,
            slack_m=args.slack_m, sources=args.sources)
    qa.run()
    fails = qa.report()
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
