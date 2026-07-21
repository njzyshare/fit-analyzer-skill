#!/usr/bin/env python3
"""
批量华为 JSON → FIT 转换器

从华为运动健康导出的 JSON 中提取所有运动记录，
按运动类型分类输出 FIT 到对应目录。

用法:
  python scripts/huawei_batch_convert.py <华为导出.json> [--output-dir OUTPUT]

输出目录结构:
  output/
  ├── Running/       (sportType 4, 101, 281)
  │   ├── 20251221_075145_21360m.fit
  │   └── ...
  ├── Walking/       (sportType 5)
  ├── Cycling/       (sportType 3)
  ├── Other/         (sportType 117, 106 — 仅心率/无GPS)
  └── skipped.log    (未能转换的记录)
"""
import json, os, re, sys, subprocess, traceback, argparse, math
import concurrent.futures
from datetime import datetime, timezone, timedelta

# ==================== 运动类型映射 ====================
SPORT_FOLDER_NAMES = {
    4: 'Running',      # 户外跑
    5: 'Walking',      # 户外步行
    3: 'Cycling',      # 户外骑行
    101: 'Running',    # 计划跑步/跑步机
    106: 'Other',      # 室内有氧（无GPS）
    117: 'Other',      # 纯心率监测（无GPS）
    281: 'Running',    # 室内运动
}

SPORT_FIT_NAMES = {
    4: 'running',
    5: 'walking',
    3: 'cycling',
    101: 'running',
    106: 'other',
    117: 'other',
    281: 'running',
}

# ==================== 复用 huawei_convert.py 的工具函数 ====================
# 直接从 huawei_convert.py 中导入需要的函数

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


def parse_attribute(attr_str):
    """解析华为手表的attribute字段"""
    if not attr_str or not isinstance(attr_str, str):
        return [], [], [], []

    lines = attr_str.split('\n')
    gps_points = []
    hr_points = []
    cadence_points = []
    alti_points = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith('HW_EXT_TRACK_DETAIL@'):
            line = line[len('HW_EXT_TRACK_DETAIL@'):]

        fields = line.split(';')
        pt = {}
        for f in fields:
            if '=' in f:
                k, v = f.split('=', 1)
                pt[k.strip()] = v.strip()

        tp = pt.get('tp', '')

        # GPS
        if 'lat' in pt and 'lon' in pt:
            try:
                lat_f = float(pt['lat'])
                lon_f = float(pt['lon'])
                if abs(lat_f) > 85 or abs(lon_f) > 180 or (abs(lat_f) < 0.001 and abs(lon_f) < 0.001):
                    continue
                gps_points.append({
                    'lat': lat_f, 'lon': lon_f,
                    'alt': float(pt.get('alt', 0)),
                    'time': int(pt['t']) if 't' in pt else 0,
                })
            except (ValueError, KeyError):
                pass

        # HR
        elif tp == 'h-r' and 'v' in pt and 'k' in pt:
            try:
                hr_val = int(pt['v'])
                if hr_val > 0:
                    hr_points.append({'hr': hr_val, 'time': int(pt['k'])})
            except (ValueError, KeyError):
                pass

        # Cadence
        elif tp == 's-r' and 'v' in pt and 'k' in pt:
            try:
                cad_val = int(pt['v'])
                if cad_val > 0:
                    cadence_points.append({'cadence': cad_val, 'time': int(pt['k'])})
            except (ValueError, KeyError):
                pass

        # Alti
        elif tp == 'alti' and 'v' in pt and 'k' in pt:
            try:
                alti_points.append({'alt': float(pt['v']), 'time': int(pt['k'])})
            except (ValueError, KeyError):
                pass

    return gps_points, hr_points, cadence_points, alti_points


def calibrate_altitude(alti_points):
    """海拔校准"""
    if len(alti_points) < 10:
        return alti_points, 0
    import statistics
    alts = [p['alt'] for p in alti_points]
    if len(alts) < 10:
        return alti_points, 0
    median_alt = statistics.median(alts)
    correction = 0
    if median_alt < -5:
        correction = -median_alt + 10
        for p in alti_points:
            p['alt'] += correction
    return alti_points, correction


def get_sport_name(st):
    """华为 sportType → FIT sport 名称"""
    return SPORT_FIT_NAMES.get(st, 'other')


def get_folder_name(st):
    """华为 sportType → 目录名称"""
    return SPORT_FOLDER_NAMES.get(st, 'Other')


# ==================== FIT 编码中间 JSON ====================

def gcj02_to_wgs84(lat, lon):
    """GCJ02 -> WGS84 反算转换"""
    import math
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


def build_fit_json(obj, gps_points, hr_points, cadence_points, alti_points,
                    st, start_time, dist_m, dur_ms, huawei_calories=None):
    """构建 fit_encode.mjs 需要的 JSON 中间格式"""
    if len(gps_points) < 2:
        return None  # 无GPS点无法生成FIT

    alti_corrected, _ = calibrate_altitude(alti_points)

    gps_sorted = sorted(gps_points, key=lambda p: p['time'])
    hr_sorted = sorted(hr_points, key=lambda p: p['time'])
    cad_sorted = sorted(cadence_points, key=lambda p: p['time'])
    alti_sorted = sorted(alti_corrected, key=lambda p: p['time'])

    st_name = get_sport_name(st)
    fit_sport = st_name.lower()
    total_time_ms = dur_ms or (gps_sorted[-1]['time'] - gps_sorted[0]['time'])
    total_dist = dist_m or 0

    # 构造 points
    points = []
    for i, gp in enumerate(gps_sorted):
        lat, lon = gcj02_to_wgs84(gp['lat'], gp['lon'])

        hr = None
        for hp in hr_sorted:
            if abs(hp['time'] - gp['time']) <= 5000:
                hr = hp['hr']
                break

        cad = None
        for cp in cad_sorted:
            if abs(cp['time'] - gp['time']) <= 5000:
                cad = cp['cadence']
                break

        alt = None
        for ap in alti_sorted:
            if abs(ap['time'] - gp['time']) <= 3000:
                alt = ap['alt']
                break

        frac = (gp['time'] - gps_sorted[0]['time']) / max(1, gps_sorted[-1]['time'] - gps_sorted[0]['time'])
        distance = total_dist * frac

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

    # 计圈
    laps = []
    if total_dist >= 1000:
        n_laps = max(1, math.ceil(total_dist / 1000))
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
        'manufacturer': 0xFF,  # development
        'product': 0,
    }
    return fit_data


# ==================== 主流程 ====================

def process(input_path, output_dir):
    """批量转换华为JSON中的所有运动记录到FIT"""
    os.makedirs(output_dir, exist_ok=True)
    
    # 初始化目录
    for folder in ['Running', 'Walking', 'Cycling', 'Other']:
        os.makedirs(os.path.join(output_dir, folder), exist_ok=True)
    
    skip_log = []
    stats = {'fit': 0, 'skipped': 0, 'no_gps': 0, 'error': 0, 'by_type': {}}
    
    # 查找 fit_encode.mjs
    encoder_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fit_encode.mjs'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fit_encode.mjs'),
    ]
    encoder_path = None
    for p in encoder_candidates:
        if os.path.isfile(p):
            encoder_path = p
            break
    if not encoder_path:
        print('[错误] 找不到 fit_encode.mjs')
        sys.exit(1)
    
    node_cwd = os.path.dirname(encoder_path)
    
    # 流式读取JSON
    with open(input_path, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 提取所有顶层对象
    print(f'[进度] 正在解析JSON...')
    
    # 先用正则修复 partTimeMap
    fixed = fix_parttime_map(content)
    data = json.loads(fixed)
    
    if not isinstance(data, list):
        data = [data]
    
    total = len(data)
    print(f'[统计] 共 {total} 条运动记录')
    
    # 预处理：只保留有GPS的记录（同时也解析好各数据点）
    candidates = []
    for i, obj in enumerate(data):
        st = obj.get('sportType', 0)
        start_time = obj.get('startTime', 0)
        dist_m = obj.get('totalDistance', 0)
        dur_ms = obj.get('totalTime', 0)
        attr = obj.get('attribute', '')
        huawei_cal = obj.get('totalCalories')
        gps_points, hr_points, cadence_points, alti_points = parse_attribute(attr)
        stats['by_type'][st] = stats['by_type'].get(st, 0) + 1
        
        if len(gps_points) < 2:
            skip_log.append(f'[{st}] no GPS, dist={dist_m}m')
            stats['no_gps'] += 1
            stats['skipped'] += 1
            continue
        
        candidates.append((i, obj, st, start_time, dist_m, dur_ms, huawei_cal,
                          gps_points, hr_points, cadence_points, alti_points))
    
    print(f'  有GPS: {len(candidates)}, 无GPS(跳过): {stats["no_gps"]}')
    
    # 并行转换
    def convert_one(args):
        i, obj, st, start_time, dist_m, dur_ms, huawei_cal, gps_points, hr_points, cadence_points, alti_points = args
        try:
            # 先构建 JSON
            fit_json = build_fit_json(obj, gps_points, hr_points, cadence_points, alti_points,
                                      st, start_time, dist_m, dur_ms, huawei_cal)
            if fit_json is None:
                return ('skip', f'[{st}] build_fit_json returned None')
            
            # 调用 fit_encode.mjs
            proc = subprocess.run(
                ['node', encoder_path],
                input=json.dumps(fit_json).encode('utf-8'),
                capture_output=True, text=False, timeout=60, cwd=node_cwd,
            )
            if proc.returncode != 0:
                err = proc.stderr.decode('utf-8', errors='replace')[:200]
                return ('error', f'[{st}] FIT编码失败: {err}')
            
            # 生成文件名
            ts_str = format_timestamp(start_time) if start_time else f'record_{i}'
            folder = get_folder_name(st)
            fname = f'{ts_str}_{int(dist_m)}m.fit'
            out_path = os.path.join(output_dir, folder, fname)
            
            with open(out_path, 'wb') as f_out:
                f_out.write(proc.stdout)
            
            return ('ok', out_path)
        except subprocess.TimeoutExpired:
            return ('error', f'[{st}] FIT编码超时')
        except Exception as e:
            return ('error', f'[{st}] build_fit_json error: {e}')
    
    done_count = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(convert_one, c) for c in candidates]
        for future in concurrent.futures.as_completed(futures):
            status, msg = future.result()
            done_count += 1
            if status == 'ok':
                stats['fit'] += 1
            elif status == 'skip':
                skip_log.append(msg)
            else:
                skip_log.append(msg)
                stats['error'] += 1
            
            if done_count % 500 == 0:
                print(f'  [{done_count}/{len(candidates)}] FIT: {stats["fit"]}, 错误: {stats["error"]}')
    
    # 输出汇总
    print('\n' + '=' * 60)
    print(f'  转换完成')
    print('=' * 60)
    print(f'  FIT生成: {stats["fit"]}')
    print(f'  跳过(无GPS): {stats["no_gps"]}')
    print(f'  错误: {stats["error"]}')
    print(f'  总计: {total}')
    print(f'\n  类型分布:')
    for st, cnt in sorted(stats['by_type'].items(), key=lambda x: -x[1]):
        print(f'    {get_folder_name(st):10s} (sportType={st}): {cnt}')
    print(f'\n  输出目录: {output_dir}')
    
    # 写跳过日志
    if skip_log:
        log_path = os.path.join(output_dir, 'skipped.log')
        with open(log_path, 'w', encoding='utf-8') as f_log:
            f_log.write('\n'.join(skip_log))
        print(f'  跳过日志: {log_path} ({len(skip_log)} 条)')
    
    return stats


def format_timestamp(ms):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y%m%d_%H%M%S')


def format_datetime(ms):
    dt = datetime.fromtimestamp(ms / 1000, tz=timezone(timedelta(hours=8)))
    return dt.strftime('%Y-%m-%d %H:%M:%S')


def main():
    parser = argparse.ArgumentParser(description='批量华为JSON→FIT转换')
    parser.add_argument('input', nargs='?', default='D:/CD-LIGHT-workbuddy/华为运动数据/motion path detail data1780557919093.json',
                        help='华为运动健康导出JSON路径')
    parser.add_argument('--output-dir', '-o', default='D:/CD-LIGHT-workbuddy/华为运动FIT',
                        help='输出目录')
    args = parser.parse_args()
    
    import math
    process(args.input, args.output_dir)


if __name__ == '__main__':
    main()
