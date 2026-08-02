#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fit_to_tcx.py — Export a Garmin FIT activity to TCX.

WHY this exists: Garmin Connect's manual upload rejects hand-built / merged
FIT files with the generic "上传出错。请重试。" error even when the file passes
every decoder (fitdecode CRC ok, Garmin SDK errors:[]). TCX is the format
Connect's web import (connect.garmin.com/modern/import-data) ingests most
reliably. Many users report FIT upload failing while TCX of the same data works.

What is preserved: GPS trackpoints + altitude, cumulative distance, heart rate,
cadence, per-lap splits (grouped by lap.start_time), sport type, and the device
name + serial number (written into <Creator>).

What is lost: proprietary device training-load streams (e.g. fenix8 unknown_233)
— TCX has no slot for them. Core running/cycling data is fully retained.

Usage:
  python fit_to_tcx.py input.fit -o output.tcx
"""
import argparse
import os
import sys
import xml.etree.ElementTree as ET
import fitdecode
from datetime import datetime, timezone, timedelta

NS_TCD = "http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2"
NS_ACT = "http://www.garmin.com/xmlschemas/ActivityExtension/v2"
NS_XSI = "http://www.w3.org/2001/XMLSchema-instance"


def fv(fr, name):
    try:
        f = fr.get_field(name)
    except KeyError:
        return None
    return f.value if f is not None else None


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    ap = argparse.ArgumentParser(description="Export a FIT activity to TCX.")
    ap.add_argument("input", help="Source .fit path")
    ap.add_argument("-o", "--output", required=True, help="Output .tcx path")
    args = ap.parse_args()

    fid = {}
    sport = "Running"
    laps = []      # start_ts, total_distance, calories, avg_hr, max_hr, avg_cad
    records = []   # ts, lat, lon, alt, dist, hr, cad

    with fitdecode.FitReader(args.input, check_crc=True) as fit:
        for fr in fit:
            if not isinstance(fr, fitdecode.records.FitDataMessage):
                continue
            if fr.name == "file_id":
                for k in ["time_created", "manufacturer", "product", "serial_number", "type"]:
                    v = fv(fr, k)
                    if v is not None:
                        fid[k] = v
            elif fr.name == "session":
                s = fv(fr, "sport")
                if s is not None:
                    sport = str(s).split(".")[-1].capitalize()
            elif fr.name == "lap":
                laps.append({
                    "start_ts": fv(fr, "start_time"),
                    "total_distance": fv(fr, "total_distance"),
                    "calories": fv(fr, "calories"),
                    "avg_hr": fv(fr, "avg_heart_rate"),
                    "max_hr": fv(fr, "max_heart_rate"),
                    "avg_cad": fv(fr, "avg_cadence"),
                })
            elif fr.name == "record":
                ts = fv(fr, "timestamp")
                if ts is None:
                    continue
                lat = fv(fr, "position_lat")
                lon = fv(fr, "position_long")
                if lat is not None and abs(lat) > 180:
                    lat = lat / 11930464.0
                if lon is not None and abs(lon) > 180:
                    lon = lon / 11930464.0
                records.append({
                    "ts": ts,
                    "lat": lat, "lon": lon,
                    "alt": fv(fr, "altitude"),
                    "dist": fv(fr, "distance"),
                    "hr": fv(fr, "heart_rate"),
                    "cad": fv(fr, "cadence"),
                })

    if not records:
        sys.exit("ERROR: no record messages found in the FIT file")

    # group records into laps by timestamp using lap.start_time as boundaries
    laps_sorted = sorted([l for l in laps if l["start_ts"] is not None],
                         key=lambda x: x["start_ts"])
    bounds = [l["start_ts"] for l in laps_sorted]
    bounds.append(records[-1]["ts"] + timedelta(seconds=1))
    groups = [[] for _ in laps_sorted]
    for r in records:
        placed = False
        for i in range(len(laps_sorted)):
            if laps_sorted[i]["start_ts"] <= r["ts"] < bounds[i + 1]:
                groups[i].append(r)
                placed = True
                break
        if not placed and groups:
            groups[-1].append(r)

    # ---- build TCX ----
    ET.register_namespace("", NS_TCD)
    ET.register_namespace("act", NS_ACT)
    ET.register_namespace("xsi", NS_XSI)

    root = ET.Element(f"{{{NS_TCD}}}TrainingCenterDatabase")
    acts = ET.SubElement(root, f"{{{NS_TCD}}}Activities")
    act = ET.SubElement(acts, f"{{{NS_TCD}}}Activity")
    act.set("Sport", sport)

    creator = ET.SubElement(act, f"{{{NS_TCD}}}Creator")
    creator.set(f"{{{NS_XSI}}}type", "Device")
    prod = fid.get("product")
    dev_name = "Garmin fenix8" if prod == 4536 else f"Garmin {prod}" if prod else "Garmin Device"
    ET.SubElement(creator, f"{{{NS_TCD}}}Name").text = dev_name
    ET.SubElement(creator, f"{{{NS_TCD}}}UnitId").text = str(fid.get("serial_number", 0))
    ET.SubElement(creator, f"{{{NS_TCD}}}ProductID").text = str(prod if prod is not None else 0)
    dev = ET.SubElement(creator, f"{{{NS_TCD}}}Device")
    ET.SubElement(dev, f"{{{NS_TCD}}}Name").text = dev_name

    ET.SubElement(act, f"{{{NS_TCD}}}Id").text = iso(records[0]["ts"])
    notes = ET.SubElement(act, f"{{{NS_TCD}}}Notes")
    notes.text = "Exported from Garmin FIT via 运动记录fit分析器."

    for i, lap in enumerate(laps_sorted):
        grp = groups[i]
        if not grp:
            continue
        g0, g1 = grp[0], grp[-1]
        total_sec = max(0.0, (g1["ts"] - g0["ts"]).total_seconds())
        d0, d1 = g0["dist"], g1["dist"]
        if d0 is not None and d1 is not None:
            lap_dist = d1 - d0
        elif lap["total_distance"] is not None:
            lap_dist = lap["total_distance"] / 100.0
        else:
            lap_dist = 0.0
        cal = lap["calories"] or 0
        hrs = [r["hr"] for r in grp if r["hr"] is not None]
        cads = [r["cad"] for r in grp if r["cad"] is not None]
        avg_hr = round(sum(hrs) / len(hrs)) if hrs else (lap["avg_hr"] or 0)
        max_hr = max(hrs) if hrs else (lap["max_hr"] or 0)
        avg_cad = round(sum(cads) / len(cads)) if cads else (lap["avg_cad"] or 0)

        le = ET.SubElement(act, f"{{{NS_TCD}}}Lap")
        le.set("StartTime", iso(g0["ts"]))
        ET.SubElement(le, f"{{{NS_TCD}}}TotalTimeSeconds").text = f"{total_sec:.1f}"
        ET.SubElement(le, f"{{{NS_TCD}}}DistanceMeters").text = f"{lap_dist:.2f}"
        ET.SubElement(le, f"{{{NS_TCD}}}MaximumSpeed").text = "0.0"
        ET.SubElement(le, f"{{{NS_TCD}}}Calories").text = str(int(cal))
        ET.SubElement(le, f"{{{NS_TCD}}}Intensity").text = "Active"
        ET.SubElement(le, f"{{{NS_TCD}}}TriggerMethod").text = "Distance"
        if avg_hr:
            ah = ET.SubElement(le, f"{{{NS_TCD}}}AverageHeartRateBpm")
            ET.SubElement(ah, f"{{{NS_TCD}}}Value").text = str(int(avg_hr))
        if max_hr:
            mh = ET.SubElement(le, f"{{{NS_TCD}}}MaximumHeartRateBpm")
            ET.SubElement(mh, f"{{{NS_TCD}}}Value").text = str(int(max_hr))
        if avg_cad:
            ET.SubElement(le, f"{{{NS_TCD}}}Cadence").text = str(int(avg_cad))

        trk = ET.SubElement(le, f"{{{NS_TCD}}}Track")
        for r in grp:
            tp = ET.SubElement(trk, f"{{{NS_TCD}}}Trackpoint")
            ET.SubElement(tp, f"{{{NS_TCD}}}Time").text = iso(r["ts"])
            if r["lat"] is not None and r["lon"] is not None:
                pos = ET.SubElement(tp, f"{{{NS_TCD}}}Position")
                ET.SubElement(pos, f"{{{NS_TCD}}}LatitudeDegrees").text = f"{r['lat']:.9f}"
                ET.SubElement(pos, f"{{{NS_TCD}}}LongitudeDegrees").text = f"{r['lon']:.9f}"
            if r["alt"] is not None:
                ET.SubElement(tp, f"{{{NS_TCD}}}AltitudeMeters").text = f"{r['alt']:.2f}"
            if r["dist"] is not None:
                ET.SubElement(tp, f"{{{NS_TCD}}}DistanceMeters").text = f"{r['dist']:.2f}"
            if r["hr"] is not None:
                hrb = ET.SubElement(tp, f"{{{NS_TCD}}}HeartRateBpm")
                ET.SubElement(hrb, f"{{{NS_TCD}}}Value").text = str(int(r["hr"]))
            if r["cad"] is not None:
                ET.SubElement(tp, f"{{{NS_TCD}}}Cadence").text = str(int(r["cad"]))

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"WROTE {args.output} ({os.path.getsize(args.output)} bytes)")
    print(f"  sport={sport} laps={len(laps_sorted)} trackpoints={len(records)}")
    print(f"  device={dev_name} serial={fid.get('serial_number')}")


if __name__ == "__main__":
    main()
