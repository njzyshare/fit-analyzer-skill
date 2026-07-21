/**
 * FIT 合并 — 极简版（核心消息，类似最初可上传的 282KB 版本）
 * 
 * 只写核心消息：file_id + event + record + lap + session + activity
 * 不加 gpsMetadata / timestampCorrelation 等
 * 确保数据正确：距离、配速、心率、爬升
 */

import {Decoder, Encoder, Stream, Profile, CrcCalculator} from '@garmin/fitsdk';
import fs from 'fs';

function crc16(data) {
  const cc = new CrcCalculator();
  cc.addBytes(data, 0, data.length);
  return cc.crc;
}

const files = [
  'C:\\Users\\feijiangbin\\Desktop\\618268744_ACTIVITY.fit',
  'C:\\Users\\feijiangbin\\Desktop\\618268745_ACTIVITY.fit',
  'C:\\Users\\feijiangbin\\Desktop\\618268750_ACTIVITY.fit',
];

const segs = files.map(fp => {
  const buf = fs.readFileSync(fp);
  const stream = Stream.fromBuffer(buf);
  const decoder = new Decoder(stream);
  const {messages} = decoder.read({includeUnknownData: true, expandSubFields: true, convertTypesToStrings: true, mergeHeartRates: true});
  return {messages, name: fp.split('\\').pop()};
});

// 排序
segs.sort((a,b) => {
  const aR = a.messages.recordMesgs?.[0]?.timestamp;
  const bR = b.messages.recordMesgs?.[0]?.timestamp;
  return aR - bR;
});

for (const s of segs) {
  const r = s.messages.recordMesgs;
  if (r?.length) console.log(`  ${r[0].timestamp.toISOString().slice(11,19)} -> ${r[r.length-1].timestamp.toISOString().slice(11,19)}`);
}

// ===== 合并 records =====
const mergedRecs = [];
let doff = 0;
for (const seg of segs) {
  const recs = seg.messages.recordMesgs || [];
  if (!recs.length) continue;
  const sd = recs[0].distance || 0;
  for (const r of recs) if (r.distance != null) r.distance = (r.distance - sd) + doff;
  mergedRecs.push(...recs);
  doff = recs[recs.length - 1].distance || doff;
}

console.log(`\n合并 records: ${mergedRecs.length}`);
const td = mergedRecs.length ? (mergedRecs[mergedRecs.length - 1].distance || 0) : 0;
console.log(`总距离: ${(td/1000).toFixed(2)}km`);

// ===== 重建计圈 (每1km) =====
const LAP = 1000;
const laps = [];
let cur = [], nb = LAP, base = mergedRecs[0]?.distance || 0;

function calcL(rs) {
  if (!rs.length) return null;
  const f = rs[0], l = rs[rs.length-1];
  const act = rs.filter(r => r.speed > 0 || (r.heartRate != null && r.heartRate > 0));
  const hrs = act.filter(r => r.heartRate != null).map(r => r.heartRate);
  const spds = act.filter(r => r.speed > 0).map(r => r.speed);
  const dist = (l.distance || 0) - (f.distance || 0);
  const el = (l.timestamp - f.timestamp) / 1000;
  let t = 0;
  for(let i = 0; i < rs.length-1; i++) if(rs[i].speed > 0 || (rs[i].heartRate != null && rs[i].heartRate > 0)) t += (rs[i+1].timestamp - rs[i].timestamp) / 1000;
  if(!t) t = el;
  return { timestamp: l.timestamp, startTime: f.timestamp, totalElapsedTime: el, totalTimerTime: t, totalDistance: dist, avgSpeed: t ? dist/t : 0, maxSpeed: spds.length ? Math.max(...spds) : undefined, avgHeartRate: hrs.length ? Math.round(hrs.reduce((a,b)=>a+b,0)/hrs.length) : undefined, maxHeartRate: hrs.length ? Math.max(...hrs) : undefined, event: 'lap', eventType: 'stop', lapTrigger: 'distance', sport: 'running', subSport: 'generic' };
}

for (const r of mergedRecs) {
  cur.push(r);
  const d = r.distance || 0;
  while(d >= base + nb) {
    let idx = -1;
    for(let i = 0; i < cur.length; i++) if((cur[i].distance||0) >= base + nb) { idx = i; break; }
    if(idx < 0) break;
    const lap = calcL(cur.slice(0, idx+1));
    if(lap && lap.totalDistance > 0) laps.push(lap);
    cur = cur.slice(idx+1);
    nb += LAP;
  }
}
if(cur.length && cur.some(r => r.speed > 0 || (r.heartRate != null && r.heartRate > 0)) && td > 0) {
  const ps = laps.reduce((s,l) => s + l.totalDistance, 0);
  const ld = td - ps;
  if(ld > 0) { const lap = calcL(cur); if(lap) { lap.totalDistance = ld; if(lap.totalTimerTime) lap.avgSpeed = ld / lap.totalTimerTime; laps.push(lap); } }
}

console.log(`计圈: ${laps.length}`);

// ===== session 数据 =====
const fR = mergedRecs[0], lR = mergedRecs[mergedRecs.length-1];
const timer = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalTimerTime) || 0), 0);
const hrs = mergedRecs.filter(r => r.heartRate != null && (r.speed > 0 || r.heartRate > 0)).map(r => r.heartRate);
const elapsed = (lR.timestamp - fR.timestamp) / 1000;
const cal = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalCalories) || 0), 0);
const ascent = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalAscent) || 0), 0);
const descent = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalDescent) || 0), 0);
const pace = timer ? (td/1000) / (timer/60) : 0;

console.log(`timer=${(timer/60).toFixed(1)}min pace=${pace.toFixed(1)}min/km HR=${hrs.length ? Math.round(hrs.reduce((a,b)=>a+b,0)/hrs.length) : '?'}/${Math.max(...hrs)} cal=${cal} ascent=${ascent}`);

// ===== 编码 =====
const enc = new Encoder();

// file_id — 显式写全所有字段
enc.writeMesg({ mesgNum: Profile.MesgNum.FILE_ID, type: 'activity', manufacturer: 'garmin', serialNumber: 3504654948, product: 4536, timeCreated: fR.timestamp, productName: 'fenix8' });

// device_info — 从第一个文件取创建设备
const f1 = segs[0];
const f1Dis = f1.messages.deviceInfoMesgs || [];
for (const di of f1Dis) {
  if (di.deviceIndex === 0 || di.deviceIndex === 'creator') {
    try { enc.writeMesg({ mesgNum: Profile.MesgNum.DEVICE_INFO, timestamp: lR.timestamp, deviceIndex: 0, manufacturer: 'garmin', serialNumber: 3504654948, product: 4536, softwareVersion: 22.38, sourceType: 'local' }); } catch(e) { console.log('  device_info fail:', e.message); }
    break;
  }
}

// sport
try { enc.writeMesg({ mesgNum: Profile.MesgNum.SPORT, sport: 'running', subSport: 'generic' }); } catch(e) { console.log('  sport fail:', e.message); }

// event: timer start
enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, timestamp: fR.timestamp, event: 'timer', eventType: 'start', eventGroup: 0 });

// records
for (const r of mergedRecs) {
  const d = { mesgNum: Profile.MesgNum.RECORD };
  if (r.timestamp) d.timestamp = r.timestamp;
  if (r.positionLat != null) d.positionLat = r.positionLat;
  if (r.positionLong != null) d.positionLong = r.positionLong;
  if (r.heartRate != null) d.heartRate = r.heartRate;
  if (r.cadence != null) d.cadence = r.cadence;
  if (r.speed != null) d.speed = r.speed;
  if (r.distance != null) d.distance = r.distance;
  if (r.power != null) d.power = r.power;
  if (r.temperature != null) d.temperature = r.temperature;
  if (r.enhancedSpeed != null) d.enhancedSpeed = r.enhancedSpeed;
  if (r.enhancedAltitude != null) d.enhancedAltitude = r.enhancedAltitude;
  enc.writeMesg(d);
}

// event: timer stop
enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, timestamp: lR.timestamp, event: 'timer', eventType: 'stop', eventGroup: 0 });

// laps
for (const lap of laps) {
  const d = { mesgNum: Profile.MesgNum.LAP, ...lap };
  for (const k of Object.keys(d)) if(d[k]===undefined) delete d[k];
  enc.writeMesg(d);
}

// session
const sesD = { mesgNum: Profile.MesgNum.SESSION, timestamp: lR.timestamp, startTime: fR.timestamp, totalElapsedTime: elapsed, totalTimerTime: timer, totalDistance: td, avgSpeed: timer ? td/timer : 0, maxSpeed: Math.max(...mergedRecs.filter(r=>r.speed>0).map(r=>r.speed)), avgHeartRate: hrs.length ? Math.round(hrs.reduce((a,b)=>a+b,0)/hrs.length) : undefined, maxHeartRate: Math.max(...hrs), totalCalories: cal, totalAscent: Math.round(ascent), totalDescent: Math.round(descent), numLaps: laps.length, sport: 'running', subSport: 'generic', trigger: 'activityEnd' };
for(const k of Object.keys(sesD)) if(sesD[k]===undefined) delete sesD[k];
enc.writeMesg(sesD);

// activity
enc.writeMesg({ mesgNum: Profile.MesgNum.ACTIVITY, timestamp: lR.timestamp, localTimestamp: Math.round(lR.timestamp.getTime()/1000+28800), numSessions: 1, type: 'manual', event: 'activity', eventType: 'stop', eventGroup: 0 });

const buf = enc.close();

// 验证
const vs = Stream.fromBuffer(buf);
const vd = new Decoder(vs);
console.log(`\nisFIT: ${vd.isFIT()} | checkIntegrity: ${vd.checkIntegrity()}`);
console.log(`大小: ${(buf.length/1024).toFixed(0)}KB`);

const {messages} = vd.read({includeUnknownData: true, expandSubFields: true, convertTypesToStrings: true, mergeHeartRates: true});
const cnt = {};
for(const key of Object.keys(messages)) if(Array.isArray(messages[key])) cnt[key.replace('Mesgs','')] = messages[key].length;
console.log('消息:', JSON.stringify(cnt));

const s = messages.sessionMesgs?.[0];
if(s) {
  const p = s.avgSpeed ? (1000/(s.avgSpeed*60)).toFixed(1) : '?';
  console.log(`\n${(s.totalDistance/1000).toFixed(2)}km | ${(s.totalTimerTime/60).toFixed(1)}min | ${p}min/km`);
  console.log(`HR: ${s.avgHeartRate}/${s.maxHeartRate} | ${s.totalCalories}kcal | ascent=${s.totalAscent}/${s.totalDescent}`);
}

// file_id 字段数
console.log(`\nfile_id def 字段数: ${buf[14+5]}`);

const outPath = 'D:\\CD-LIGHT-workbuddy\\merged_activity.fit';
fs.writeFileSync(outPath, buf);
console.log(`\n✅ 输出: ${outPath}`);
