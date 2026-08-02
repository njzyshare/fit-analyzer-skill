#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_fit_segments.py — Merge several Garmin FIT activity files that actually
belong to ONE continuous workout (e.g. a run split into parts because the user
accidentally pressed "save" mid-activity) back into a single uploadable FIT.

Strategy: byte-level concatenation (preserves ALL messages including proprietary
device streams that the official garmin-fit-sdk Encoder refuses to write), with
two corrections required for the result to be accepted by Garmin Connect:

  1. Cumulative distance: each segment's record.distance (field 5) is
     SEGMENT-LOCAL (starts at 0). After concatenation the distance drops back
     to 0 at every boundary, which makes the track non-monotonic and Garmin
     Connect rejects the upload ("upload error"). Fix: add the running
     cumulative distance (in raw cm) as a constant offset to every record of
     segments 2..N.

  2. Laps are REGENERATED from scratch (see regenerate_laps): COROS stores
     *per-lap* distance, so a naive concatenation leaves two scattered partial
     laps (each segment's tail). We drop the original lap messages and re-cut
     uniform ~1 km laps from the cumulative record distance — every full 1000 m
     becomes one lap and the final remainder becomes its own lap, exactly as a
     single continuous recording would look.

  2. Session summary: only seg1's session is kept; patch its totals
     (total_distance=9, total_timer_time=8, total_elapsed_time=7,
     num_laps=26, timestamp=253) to the merged values.

  3. message_index uniqueness: every segment starts its own lap / split /
     split_summary message_index at 0, so after concatenation the SAME index
     value appears several times (e.g. lap 0 three times). Garmin Connect reads
     laps/splits BY message_index and chokes on duplicates ("upload error").
     Fix: renumber every message type that carries a message_index (field 254)
     to a sequential 0..N counter per message type.

Also: device_info is de-duplicated by device identity across segments (keep the
first occurrence of each unique device; identical devices therefore collapse to a
single entry). This prevents strict parsers (e.g. COROS) from seeing two device
entries and labelling the activity "unknown device". Files without compressed
timestamps (e.g. COROS) are unaffected by dropping the duplicate; files WITH
compressed timestamps and genuinely different devices per segment keep both.

Requirements: fitdecode  (pip install fitdecode). Optionally garmin-fit-sdk for
the --sdk-check validation.

Usage:
  python merge_fit_segments.py seg1.fit seg2.fit [seg3.fit ...] -o merged.fit [--zip]
"""
import os, struct, argparse, sys
import fitdecode
from datetime import datetime, timezone

FIT_EPOCH = datetime(1989, 12, 31, 0, 0, 0, tzinfo=timezone.utc)

# Standard singleton config messages: keep only seg1's copy. device_info (23)
# is intentionally NOT here — it is de-duplicated separately (see the loop below):
# the FIRST occurrence's definition+data are kept, and any later segment carrying an
# identical device (same non-timestamp fields) has BOTH its def and data dropped, so
# the merged file has exactly one device_info and no orphan definition.
DROP_NAMES = {
    "file_id", "file_creator", "activity", "session", "device_settings",
    "user_profile", "sport", "training_settings", "zones_target",
    # Developer-field definitions must be de-duplicated across segments. Each
    # source file carries its own developer_data_id (index 0) + field_description
    # set; concatenating them yields duplicate developer_data_index values, which
    # violates the FIT spec (index must be unique per file) and makes strict
    # parsers (e.g. COROS) discard ALL private fields (e.g. "Effort Pace"/等强配速).
    # Segments from the SAME device share identical definitions, so keep only
    # seg1's copy and drop the rest; per-record developer values survive and still
    # resolve against the single remaining definition.
    "developer_data_id", "field_description",
}
# Add device-specific proprietary singletons as discovered (fenix8 example):
#   "unknown_140","unknown_141","unknown_147","unknown_79","unknown_499","unknown_517"

SESSION_FIELDS = {"total_distance": 9, "total_timer_time": 8,
                  "total_elapsed_time": 7, "num_laps": 26, "timestamp": 253}
# Activity (global 34) top-level summary — align with the merged session so
# Garmin Connect's session/activity consistency check passes. Only uint32
# fields are safe to patch generically; patch_session skips fields that
# cannot hold the value (e.g. a 2-byte local_timestamp on some devices).
ACTIVITY_FIELDS = {"total_timer_time": 0, "timestamp": 253}


# ---------- low-level frame walker ----------
def read_body(path):
    d = open(path, "rb").read()
    hsize = d[0]
    datasize = int.from_bytes(d[4:8], "little")
    return d, d[hsize:hsize + datasize]


def walk(raw):
    i = 0; n = len(raw); active = {}; frames = []
    while i < n:
        start = i; hb = raw[i]; i += 1
        if hb & 0x80:  # compressed timestamp
            local = (hb >> 5) & 0x03; dd = active[local]; i += dd["data_size"]
            frames.append({"hb": hb, "chunk": raw[start:i], "global": dd["global"],
                           "is_def": False, "dd": dd, "compressed": True, "dev": False})
        else:
            is_def = bool(hb & 0x40); dev = bool(hb & 0x20); local = hb & 0x0F
            if is_def:
                i += 2; gnum = int.from_bytes(raw[i:i + 2], "little"); i += 2; nf = raw[i]; i += 1
                fields = []
                for _ in range(nf):
                    dn = raw[i]; sz = raw[i + 1]; bt = raw[i + 2]; i += 3; fields.append((dn, sz, bt))
                devf = []
                if dev:
                    nd = raw[i]; i += 1
                    for _ in range(nd):
                        dn = raw[i]; sz = raw[i + 1]; di = raw[i + 2]; i += 3; devf.append((dn, sz, di))
                ds = sum(f[1] for f in fields) + sum(x[1] for x in devf)
                active[local] = {"global": gnum, "fields": fields, "dev_fields": devf, "data_size": ds}
                frames.append({"hb": hb, "chunk": raw[start:i], "global": gnum,
                               "is_def": True, "dd": active[local], "compressed": False, "dev": dev})
            else:
                if dev: i += 1  # developer data index byte
                dd = active[local]; i += dd["data_size"]
                frames.append({"hb": hb, "chunk": raw[start:i], "global": dd["global"],
                               "is_def": False, "dd": dd, "compressed": False, "dev": dev})
    return frames


def field_payload_offset(dd, target):
    off = 0
    for (dn, sz, bt) in dd["fields"]:
        if dn == target:
            return off
        off += sz
    return None


def read_field_raw(chunk, dd, target, compressed, dev):
    off = field_payload_offset(dd, target)
    if off is None:
        return None, None, None
    ps = 2 if (dev and not compressed) else 1
    pos = ps + off
    sz = bt = None
    for (dn, s, b) in dd["fields"]:
        if dn == target:
            sz, bt = s, b; break
    return chunk[pos:pos + sz], sz, bt


def add_distance_offset(chunk, dd, target, offset, compressed, dev):
    raw, sz, bt = read_field_raw(chunk, dd, target, compressed, dev)
    if raw is None or sz != 4:
        return None
    base = int.from_bytes(raw, "little")
    if (bt & 0x1F) == 0x08:  # float32
        val = struct.unpack("<f", raw)[0] + offset
        newraw = struct.pack("<f", val)
    else:  # uint32 (distance is normally stored in cm)
        val = (base + offset) & 0xFFFFFFFF
        newraw = val.to_bytes(4, "little")
    ps = 2 if (dev and not compressed) else 1
    pos = ps + field_payload_offset(dd, target)
    out = bytearray(chunk)
    out[pos:pos + 4] = newraw
    return bytes(out)


def last_record_distance(body):
    val = None
    for fr in walk(body):
        if not fr["is_def"] and fr["global"] == 20:
            raw, _, _ = read_field_raw(fr["chunk"], fr["dd"], 5, fr["compressed"], fr["dev"])
            if raw is not None:
                val = int.from_bytes(raw, "little")
    return val


def offset_body(body, off):
    # record (20) distance lives at field 5 and is already CUMULATIVE per segment,
    # so a constant offset correctly continues it across the merge. lap distances
    # are left untouched (COROS per-lap semantics) — handled elsewhere as a no-op.
    out = bytearray()
    for fr in walk(body):
        if not fr["is_def"] and fr["global"] == 20:  # record only
            new = add_distance_offset(fr["chunk"], fr["dd"], 5, off, fr["compressed"], fr["dev"])
            out += new if new is not None else fr["chunk"]
        else:
            out += fr["chunk"]
    return bytes(out)


def dev_identity(chunk, dd, compressed, dev):
    """Device identity key from a device_info (global 23) data message. Uses the
    raw bytes of every field EXCEPT the volatile timestamp (253), so it works
    regardless of which field number the manufacturer/product/serial/product_name
    happens to occupy (COROS puts manufacturer at field 2 and product_name at field
    27, which a fixed (1,2,3,20) tuple would miss). Two device_info with identical
    non-timestamp fields are the same physical device and get de-duplicated, so
    strict parsers (e.g. COROS) don't see two device entries and label the activity
    'unknown device'."""
    key = []
    for (dn, sz, bt) in dd["fields"]:
        if dn == 253:  # timestamp: volatile, ignore
            continue
        raw, _, _ = read_field_raw(chunk, dd, dn, compressed, dev)
        key.append((dn, raw))
    return tuple(key)


def patch_session(chunk, dd, values):
    hb = chunk[0]; payload = bytearray(chunk[1:]); off = 0
    for (dn, sz, bt) in dd["fields"]:
        if dn in values:
            try:
                payload[off:off + sz] = values[dn].to_bytes(sz, "little", signed=False)
            except OverflowError:
                # field too narrow for the patched value (e.g. 2-byte
                # local_timestamp) — leave it untouched rather than crash.
                pass
        off += sz
    for (dn, sz, di) in dd["dev_fields"]:
        off += sz
    return bytes([hb]) + bytes(payload)


def crc16(data):
    return fitdecode.utils.compute_crc(data)


def _has_message_index(dd):
    return any(dn == 254 for (dn, _s, _b) in dd["fields"])


def patch_message_index(chunk, dd, new_idx):
    hb = chunk[0]; payload = bytearray(chunk[1:]); off = 0
    for (dn, sz, bt) in dd["fields"]:
        if dn == 254:  # message_index
            payload[off:off + sz] = new_idx.to_bytes(sz, "little", signed=False)
            return bytes([hb]) + bytes(payload)
        off += sz
    for (dn, sz, di) in dd["dev_fields"]:
        off += sz
    return chunk


def renumber_message_indices(body):
    """Renumber message_index (field 254) of every data message to a per-type
    sequential 0..N counter. Required so Garmin Connect can resolve laps/splits
    by index without hitting duplicate keys."""
    from collections import defaultdict
    counters = defaultdict(int)
    out = bytearray()
    for fr in walk(body):
        if not fr["is_def"] and _has_message_index(fr["dd"]):
            out += patch_message_index(fr["chunk"], fr["dd"], counters[fr["global"]])
            counters[fr["global"]] += 1
        else:
            out += fr["chunk"]
    return bytes(out)


# ---------- timestamp shift (whole-file, preserves everything else) ----------
def _maybe_shift_field(chunk, dd, target, delta, compressed, dev):
    raw, sz, bt = read_field_raw(chunk, dd, target, compressed, dev)
    if raw is None or sz != 4:
        return chunk
    val = (int.from_bytes(raw, "little") + delta) & 0xFFFFFFFF
    ps = 2 if (dev and not compressed) else 1
    pos = ps + field_payload_offset(dd, target)
    c = bytearray(chunk)
    c[pos:pos + 4] = val.to_bytes(4, "little")
    return bytes(c)


def shift_timestamps(body, delta):
    """Shift every absolute-time field by `delta` seconds, leaving all other
    bytes untouched. Affected fields:
      - field 253 (timestamp) in ANY data message
      - file_id(0) field 4 (time_created)
      - session(18)/lap(19) field 2 (start_time)
    Developer fields and (compressed) timestamp-header messages pass through
    untouched. COROS files are uncompressed and carry Effort-Pace dev fields, so
    this is the common, byte-safe path. Returns new body bytes (caller recomputes
    the file CRC).

    Why not the garmin-fit-sdk re-encode (shift_time_sdk.mjs)? The Encoder drops
    the 29 manual "resume" timer events on these COROS files, which makes COROS
    mis-scale the pace chart at pauses. Byte-level shift keeps all 62 events.
    """
    out = bytearray()
    for fr in walk(body):
        if fr["is_def"]:
            out += fr["chunk"]
            continue
        c = bytearray(fr["chunk"])
        c = _maybe_shift_field(c, fr["dd"], 253, delta, fr["compressed"], fr["dev"])
        if fr["global"] == 0:
            c = _maybe_shift_field(c, fr["dd"], 4, delta, fr["compressed"], fr["dev"])
        if fr["global"] in (18, 19):
            c = _maybe_shift_field(c, fr["dd"], 2, delta, fr["compressed"], fr["dev"])
        out += bytes(c)
    return bytes(out)


# ---------- lap regeneration (uniform distance laps) ----------
def _base_signed(base):
    """FIT base type -> signedness for integer packing."""
    return (base & 0x1F) in (1, 3, 5, 13)  # sint8/sint16/sint32/sint64


def pack_field(sz, base, value):
    """Pack a python int/float into `sz` raw bytes using the FIT base type."""
    t = base & 0x1F
    if t == 8:   # float32
        return struct.pack("<f", float(value))[:sz]
    if t == 9:   # float64
        return struct.pack("<d", float(value))[:sz]
    return int(round(value)).to_bytes(sz, "little", signed=_base_signed(base))


def write_field(chunk, dd, target, value, compressed, dev):
    """Overwrite a single field's raw payload in a data message chunk."""
    off = field_payload_offset(dd, target)
    if off is None:
        return chunk
    sz = bt = None
    for (dn, s, b) in dd["fields"]:
        if dn == target:
            sz, bt = s, b
            break
    if sz is None:
        return chunk
    raw = pack_field(sz, bt, value)
    ps = 2 if (dev and not compressed) else 1
    pos = ps + off
    c = bytearray(chunk)
    c[pos:pos + sz] = raw
    return bytes(c)


def _read_int(chunk, dd, target, compressed, dev):
    raw, _, _ = read_field_raw(chunk, dd, target, compressed, dev)
    if raw is None:
        return None
    fld = next((f for f in dd["fields"] if f[0] == target), None)
    if fld is None:
        return None
    return int.from_bytes(raw, "little", signed=_base_signed(fld[2]))


def regenerate_laps(merged, pause_gap_sec=60):
    """Rewrite the existing lap messages so distances are uniform ~1 km cuts of
    the (already cumulative) record stream: every full 1000 m becomes one lap and
    the remaining fraction becomes the final lap. This is what a single
    continuous recording would produce, instead of two scattered partial laps.

    The original lap message *structure* (definitions + N data frames) is kept
    intact — only per-lap fields are overwritten in place — so no message
    definition / local-number bookkeeping is disturbed.

    Pause-aware timing (FIX 2026-08-02):
      * Pauses are detected as >pause_gap_sec jumps in consecutive *record*
        timestamps. The watch stops writing records while paused, so a real pause
        shows up as a time gap at (near) constant distance — both the inter-segment
        pause and every in-lap pause are caught this way.
      * Each lap's total_timer_time = total_elapsed_time − (sum of pause seconds
        overlapping that lap's [start_ts, end_ts]). A pause that straddles a lap
        boundary is split, each lap getting only its portion.
      * avg_pace (field 11, encoded as s/m*1000) and total_moving_time (field 10)
        are recomputed from the pause-corrected timer time, so per-lap pace no
        longer includes paused time.
      * device_info is NEVER touched here. COROS stores manufacturer in field 2 of
        device_info (there is no field 1); rewriting device_info (e.g. setting
        field 2 = product code, or adding a field 1) makes COROS mis-parse the
        whole file and render laps wrong (lap5 shown as the ~120 m short tail).
        See MEMORY / 2026-08-02 note. Keep device_info byte-identical to source.

    Returns new body bytes.
    """
    import bisect
    # 1) collect records (distance cm, timestamp sec), sorted by distance
    D, T = [], []
    for fr in walk(merged):
        if not fr["is_def"] and fr["global"] == 20:
            d = _read_int(fr["chunk"], fr["dd"], 5, fr["compressed"], fr["dev"])
            t = _read_int(fr["chunk"], fr["dd"], 253, fr["compressed"], fr["dev"])
            if d is not None and t is not None:
                D.append(d)
                T.append(t)
    if not D:
        return merged
    order = sorted(range(len(D)), key=lambda i: D[i])
    D = [D[i] for i in order]
    T = [T[i] for i in order]
    total = D[-1]

    # 2) pause intervals from record time gaps (timestamps sorted with distance)
    gaps = []
    for i in range(1, len(T)):
        dt = T[i] - T[i - 1]
        if dt > pause_gap_sec:
            gaps.append((T[i - 1], T[i]))

    def interp_ts(d):
        if d <= D[0]:
            return T[0]
        if d >= D[-1]:
            return T[-1]
        i = bisect.bisect_right(D, d) - 1
        d0, d1, t0, t1 = D[i], D[i + 1], T[i], T[i + 1]
        if d1 == d0:
            return t1
        return t0 + (d - d0) / (d1 - d0) * (t1 - t0)

    def pause_in(s_ts, e_ts):
        s = 0.0
        for (a, b) in gaps:
            lo, hi = max(a, s_ts), min(b, e_ts)
            if hi > lo:
                s += hi - lo
        return s

    # 3) lap boundaries (every 1000 m, final remainder)
    n_full = total // 100000
    bounds = [(k + 1) * 100000 for k in range(n_full)]
    if not bounds or bounds[-1] < total:
        bounds.append(total)

    # 4) rewrite each existing lap data frame in stream order
    out = bytearray()
    lap_idx = 0
    for fr in walk(merged):
        if fr["global"] == 19 and not fr["is_def"]:
            if lap_idx >= len(bounds):
                out += fr["chunk"]
                continue
            end = bounds[lap_idx]
            start = bounds[lap_idx - 1] if lap_idx > 0 else 0
            dist = end - start
            s_ts = interp_ts(start)
            e_ts = interp_ts(end)
            elapsed_ms = int(round((e_ts - s_ts) * 1000))
            paus = pause_in(s_ts, e_ts)
            timer_ms = max(elapsed_ms - int(round(paus * 1000)), 0)
            chunk = bytearray(fr["chunk"])
            chunk = write_field(chunk, fr["dd"], 254, lap_idx, fr["compressed"], fr["dev"])   # message_index
            chunk = write_field(chunk, fr["dd"], 253, int(round(e_ts)), fr["compressed"], fr["dev"])  # timestamp (end)
            chunk = write_field(chunk, fr["dd"], 2, int(round(s_ts)), fr["compressed"], fr["dev"])    # start_time
            chunk = write_field(chunk, fr["dd"], 8, timer_ms, fr["compressed"], fr["dev"])   # total_timer_time
            chunk = write_field(chunk, fr["dd"], 7, elapsed_ms, fr["compressed"], fr["dev"])  # total_elapsed_time
            chunk = write_field(chunk, fr["dd"], 9, dist, fr["compressed"], fr["dev"])        # total_distance
            dist_km = dist / 100000.0
            if dist_km > 0:
                pace_raw = int(round((timer_ms / 1000.0) / dist_km))   # s/m*1000 == s per km for 1km lap
                chunk = write_field(chunk, fr["dd"], 11, pace_raw, fr["compressed"], fr["dev"])  # avg_pace
            chunk = write_field(chunk, fr["dd"], 10, timer_ms, fr["compressed"], fr["dev"])     # total_moving_time
            out += bytes(chunk)
            lap_idx += 1
        else:
            out += fr["chunk"]
    return bytes(out)


# ---------- per-segment summary via fitdecode ----------
def seg_summary(path):
    timer = elapsed = None
    last_ts = first_ts = None
    lap_count = 0
    with fitdecode.FitReader(path, check_crc=False) as fit:
        for fr in fit:
            if isinstance(fr, fitdecode.records.FitDataMessage):
                if fr.name == "session":
                    def gf(msg, name):
                        try:
                            return msg.get_field(name)
                        except KeyError:
                            return None
                    v = gf(fr, "total_timer_time")
                    if v is not None:
                        timer = v.value
                    v = gf(fr, "total_elapsed_time")
                    if v is not None:
                        elapsed = v.value
                if fr.name == "lap":
                    lap_count += 1
                if fr.name == "record":
                    ts = None
                    try:
                        ts = fr.get_field("timestamp")
                    except KeyError:
                        ts = None
                    if ts is not None:
                        ts = ts.value
                        last_ts = ts
                        if first_ts is None:
                            first_ts = ts
    return timer, elapsed, lap_count, last_ts, first_ts


def name_map_of(path):
    nm = {}
    with fitdecode.FitReader(path, check_crc=False) as fit:
        for fr in fit:
            if hasattr(fr, "global_mesg_num"):
                nm[fr.global_mesg_num] = getattr(fr, "name", None) or f"unknown_{fr.global_mesg_num}"
    return nm


def main():
    ap = argparse.ArgumentParser(description="Merge split Garmin FIT activities into one.")
    ap.add_argument("segments", nargs="+", help="Segment .fit files in chronological order")
    ap.add_argument("-o", "--output", required=True, help="Output merged .fit path")
    ap.add_argument("--zip", action="store_true", help="Also write a .zip next to output")
    ap.add_argument("--drop", nargs="*", default=[], help="Extra global names to drop from seg2..N")
    ap.add_argument("--shift-seconds", type=int, default=0,
                    help="整体平移时间戳±秒数(改开始时间、保持时长)，用于规避平台按时间去重")
    args = ap.parse_args()

    drop = DROP_NAMES | set(args.drop)
    name_map = name_map_of(args.segments[0])

    bodies = [read_body(p)[1] for p in args.segments]
    summaries = [seg_summary(p) for p in args.segments]

    # cumulative distance offsets (raw cm)
    raw_ends = [last_record_distance(b) for b in bodies]
    if any(r is None for r in raw_ends):
        sys.exit("ERROR: could not read record.distance from a segment (field 5 missing?)")
    offsets = [0]
    for k in range(1, len(bodies)):
        offsets.append(offsets[-1] + raw_ends[k - 1])
    total_raw = sum(raw_ends)
    print(f"segment last-record distances (raw cm): {raw_ends}")
    print(f"applied offsets (cm): {offsets}  -> total = {total_raw} cm = {total_raw/100000:.3f} km")

    # session summary
    # total_timer_time = sum of per-segment timer times (excludes pauses) -> ms
    TIMER = int(round(sum(s[0] for s in summaries if s[0] is not None) * 1000))
    # total_elapsed_time = wall-clock span first-record -> last-record (INCLUDES
    # the inter-segment pauses, which are real stop/start events) -> ms
    first_dt = summaries[0][4]
    end_dt = summaries[-1][3]
    ELAPSED = int(round((end_dt - first_dt).total_seconds() * 1000)) if (first_dt and end_dt) else \
        int(round(sum(s[1] for s in summaries if s[1] is not None) * 1000))
    LAPS = sum(s[2] for s in summaries if s[2] is not None)
    END_TS = int((end_dt - FIT_EPOCH).total_seconds()) if end_dt else 0
    print(f"session: timer={TIMER/1000:.1f}s elapsed={ELAPSED/1000:.1f}s laps={LAPS} "
          f"span={first_dt} -> {end_dt}")

    # offset seg2..N
    bodies_off = [bodies[0]] + [offset_body(bodies[k], offsets[k]) for k in range(1, len(bodies))]

    # build
    merged = bytearray()
    patched = False
    activity_patched = False
    seen_dev = set()
    for fr in walk(bodies_off[0]):
        if fr["global"] == 18 and not fr["is_def"]:
            merged += patch_session(fr["chunk"], fr["dd"], {
                SESSION_FIELDS["total_distance"]: total_raw,
                SESSION_FIELDS["total_timer_time"]: TIMER,
                SESSION_FIELDS["total_elapsed_time"]: ELAPSED,
                SESSION_FIELDS["num_laps"]: LAPS,
                SESSION_FIELDS["timestamp"]: END_TS,
            })
            patched = True
        elif fr["global"] == 34 and not fr["is_def"]:
            merged += patch_session(fr["chunk"], fr["dd"], {
                ACTIVITY_FIELDS["total_timer_time"]: TIMER,
                ACTIVITY_FIELDS["timestamp"]: END_TS,
            })
            activity_patched = True
        else:
            if fr["global"] == 23 and not fr["is_def"]:  # device_info: record identity
                seen_dev.add(dev_identity(fr["chunk"], fr["dd"], fr["compressed"], fr["dev"]))
            merged += fr["chunk"]
    assert patched, "seg1 had no session message"
    if not activity_patched:
        print("WARNING: seg1 had no activity message; skipping activity patch")
    for k in range(1, len(bodies_off)):
        pending_di_def = None
        for fr in walk(bodies_off[k]):
            name = name_map.get(fr["global"], f"unknown_{fr['global']}")
            if name in drop:
                continue
            if fr["global"] == 23:  # device_info: drop duplicate devices (DEF AND data)
                if fr["is_def"]:
                    pending_di_def = fr  # decide once the following data frame arrives
                    continue
                ident = dev_identity(fr["chunk"], fr["dd"], fr["compressed"], fr["dev"])
                if ident in seen_dev:
                    pending_di_def = None  # duplicate device -> drop BOTH def and data
                    continue
                seen_dev.add(ident)
                if pending_di_def is not None:
                    merged += pending_di_def["chunk"]
                    pending_di_def = None
                merged += fr["chunk"]
                continue
            if pending_di_def is not None:
                merged += pending_di_def["chunk"]
                pending_di_def = None
            merged += fr["chunk"]
        if pending_di_def is not None:  # stray def without data (shouldn't happen)
            merged += pending_di_def["chunk"]
    merged = bytes(merged)

    # NOTE: lap messages are REGENERATED below. COROS stores *per-lap* distance,
    # so concatenating two segments yields two scattered partial laps (the tail of
    # each segment). Instead we drop the original lap messages and re-cut uniform
    # ~1 km laps from the (now cumulative) record distances: every full 1000 m is
    # one lap and the final remainder is its own lap — exactly what a single
    # continuous recording would produce.
    merged = regenerate_laps(merged)
    # correction #3: make every message_index unique per message type
    merged = renumber_message_indices(merged)
    # optional whole-file timestamp shift (preserves device_info / events / dev fields)
    if args.shift_seconds:
        merged = shift_timestamps(merged, args.shift_seconds)
        print(f"shifted timestamps by {args.shift_seconds:+d}s")

    # 14-byte header with header CRC
    d0 = open(args.segments[0], "rb").read()
    proto = d0[1]; profile = int.from_bytes(d0[2:4], "little")
    prefix = bytes([14, proto, profile & 0xff, (profile >> 8) & 0xff]) + len(merged).to_bytes(4, "little") + b".FIT"
    header = prefix + crc16(prefix).to_bytes(2, "little")
    out = header + merged + crc16(header + merged).to_bytes(2, "little")

    open(args.output, "wb").write(out)
    print(f"WROTE {args.output} ({len(out)} bytes)")

    # validate
    from collections import Counter, defaultdict
    cnt = Counter(); dist = []; idx_map = defaultdict(list)
    with fitdecode.FitReader(args.output, check_crc=True) as fit:
        for fr in fit:
            if isinstance(fr, fitdecode.records.FitDataMessage):
                cnt[fr.name] += 1
                if fr.name == "record" and fr.get_field("distance") is not None:
                    dist.append(fr.get_field("distance").value)
                try:
                    m = fr.get_field("message_index")
                    idx_map[fr.name].append(m.value)
                except KeyError:
                    pass
    bad = sum(1 for i in range(1, len(dist)) if dist[i] < dist[i - 1] - 1)
    print(f"VALIDATE: file_id={cnt.get('file_id')} session={cnt.get('session')} "
          f"record={cnt.get('record')} lap={cnt.get('lap')} device_info={cnt.get('device_info')} "
          f"developer_data_id={cnt.get('developer_data_id')} field_description={cnt.get('field_description')}")
    print(f"distance monotonic drops(>1m): {bad}  (first={dist[0]:.1f} last={dist[-1]:.1f} m)")
    dup = {n: v for n, v in idx_map.items() if len(set(v)) != len(v)}
    print(f"message_index duplicates: {dup if dup else 'NONE (ok)'}")

    if args.zip:
        import zipfile
        zp = os.path.splitext(args.output)[0] + ".zip"
        if os.path.exists(zp):
            os.remove(zp)
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(args.output, os.path.basename(args.output))
        print(f"ZIP {zp} ({os.path.getsize(zp)} bytes)")


if __name__ == "__main__":
    main()
