#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_fit_segments.py — Merge several Garmin FIT activity files that actually
belong to ONE continuous workout (e.g. a run split into parts because the user
accidentally pressed "save" mid-activity) back into a single uploadable FIT.

Strategy: byte-level concatenation (preserves ALL messages including proprietary
device streams that the official garmin-fit-sdk Encoder refuses to write), with
two corrections required for the result to be accepted by Garmin Connect:

  1. Cumulative distance: each segment's record.distance (field 5) and
     lap.total_distance (field 5) are SEGMENT-LOCAL (start at 0). After
     concatenation the distance drops back to 0 at every boundary, which makes
     the track non-monotonic and Garmin Connect rejects the upload ("upload
     error"). Fix: add the running cumulative distance (in raw cm) as an offset
     to every record/lap distance field of segments 2..N.

  2. Session summary: only seg1's session is kept; patch its totals
     (total_distance=9, total_timer_time=8, total_elapsed_time=7,
     num_laps=26, timestamp=253) to the merged values.

  3. message_index uniqueness: every segment starts its own lap / split /
     split_summary message_index at 0, so after concatenation the SAME index
     value appears several times (e.g. lap 0 three times). Garmin Connect reads
     laps/splits BY message_index and chokes on duplicates ("upload error").
     Fix: renumber every message type that carries a message_index (field 254)
     to a sequential 0..N counter per message type.

Also: keep device_info from ALL segments (never drop) — this is what lets the
compressed-timestamp data messages (header bit 7) reset their reference at each
segment boundary.

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
# is intentionally NOT here — it is kept from every segment.
DROP_NAMES = {
    "file_id", "file_creator", "activity", "session", "device_settings",
    "user_profile", "sport", "training_settings", "zones_target",
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
    out = bytearray()
    for fr in walk(body):
        if not fr["is_def"] and fr["global"] in (20, 19):  # record / lap
            new = add_distance_offset(fr["chunk"], fr["dd"], 5, off, fr["compressed"], fr["dev"])
            out += new if new is not None else fr["chunk"]
        else:
            out += fr["chunk"]
    return bytes(out)


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


# ---------- per-segment summary via fitdecode ----------
def seg_summary(path):
    timer = elapsed = num_laps = None
    last_ts = first_ts = None
    with fitdecode.FitReader(path, check_crc=False) as fit:
        for fr in fit:
            if isinstance(fr, fitdecode.records.FitDataMessage):
                if fr.name == "session":
                    if fr.get_field("total_timer_time") is not None:
                        timer = fr.get_field("total_timer_time").value
                    if fr.get_field("total_elapsed_time") is not None:
                        elapsed = fr.get_field("total_elapsed_time").value
                    nl = fr.get_field("num_laps")
                    if nl is not None:
                        num_laps = nl.value
                if fr.name == "record" and fr.get_field("timestamp") is not None:
                    ts = fr.get_field("timestamp").value
                    last_ts = ts
                    if first_ts is None:
                        first_ts = ts
    return timer, elapsed, num_laps, last_ts, first_ts


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
            merged += fr["chunk"]
    assert patched, "seg1 had no session message"
    if not activity_patched:
        print("WARNING: seg1 had no activity message; skipping activity patch")
    for k in range(1, len(bodies_off)):
        for fr in walk(bodies_off[k]):
            name = name_map.get(fr["global"], f"unknown_{fr['global']}")
            if name in drop:
                continue
            merged += fr["chunk"]
    merged = bytes(merged)
    # correction #3: make every message_index unique per message type
    merged = renumber_message_indices(merged)

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
          f"record={cnt.get('record')} lap={cnt.get('lap')} device_info={cnt.get('device_info')}")
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
