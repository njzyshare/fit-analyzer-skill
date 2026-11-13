#!/usr/bin/env python3
"""
FIT 运动数据预览器 — 生成交互式 HTML 预览页面

用法:
  python scripts/fit_preview.py input.fit
  python scripts/fit_preview.py input.fit -o preview.html

输出: 包含轨迹地图 + Session 摘要 + 全字段统计 + 计圈详情的 HTML 文件。
依赖: fitdecode (pip install fitdecode)
      预览页面在浏览器打开（无网络依赖仅底图需要），高德地图瓦片国内可访问。
"""
import fitdecode, json, os, sys, re
from datetime import datetime, timezone
from math import radians, sin, cos, sqrt, asin

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000
    dlat = radians(lat2 - lat1); dlon = radians(lon2 - lon1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon/2)**2
    return 2 * R * asin(sqrt(a))

def extract_fit_data(fit_path):
    """从 FIT 文件中提取所有展示数据"""
    with fitdecode.FitReader(fit_path) as fit:
        records_detail = []
        coords_raw = []
        sessions = []
        laps_raw = []
        file_ids = []

        for frame in fit:
            if frame.frame_type != fitdecode.FIT_FRAME_DATA:
                continue
            mt = frame.name if hasattr(frame, 'name') else '?'
            fields = {}
            for f in frame.fields:
                v = f.value
                if isinstance(v, datetime):
                    v = v.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')
                fields[f.name] = v

            if mt == 'record':
                records_detail.append(fields)
                lat = fields.get('position_lat')
                lon = fields.get('position_long')
                if lat is not None and lon is not None:
                    coords_raw.append((lat, lon))
            elif mt == 'session':
                sessions.append(fields)
            elif mt == 'lap':
                laps_raw.append(fields)
            elif mt == 'file_id':
                file_ids.append(fields)

    # 坐标转换
    def sc(v): return v * 180 / (2**31)
    lats = [sc(c[0]) for c in coords_raw]
    lons = [sc(c[1]) for c in coords_raw]

    # 总距离 Haversine
    total_haversine = sum(haversine(lats[i], lons[i], lats[i+1], lons[i+1]) for i in range(len(lats)-1))

    # Record 字段统计
    all_fields = set()
    for rec in records_detail:
        all_fields.update(rec.keys())

    FIELD_NAMES = {
        'heart_rate': '心率 (bpm)', 'cadence': '步频 (spm)',
        'speed': '速度 (m/s)', 'enhanced_speed': '速度(增强) (m/s)',
        'distance': '累积距离 (m)', 'enhanced_altitude': '海拔 (m)',
        'position_lat': '纬度(半圆)', 'position_long': '经度(半圆)',
        'timestamp': '时间戳',
    }

    record_stats = {}
    for field_name in sorted(all_fields):
        vals = [r[field_name] for r in records_detail if r.get(field_name) is not None]
        num_vals = [v for v in vals if isinstance(v, (int, float))]
        if num_vals and field_name not in ('position_lat', 'position_long', 'timestamp'):
            record_stats[field_name] = {
                'label': FIELD_NAMES.get(field_name, field_name),
                'min': round(min(num_vals), 1),
                'max': round(max(num_vals), 1),
                'avg': round(sum(num_vals) / len(num_vals), 1),
                'count': len(num_vals)
            }

    # Session 摘要
    session = sessions[0] if sessions else {}
    def sf(key, default=0):
        v = session.get(key)
        try: return float(v) if v is not None else default
        except: return default

    total_dist = sf('total_distance')
    total_timer = sf('total_timer_time') or sf('total_elapsed_time')
    total_elapsed = sf('total_elapsed_time')

    pace_val = total_timer / 60 / (total_dist / 1000) if total_dist > 0 else 0
    pace_str = f"{int(pace_val)}:{int((pace_val % 1) * 60):02d}"

    session_summary = {
        'total_distance': round(total_dist, 2),
        'total_timer_time': round(total_timer, 0),
        'total_elapsed_time': round(total_elapsed, 0),
        'avg_pace': round(pace_val, 2),
        'avg_pace_str': pace_str,
        'avg_heart_rate': int(sf('avg_heart_rate')),
        'max_heart_rate': int(sf('max_heart_rate')),
        'avg_running_cadence': int(sf('avg_running_cadence')) if session.get('avg_running_cadence') else None,
        'max_running_cadence': int(sf('max_running_cadence')) if session.get('max_running_cadence') else None,
        'total_calories': int(sf('total_calories')),
        'num_laps': int(sf('num_laps')),
        'sport': session.get('sport', ''),
        'sub_sport': session.get('sub_sport', ''),
        'trigger': session.get('trigger', ''),
        'total_training_effect': sf('total_training_effect') if session.get('total_training_effect') else None,
        'total_anaerobic_training_effect': sf('total_anaerobic_training_effect') if session.get('total_anaerobic_training_effect') else None,
        'total_ascent': int(sf('total_ascent')),
        'total_descent': int(sf('total_descent')),
        'avg_speed': round(sf('avg_speed'), 3),
        'max_speed': round(sf('max_speed'), 3),
        'total_haversine_km': round(total_haversine / 1000, 2),
    }

    # Laps
    laps_out = []
    for lap in laps_raw:
        ld = float(lap.get('total_distance', 0))
        lt = float(lap.get('total_timer_time', 0) or lap.get('total_elapsed_time', 0))
        lp = lt / 60 / (ld / 1000) if ld > 0 else 0
        laps_out.append({
            'idx': int(lap.get('message_index', len(laps_out))),
            'distance': round(ld, 0),
            'timer': round(lt, 0),
            'pace_str': f"{int(lp)}:{int((lp % 1) * 60):02d}",
            'avg_hr': int(float(lap['avg_heart_rate'])) if lap.get('avg_heart_rate') else None,
            'max_hr': int(float(lap['max_heart_rate'])) if lap.get('max_heart_rate') else None,
            'avg_cad': int(float(lap['avg_running_cadence'])) if lap.get('avg_running_cadence') else None,
            'calories': int(float(lap['total_calories'])) if lap.get('total_calories') else 0,
            'ascent': int(float(lap['total_ascent'])) if lap.get('total_ascent') else None,
            'descent': int(float(lap['total_descent'])) if lap.get('total_descent') else None,
        })

    # 轨迹采样（约 500 点）
    step = max(1, len(lats) // 500)
    track_pts = [[round(lats[i], 6), round(lons[i], 6)] for i in range(0, len(lats), step)]
    if track_pts and track_pts[-1] != [round(lats[-1], 6), round(lons[-1], 6)]:
        track_pts.append([round(lats[-1], 6), round(lons[-1], 6)])

    file_id = file_ids[0] if file_ids else {}

    return {
        'file_id': file_id,
        'session': session_summary,
        'laps': laps_out,
        'record_stats': record_stats,
        'record_count': len(records_detail),
        'coords': {
            'points': len(lats),
            'track': track_pts,
            'lat_range': [round(min(lats), 6), round(max(lats), 6)],
            'lon_range': [round(min(lons), 6), round(max(lons), 6)],
            'start': [round(lats[0], 6), round(lons[0], 6)] if lats else None,
            'end': [round(lats[-1], 6), round(lons[-1], 6)] if lats else None,
        }
    }


def generate_html(data, fit_filename=''):
    """从数据生成完整的 HTML 预览页面"""
    data_json = json.dumps(data, ensure_ascii=False)

    # 文件名显示
    file_label = f'<span style="color:#4fc3f7">' + fit_filename.replace('<', '&lt;').replace('>', '&gt;') + '</span>' if fit_filename else ''

    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>FIT 运动数据预览</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1923;color:#e0e0e0}}
.app{{max-width:1400px;margin:0 auto;padding:16px}}
.header{{margin-bottom:16px}}
.header h1{{font-size:22px;color:#fff}}
.header .sub{{font-size:13px;color:#888;margin-top:4px}}
.layout{{display:flex;gap:16px}}
.map-panel{{flex:1;min-width:0}}
.side-panel{{width:440px;flex-shrink:0}}
@media(max-width:1000px){{.layout{{flex-direction:column}}.side-panel{{width:100%}}}}
#map{{width:100%;height:640px;border-radius:10px;border:1px solid #2a3a4a}}
.sg{{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px}}
.sc{{background:#162334;border-radius:8px;padding:10px 14px}}
.sc .l{{font-size:11px;color:#6b7a8a}}
.sc .v{{font-size:20px;font-weight:600;color:#4fc3f7;margin-top:2px}}
.sc .v.gn{{color:#66bb6a}} .sc .v.og{{color:#ffa726}} .sc .v.pk{{color:#ec407a}} .sc .v.pp{{color:#b388ff}}
.sec{{background:#162334;border-radius:10px;border:1px solid #2a3a4a;margin-bottom:12px;overflow:hidden}}
.st{{font-size:13px;font-weight:500;color:#8a9aa8;padding:12px 16px 8px;letter-spacing:1px;text-transform:uppercase}}
.fr{{display:flex;justify-content:space-between;padding:5px 16px;font-size:13px}}
.fr:nth-child(even){{background:#1a2a3a}}
.fr .l{{color:#6b7a8a}} .fr .v{{color:#e0e0e0;font-weight:500;text-align:right}}
.lt{{width:100%;border-collapse:collapse;font-size:12px}}
.lt th{{background:#1a2a3a;color:#6b7a8a;font-weight:500;padding:6px 8px;text-align:right;position:sticky;top:0;white-space:nowrap}}
.lt th:first-child{{text-align:center}}
.lt td{{padding:4px 8px;text-align:right;border-top:1px solid #1a2a3a;font-size:12px;white-space:nowrap}}
.lt td:first-child{{text-align:center;color:#6b7a8a}}
.lt tr:nth-child(even) td{{background:#1a2a3a40}}
.ltw{{overflow-x:auto;max-height:350px;overflow-y:auto}}
.fg{{display:grid;grid-template-columns:1fr 1fr;gap:0}}
.sb{{padding:8px 12px;border-bottom:1px solid #1a2a3a}}
.sb .sl{{color:#6b7a8a;font-size:11px}}
.sb .sv{{color:#b0c0d0;font-size:13px;font-weight:500}}
.sb .sr{{color:#5a7a8a;font-size:11px}}
.dg{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;padding:8px 16px 12px}}
.di{{background:#1a2a3a;border-radius:6px;padding:8px 12px}}
.di .dl{{font-size:10px;color:#6b7a8a}}
.di .dv{{font-size:13px;color:#e0e0e0;font-weight:500}}
.tb{{display:flex;border-bottom:1px solid #2a3a4a}}
.tb .t{{padding:8px 16px;font-size:13px;color:#6b7a8a;cursor:pointer;border-bottom:2px solid transparent}}
.tb .t:hover{{color:#b0c0d0}}
.tb .t.ac{{color:#4fc3f7;border-bottom-color:#4fc3f7}}
.tp{{display:none}}
.tp.ac{{display:block}}
</style>
</head>
<body>
<div class="app">
<div class="header">
<h1>FIT 运动数据预览</h1>
<div class="sub" id="sub">加载中...</div>
</div>
<div class="sg" id="sg"></div>
<div class="layout">
<div class="map-panel"><div id="map"></div></div>
<div class="side-panel">
<div class="sec"><div class="st">设备信息</div><div class="dg" id="dg"></div></div>
<div class="sec">
<div class="tb" id="tb">
<div class="t ac" data-tab="session">Session</div>
<div class="t" data-tab="fields">全字段</div>
<div class="t" data-tab="laps">计圈</div>
</div>
<div class="tp ac" id="psession"></div>
<div class="tp" id="pfields"></div>
<div class="tp" id="plaps"></div>
</div>
</div>
</div>
</div>
<script>
var d={data_json};
var s=d.session,c=d.coords;
document.getElementById('sub').textContent=(c.track?c.track.length:0)+' 轨迹点 '+(c.points||'?')+' GPS 点 '+(c.lat_range?c.lat_range[0]+'~'+c.lat_range[1]+'N':'-')+' '+(c.lon_range?c.lon_range[0]+'~'+c.lon_range[1]+'E':'-');
var sum=[
  ['距离',(s.total_distance/1000).toFixed(2)+' km','gn'],
  ['运动时长',(s.total_timer_time/60).toFixed(1)+' min',''],
  ['配速',s.avg_pace_str+' /km','og'],
  ['心率',s.avg_heart_rate+' / '+s.max_heart_rate,'pk'],
  ['步频',(s.avg_running_cadence||'-')+(s.max_running_cadence?' / '+s.max_running_cadence:'')+' spm','pp'],
  ['卡路里',s.total_calories+' kcal',''],
  ['爬升',(s.total_ascent||0)+' m / '+(s.total_descent||0)+' m',''],
  ['效果',(s.total_training_effect||'-')+' / '+(s.total_anaerobic_training_effect||'-'),'']
];
sum.push(['record',d.record_count+' 条','']);
var sg=document.getElementById('sg');
sum.forEach(function(x){{var e=document.createElement('div');e.className='sc';e.innerHTML='<div class="l">'+x[0]+'</div><div class="v'+(x[2]?' '+x[2]:'')+'">'+x[1]+'</div>';sg.appendChild(e)}});
var dev=[['制造商',d.file_id.manufacturer||'-'],['序列号',d.file_id.serial_number||'-'],['产品',d.file_id.product||'-'],['类型',d.file_id.type||'-'],['创建',d.file_id.time_created||'-'],['Haversine',(s.total_haversine_km||'-')+' km']];
var dg=document.getElementById('dg');
dev.forEach(function(x){{if(!x[1])return;var e=document.createElement('div');e.className='di';e.innerHTML='<div class="dl">'+x[0]+'</div><div class="dv">'+x[1]+'</div>';dg.appendChild(e)}});
var sf=[
  ['距离',(s.total_distance/1000).toFixed(2)+' km'],
  ['含暂停时间',(s.total_elapsed_time/60).toFixed(1)+' min'],
  ['运动时间',(s.total_timer_time/60).toFixed(1)+' min'],
  ['配速',s.avg_pace_str+' /km'],
  ['速度',s.avg_speed.toFixed(2)+' m/s ('+(s.avg_speed*3.6).toFixed(1)+' km/h)'],
  ['最大速度',s.max_speed.toFixed(2)+' m/s ('+(s.max_speed*3.6).toFixed(1)+' km/h)'],
  ['平均心率',s.avg_heart_rate+' bpm'],
  ['最大心率',s.max_heart_rate+' bpm'],
  ['步频',(s.avg_running_cadence||'-')+(s.max_running_cadence?' (max '+s.max_running_cadence+')':'')],
  ['卡路里',s.total_calories+' kcal'],
  ['计圈',s.num_laps],
  ['运动类型',s.sport+' / '+s.sub_sport],
  ['触发',s.trigger],
  ['有氧效果',s.total_training_effect||'-'],
  ['无氧效果',s.total_anaerobic_training_effect||'-'],
];
var ps=document.getElementById('psession');
sf.forEach(function(f){{var r=document.createElement('div');r.className='fr';r.innerHTML='<span class="l">'+f[0]+'</span><span class="v">'+f[1]+'</span>';ps.appendChild(r)}});
var pf=document.getElementById('pfields');
var rs=d.record_stats;
['heart_rate','cadence','speed','enhanced_speed','distance','enhanced_altitude'].forEach(function(fn){{var f=rs[fn];if(!f)return;var r=document.createElement('div');r.className='sb';r.innerHTML='<div class="sl">'+f.label+'</div><div class="sv">'+f.avg+' <span class="sr">avg</span> | '+f.min+' <span class="sr">min</span> | '+f.max+' <span class="sr">max</span></div><div class="sr">'+f.count+'/'+d.record_count+' 点</div>';pf.appendChild(r)}});
var pl=document.getElementById('plaps');
if(d.laps.length){{var w=document.createElement('div');w.className='ltw';var t=document.createElement('table');t.className='lt';var h=document.createElement('thead');h.innerHTML='<tr><th>#</th><th>距离</th><th>时长</th><th>配速</th><th>平均HR</th><th>最大HR</th><th>步频</th><th>爬升</th><th>下降</th><th>卡路里</th></tr>';t.appendChild(h);var b=document.createElement('tbody');d.laps.forEach(function(l){{var r=document.createElement('tr');r.innerHTML='<td>'+(l.idx+1)+'</td><td>'+l.distance+'m</td><td>'+l.timer+'s</td><td>'+l.pace_str+'</td><td>'+(l.avg_hr||'-')+'</td><td>'+(l.max_hr||'-')+'</td><td>'+(l.avg_cad||'-')+'</td><td>'+(l.ascent||'-')+'</td><td>'+(l.descent||'-')+'</td><td>'+(l.calories||0)+'</td>';b.appendChild(r)}});t.appendChild(b);w.appendChild(t);pl.appendChild(w)}}

var tabs=document.querySelectorAll('.tb .t'),panels=document.querySelectorAll('.tp');
tabs.forEach(function(t){{t.addEventListener('click',function(){{tabs.forEach(function(x){{x.classList.remove('ac')}});panels.forEach(function(x){{x.classList.remove('ac')}});t.classList.add('ac');document.getElementById('p'+t.dataset.tab).classList.add('ac')}})}});

var tk=c.track;
if(tk&&tk.length){{var PI=Math.PI,A=6378245.0,EE=0.00669342162296594323;
function oc(lat,lon){{return!(lon>73.66&&lon<135.05&&lat>3.86&&lat<53.55)}}
function tl(x,y){{var r=-100+2*x+3*y+0.2*y*y+0.1*x*y+0.2*Math.sqrt(Math.abs(x));r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;r+=(20*Math.sin(y*PI)+40*Math.sin(y/3*PI))*2/3;r+=(160*Math.sin(y/12*PI)+320*Math.sin(y*PI/30))*2/3;return r}}
function tn(x,y){{var r=300+x+2*y+0.1*x*x+0.1*x*y+0.1*Math.sqrt(Math.abs(x));r+=(20*Math.sin(6*x*PI)+20*Math.sin(2*x*PI))*2/3;r+=(20*Math.sin(x*PI)+40*Math.sin(x/3*PI))*2/3;r+=(150*Math.sin(x/12*PI)+300*Math.sin(x/30*PI))*2/3;return r}}
function wg(lat,lon){{if(oc(lat,lon))return[lat,lon];var d=tl(lon-105,lat-35),n=tn(lon-105,lat-35),rl=lat/180*PI,m=Math.sin(rl);m=1-EE*m*m;var s=Math.sqrt(m);d=(d*180)/((A*(1-EE))/(m*s)*PI);n=(n*180)/(A/s*Math.cos(rl)*PI);return[lat+d,lon+n]}}
var tr=tk.map(function(p){{return wg(p[0],p[1])}});
var map=L.map('map',{{zoomControl:true}}).setView([24.65,118.18],13);
L.tileLayer('https://webrd0{{s}}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={{x}}&y={{y}}&z={{z}}',{{subdomains:['1','2','3','4'],maxZoom:18,attribution:'高德'}}).addTo(map);
L.polyline(tr,{{color:'#ff6f00',weight:3,opacity:.85}}).addTo(map);
L.circleMarker(tr[0],{{color:'#4caf50',fillColor:'#4caf50',fillOpacity:.9,radius:8}}).addTo(map).bindTooltip('起点',{{direction:'right'}});
L.circleMarker(tr[tr.length-1],{{color:'#f44336',fillColor:'#f44336',fillOpacity:.9,radius:8}}).addTo(map).bindTooltip('终点',{{direction:'right'}});
map.fitBounds(L.polyline(tr).getBounds().pad(0.05));
}}
</script>
</body>
</html>'''


def main():
    import argparse
    parser = argparse.ArgumentParser(description='FIT 运动数据预览器')
    parser.add_argument('input', help='输入 .fit 文件路径')
    parser.add_argument('-o', '--output', default=None, help='输出 HTML 路径（默认：输入文件名_preview.html）')
    args = parser.parse_args()

    if not os.path.isfile(args.input):
        print(f'[错误] 找不到文件: {args.input}')
        sys.exit(1)

    print(f'[读取] {args.input}')
    data = extract_fit_data(args.input)

    output_path = args.output
    if not output_path:
        base = os.path.splitext(args.input)[0]
        output_path = base + '_preview.html'

    fit_filename = os.path.basename(args.input)
    html = generate_html(data, fit_filename)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(html)

    print(f'[生成] {output_path}')
    s = data['session']
    print(f'[摘要] {s["total_distance"]/1000:.2f}km | {s["total_timer_time"]/60:.1f}min | {s["avg_pace_str"]} /km | HR {s["avg_heart_rate"]}/{s["max_heart_rate"]} | {s["total_calories"]}kcal')


if __name__ == '__main__':
    main()
