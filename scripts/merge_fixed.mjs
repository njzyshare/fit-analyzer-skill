/**
 * FIT 合并 — 主力方案
 *
 * 用 @garmin/fitsdk Encoder 生成 protocol=2 的核心消息版本。
 * 经过实战验证，Garmin Connect 可上传。
 *
 * 可上传的消息组合：
 *   fileId + deviceInfo + sport + fileCreator + deviceSettings + userProfile +
 *   timeInZone + event + record(全字段含触地时间) + lap(26圈+步态数据) +
 *   session(含步频) + activity
 *
 * 不可上传：
 *   ❌ gpsMetadata / timestampCorrelation → 导致"上传出错，请重试"
 *   ❌ split / splitSummary → 同样导致上传失败
 *
 * 数据来源：
 *   - timer = Σ(各段原始 session.totalTimerTime) [不含暂停]
 *   - ascent/descent = Σ(各段原始 session.totalAscent)
 *   - calories = Σ(各段原始 session.totalCalories)
 *   - avgHeartRate = 加权平均所有运动中 records
 *   - lap = 按 1km 重建（含步态数据）
 */

import {Decoder, Encoder, Stream, Profile} from '@garmin/fitsdk';
import fs from 'fs';

const files = [
  './seg1.fit',  // 替换为你的分段文件路径
  './seg2.fit',
  './seg3.fit',
];

const segs = files.map(fp => {
  const {messages} = new Decoder(Stream.fromBuffer(fs.readFileSync(fp))).read({includeUnknownData: true, expandSubFields: true, convertTypesToStrings: true, mergeHeartRates: true});
  return {messages, name: fp.split('\\').pop()};
});
segs.sort((a,b) => (a.messages.recordMesgs?.[0]?.timestamp) - (b.messages.recordMesgs?.[0]?.timestamp));

// 合并 records（含暂停段插入）
const mergedRecs = [];
let doff = 0;
for (let si = 0; si < segs.length; si++) {
  const seg = segs[si];
  const recs = seg.messages.recordMesgs || [];
  if (!recs.length) continue;
  const sd = recs[0].distance || 0;
  for (const r of recs) if (r.distance != null) r.distance = (r.distance - sd) + doff;
  mergedRecs.push(...recs);
  doff = recs[recs.length - 1].distance || doff;

  if (si < segs.length - 1) {
    const nextSeg = segs[si + 1];
    if (!nextSeg.messages.recordMesgs?.length) continue;
    const gap = (nextSeg.messages.recordMesgs[0].timestamp - recs[recs.length - 1].timestamp) / 1000;
    if (gap > 0) {
      const lr = recs[recs.length - 1];
      for (let t = recs[recs.length - 1].timestamp / 1000 + 5; t < nextSeg.messages.recordMesgs[0].timestamp / 1000; t += 5) {
        mergedRecs.push({timestamp: new Date(t * 1000), heartRate: lr.heartRate, speed: 0, distance: doff,
          enhancedAltitude: lr.enhancedAltitude, positionLat: lr.positionLat, positionLong: lr.positionLong});
      }
    }
  }
}

const td = mergedRecs[mergedRecs.length - 1].distance || 0;
const fR = mergedRecs[0], lR = mergedRecs[mergedRecs.length - 1];

// ===== 正确的数据（从原始 session 取，不是从 records 推算） =====
const correctTimer = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalTimerTime) || 0), 0);  // 8679s = 144.7min
const correctAscent = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalAscent) || 0), 0);     // 87m
const correctDescent = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalDescent) || 0), 0);  // 87m
const cal = segs.reduce((s, seg) => s + ((seg.messages.sessionMesgs?.[0]?.totalCalories) || 0), 0);            // 1799
const hrs = mergedRecs.filter(r => r.heartRate != null && (r.speed > 0 || r.heartRate > 0)).map(r => r.heartRate);
const avgHr = hrs.length ? Math.round(hrs.reduce((a,b)=>a+b,0) / hrs.length) : undefined;
const maxHr = Math.max(...(hrs.length ? hrs : [0]));
const maxSpeed = Math.max(...mergedRecs.filter(r => r.speed > 0).map(r => r.speed));

const elapsed = (lR.timestamp - fR.timestamp) / 1000;  // 墙钟含暂停
const pace = correctTimer ? ((td/1000) / (correctTimer/60)).toFixed(1) : '?';

console.log(`records: ${mergedRecs.length}, dist: ${(td/1000).toFixed(2)}km`);
console.log(`timer(正确): ${(correctTimer/60).toFixed(1)}min, timer(含暂停): ${(elapsed/60).toFixed(1)}min`);

// ===== 重建计圈 (每1km) =====
const LAP_DIST = 1000;
const laps = [];
let cur = [], nb = LAP_DIST, base = mergedRecs[0]?.distance || 0;

function calcLapSummary(rs) {
  if (!rs.length) return null;
  const f=rs[0], l=rs[rs.length-1];
  const act=rs.filter(r=>r.speed>0||(r.heartRate!=null&&r.heartRate>0));
  const hrs=act.filter(r=>r.heartRate!=null).map(r=>r.heartRate);
  const spds=act.filter(r=>r.speed>0).map(r=>r.speed);
  const dist=(l.distance||0)-(f.distance||0);
  const el=(l.timestamp-f.timestamp)/1000;
  let t=0; for(let i=0;i<rs.length-1;i++) if(rs[i].speed>0||(rs[i].heartRate!=null&&rs[i].heartRate>0)) t+=(rs[i+1].timestamp-rs[i].timestamp)/1000;
  if(!t) t=el;
  
  // 从 records 中收集步态数据
  const vos=act.map(r=>r.verticalOscillation).filter(v=>v!=null);
  const sts=act.map(r=>r.stanceTime).filter(v=>v!=null);
  const vrs=act.map(r=>r.verticalRatio).filter(v=>v!=null);
  const sls=act.map(r=>r.stepLength).filter(v=>v!=null);
  const pwrs=act.map(r=>r.power).filter(v=>v!=null);
  
  return {timestamp:l.timestamp, startTime:f.timestamp, totalElapsedTime:el, totalTimerTime:t, totalDistance:dist,
    startPositionLat:f.positionLat, startPositionLong:f.positionLong,
    endPositionLat:l.positionLat, endPositionLong:l.positionLong,
    avgSpeed:t?dist/t:0, maxSpeed:spds.length?Math.max(...spds):undefined,
    avgHeartRate:hrs.length?Math.round(hrs.reduce((a,b)=>a+b,0)/hrs.length):undefined,
    maxHeartRate:hrs.length?Math.max(...hrs):undefined,
    avgVerticalOscillation:vos.length?Math.round(vos.reduce((a,b)=>a+b,0)/vos.length*10)/10:undefined,
    avgStanceTime:sts.length?Math.round(sts.reduce((a,b)=>a+b,0)/sts.length*10)/10:undefined,
    avgVerticalRatio:vrs.length?Math.round(vrs.reduce((a,b)=>a+b,0)/vrs.length*100)/100:undefined,
    avgStepLength:sls.length?Math.round(sls.reduce((a,b)=>a+b,0)/sls.length*10)/10:undefined,
    avgPower:pwrs.length?Math.round(pwrs.reduce((a,b)=>a+b,0)/pwrs.length):undefined,
    event:'lap', eventType:'stop', lapTrigger:'distance', sport:'running', subSport:'generic'};
}

for(const r of mergedRecs) {
  cur.push(r); const d=r.distance||0;
  while(d>=base+nb) {
    let idx=-1; for(let i=0;i<cur.length;i++) if((cur[i].distance||0)>=base+nb){idx=i;break;}
    if(idx<0) break;
    const lap=calcLapSummary(cur.slice(0,idx+1)); if(lap&&lap.totalDistance>0) laps.push(lap);
    cur=cur.slice(idx+1); nb+=LAP_DIST;
  }
}
if(cur.length&&cur.some(r=>r.speed>0||(r.heartRate!=null&&r.heartRate>0))&&td>0) {
  const ps=laps.reduce((s,l)=>s+l.totalDistance,0); const ld=td-ps;
  if(ld>0){const lap=calcLapSummary(cur);if(lap){lap.totalDistance=ld;if(lap.totalTimerTime)lap.avgSpeed=ld/lap.totalTimerTime;laps.push(lap);}}
}

console.log(`计圈: ${laps.length}`);

// ===== 从第一段文件提取原始 manufacturer/product =====
// 读取第一段文件的 file_id，继承设备信息，不写死品牌。
// 若原始 manufacturer 未知或不存在，用 0xFF (development)。
const firstFileId = segs[0]?.messages?.fileIdMesgs?.[0];
const origManufacturer = (firstFileId?.manufacturer != null && firstFileId.manufacturer !== 0xFF) ? firstFileId.manufacturer : 0xFF;
const origProduct = firstFileId?.product != null ? firstFileId.product : 0;
const origSerialNumber = firstFileId?.serialNumber != null ? firstFileId.serialNumber : 0;
const origProductName = firstFileId?.productName || '';

console.log(`原始设备: manufacturer=${origManufacturer} product=${origProduct} serial=${origSerialNumber}${origProductName ? ` name=${origProductName}` : ''}`);

// ===== 编码 =====
const enc = new Encoder();

// fileId — 从原始数据继承 manufacturer/product，不写死品牌
const fileIdMsg = {
  mesgNum: Profile.MesgNum.FILE_ID,
  type: 'activity',
  manufacturer: origManufacturer,
  serialNumber: origSerialNumber,
  product: origProduct,
  timeCreated: fR.timestamp,
};
if (origProductName) fileIdMsg.productName = origProductName;
enc.writeMesg(fileIdMsg);

// 设备信息 — 同 file_id
try {
  enc.writeMesg({
    mesgNum: Profile.MesgNum.DEVICE_INFO,
    timestamp: lR.timestamp,
    deviceIndex: 0,
    manufacturer: origManufacturer,
    serialNumber: origSerialNumber,
    product: origProduct,
    sourceType: 'local',
  });
} catch(e) { console.log('  device_info跳过:', e.message); }

// 文件创建者 + 设备设置 + 用户简档
try { enc.writeMesg({ mesgNum: Profile.MesgNum.FILE_CREATOR, softwareVersion: 2238 }); } catch(e) { console.log('  fileCreator跳过:', e.message); }
try { enc.writeMesg({ mesgNum: Profile.MesgNum.DEVICE_SETTINGS, activeTimeZone: 0, utcOffset: 0, timeOffset: [28800], timeMode: ['hour24'], backlightMode: 'autoBrightness', dateMode: 'monthDay', mountingSide: 'left' }); } catch(e) { console.log('  deviceSettings跳过:', e.message); }
try { enc.writeMesg({ mesgNum: Profile.MesgNum.USER_PROFILE, gender: 'male', age: 35, weight: 74, height: 1.77, weightSetting: 'metric', heightSetting: 'metric', distSetting: 'metric', restingHeartRate: 60 }); } catch(e) { console.log('  userProfile跳过:', e.message); }

// 运动类型
try { enc.writeMesg({ mesgNum: Profile.MesgNum.SPORT, sport: 'running', subSport: 'generic' }); } catch(e) { console.log('  sport跳过:', e.message); }

// timeInZone — 心率区间时间统计
for (const seg of segs) {
  for (const r of (seg.messages.timeInZoneMesgs || [])) {
    try { const d={mesgNum: Profile.MesgNum.TIME_IN_ZONE, ...r}; for(const k of Object.keys(d)) if(d[k]===undefined) delete d[k]; enc.writeMesg(d); } catch(e) {}
  }
}

enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, timestamp: fR.timestamp, event: 'timer', eventType: 'start', eventGroup: 0 });

for (const r of mergedRecs) {
  const d = { mesgNum: Profile.MesgNum.RECORD, timestamp: r.timestamp };
  // 写入所有 Profile 已知的非空字段
  const knownFields = ['positionLat', 'positionLong', 'heartRate', 'cadence', 'speed', 'distance', 'power', 'temperature',
    'enhancedSpeed', 'enhancedAltitude', 'cycleLength16', 'fractionalCadence', 'activityType',
    'verticalOscillation', 'stanceTime', 'verticalRatio', 'stepLength', 'stanceTimeBalance',
    'accumulatedPower', 'gpsAccuracy', 'leftRightBalance', 'grade', 'resistance',
    'compressedSpeedDistance', 'enhancedRespirationRate', 'respirationRate'];
  for (const k of knownFields) {
    if (r[k] != null) d[k] = r[k];
  }
  enc.writeMesg(d);
}

enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, timestamp: lR.timestamp, event: 'timer', eventType: 'stop', eventGroup: 0 });

// 写入所有计圈
for (const lap of laps) {
  const d = { mesgNum: Profile.MesgNum.LAP, ...lap };
  for (const k of Object.keys(d)) if (d[k] === undefined) delete d[k];
  enc.writeMesg(d);
}

// 从合并 records 计算步态和功率汇总
const vos = mergedRecs.filter(r => r.verticalOscillation != null).map(r => r.verticalOscillation);
const sts = mergedRecs.filter(r => r.stanceTime != null).map(r => r.stanceTime);
const vrs = mergedRecs.filter(r => r.verticalRatio != null).map(r => r.verticalRatio);
const sls = mergedRecs.filter(r => r.stepLength != null).map(r => r.stepLength);
const pws = mergedRecs.filter(r => r.power != null && r.power > 0).map(r => r.power);
const cads = mergedRecs.filter(r => r.cadence != null && r.cadence > 0).map(r => r.cadence);
const temps = mergedRecs.filter(r => r.temperature != null).map(r => r.temperature);

enc.writeMesg({ mesgNum: Profile.MesgNum.SESSION, timestamp: lR.timestamp, startTime: fR.timestamp,
  totalElapsedTime: elapsed, totalTimerTime: correctTimer, totalDistance: td,
  avgSpeed: correctTimer ? td / correctTimer : 0, maxSpeed: maxSpeed,
  enhancedAvgSpeed: correctTimer ? td / correctTimer : 0, enhancedMaxSpeed: maxSpeed,
  avgHeartRate: avgHr, maxHeartRate: maxHr,
  totalCalories: cal, totalAscent: Math.round(correctAscent), totalDescent: Math.round(correctDescent),
  numLaps: laps.length, sport: 'running', subSport: 'generic', trigger: 'activityEnd',
  event: 'session', eventType: 'stop',
  totalStrides: cads.length,
  avgCadence: cads.length ? Math.round(cads.reduce((a,b)=>a+b,0)/cads.length) : undefined,
  maxCadence: cads.length ? Math.max(...cads) : undefined,
  avgRunningCadence: cads.length ? Math.round(cads.reduce((a,b)=>a+b,0)/cads.length) : undefined,
  maxRunningCadence: cads.length ? Math.max(...cads) : undefined,
  avgPower: pws.length ? Math.round(pws.reduce((a,b)=>a+b,0)/pws.length) : undefined,
  maxPower: pws.length ? Math.max(...pws) : undefined,
  avgVerticalOscillation: vos.length ? Math.round(vos.reduce((a,b)=>a+b,0)/vos.length*10)/10 : undefined,
  avgStanceTime: sts.length ? Math.round(sts.reduce((a,b)=>a+b,0)/sts.length*10)/10 : undefined,
  avgVerticalRatio: vrs.length ? Math.round(vrs.reduce((a,b)=>a+b,0)/vrs.length*100)/100 : undefined,
  avgStepLength: sls.length ? Math.round(sls.reduce((a,b)=>a+b,0)/sls.length*10)/10 : undefined,
  avgTemperature: temps.length ? Math.round(temps.reduce((a,b)=>a+b,0)/temps.length) : undefined,
  totalTrainingEffect: 4.2,
  totalAnaerobicTrainingEffect: 1.1 });

enc.writeMesg({ mesgNum: Profile.MesgNum.ACTIVITY, timestamp: lR.timestamp,
  localTimestamp: Math.round(lR.timestamp.getTime() / 1000 + 28800),
  numSessions: 1, type: 'manual', event: 'activity', eventType: 'stop', eventGroup: 0 });

const buf = enc.close();

// 验证
const vs = Stream.fromBuffer(buf);
const vd = new Decoder(vs);
console.log(`\nisFIT: ${vd.isFIT()} | checkIntegrity: ${vd.checkIntegrity()}`);
console.log(`大小: ${(buf.length/1024).toFixed(0)}KB`);

const {messages} = vd.read({includeUnknownData: true, expandSubFields: true, convertTypesToStrings: true, mergeHeartRates: true});
const s = messages.sessionMesgs?.[0];
if (s) {
  const p = s.avgSpeed ? (1000/(s.avgSpeed*60)).toFixed(1) : '?';
  console.log(`\nSession: ${(s.totalDistance/1000).toFixed(2)}km | ${(s.totalTimerTime/60).toFixed(1)}min | ${p}min/km`);
  console.log(`HR: ${s.avgHeartRate}/${s.maxHeartRate} | ${s.totalCalories}kcal | ascent=${s.totalAscent}/${s.totalDescent}`);
}

console.log(`\n协议: protocol=${buf[1]} profile=${(buf[2] | buf[3] << 8)} fCount=${buf[14+5]}`);

const outPath = './merged_activity_fixed.fit';  // 输出路径（可修改）
// Uint8Array 不能直接 fs.writeFileSync，转成 Buffer
const outBuf = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
fs.writeFileSync(outPath, outBuf);
console.log(`\n✅ 输出: ${outPath}`);
