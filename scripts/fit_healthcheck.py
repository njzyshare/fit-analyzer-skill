#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_healthcheck.py — Pre-upload sanity check for a merged/edited Garmin FIT.

Catches the semantic problems that make Garmin Connect reject an otherwise
"valid" file with the generic "上传出错。请重试。" error (no detail given).
Run this BEFORE declaring a merge/rebuild done.

Checks (each maps to a known Connect rejection cause):
  1. record timestamps strictly monotonic (reconstructs compressed timestamps,
     header bit 7, using the last full timestamp as reference).
  2. record distance strictly monotonic (no drop back to 0 at segment joins).
  3. segment boundaries: time gaps > 30s between consecutive records (the
     accidental-save pauses — expected, just reported).
  4. activity + session summary fields (timer/elapsed/distance/timestamp) so
     you can eyeball that the top-level totals align with the records.
  5. duplicate message_index across every message type (Connect resolves
     laps/splits by message_index; duplicates => reject).

Usage:
  python fit_healthcheck.py file.fit
"""
import argparse
import struct
import datetime
import fitdecode
from collections import defaultdict

FIT_EPOCH = 631065600  # 1989-12-31 UTC, seconds


def ts2dt(ts):
    return datetime.datetime.fromtimestamp(FIT_EPOCH + ts, datetime.timezone.utc)


def read_parts(path):
    with open(path, "rb") as f:
        data = f.read()
    hsize = data[0]
    ds = struct.unpack("<I", data[4:8])[0]
    return data[:hsize], data[hsize:hsize + ds]


def walk(raw):
    i, n = 0, len(raw)
    active = {}
    while i < n:
        start = i
        hb = raw[i]; i += 1
        if hb & 0x80:  # compressed timestamp
            lt = (hb >> 5) & 0x03
            dd = active.get(lt)
            if dd is None:
                continue
            i += dd["data_size"]
            yield {"global": dd["global"], "is_def": False, "chunk": raw[start:i],
                   "dd": dd, "compressed": True, "offset": hb & 0x1F}
        else:
            lt = hb & 0x0F
            is_def = (hb & 0x40) != 0
            if is_def:
                i += 2
                gnum = raw[i] | (raw[i + 1] << 8); i += 2
                numf = raw[i]; i += 1
                fields = []
                for _ in range(numf):
                    fnum = raw[i]; fsize = raw[i + 1]; ftype = raw[i + 2]; i += 3
                    fields.append((fnum, fsize, ftype))
                dev_fields = []
                if hb & 0x20:
                    numdev = raw[i]; i += 1
                    for _ in range(numdev):
                        fnum = raw[i]; fsize = raw[i + 1]; ftype = raw[i + 2]; i += 3
                        dev_fields.append((fnum, fsize, ftype))
                data_size = sum(f[1] for f in fields) + sum(d[1] for d in dev_fields)
                dd = {"global": gnum, "fields": fields, "dev_fields": dev_fields,
                      "data_size": data_size}
                active[lt] = dd
                yield {"global": gnum, "is_def": True, "chunk": raw[start:i], "dd": dd,
                       "compressed": False, "offset": 0}
            else:
                dd = active.get(lt)
                if dd is None:
                    continue
                i += dd["data_size"]
                yield {"global": dd["global"], "is_def": False, "chunk": raw[start:i],
                       "dd": dd, "compressed": False, "offset": 0}


def read_field(chunk, dd, fnum):
    payload = chunk[1:]
    off = 0
    for (fn, sz, ft) in dd["fields"]:
        if fn == fnum:
            return int.from_bytes(payload[off:off + sz], "little", signed=False)
        off += sz
    for (fn, sz, ft) in dd["dev_fields"]:
        off += sz
    return None


def main():
    ap = argparse.ArgumentParser(description="Health-check a FIT before uploading to Connect.")
    ap.add_argument("input", help=".fit path to check")
    args = ap.parse_args()

    header, body = read_parts(args.input)

    # 1+2) record ts / distance + 3) boundaries
    last_full = None
    prev_ts = prev_dist = None
    bad_ts = bad_dist = 0
    recs = []
    for fr in walk(body):
        if fr["is_def"]:
            continue
        chunk, dd = fr["chunk"], fr["dd"]
        ts = None
        full = read_field(chunk, dd, 253)
        if full is not None:
            last_full = full
            ts = full
        elif fr["compressed"] and last_full is not None:
            ts = last_full + fr["offset"]
        if fr["global"] == 20:  # record
            dist = read_field(chunk, dd, 5)
            if ts is not None:
                recs.append((ts, dist))
                if prev_ts is not None and ts < prev_ts:
                    bad_ts += 1
                prev_ts = ts
            if dist is not None:
                if prev_dist is not None and dist + 1 < prev_dist:
                    bad_dist += 1
                prev_dist = dist

    print("=== RECORD TIMESTAMP / DISTANCE MONOTONICITY ===")
    print(f"records: {len(recs)}  NON-monotonic ts: {bad_ts}  NON-monotonic dist: {bad_dist}")
    if recs:
        print(f"first: {ts2dt(recs[0][0])} dist={recs[0][1]}cm  "
              f"last: {ts2dt(recs[-1][0])} dist={recs[-1][1]}cm")

    print("\n=== SEGMENT BOUNDARIES (gap > 30s) ===")
    nb = 0
    for k in range(1, len(recs)):
        d = recs[k][0] - recs[k - 1][0]
        if d > 30:
            nb += 1
            print(f"   idx {k}: {ts2dt(recs[k-1][0])} -> {ts2dt(recs[k][0])}  "
                  f"gap={d}s  dist {recs[k-1][1]}->{recs[k][1]}cm")
    print(f"(found {nb} boundary/boundaries — expected for accidental-save pauses)")

    # 4) activity + session summaries
    for want in ("activity", "session"):
        print(f"\n=== {want.upper()} full fields ===")
        with fitdecode.FitReader(args.input, check_crc=True) as fit:
            for fr in fit:
                if isinstance(fr, fitdecode.records.FitDataMessage) and fr.name == want:
                    for f in fr.fields:
                        try:
                            v = f.value
                        except Exception:
                            v = "?"
                        print(f"   f{f.def_num:<3} {f.name:<22} = {v}")
                    break

    # 5) duplicate message_index per message type
    print("\n=== message_index DUPLICATE CHECK ===")
    idx_map = defaultdict(list)
    with fitdecode.FitReader(args.input, check_crc=True) as fit:
        for fr in fit:
            if isinstance(fr, fitdecode.records.FitDataMessage):
                try:
                    m = fr.get_field("message_index")
                except KeyError:
                    continue
                idx_map[fr.name].append(m.value)
    any_dup = False
    for name, vals in idx_map.items():
        u = len(set(vals))
        ok = u == len(vals)
        if not ok:
            any_dup = True
        print(f"   {name:14} count={len(vals):4} unique={u:4} {'DUPLICATE!' if not ok else 'ok'}")
    print("\nRESULT:", "ALL CHECKS PASSED" if (bad_ts == 0 and bad_dist == 0 and not any_dup)
          else "ISSUES FOUND — fix before upload")


if __name__ == "__main__":
    main()
