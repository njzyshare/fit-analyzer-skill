#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════╗
║   华为手表 -> 高驰/佳明 运动数据一键转换工具         ║
║   Huawei Watch to COROS/Garmin Data Converter       ║
╚══════════════════════════════════════════════════════╝

使用方法：
  [方式一] 拖放：直接把华为导出的JSON文件拖到这个脚本上
  [方式二] 命令行：python huawei_to_coros.py <文件路径.json>
  [方式三] 双击运行：会弹出文件选择窗口

依赖：Python 3.8+，无需安装任何第三方库（仅使用标准库）

功能：
  [OK] 自动解析华为手表的运动数据JSON
  [OK] 生成GPX文件（GPS轨迹+心率，两边都能用）
  [OK] 生成TCX文件（佳明原生格式，也能导入高驰）
  [OK] 配速智能识别：走路误标为跑步的自动修正（<8min/km）
  [OK] 输出汇总报告

输出说明：
  - 在JSON文件同目录下创建 converted_coros/ 文件夹
  - 每个运动记录同时输出 GPX + TCX 两个格式
  - GPX文件：GPS轨迹 + 心率，文件名：日期_运动类型_距离.gpx
  - TCX文件：佳明原生格式，含心率+GPS，文件名：日期_运动类型_距离.tcx

平台兼容性：
  高驰 COROS APP：
    GPX -> 直接导入为运动记录（推荐）
    TCX -> 也可以导入
  佳明 Garmin Connect：
    TCX -> 佳明原生格式，导入即为运动记录（推荐）
    GPX -> 导入为路线（非运动记录）

  建议：
  [高驰用户] 优先导入 GPX 文件
  [佳明用户] 优先导入 TCX 文件
  [两边都用] GPX和TCX都留着，各取所需

导入佳明步骤（人工操作）：
  网页版 Garmin Connect：
    1. 浏览器登录 connect.garmin.com
    2. 左上角菜单 -> 导入数据 -> 选择TCX文件
    3. 导入后可在"活动"中查看

  手机版 Garmin Connect：
    1. 手机打开 Garmin Connect APP
    2. 更多 -> 导入活动 -> 选择TCX文件
    3. 或通过浏览器上传更方便

导入高驰步骤（人工操作）：
  1. 手机打开 COROS APP
  2. 首页右上角 [+] -> 导入运动数据
  3. 选择输出的 GPX 文件（推荐）
  4. 一次可多选，建议分批导入

注意事项：
  [注意] 华为手表导出的JSON文件较大（通常100MB+），请耐心等待
  [注意] 转换过程中会实时显示进度
  [注意] 首次运行建议用短文件测试
"""

import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from xml.dom import minidom

# ============================================================
# 运动类型映射表
# 说明：华为手表的sportType编号可能因版本不同而不同
# 实测数据中：4=跑步, 5=走路, 3=骑行
# 其他未列出的类型会保留原始编号显示
# ============================================================
SPORT_TYPE_NAMES = {
    1: 'Walking',
    2: 'Running',
    3: 'Cycling',
    4: 'Running',       # 华为手表实测：sportType=4 是户外跑（有GPS轨迹）
    5: 'Walking',
    6: 'IndoorCycling',
    7: 'Swimming',
}

# 配速阈值：走路配速快于此值(分钟/公里)则判定为跑步
PACE_THRESHOLD_RUNNING = 8.0  # min/km

# 配速阈值：最小判断距离，小于此值不进行配速判断（米）
MIN_DISTANCE_FOR_PACE_CHECK = 500


# ============================================================
# 核心转换逻辑
# ============================================================

def fix_parttime_map(obj_str):
    """
    修复JSON中 "partTimeMap":{1.0:335.0,4.0:1384.0,...} 的数字键问题
    华为导出的JSON文件存在这个格式问题，标准JSON解析器无法解析
    """
    pattern = re.compile(r'("partTimeMap":\s*\{)([^}]+)(\})')
    def fix_keys(m):
        prefix = m.group(1)
        body = m.group(2)
        suffix = m.group(3)
        fixed = re.sub(r'(\d+\.?\d*)\s*:', r'"\1":', body)
        return prefix + fixed + suffix
    return pattern.sub(fix_keys, obj_str)


def extract_all_objects(json_content):
    """
    从JSON数组中提取所有顶层对象（字符串形式）
    不使用 json.loads 以避免文件中的格式问题
    使用大括号深度追踪逐层解析
    """
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
    返回：(gps_points列表, hr_points列表)

    GPS点格式: tp=lbs;k=N;lat=...;lon=...;alt=...;t=timestamp_ms;
    心率点格式: tp=h-r;k=timestamp_ms;v=HR;
    """
    if not attr_str or not isinstance(attr_str, str):
        return [], []

    lines = attr_str.split('\n')
    gps_points = []
    hr_points = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 去掉 HW_EXT_TRACK_DETAIL@ 前缀
        if line.startswith('HW_EXT_TRACK_DETAIL@'):
            line = line[len('HW_EXT_TRACK_DETAIL@'):]

        # GPS轨迹点
        if 'lat=' in line and 'lon=' in line:
            fields = line.split(';')
            pt = {}
            for f in fields:
                if '=' in f:
                    k, v = f.split('=', 1)
                    pt[k.strip()] = v.strip()
            if 'lat' in pt and 'lon' in pt:
                try:
                    gps_points.append({
                        'lat': float(pt['lat']),
                        'lon': float(pt['lon']),
                        'alt': float(pt.get('alt', 0)),
                        'time': int(pt['t']) if 't' in pt else 0,
                    })
                except (ValueError, KeyError):
                    pass

        # 心率数据点
        elif 'h-r' in line or ('tp=' in line and 'v=' in line):
            fields = line.split(';')
            pt = {}
            for f in fields:
                if '=' in f:
                    k, v = f.split('=', 1)
                    pt[k.strip()] = v.strip()
            if 'v' in pt and 'k' in pt:
                try:
                    hr_val = int(pt['v'])
                    if hr_val > 0:  # 忽略-1的无效值
                        hr_points.append({
                            'hr': hr_val,
                            'time': int(pt['k']),
                        })
                except (ValueError, KeyError):
                    pass

    return gps_points, hr_points


def detect_actual_sport(dist_m, dur_ms, original_st):
    """
    基于配速智能识别运动类型
    走路(sportType=5)但配速<8min/km -> 跑步
    """
    if original_st != 5 or dist_m < MIN_DISTANCE_FOR_PACE_CHECK:
        return original_st, None

    pace = dur_ms / 60 / dist_m  # min/km
    if pace < PACE_THRESHOLD_RUNNING:
        return 4, pace  # 4=Running

    return original_st, None


def build_gpx(gps_points, hr_points, sport_type, start_time_ms, distance_m):
    """生成GPX XML文档"""
    gpx = ET.Element('gpx', {
        'version': '1.1',
        'creator': 'HuaweiToCOROS-Converter',
        'xmlns': 'http://www.topografix.com/GPX/1/1',
        'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xmlns:gpxtpx': 'http://www.garmin.com/xmlschemas/TrackPointExtension/v1',
        'xsi:schemaLocation': 'http://www.topografix.com/GPX/1/1 '
                              'http://www.topografix.com/GPX/1/1/gpx.xsd '
                              'http://www.garmin.com/xmlschemas/TrackPointExtension/v1 '
                              'http://www.garmin.com/xmlschemas/TrackPointExtensionv1.xsd',
    })

    # 元数据
    meta_time = datetime.fromtimestamp(start_time_ms / 1000,
                                       tz=timezone(timedelta(hours=8)))
    ET.SubElement(ET.SubElement(gpx, 'metadata'), 'time').text = meta_time.isoformat()

    # 轨迹段
    trk = ET.SubElement(gpx, 'trk')
    ET.SubElement(trk, 'name').text = SPORT_TYPE_NAMES.get(sport_type, f'Sport{sport_type}')
    seg = ET.SubElement(trk, 'trkseg')

    gps_sorted = sorted(gps_points, key=lambda p: p['time'])
    hr_sorted = sorted(hr_points, key=lambda p: p['time'])

    for gp in gps_sorted:
        tp = ET.SubElement(seg, 'trkpt', {
            'lat': f"{gp['lat']:.7f}",
            'lon': f"{gp['lon']:.7f}",
        })

        if gp['alt'] > 0:
            ET.SubElement(tp, 'ele').text = f"{gp['alt']:.1f}"

        tp_time = datetime.fromtimestamp(gp['time'] / 1000,
                                         tz=timezone(timedelta(hours=8)))
        ET.SubElement(tp, 'time').text = tp_time.isoformat()

        # 嵌入心率数据（匹配5秒内的最近心率点）
        for hp in hr_sorted:
            if abs(hp['time'] - gp['time']) <= 5000:
                ext = ET.SubElement(tp, 'extensions')
                tpx = ET.SubElement(ext, 'gpxtpx:TrackPointExtension')
                ET.SubElement(tpx, 'gpxtpx:hr').text = str(hp['hr'])
                break

    return gpx


def build_tcx(hr_points, gps_points, sport_type, start_time_ms, distance_m, duration_ms):
    """生成TCX XML文档（含心率和GPS）"""
    tcx = ET.Element('TrainingCenterDatabase', {
        'xmlns': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2',
        'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
        'xsi:schemaLocation': 'http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2 '
                              'http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd',
    })

    activities = ET.SubElement(tcx, 'Activities')
    activity = ET.SubElement(activities, 'Activity', {
        'Sport': SPORT_TYPE_NAMES.get(sport_type, 'Other')
    })

    start_dt = datetime.fromtimestamp(start_time_ms / 1000,
                                      tz=timezone(timedelta(hours=8)))
    ET.SubElement(activity, 'Id').text = start_dt.isoformat()

    # 一圈（Lap）
    lap = ET.SubElement(activity, 'Lap', {'StartTime': start_dt.isoformat()})
    ET.SubElement(lap, 'TotalTimeSeconds').text = f"{max(duration_ms, 1) / 1000:.0f}"
    ET.SubElement(lap, 'DistanceMeters').text = str(distance_m) if distance_m else "0"

    # 心率统计
    valid_hrs = [h['hr'] for h in hr_points if h['hr'] > 0]
    if valid_hrs:
        ET.SubElement(lap, 'MaximumHeartRateBpm').text = str(max(valid_hrs))
        avg_hr = int(sum(valid_hrs) / len(valid_hrs))
        ET.SubElement(lap, 'AverageHeartRateBpm').text = str(avg_hr)

    ET.SubElement(lap, 'Intensity').text = 'Active'
    ET.SubElement(lap, 'TriggerMethod').text = 'Manual'

    # 轨迹点
    track = ET.SubElement(lap, 'Track')

    if len(gps_points) >= 2:
        # 有GPS：按GPS点生成，心率尽量匹配
        gps_sorted = sorted(gps_points, key=lambda p: p['time'])
        hr_sorted = sorted(hr_points, key=lambda p: p['time'])

        for gp in gps_sorted:
            tp = ET.SubElement(track, 'Trackpoint')
            tp_time = datetime.fromtimestamp(gp['time'] / 1000,
                                             tz=timezone(timedelta(hours=8)))
            ET.SubElement(tp, 'Time').text = tp_time.isoformat()

            pos = ET.SubElement(tp, 'Position')
            ET.SubElement(pos, 'LatitudeDegrees').text = f"{gp['lat']:.7f}"
            ET.SubElement(pos, 'LongitudeDegrees').text = f"{gp['lon']:.7f}"

            if gp['alt'] > 0:
                ET.SubElement(tp, 'AltitudeMeters').text = f"{gp['alt']:.1f}"

            for hp in hr_sorted:
                if abs(hp['time'] - gp['time']) <= 5000:
                    ET.SubElement(ET.SubElement(tp, 'HeartRateBpm'), 'Value').text = str(hp['hr'])
                    break
    else:
        # 无GPS：按心率时间点生成
        for hp in sorted(hr_points, key=lambda p: p['time']):
            tp = ET.SubElement(track, 'Trackpoint')
            tp_time = datetime.fromtimestamp(hp['time'] / 1000,
                                             tz=timezone(timedelta(hours=8)))
            ET.SubElement(tp, 'Time').text = tp_time.isoformat()
            ET.SubElement(ET.SubElement(tp, 'HeartRateBpm'), 'Value').text = str(hp['hr'])

    return tcx


def format_timestamp(ms):
    """毫秒时间戳 -> 文件名友好格式"""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y%m%d_%H%M%S')


def format_datetime(ms):
    """毫秒时间戳 -> 可读格式"""
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def pretty_xml(element):
    """美化XML输出"""
    rough = ET.tostring(element, encoding='unicode')
    parsed = minidom.parseString(rough)
    return parsed.toprettyxml(indent="  ", encoding='utf-8')


# ============================================================
# 主流程
# ============================================================

def process_file(input_path):
    """处理单个华为JSON文件"""

    # ---- 检查输入文件 ----
    if not os.path.isfile(input_path):
        print("\n[错误] 找不到文件: %s" % input_path)
        return False

    file_size = os.path.getsize(input_path)
    print("\n[文件] 输入文件: %s" % input_path)
    print("[大小] %.1f MB" % (file_size / 1024 / 1024))

    if file_size == 0:
        print("[错误] 文件为空")
        return False

    # ---- 确定输出目录 ----
    base_dir = os.path.dirname(os.path.abspath(input_path))
    output_dir = os.path.join(base_dir, "converted_coros")
    os.makedirs(output_dir, exist_ok=True)
    print("[目录] 输出目录: %s" % output_dir)

    # ---- 读取JSON文件 ----
    print("\n[进度] 正在读取JSON文件（大文件可能需要几秒）...")
    try:
        with open(input_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        print("[错误] 读取文件失败: %s" % e)
        print("  [提示] 请确认文件是UTF-8编码的JSON文件")
        return False

    # ---- 提取所有运动记录 ----
    print("[进度] 正在解析运动记录...")
    obj_strings = extract_all_objects(content)
    total = len(obj_strings)
    print("[统计] 共发现 %d 条运动记录" % total)

    if total == 0:
        print("[错误] 未找到任何运动数据，请确认文件格式")
        return False

    # ---- 逐条转换 ----
    print("\n[进度] 正在转换...")

    stats = {
        'gpx': 0, 'tcx': 0, 'skipped': 0,
        'corrected': 0,  # 配速修正数
        'sport_types': {},
        'date_range': [None, None],
        'total_distance_km': 0,
        'total_duration_h': 0,
        'running_count': 0,
        'running_distance_km': 0,
        'walking_count': 0,
        'walking_distance_km': 0,
        'cycling_count': 0,
        'cycling_distance_km': 0,
        'corrected_records': [],
    }

    for i, raw in enumerate(obj_strings):
        # ---- 解析JSON对象 ----
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

        # ---- 提取字段 ----
        st = obj.get('sportType', 0)
        start_time = obj.get('startTime', 0)
        dist_m = obj.get('totalDistance', 0)
        dur_ms = obj.get('totalTime', 0)
        attr = obj.get('attribute', '')

        ts_str = format_timestamp(start_time) if start_time else "record%d" % i

        # ---- 配速智能识别 ----
        corrected_st, pace_val = detect_actual_sport(dist_m, dur_ms, st)
        if corrected_st != st:
            stats['corrected'] += 1
            pace_str = "%.2f" % (dur_ms / 60 / dist_m) if dist_m > 0 else "?"
            info = "[%d/%d] %s 走路->跑步 (配速%smin/km, %.2fkm)" % (
                i + 1, total, format_datetime(start_time), pace_str, dist_m / 1000)
            stats['corrected_records'].append(info)
            st = corrected_st

        # ---- 更新统计 ----
        st_name = SPORT_TYPE_NAMES.get(st, 'Sport%d' % st)
        stats['sport_types'][st] = stats['sport_types'].get(st, 0) + 1
        stats['total_distance_km'] += dist_m / 1000
        stats['total_duration_h'] += dur_ms / 1000 / 3600

        if st == 4:  # Running
            stats['running_count'] += 1
            stats['running_distance_km'] += dist_m / 1000
        elif st == 5:  # Walking
            stats['walking_count'] += 1
            stats['walking_distance_km'] += dist_m / 1000
        elif st == 3:  # Cycling
            stats['cycling_count'] += 1
            stats['cycling_distance_km'] += dist_m / 1000

        if start_time > 0:
            dt = datetime.fromtimestamp(start_time / 1000,
                                        tz=timezone(timedelta(hours=8)))
            if stats['date_range'][0] is None or dt < stats['date_range'][0]:
                stats['date_range'][0] = dt
            if stats['date_range'][1] is None or dt > stats['date_range'][1]:
                stats['date_range'][1] = dt

        # ---- 解析轨迹和心率 ----
        gps_points, hr_points = parse_attribute(attr)

        made_gpx = made_tcx = False

        # 生成GPX（有GPS轨迹的记录）
        if len(gps_points) >= 2:
            try:
                gpx = build_gpx(gps_points, hr_points, st, start_time, dist_m)
                gpx_filename = "%s_%s_%dm.gpx" % (ts_str, st_name, dist_m)
                with open(os.path.join(output_dir, gpx_filename), 'wb') as f:
                    f.write(pretty_xml(gpx))
                stats['gpx'] += 1
                made_gpx = True
            except Exception:
                pass

        # 生成TCX（有心率数据的记录）
        if hr_points:
            try:
                tcx = build_tcx(hr_points, gps_points, st, start_time, dist_m, dur_ms)
                if made_gpx:
                    tcx_filename = "%s_%s_%dm.tcx" % (ts_str, st_name, dist_m)
                else:
                    tcx_filename = "%s_%s_HRonly.tcx" % (ts_str, st_name)
                with open(os.path.join(output_dir, tcx_filename), 'wb') as f:
                    f.write(pretty_xml(tcx))
                stats['tcx'] += 1
                made_tcx = True
            except Exception:
                pass

        if not made_gpx and not made_tcx:
            stats['skipped'] += 1

        # ---- 进度显示 ----
        if (i + 1) % 50 == 0 or i + 1 == total:
            _print_progress(i + 1, total, stats)

    # ---- 输出汇总 ----
    _print_summary(total, stats, output_dir)
    return True


def _print_progress(processed, total, stats):
    """打印进度"""
    bar_len = 30
    filled = int(bar_len * processed / total)
    bar = '#' * filled + '.' * (bar_len - filled)
    pct = processed / total * 100
    g = stats['gpx']
    t = stats['tcx']
    s = stats['skipped']
    sys.stdout.write("\r  [%s] %d/%d (%d%%) GPX:%d TCX:%d 跳过:%d" %
                     (bar, processed, total, pct, g, t, s))
    sys.stdout.flush()


def _print_summary(total, stats, output_dir):
    """打印最终汇总"""
    print("\n\n" + "=" * 60)
    print("  [完成] 转换完成！汇总报告")
    print("=" * 60)

    # 基本统计
    print("\n  [统计] 总记录数: %d" % total)
    print("  [GPX]  生成GPX: %d 个" % stats['gpx'])
    print("  [TCX]  生成TCX: %d 个" % stats['tcx'])
    print("  [跳过] 跳过(无数据): %d 条" % stats['skipped'])
    if stats['corrected'] > 0:
        print("  [修正] 配速修正(走路->跑步): %d 条" % stats['corrected'])
        for info in stats['corrected_records']:
            print("    %s" % info)

    # 时间范围
    if stats['date_range'][0] and stats['date_range'][1]:
        d0 = stats['date_range'][0].strftime('%Y-%m-%d')
        d1 = stats['date_range'][1].strftime('%Y-%m-%d')
        print("\n  [日期] 时间范围: %s ~ %s" % (d0, d1))
        print("  [距离] 总距离: %.1f km" % stats['total_distance_km'])
        print("  [时长] 总时长: %.1f 小时" % stats['total_duration_h'])

    # 运动类型分布
    print("\n  [类型] 运动类型分布:")
    for st, cnt in sorted(stats['sport_types'].items(), key=lambda x: -x[1]):
        name = SPORT_TYPE_NAMES.get(st, 'Unknown(%d)' % st)
        extra = ""
        if st == 4:
            extra = " (%.1fkm)" % stats['running_distance_km']
        elif st == 5:
            extra = " (%.1fkm)" % stats['walking_distance_km']
        elif st == 3:
            extra = " (%.1fkm)" % stats['cycling_distance_km']
        print("    %-15s %4d 条%s" % (name, cnt, extra))

    # 输出目录
    print("\n  [目录] 输出目录: %s" % output_dir)
    total_files = stats['gpx'] + stats['tcx']
    print("  [文件] 共 %d 个文件" % total_files)

    # 导入指引
    print("\n" + "=" * 60)
    print("  导入高驰 COROS APP（推荐用GPX文件）")
    print("=" * 60)
    print("""
  1. 将 GPX 文件传输到手机
  2. 打开 COROS APP
  3. 首页右上角 [+] -> 导入运动数据
  4. 选择 GPX 文件（一次可选多个）
  5. 导入后自动匹配到对应日期
    """)

    print("=" * 60)
    print("  导入佳明 Garmin Connect（推荐用TCX文件）")
    print("=" * 60)
    print("""
  网页版方式（推荐）：
  1. 浏览器登录 connect.garmin.com
  2. 左上角菜单 -> 导入数据 -> 选择TCX文件
  3. 导入后可在"活动"中查看

  手机APP方式：
  1. 手机打开 Garmin Connect APP
  2. 更多 -> 导入活动 -> 选择TCX文件
    """)

    print("=" * 60)
    print("  注意事项")
    print("=" * 60)
    print("""
  - GPX适合高驰，TCX适合佳明，两边都留着就行
  - 导入后运动类型可在APP中手动修改
  - 如果文件太多，建议按月份分批导入
  - 仅心率的记录用TCX格式（文件名含 _HRonly）
    """)


# ============================================================
# 入口
# ============================================================

def main():
    """主入口"""
    print()
    print("╔══════════════════════════════════════════════╗")
    print("║   华为手表 - 高驰/佳明 运动数据转换工具     ║")
    print("║   Huawei Watch to COROS/Garmin Converter    ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # 确定输入文件
    input_file = None

    if len(sys.argv) >= 2:
        # 命令行参数或拖放
        input_file = sys.argv[1]
    else:
        # 交互模式
        print("请选择华为手表导出的JSON数据文件。")
        print("  [提示] 你也可以直接把文件拖到这个脚本上运行")
        print()

        # 尝试使用文件选择对话框
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
            # 没有图形界面，提示手动输入
            input_file = input("请输入JSON文件路径: ").strip().strip('"').strip("'")

    if not input_file:
        print("[错误] 未选择文件，退出")
        sys.exit(1)

    # 处理路径中的引号
    input_file = input_file.strip().strip('"').strip("'")

    print("  [文件] 输入文件: %s" % input_file)
    print()

    # 执行转换
    success = process_file(input_file)

    if success:
        print("\n[完成] 转换完成！请按照上方指引导入高驰APP。")
    else:
        print("\n[错误] 转换失败，请检查文件格式后重试。")
        print("  [提示] 常见问题:")
        print("    - 文件不是华为手表导出的JSON格式")
        print("    - 文件编码不是UTF-8")
        print("    - 文件已被损坏")

    # 在Windows上暂停，让用户看到结果
    if sys.platform == 'win32':
        input("\n按 Enter 键退出...")


if __name__ == '__main__':
    main()
