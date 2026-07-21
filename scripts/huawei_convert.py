#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   华为手表 -> 高驰/佳明 运动数据一键转换工具         ║
║   v3.0 — 统一版（默认 FIT，可选 GPX/TCX）           ║
╚══════════════════════════════════════════════════════╝

基于原 huawei_to_coros.py（已从 GitHub 删除）重构。
输出格式：
  - FIT（默认）: 通过 fit_encode.mjs（Node.js @garmin/fitsdk）编码
  - GPX: 原生生成，适合导入高驰
  - TCX: 原生生成，适合导入佳明

从 FIT 转其他格式请用 fit_to_gpx_tcx.py。

用法：
  python scripts/huawei_convert.py <华为导出.json>                   # 默认 FIT
  python scripts/huawei_convert.py <华为导出.json> --format gpx      # GPX
  python scripts/huawei_convert.py <华为导出.json> --format tcx      # TCX
  python scripts/huawei_convert.py <华为导出.json> --format all      # 全部

依赖：Python 3.8+，FIT 模式需 Node.js + @garmin/fitsdk 在 PATH 或同目录下
"""

import json
import math
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from xml.dom import minidom
import statistics

# ============================================================
# 运动类型映射表
# ============================================================
SPORT_TYPE_NAMES = {
    1: 'Walking',
    2: 'Running',
    3: 'Cycling',
    4: 'Running',        # 户外跑（157条，含半马）
    5: 'Walking',         # 户外步行（417条）
    6: 'IndoorCycling',
    7: 'Swimming',
    # 实测中发现的华为其他编号
    101: 'Running',       # 跑步机/计划跑步（2条，7-8km，有步频无GPS）
    106: 'Other',         # 室内有氧/心率（5条，0距离无数据）
    117: 'Other',         # 纯心率监测（275条，睡前/静息，无GPS）
    281: 'Running',       # 室内运动（3条，0.2-1.2km，有步频）
}

# 华为手表已知的 sportType 编号（仅供查阅，实际推断不依赖此表）
#   1: Walking       慢走（很少见）
#   2: Running       室内跑步（极少见）
#   3: Cycling       户外骑行（110条）
#   4: Running       户外跑步（157条）⚠️ 最常见的跑步编号
#   5: Walking       户外步行（417条）⚠️ 最常见的步行编号
#   6: IndoorCycling 室内骑行
#   7: Swimming      游泳
#   101: 计划跑步/跑步机（2条）
#   106: 室内有氧（5条，0距离）
#   117: 心率监测（275条，无GPS）
#   281: 室内运动（3条，0.2-1.2km）

# 最小判断距离，小于此值不进行配速判断（米）
MIN_DISTANCE_FOR_PACE_CHECK = 500


# ============================================================
# JSON 解析
# ============================================================

def fix_parttime_map(obj_str):
    """修复JSON中 partTimeMap 的数字键问题"""
    pattern = re.compile(r'("partTimeMap":\s*\{)([^}]+)(\})')
    def fix_keys(m):
        prefix = m.group(1)
        body = m.group(2)
        suffix = m.group(3)
        fixed = re.sub(r'(\d+\.?\d*)\s*:', r'"\1":', body)
        return prefix + fixed + suffix
    return pattern.sub(fix_keys, obj_str)


def extract_all_objects(json_content):
    """从JSON数组中提取所有顶层对象"""
    brace_depth = 0
    in_str = False
    escaped = False
    obj_start = -1
    objects = []

    for idx, ch in enumerate(json_content):
        if escaped:
            escaped = False
            continue
        if ch == '\\' and in_str:
            escaped = True
            continue
        if ch == '"' and not escaped:
            in_str = not in_str
            continue
        if not in_str:
            if ch == '{':
                brace_depth += 1
                if brace_depth == 1:
                    obj_start = idx
            elif ch == '}':
                brace_depth -= 1
                if brace_depth == 0 and obj_start >= 0:
                    objects.append(json_content[obj_start:idx + 1])

    return objects


def parse_attribute(attr_str):
    """
    解析华为手表的attribute字段
    返回：(gps_points列表, hr_points列表, cadence_points列表)

    华为数据格式：
      GPS: tp=lbs;k=N;lat=...;lon=...;alt=...;t=timestamp_ms;
      HR:  tp=h-r;k=timestamp_ms;v=HR;
      步频: tp=rt-cadence;k=timestamp_ms;v=步频;
    """
    if not attr_str or not isinstance(attr_str, str):
        return [], [], [], []

    lines = attr_str.split('\n')
    gps_points = []
    hr_points = []
    cadence_points = []
    alti_points = []  # 气压计海拔数据

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if line.startswith('HW_EXT_TRACK_DETAIL@'):
            line = line[len('HW_EXT_TRACK_DETAIL@'):]

        # 提取字段
        fields = line.split(';')
        pt = {}
        for f in fields:
            if '=' in f:
                k, v = f.split('=', 1)
                pt[k.strip()] = v.strip()
        
        tp = pt.get('tp', '')

        # GPS 轨迹点（过滤华为手表经常在末尾写入的 lat=90 lon=-80 无效点）
        if 'lat' in pt and 'lon' in pt:
            try:
                lat_f = float(pt['lat'])
                lon_f = float(pt['lon'])
                # 过滤：北极/南极/原点
                if abs(lat_f) > 85 or abs(lon_f) > 180 or (abs(lat_f) < 0.001 and abs(lon_f) < 0.001):
                    continue
                gps_points.append({
                    'lat': lat_f,
                    'lon': lon_f,
                    'alt': float(pt.get('alt', 0)),
                    'time': int(pt['t']) if 't' in pt else 0,
                })
            except (ValueError, KeyError):
                pass

        # 心率 (h-r)
        elif tp == 'h-r' and 'v' in pt and 'k' in pt:
            try:
                hr_val = int(pt['v'])
                if hr_val > 0:
                    hr_points.append({
                        'hr': hr_val,
                        'time': int(pt['k']),
                    })
            except (ValueError, KeyError):
                pass

        # 步频/节奏 (s-r: 华为跑步步频，v=步频值)
        elif tp == 's-r' and 'v' in pt and 'k' in pt:
            try:
                cad_val = int(pt['v'])
                if cad_val > 0:
                    cadence_points.append({
                        'cadence': cad_val,
                        'time': int(pt['k']),
                    })
            except (ValueError, KeyError):
                pass

        # 海拔 (alti: 气压计海拔，v=海拔米数)
        elif tp == 'alti' and 'v' in pt and 'k' in pt:
            try:
                alti_points.append({
                    'alt': float(pt['v']),
                    'time': int(pt['k']),
                })
            except (ValueError, KeyError):
                pass

    return gps_points, hr_points, cadence_points, alti_points


def calibrate_altitude(alti_points):
    """
    海拔校准：气压计海拔数据整体偏移修正
    华为手表气压计可能存在整体偏移（常见约 -30m）。
    取所有 alti 点海拔的中位数进行修正。
    """
    if len(alti_points) < 10:
        return alti_points, 0

    alts = [p['alt'] for p in alti_points]
    if len(alts) < 10:
        return alti_points, 0

    median_alt = statistics.median(alts)
    correction = 0
    if median_alt < -5:
        correction = -median_alt + 10
        print(f"    [海拔] 检测到整体偏移（中位数 {median_alt:.1f}m），修正 +{correction:.0f}m")
        for p in alti_points:
            p['alt'] += correction

    return alti_points, correction



def get_sport_name(sport_type):
    """根据 sportType 返回标准运动名称，未识别的默认 Running"""
    name = SPORT_TYPE_NAMES.get(sport_type)
    if name:
        return name
    # fallback：如果是走路配速但未匹配，返回 Running
    return 'Running'


# ============================================================
# GPX 生成
# ============================================================

def build_gpx(gps_points, hr_points, cadence_points, alti_points, sport_type, start_time_ms, distance_m):
    """生成GPX XML文档"""
    gpx = ET.Element('gpx', {
        'version': '1.1',
        'creator': 'HuaweiToCOROS-Converter-v2',
        'xmlns': 'http://www.topografix.com/GPX/1/1',
        'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xmlns:gpxtpx': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1',
        'xsi:schemaLocation': 'http://www.topografix.com/GPX/1/1 '
                              'http://www.topografix.com/GPX/1/1/gpx.xsd '
                              'http://www.garmin.com/xmlschemas/TrackPointExtension/v1 '
                              'http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd',
    })

    meta_time = datetime.fromtimestamp(start_time_ms / 1000,
                                       tz=timezone(timedelta(hours=8)))
    ET.SubElement(ET.SubElement(gpx, 'metadata'), 'time').text = meta_time.isoformat()

    trk = ET.SubElement(gpx, 'trk')
    ET.SubElement(trk, 'name').text = get_sport_name(sport_type)
    seg = ET.SubElement(trk, 'trkseg')

    gps_sorted = sorted(gps_points, key=lambda p: p['time'])
    hr_sorted = sorted(hr_points, key=lambda p: p['time'])
    cad_sorted = sorted(cadence_points, key=lambda p: p['time'])
    alti_sorted = sorted(alti_points, key=lambda p: p['time'])

    for gp in gps_sorted:
        tp = ET.SubElement(seg, 'trkpt', {
            'lat': f"{gp['lat']:.7f}",
            'lon': f"{gp['lon']:.7f}",
        })

        # 海拔：从 alti 数据按时间匹配（优先用气压计海拔）
        alt_val = None
        for ap in alti_sorted:
            if abs(ap['time'] - gp['time']) <= 3000:
                alt_val = ap['alt']
                break
        if alt_val is not None and alt_val != 0:
            ET.SubElement(tp, 'ele').text = f"{alt_val:.1f}"

        tp_time = datetime.fromtimestamp(gp['time'] / 1000,
                                         tz=timezone(timedelta(hours=8)))
        ET.SubElement(tp, 'time').text = tp_time.isoformat()

        # 扩展数据（心率和步频）
        ext = None
        # HR
        for hp in hr_sorted:
            if abs(hp['time'] - gp['time']) <= 5000:
                if ext is None:
                    ext = ET.SubElement(tp, 'extensions')
                    tpx = ET.SubElement(ext, 'gpxtpx:TrackPointExtension')
                ET.SubElement(tpx, 'gpxtpx:hr').text = str(hp['hr'])
                break

        # Cadence
        for cp in cad_sorted:
            if abs(cp['time'] - gp['time']) <= 5000:
                if ext is None:
                    ext = ET.SubElement(tp, 'extensions')
                    tpx = ET.SubElement(ext, 'gpxtpx:TrackPointExtension')
                ET.SubElement(tpx, 'gpxtpx:cad').text = str(cp['cadence'])
                break

    return gpx


# ============================================================
# TCX 生成
# ============================================================

def build_tcx(hr_points, gps_points, cadence_points, alti_points, sport_type,
              start_time_ms, distance_m, duration_ms, huawei_calories=None):
    """生成TCX XML文档（含心率和GPS，修复海拔+卡路里）"""
    tcx = ET.Element('TrainingCenterDatabase', {
        'xmlns': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2',
        'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xmlns:ns3': 'http://www.garmin.com/xmlschemas/ActivityExtension/v2',
        'xsi:schemaLocation': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                              'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd',
    })

    activities = ET.SubElement(tcx, 'Activities')
    activity = ET.SubElement(activities, 'Activity', {
        'Sport': get_sport_name(sport_type)
    })

    start_dt = datetime.fromtimestamp(start_time_ms / 1000,
                                      tz=timezone(timedelta(hours=8)))
    ET.SubElement(activity, 'Id').text = start_dt.isoformat()

    # Lap
    lap = ET.SubElement(activity, 'Lap', {'StartTime': start_dt.isoformat()})
    duration_s = max(duration_ms, 1) / 1000
    ET.SubElement(lap, 'TotalTimeSeconds').text = f"{duration_s:.0f}"
    ET.SubElement(lap, 'DistanceMeters').text = str(int(distance_m)) if distance_m else "0"

    # — 卡路里估算（优先用华为原始数据） —
    calories = estimate_calories(duration_s, distance_m, hr_points, huawei_calories)
    if calories:
        ET.SubElement(lap, 'Calories').text = str(calories)

    # 心率统计
    valid_hrs = [h['hr'] for h in hr_points if h['hr'] > 0]
    if valid_hrs:
        max_hr_bpm = ET.SubElement(lap, 'MaximumHeartRateBpm')
        ET.SubElement(max_hr_bpm, 'Value').text = str(max(valid_hrs))
        avg_hr = int(sum(valid_hrs) / len(valid_hrs))
        avg_hr_bpm = ET.SubElement(lap, 'AverageHeartRateBpm')
        ET.SubElement(avg_hr_bpm, 'Value').text = str(avg_hr)

    ET.SubElement(lap, 'Intensity').text = 'Active'
    ET.SubElement(lap, 'TriggerMethod').text = 'Manual'

    # Track
    track = ET.SubElement(lap, 'Track')

    if len(gps_points) >= 2:
        gps_sorted = sorted(gps_points, key=lambda p: p['time'])
        hr_sorted = sorted(hr_points, key=lambda p: p['time'])
        cad_sorted = sorted(cadence_points, key=lambda p: p['time'])
        alti_sorted = sorted(alti_points, key=lambda p: p['time'])

        for gp in gps_sorted:
            tp = ET.SubElement(track, 'Trackpoint')
            tp_time = datetime.fromtimestamp(gp['time'] / 1000,
                                             tz=timezone(timedelta(hours=8)))
            ET.SubElement(tp, 'Time').text = tp_time.isoformat()

            pos = ET.SubElement(tp, 'Position')
            ET.SubElement(pos, 'LatitudeDegrees').text = f"{gp['lat']:.7f}"
            ET.SubElement(pos, 'LongitudeDegrees').text = f"{gp['lon']:.7f}"

            # 海拔：从 alti 数据按时间匹配（华为气压计海拔在独立数据中）
            alt_val = None
            for ap in alti_sorted:
                if abs(ap['time'] - gp['time']) <= 3000:
                    alt_val = ap['alt']
                    break
            if alt_val is not None and alt_val != 0:
                ET.SubElement(tp, 'AltitudeMeters').text = f"{alt_val:.1f}"

            # 心率
            for hp in hr_sorted:
                if abs(hp['time'] - gp['time']) <= 5000:
                    hr_bpm = ET.SubElement(tp, 'HeartRateBpm')
                    ET.SubElement(hr_bpm, 'Value').text = str(hp['hr'])
                    break

            # 扩展：Speed + Cadence
            ext = None
            # Cadence
            for cp in cad_sorted:
                if abs(cp['time'] - gp['time']) <= 5000:
                    if ext is None:
                        ext = ET.SubElement(tp, 'Extensions')
                        tpx = ET.SubElement(ext, 'TPX',
                            {'xmlns': 'http://www.garmin.com/xmlschemas/ActivityExtension/v2'})
                    ET.SubElement(tpx, 'RunCadence').text = str(cp['cadence'])
                    break
    else:
        # 无 GPS：按心率时间点生成
        for hp in sorted(hr_points, key=lambda p: p['time']):
            tp = ET.SubElement(track, 'Trackpoint')
            tp_time = datetime.fromtimestamp(hp['time'] / 1000,
                                             tz=timezone(timedelta(hours=8)))
            ET.SubElement(tp, 'Time').text = tp_time.isoformat()
            hr_bpm = ET.SubElement(tp, 'HeartRateBpm')
            ET.SubElement(hr_bpm, 'Value').text = str(hp['hr'])

    return tcx


def estimate_calories(duration_s, distance_m, hr_points, huawei_calories=None):
    """
    估算卡路里消耗
    优先级：华为原始数据 > 心率估算 > 距离估算
    """
    # 华为原始卡路里（单位小卡 cal，除以 1000 得 kcal）
    if huawei_calories and huawei_calories > 0:
        return int(huawei_calories / 1000)
    
    if distance_m <= 0:
        return None

    weight_kg = 74
    dist_km = distance_m / 1000

    if hr_points:
        valid_hrs = [h['hr'] for h in hr_points if h['hr'] > 0]
        if len(valid_hrs) > 10:
            avg_hr = int(sum(valid_hrs) / len(valid_hrs))
            mets = 8 + (avg_hr - 100) / 30
            hours = duration_s / 3600
            return int(mets * weight_kg * hours)

    return int(weight_kg * dist_km * 1.036)


# ============================================================
# 工具函数
# ============================================================

def format_timestamp(ms):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y%m%d_%H%M%S')


def format_datetime(ms):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def pretty_xml(element):
    """美化 XML 输出（单行压缩模式，节省空间）"""
    rough = ET.tostring(element, encoding='unicode')
    # 如果文件较大（>1MB）不缩进，减少体积
    if len(rough) > 1_000_000:
        return rough.encode('utf-8')
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding='utf-8')


# ============================================================
# GCJ02 -> WGS84 坐标系转换
# ============================================================

GCJ_A = 6378245.0
GCJ_EE = 0.00669342162296594323


def _out_of_china(lat, lon):
    return not (73.66 < lon < 135.05 and 3.86 < lat < 53.55)


def _transform_lat(x, y):
    ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * abs(x) ** 0.5
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(y * math.pi) + 40.0 * math.sin(y / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(y / 12.0 * math.pi) + 320.0 * math.sin(y * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lon(x, y):
    ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * abs(x) ** 0.5
    ret += (20.0 * math.sin(6.0 * x * math.pi) + 20.0 * math.sin(2.0 * x * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(x * math.pi) + 40.0 * math.sin(x / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(x / 12.0 * math.pi) + 300.0 * math.sin(x / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def gcj02_to_wgs84(lat, lon):
    """GCJ02 -> WGS84 反算转换"""
    if _out_of_china(lat, lon):
        return lat, lon
    dlat = _transform_lat(lon - 105.0, lat - 35.0)
    dlon = _transform_lon(lon - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - GCJ_EE * magic * magic
    sqrt_magic = math.sqrt(magic)
    mg_lat = (dlat * 180.0) / ((GCJ_A * (1 - GCJ_EE)) / (magic * sqrt_magic) * math.pi)
    mg_lon = (dlon * 180.0) / (GCJ_A / sqrt_magic * math.cos(radlat) * math.pi)
    return lat - mg_lat, lon - mg_lon


# ============================================================
# FIT 导出 — 生成中间 JSON → 调用 fit_encode.mjs
# ============================================================

def _find_fit_encoder():
    """查找 fit_encode.mjs 路径"""
    candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fit_encode.mjs'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fit_encode.mjs'),
        # 开发目录中的 fit_encode.mjs（有完整的 package.json + node_modules）
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', '..', '运动数据编辑工具', 'fit_encode.mjs'),
        'fit_encode.mjs',
    ]
    for p in candidates:
        resolved = os.path.abspath(p)
        if os.path.isfile(resolved):
            return resolved
    return None


def _find_node_dir(encoder_path):
    """返回 fit_encode.mjs 所在的目录（即 package.json 所在目录）"""
    return os.path.dirname(encoder_path)


def export_fit(single_obj, gps_points, hr_points, cadence_points, alti_points,
               st, start_time, dist_m, dur_ms, output_path, huawei_calories=None):
    """将解析后的华为数据导出为 FIT 文件.
    内部构造中间 JSON，subprocess 调用 fit_encode.mjs。
    """
    if len(gps_points) < 2:
        raise ValueError("FIT 导出需要至少 2 个 GPS 点")

    # 海拔校准
    alti_corrected, _ = calibrate_altitude(alti_points)

    # 按时间排序
    gps_sorted = sorted(gps_points, key=lambda p: p['time'])
    hr_sorted = sorted(hr_points, key=lambda p: p['time'])
    cad_sorted = sorted(cadence_points, key=lambda p: p['time'])
    alti_sorted = sorted(alti_corrected, key=lambda p: p['time'])

    st_name = get_sport_name(st)
    fit_sport = st_name.lower()

    # 构造 points
    points = []
    total_time_ms = dur_ms or (gps_sorted[-1]['time'] - gps_sorted[0]['time'])
    total_dist = dist_m or 0

    for i, gp in enumerate(gps_sorted):
        # GCJ02 -> WGS84
        lat, lon = gcj02_to_wgs84(gp['lat'], gp['lon'])

        # 匹配心率
        hr = None
        for hp in hr_sorted:
            if abs(hp['time'] - gp['time']) <= 5000:
                hr = hp['hr']
                break

        # 匹配步频
        cad = None
        for cp in cad_sorted:
            if abs(cp['time'] - gp['time']) <= 5000:
                cad = cp['cadence']
                break

        # 匹配海拔
        alt = None
        for ap in alti_sorted:
            if abs(ap['time'] - gp['time']) <= 3000:
                alt = ap['alt']
                break

        # 距离（按时间比例分配）
        frac = (gp['time'] - gps_sorted[0]['time']) / max(1, gps_sorted[-1]['time'] - gps_sorted[0]['time'])
        distance = total_dist * frac

        # 速度
        speed = None
        if i > 0:
            dt = (gp['time'] - gps_sorted[i - 1]['time']) / 1000
            dd = distance - (gps_sorted[i - 1].get('_dist', 0))
            if dt > 0 and dd >= 0:
                speed = dd / dt
        gps_sorted[i]['_dist'] = distance

        pt = {
            'lat': lat,
            'lon': lon,
            'ts': gp['time'],
            'distance': round(distance, 1),
        }
        if hr:
            pt['hr'] = hr
        if cad:
            pt['cadence'] = cad
        if alt is not None and alt != 0:
            pt['altitude'] = round(alt, 1)
        if speed is not None:
            pt['speed'] = round(speed, 4)
        points.append(pt)

    # 计圈：每 1km
    if total_dist >= 1000:
        n_laps = max(1, math.ceil(total_dist / 1000))
        laps = []
        for li in range(n_laps):
            start_i = li * len(points) // n_laps
            end_i = (li + 1) * len(points) // n_laps - 1
            if end_i >= len(points):
                end_i = len(points) - 1
            lap_pts = points[start_i:end_i + 1]
            if not lap_pts:
                continue
            lap_dist = lap_pts[-1]['distance'] - lap_pts[0]['distance']
            lap_time = (lap_pts[-1]['ts'] - lap_pts[0]['ts']) / 1000
            lap_hrs = [p.get('hr') for p in lap_pts if p.get('hr')]
            lap_cads = [p.get('cadence') for p in lap_pts if p.get('cadence')]
            lap_speeds = [p.get('speed') for p in lap_pts if p.get('speed')]
            laps.append({
                'start_idx': start_i,
                'end_idx': end_i,
                'totalDistance': round(lap_dist, 1),
                'totalElapsedTime': round(lap_time, 1),
                'avgHeartRate': round(sum(lap_hrs) / len(lap_hrs)) if lap_hrs else None,
                'maxHeartRate': max(lap_hrs) if lap_hrs else None,
                'avgCadence': round(sum(lap_cads) / len(lap_cads)) if lap_cads else None,
                'avgSpeed': round(sum(lap_speeds) / len(lap_speeds), 4) if lap_speeds else None,
                'maxSpeed': round(max(lap_speeds), 4) if lap_speeds else None,
                'totalCalories': round((huawei_calories or total_dist * 0.074) * lap_dist / total_dist) if total_dist > 0 else 0,
                'startLat': points[start_i]['lat'],
                'startLon': points[start_i]['lon'],
                'endLat': points[end_i]['lat'],
                'endLon': points[end_i]['lon'],
            })
    else:
        laps = []

    # Session
    avg_hr = round(sum(p.get('hr', 0) for p in points if p.get('hr')) / max(1, sum(1 for p in points if p.get('hr')))) if any(p.get('hr') for p in points) else None
    max_hr = max(p['hr'] for p in points if p.get('hr')) if any(p.get('hr') for p in points) else None
    avg_cad = round(sum(p.get('cadence', 0) for p in points if p.get('cadence')) / max(1, sum(1 for p in points if p.get('cadence')))) if any(p.get('cadence') for p in points) else None
    max_cad = max(p['cadence'] for p in points if p.get('cadence')) if any(p.get('cadence') for p in points) else None
    avg_spd = total_dist / max(1, total_time_ms / 1000) if total_time_ms > 0 else 0
    max_spd = max(p.get('speed', 0) for p in points if p.get('speed')) if any(p.get('speed') for p in points) else None

    fit_data = {
        'points': points,
        'laps': laps,
        'session': {
            'startTime': start_time,
            'totalTime': total_time_ms,
            'totalDistance': total_dist,
            'totalCalories': round((huawei_calories or 0) / 1000) if huawei_calories else round(total_dist * 0.074),
            'avgHeartRate': avg_hr,
            'maxHeartRate': max_hr,
            'avgCadence': avg_cad,
            'maxCadence': max_cad,
            'avgSpeed': round(avg_spd, 4),
            'maxSpeed': round(max_spd, 4) if max_spd else None,
            'sport': fit_sport if fit_sport in ('running', 'cycling', 'walking', 'swimming') else 'other',
            'subSport': 'generic',
        },
        'manufacturer': 0xFF,  # development（华为未注册 ANT+ manufacturer ID）
        'product': 0,
    }

    # 找 fit_encode.mjs
    encoder_path = _find_fit_encoder()
    if not encoder_path:
        print("[错误] 找不到 fit_encode.mjs。脚本应与 fit_encode.mjs 在同一目录或父目录。")
        print(f"       查找路径: {os.path.dirname(os.path.abspath(__file__))}")
        sys.exit(1)

    # 在 encoder 所在目录下运行（找到 package.json + node_modules）
    node_cwd = _find_node_dir(encoder_path)

    # subprocess 调用（在 encoder 目录执行，保证 node 能找到 package.json）
    try:
        proc = subprocess.run(
            ['node', encoder_path],
            input=json.dumps(fit_data).encode('utf-8'),
            capture_output=True,
            text=False,
            timeout=120,
            cwd=node_cwd,
        )
    except FileNotFoundError:
        print("[错误] 找不到 node 命令。请安装 Node.js 和 @garmin/fitsdk。")
        sys.exit(1)

    if proc.returncode != 0:
        stderr = proc.stderr.decode('utf-8', errors='replace')
        print(f"[错误] FIT 编码失败:")
        print(f"       {stderr[:500]}")
        sys.exit(1)

    with open(output_path, 'wb') as f:
        f.write(proc.stdout)

    # 验证
    file_size_kb = len(proc.stdout) / 1024
    print(f"    [FIT] {os.path.basename(output_path)} ({file_size_kb:.0f}KB, {len(points)} 点, {len(laps)} 圈)")

    return True


# ============================================================


# ============================================================
# 主流程
# ============================================================

def process_file(input_path, output_format='fit'):
    """处理单个华为JSON文件
    Args:
        input_path: 华为导出JSON路径
        output_format: 'fit'（默认）, 'gpx', 'tcx', 'all'
    """
    if not os.path.isfile(input_path):
        print(f"\n[错误] 找不到文件: {input_path}")
        return False

    file_size = os.path.getsize(input_path)
    print(f"\n[文件] 输入文件: {input_path}")
    print(f"[大小] {file_size / 1024 / 1024:.1f} MB")

    if file_size == 0:
        print("[错误] 文件为空")
        return False

    base_dir = os.path.dirname(os.path.abspath(input_path))
    output_dir = os.path.join(base_dir, "converted_coros_v2")
    os.makedirs(output_dir, exist_ok=True)
    print(f"[目录] 输出目录: {output_dir}")

    print("\n[进度] 正在读取JSON文件...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print(f"[错误] 读取文件失败: {e}")
        return False

    # 先尝试直接 JSON 解析（小文件、单条记录等）
    data = None
    for attempt in [content, fix_parttime_map(content)]:
        try:
            data = json.loads(attempt)
            break
        except json.JSONDecodeError:
            continue

    if data is not None:
        if isinstance(data, list):
            obj_strings = [json.dumps(obj, ensure_ascii=False) for obj in data]
        else:
            obj_strings = [json.dumps(data, ensure_ascii=False)]
        total = len(obj_strings)
        print(f"[统计] 共发现 {total} 条运动记录")
    else:
        # 大文件：partTimeMap 格式复杂，走逐对象字符串提取
        print("[进度] 大文件模式，逐条提取...")
        obj_strings = extract_all_objects(content)
        total = len(obj_strings)
        print(f"[统计] 共发现 {total} 条运动记录")

    if total == 0:
        print("[错误] 未找到任何运动数据")
        return False

    print("\n[进度] 正在转换...\n")

    stats = {
        'fit': 0, 'gpx': 0, 'tcx': 0, 'skipped': 0,
        'corrected': 0,
        'alt_calibrated': 0,
        'sport_types': {},
        'total_distance_km': 0,
        'total_duration_h': 0,
        'corrected_records': [],
    }

    for i, raw in enumerate(obj_strings):
        # 解析JSON
        obj = None
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            fixed = fix_parttime_map(raw)
            try:
                obj = json.loads(fixed)
            except json.JSONDecodeError:
                pass

        if obj is None:
            stats['skipped'] += 1
            _print_progress(i + 1, total, stats)
            continue

        st = obj.get('sportType', 0)
        start_time = obj.get('startTime', 0)
        dist_m = obj.get('totalDistance', 0)
        dur_ms = obj.get('totalTime', 0)
        attr = obj.get('attribute', '')

        # 解析轨迹和心率（配速识别需要知道有无GPS）
        gps_points, hr_points, cadence_points, alti_points = parse_attribute(attr)

        ts_str = format_timestamp(start_time) if start_time else f"record{i}"

        # 运动类型推断规则（按优先级）：
        #   1. 有GPS + 有距离 + 配速 ≤ 10min/km → Running（有心率更好）
        #   2. 有GPS + 有距离 + 配速 > 10min/km → Walking
        #   3. 无GPS + 无距离 + 有心率 → Other（纯心率监测，睡前/凌晨）
        #   4. 其他情况 → 保留华为原始类型
        has_gps = len(gps_points) >= 2
        has_hr = len(hr_points) > 0
        has_real_dist = dist_m >= MIN_DISTANCE_FOR_PACE_CHECK

        corrected_st = st
        has_cadence = len(cadence_points) > 10  # 有步频数据

        if has_gps and has_real_dist and dur_ms > 0:
            pace = dur_ms / 60 / dist_m
            # Step 1: 骑行/游泳不管配速都保留原始类型（无步频是正常特征）
            if st in (3, 6, 7):
                corrected_st = st
            # Step 2: 有步频数据 → 跑步
            elif has_cadence and pace <= 10.0:
                corrected_st = 4  # Running
            # Step 3: 无步频+配速快 → 可能是骑行被华为标错为其他，保留原始
            elif not has_cadence and pace <= 10.0:
                corrected_st = st
            # Step 4: 配速慢 → 步行
            else:
                corrected_st = 5  # Walking
        elif not has_gps and not has_real_dist and has_hr:
            corrected_st = 117  # Other (纯心率)

        if corrected_st != st:
            stats['corrected'] += 1
            direction = {4: "→跑步", 5: "→走路", 117: "→心率监测(Other)"}.get(corrected_st, f"→{corrected_st}")
            pace_str = f"{dur_ms / 60 / dist_m:.2f}" if dist_m > 0 else "?"
            info = (f"  [{i+1}/{total}] {format_datetime(start_time)} "
                    f"类型{st}{direction} (配速{pace_str}min/km, {dist_m/1000:.2f}km)")
            stats['corrected_records'].append(info)
            st = corrected_st

        st_name = get_sport_name(st)

        # 更新统计
        stats['sport_types'][st] = stats['sport_types'].get(st, 0) + 1
        stats['total_distance_km'] += dist_m / 1000
        stats['total_duration_h'] += dur_ms / 1000 / 3600

        # 海拔校准（从 alti_points 读取气压计海拔）
        if len(alti_points) >= 2:
            alti_points, alt_correction = calibrate_altitude(alti_points)

        huawei_cal = obj.get('totalCalories')
        made = False

        # ===== 根据 format 输出 =====
        if output_format in ('fit', 'all') and len(gps_points) >= 2:
            try:
                fit_path = os.path.join(output_dir, f"{ts_str}_{st_name}_{int(dist_m)}m.fit")
                export_fit(obj, gps_points, hr_points, cadence_points, alti_points,
                          st, start_time, dist_m, dur_ms, fit_path, huawei_cal)
                stats['fit'] += 1
                made = True
            except Exception as e:
                print(f"\n  [警告] FIT生成失败: {e}")
                import traceback
                traceback.print_exc()

        if output_format in ('gpx', 'all') and len(gps_points) >= 2:
            try:
                gpx = build_gpx(gps_points, hr_points, cadence_points, alti_points, st, start_time, dist_m)
                gpx_filename = f"{ts_str}_{st_name}_{int(dist_m)}m.gpx"
                with open(os.path.join(output_dir, gpx_filename), 'wb') as f:
                    f.write(pretty_xml(gpx))
                stats['gpx'] += 1
                made = True
            except Exception as e:
                print(f"\n  [警告] GPX生成失败 ({gpx_filename}): {e}")

        if output_format in ('tcx', 'all') and (hr_points or len(gps_points) >= 2):
            try:
                tcx = build_tcx(hr_points, gps_points, cadence_points, alti_points, st, start_time, dist_m, dur_ms, huawei_cal)
                if len(gps_points) >= 2:
                    tcx_filename = f"{ts_str}_{st_name}_{int(dist_m)}m.tcx"
                else:
                    tcx_filename = f"{ts_str}_{st_name}_HRonly.tcx"
                with open(os.path.join(output_dir, tcx_filename), 'wb') as f:
                    f.write(pretty_xml(tcx))
                stats['tcx'] += 1
                made = True
            except Exception as e:
                print(f"\n  [警告] TCX生成失败 ({tcx_filename}): {e}")

        if not made:
            stats['skipped'] += 1

        if (i + 1) % 50 == 0 or i + 1 == total:
            _print_progress(i + 1, total, stats)

    _print_summary(total, stats, output_dir)
    return True


def _print_progress(processed, total, stats):
    bar_len = 30
    filled = int(bar_len * processed / total)
    bar = '#' * filled + '.' * (bar_len - filled)
    pct = processed / total * 100
    sys.stdout.write(f"\r  [{bar}] {processed}/{total} ({pct:.0f}%) "
                     f"FIT:{stats.get('fit',0)} GPX:{stats['gpx']} TCX:{stats['tcx']} 跳过:{stats['skipped']}")
    sys.stdout.flush()


def _print_summary(total, stats, output_dir):
    print("\n\n" + "=" * 60)
    print("  [完成] 转换完成！汇总报告")
    print("=" * 60)

    print(f"\n  [统计] 总记录数: {total}")
    if stats.get('fit'):
        print(f"  [FIT]  生成FIT: {stats['fit']} 个")
    if stats['gpx']:
        print(f"  [GPX]  生成GPX: {stats['gpx']} 个")
    if stats['tcx']:
        print(f"  [TCX]  生成TCX: {stats['tcx']} 个")
    print(f"  [跳过] 跳过: {stats['skipped']} 条")

    if stats['corrected'] > 0:
        print(f"  [修正] 配速修正(走路->跑步): {stats['corrected']} 条")
        for info in stats['corrected_records']:
            print(f"    {info}")

    print(f"\n  [距离] 总距离: {stats['total_distance_km']:.1f} km")
    print(f"  [时长] 总时长: {stats['total_duration_h']:.1f} 小时")

    print(f"\n  [类型] 运动类型分布:")
    for st, cnt in sorted(stats['sport_types'].items(), key=lambda x: -x[1]):
        name = get_sport_name(st)
        print(f"    {name:<15} {cnt:4d} 条")

    print(f"\n  [目录] 输出目录: {output_dir}")
    n_files = stats.get('fit', 0) + stats['gpx'] + stats['tcx']
    print(f"  [文件] 共 {n_files} 个文件")

    print("\n" + "=" * 60)
    print("  导入指引")
    print("=" * 60)
    print("""
  [高驰] 用 GPX 文件导入 COROS APP
         首页右上角 [+] -> 导入运动数据 -> 选择 GPX 文件

  [佳明] 用 TCX 文件导入 Garmin Connect
         网页版: 左上角菜单 -> 导入数据 -> 选择 TCX 文件

  [修复说明] v2.0 相比原脚本的改进:
    1. 海拔校准：自动检测偏移并修正（修复全负数问题）
    2. 卡路里：估算写入（基于心率和距离）
    3. 步频：从华为数据提取并写入
    4. Sport 类型：未识别时默认 "Running"
    5. Speed 扩展字段：写入 TCX 扩展
    """)


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="华为手表 -> 高驰/佳明 运动数据转换工具 (v3.0)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例:\n"
            "  %(prog)s huawei_export.json                    # 默认输出 FIT\n"
            "  %(prog)s huawei_export.json --format gpx       # 输出 GPX\n"
            "  %(prog)s huawei_export.json --format all       # 三种格式都输出\n"
            "  %(prog)s huawei_export.json -o ./out/          # 指定输出目录\n"
        ),
    )
    parser.add_argument('input', nargs='?', help='华为手表导出JSON文件路径')
    parser.add_argument('--format', '-f', default='fit',
                        choices=['fit', 'gpx', 'tcx', 'all'],
                        help='输出格式 (默认: fit)')
    parser.add_argument('--output-dir', '-o', default=None,
                        help='输出目录 (默认: 输入文件目录下的 converted_coros_v2/)')

    args = parser.parse_args()

    print()
    print("╔═══════════════════════════════════════════════════╗")
    print("║   Huawei -> COROS/Garmin Converter v3.0          ║")
    print("╚═══════════════════════════════════════════════════╝")
    print()

    input_file = args.input

    if not input_file:
        print("请选择华为手表导出的JSON数据文件。")
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            input_file = filedialog.askopenfilename(
                title="选择华为手表导出的JSON数据文件",
                initialdir=os.getcwd(),
                filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
            )
            root.destroy()
        except ImportError:
            input_file = input("请输入JSON文件路径: ").strip().strip('"').strip("'")

    if not input_file:
        print("[错误] 未选择文件，退出")
        sys.exit(1)

    input_file = input_file.strip().strip('"').strip("'")
    print(f"  [文件] 输入文件: {input_file}")
    print(f"  [格式] 输出格式: {args.format}")
    print()

    success = process_file(input_file, args.format)

    if success:
        print("\n[完成] 转换完成！请按照上方指引导入运动APP。")
    else:
        print("\n[错误] 转换失败，请检查文件格式后重试。")

    if sys.platform == 'win32' and sys.stdin.isatty():
        try:
            input("\n按 Enter 键退出...")
        except EOFError:
            pass


if __name__ == '__main__':
    main()
