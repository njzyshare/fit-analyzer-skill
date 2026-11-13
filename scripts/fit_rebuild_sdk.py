#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_rebuild_sdk.py — Re-encode a FIT activity through the OFFICIAL Garmin SDK
(garmin-fit-sdk), preserving the original message order.

WHY: a last-resort path when byte-level merge/rebuild is still rejected. The
official SDK produces the most "standard" possible file, which Connect is most
likely to accept. Trade-off: the SDK Encoder REFUSES to write proprietary device
messages (mesg_num not in Profile, e.g. fenix8 unknown_233 training-load
streams) — those are dropped. All standard messages (record/lap/session/
activity/event/device_info/...) are kept, in original order.

KEY SDK details (learned the hard way):
  * Decoder.read(mesg_listener=fn) fires fn(mesg_num, message) per message in
    FILE ORDER — use this (not the grouped read()) so record/event interleaving
    is preserved.
  * Encoder.write_mesg(msg) needs the dict to carry a 'mesg_num' key.
  * Proprietary messages (mesg_num not in Profile['mesg_num'].values()) cannot
    be encoded -> skip them.
  * float nan/inf fields (session/lap avg/max) crash the encoder with
    "Could not convert nan to float32" -> set them to None before encoding.
  * If the input has compressed-timestamp messages (header bit 7), the SDK
    decode raises; such files must be expanded first (use fit_merge.py which
    keeps them) — but a merged file that passed SDK decode has none.

Usage:
  python fit_rebuild_sdk.py input.fit -o output.fit [--zip]
"""
import argparse
import math
import os
import zipfile
import garmin_fit_sdk as fit
from garmin_fit_sdk import Encoder, Profile
from collections import Counter


def clean(msg):
    out = {}
    for k, v in msg.items():
        if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
            out[k] = None
        elif isinstance(v, list):
            out[k] = [None if isinstance(x, float) and (math.isnan(x) or math.isinf(x)) else x
                      for x in v]
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Rebuild a FIT via official Garmin SDK.")
    ap.add_argument("input", help="Source .fit (already merged/clean)")
    ap.add_argument("-o", "--output", required=True, help="Output .fit path")
    ap.add_argument("--zip", action="store_true", help="Also write a .zip next to output")
    args = ap.parse_args()

    VALID_NUMS = set(Profile["mesg_num"].values())

    skipped = []
    enc = Encoder()

    def listener(mesg_num, message):
        if mesg_num not in VALID_NUMS:
            skipped.append((mesg_num, "proprietary (dropped)"))
            return  # proprietary -> drop
        m = clean(dict(message))
        m["mesg_num"] = mesg_num
        try:
            enc.write_mesg(m)
        except Exception as e:
            skipped.append((mesg_num, str(e)[:80]))

    print("Decoding (preserving order) + encoding ...")
    s = fit.Stream.from_byte_array(open(args.input, "rb").read())
    msgs, errs = fit.Decoder(s).read(enable_crc_check=True, mesg_listener=listener)
    data = enc.close()
    open(args.output, "wb").write(data)

    print("decode errors:", errs[:3])
    print("written FIT bytes:", len(data))
    print("skipped (proprietary/encode-fail) msgs:", len(skipped))
    if skipped:
        print("  skip breakdown:", dict(Counter(k for k, _ in skipped)))

    # re-validate the freshly written file
    print("\nRe-validating with SDK ...")
    s2 = fit.Stream.from_byte_array(data)
    m2, e2 = fit.Decoder(s2).read(enable_crc_check=True)
    c = Counter({k: len(v) for k, v in m2.items()})
    print("errors:", e2[:3])
    print("file_id:", c.get("file_id_mesgs"), "session:", c.get("session_mesgs"),
          "activity:", c.get("activity_mesgs"), "record:", c.get("record_mesgs"),
          "lap:", c.get("lap_mesgs"), "device_info:", c.get("device_info_mesgs"),
          "event:", c.get("event_mesgs"))
    ses = m2.get("session_mesgs", [{}])[0]
    if ses:
        print("session dist(m):", ses.get("total_distance"),
              "timer(s):", ses.get("total_timer_time"),
              "elapsed(s):", ses.get("total_elapsed_time"),
              "num_laps:", ses.get("num_laps"))
    recs = m2.get("record_mesgs", [])
    if recs:
        print("first ts:", recs[0].get("timestamp"), "last ts:", recs[-1].get("timestamp"))

    if args.zip:
        zp = os.path.splitext(args.output)[0] + ".zip"
        with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(args.output, os.path.basename(args.output))
        print("\nFIT:", args.output, os.path.getsize(args.output), "bytes")
        print("ZIP:", zp, os.path.getsize(zp), "bytes")


if __name__ == "__main__":
    main()
