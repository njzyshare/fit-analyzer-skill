#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   华为手表 -> 高驰/佳明 运动数据一键转换工具         ║
║   v2.0 — 修复版                                     ║
╚══════════════════════════════════════════════════════╝

基于原 huawei_to_coros.py（已从 GitHub 删除）重构。
修复清单（详见 references/huawei_converter_analysis.md）：
  1. [修复] 海拔全负值 → 自动校准偏移 + 中位数修正
  2. [修复] 缺失卡路里 → Lap 中写入 Calories
  3. [修复] 缺失步频 → 从华为数据提取步频并写入
  4. [修复] Sport fallback → 未识别类型默认 Running
  5. [修复] 海拔过滤 → 华为 alt=0 表示无数据，负值表示有数据
  6. [新增] Speed 字段写入 TCX 扩展

使用方法：
  python scripts/huawei_convert.py <华为导出.json>

依赖：Python 3.8+，无需第三方库
"""

import json
import os
import re
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
# 主流程
# ============================================================

def process_file(input_path):
    """处理单个华为JSON文件"""
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
        'gpx': 0, 'tcx': 0, 'skipped': 0,
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

        made_gpx = made_tcx = False

        # GPX
        if len(gps_points) >= 2:
            try:
                gpx = build_gpx(gps_points, hr_points, cadence_points, alti_points, st, start_time, dist_m)
                gpx_filename = f"{ts_str}_{st_name}_{int(dist_m)}m.gpx"
                with open(os.path.join(output_dir, gpx_filename), 'wb') as f:
                    f.write(pretty_xml(gpx))
                stats['gpx'] += 1
                made_gpx = True
            except Exception as e:
                print(f"\n  [警告] GPX生成失败 ({gpx_filename}): {e}")

        # TCX
        if hr_points or len(gps_points) >= 2:
            try:
                huawei_cal = obj.get('totalCalories')
                tcx = build_tcx(hr_points, gps_points, cadence_points, alti_points, st, start_time, dist_m, dur_ms, huawei_cal)
                if made_gpx:
                    tcx_filename = f"{ts_str}_{st_name}_{int(dist_m)}m.tcx"
                else:
                    tcx_filename = f"{ts_str}_{st_name}_HRonly.tcx"
                with open(os.path.join(output_dir, tcx_filename), 'wb') as f:
                    f.write(pretty_xml(tcx))
                stats['tcx'] += 1
                made_tcx = True
            except Exception as e:
                print(f"\n  [警告] TCX生成失败 ({tcx_filename}): {e}")

        if not made_gpx and not made_tcx:
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
                     f"GPX:{stats['gpx']} TCX:{stats['tcx']} 跳过:{stats['skipped']}")
    sys.stdout.flush()


def _print_summary(total, stats, output_dir):
    print("\n\n" + "=" * 60)
    print("  [完成] 转换完成！汇总报告")
    print("=" * 60)

    print(f"\n  [统计] 总记录数: {total}")
    print(f"  [GPX]  生成GPX: {stats['gpx']} 个")
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
    print(f"  [文件] 共 {stats['gpx'] + stats['tcx']} 个文件")

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
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   华为手表 - 高驰/佳明 运动数据转换工具     ║")
    print("║   v2.0 — 修复版                             ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    input_file = None

    if len(sys.argv) >= 2:
        input_file = sys.argv[1]
    else:
        print("请选择华为手表导出的JSON数据文件。")
        print("  [提示] 你也可以直接把文件拖到这个脚本上运行\n")

        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk()
            root.withdraw()
            root.attributes('-topmost', True)
            input_file = filedialog.askopenfilename(
                title="选择华为手表导出的JSON数据文件",
                filetypes=[("JSON文件", "*.json"), ("所有文件", "*.*")]
            )
            root.destroy()
        except ImportError:
            input_file = input("请输入JSON文件路径: ").strip().strip('"').strip("'")

    if not input_file:
        print("[错误] 未选择文件，退出")
        sys.exit(1)

    input_file = input_file.strip().strip('"').strip("'")
    print(f"  [文件] 输入文件: {input_file}\n")

    success = process_file(input_file)

    if success:
        print("\n[完成] 转换完成！请按照上方指引导入运动APP。")
    else:
        print("\n[错误] 转换失败，请检查文件格式后重试。")

    if sys.platform == 'win32':
        input("\n按 Enter 键退出...")


if __name__ == '__main__':
    main()
