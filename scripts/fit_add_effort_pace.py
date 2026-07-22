#!/usr/bin/env python3
"""
FIT Effort Pace 写入工具

给任意 FIT 文件添加等强配速（Effort Pace）数据，
使用 V2 融合方案（Minetti 坡度基准 + 心率修正）。
写入后高驰 APP 可识别显示等强配速。

用法:
  python scripts/fit_add_effort_pace.py input.fit
  python scripts/fit_add_effort_pace.py input.fit -o output.fit
"""
import argparse, json, os, subprocess, sys, math
from datetime import datetime, timezone

def extract_fit_points(fit_path):
    """从 FIT 文件提取 points 和 session 数据"""
    import fitdecode
    
    points = []
    session = {}
    laps = []
    
    with fitdecode.FitReader(fit_path) as fit:
        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            mt = frame.name if hasattr(frame, 'name') else '?'
            fields = {}
            for f in frame.fields:
                v = f.value
                if isinstance(v, datetime):
                    v = v.astimezone(timezone.utc)
                fields[f.name] = v
            
            if mt == 'record':
                rec = {
                    'ts': int(fields.get('timestamp').timestamp() * 1000) if fields.get('timestamp') else 0,
                    'distance': fields.get('distance'),
                    'speed': fields.get('speed') or fields.get('enhanced_speed'),
                    'hr': fields.get('heart_rate'),
                    'altitude': fields.get('enhanced_altitude') or fields.get('altitude'),
                    'lat': fields.get('position_lat'),
                    'lon': fields.get('position_long'),
                }
                # 转换半圆坐标
                if rec['lat'] is not None:
                    rec['lat'] = rec['lat'] * 180 / (2**31)
                if rec['lon'] is not None:
                    rec['lon'] = rec['lon'] * 180 / (2**31)
                points.append(rec)
            
            elif mt == 'session':
                session = {
                    'startTime': int(fields.get('start_time').timestamp() * 1000) if fields.get('start_time') else 0,
                    'totalTime': float(fields.get('total_timer_time', 0) or fields.get('total_elapsed_time', 0)) * 1000,
                    'totalDistance': fields.get('total_distance', 0),
                    'totalCalories': fields.get('total_calories', 0),
                    'avgHeartRate': fields.get('avg_heart_rate'),
                    'maxHeartRate': fields.get('max_heart_rate'),
                    'avgCadence': fields.get('avg_running_cadence'),
                    'maxCadence': fields.get('max_running_cadence'),
                    'avgSpeed': fields.get('avg_speed') or fields.get('enhanced_avg_speed'),
                    'maxSpeed': fields.get('max_speed') or fields.get('enhanced_max_speed'),
                    'sport': fields.get('sport', 'running'),
                    'subSport': fields.get('sub_sport', 'generic'),
                }
    
    return points, session


def main():
    parser = argparse.ArgumentParser(description='FIT Effort Pace 写入工具')
    parser.add_argument('input', help='输入 .fit 文件')
    parser.add_argument('-o', '--output', default=None, help='输出 .fit 路径（默认：输入名+_effort.fit）')
    args = parser.parse_args()
    
    if not os.path.isfile(args.input):
        print(f'[错误] 找不到文件: {args.input}')
        sys.exit(1)
    
    output_path = args.output or os.path.splitext(args.input)[0] + '_effort.fit'
    
    print(f'[读取] {args.input}')
    points, session = extract_fit_points(args.input)
    print(f'  {len(points)} 个点')
    
    if len(points) < 2:
        print('[错误] 数据点不足')
        sys.exit(1)
    
    # 构造 fit_encode.mjs 需要的 JSON
    fit_data = {
        'points': points,
        'session': session,
        'enableEffortPace': True,
        'manufacturer': 0xFF,
        'product': 0,
    }
    
    # 找 fit_encode.mjs
    encoder_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fit_encode.mjs'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fit_encode.mjs'),
        'fit_encode.mjs',
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
    
    print(f'[编码] 写入等强配速...')
    try:
        proc = subprocess.run(
            ['node', encoder_path],
            input=json.dumps(fit_data).encode('utf-8'),
            capture_output=True, text=False, timeout=60, cwd=node_cwd,
        )
    except FileNotFoundError:
        print('[错误] 找不到 node 命令')
        sys.exit(1)
    
    if proc.returncode != 0:
        err = proc.stderr.decode('utf-8', errors='replace')[:500]
        print(f'[错误] FIT 编码失败: {err}')
        sys.exit(1)
    
    with open(output_path, 'wb') as f:
        f.write(proc.stdout)
    
    size_kb = len(proc.stdout) / 1024
    print(f'[生成] {output_path} ({size_kb:.0f}KB)')
    
    # 验证
    try:
        import fitdecode
        ep_count = 0
        hr_count = 0
        with fitdecode.FitReader(output_path) as fit:
            for frame in fit:
                if frame.frame_type == fitdecode.FIT_FRAME_DEFINITION:
                    if hasattr(frame, 'name') and frame.name in ('developer_data_id', 'field_description'):
                        print(f'  [结构] {frame.name} 存在 ✅')
        # Garmin SDK 验证
        proc2 = subprocess.run(
            ['node', '-e', '''
                const {Decoder, Stream} = require("@garmin/fitsdk");
                const fs = require("fs");
                const r = new Decoder(Stream.fromBuffer(fs.readFileSync("''' + output_path.replace('\\', '\\\\') + '''"))).read({
                    includeUnknownData: true, expandSubFields: true, convertTypesToStrings: true
                });
                const d = r.messages.developerDataIdMesgs;
                const f = r.messages.fieldDescriptionMesgs;
                const s = r.messages.sessionMesgs?.[0];
                const ep = r.messages.recordMesgs?.filter(x => x.developerFields && x.developerFields["0"] != null).length;
                console.log("dev:" + (d?.length||0) + " desc:" + (f?.length||0) + " rec_ep:" + ep + " sess_ep:" + (s?.developerFields?.["0"]||"-"));
                if (s?.developerFields?.["0"]) {
                    const v = s.developerFields["0"];
                    console.log("avg_effort_pace_mps:" + v.toFixed(3));
                    const pace = 1000 / v / 60;
                    console.log("avg_effort_pace:" + Math.floor(pace) + ":" + String(Math.round((pace%1)*60)).padStart(2,"0") + "/km");
                }
            '''],
            capture_output=True, text=True, timeout=15, cwd=node_cwd,
        )
        if proc2.returncode == 0:
            for line in proc2.stdout.strip().split('\n'):
                print(f'  [验证] {line}')
    except Exception as e:
        print(f'  [验证] 验证失败: {e}')


if __name__ == '__main__':
    main()
