#!/usr/bin/env node
// 从两个原始 COROS 文件直接合并：保留各自源生 lap 消息（只重编号+平移时间戳+保持连续距离），
// 协议字节改回 COROS 原生 0x20，整体时间戳向前+60s。规避 regenerate_laps 重算 lap 导致 COROS 不认的问题。
import { Decoder, Encoder, Stream, Profile } from '@garmin/fitsdk';
import CrcCalculator from '@garmin/fitsdk/src/crc-calculator.js';
import fs from 'fs';

const SRC1 = process.argv[2];
const SRC2 = process.argv[3];
const OUT = process.argv[4] || 'merged_preserve.fit';
const GLOBAL_SHIFT = (Number(process.argv[5] ?? 60)) * 1000; // ms，向前1分钟

function shiftObj(o, delta) {
  const out = {};
  for (const k of Object.keys(o)) {
    let v = o[k];
    if ((k === 'timestamp' || k === 'timeCreated' || k === 'startTime') && v instanceof Date) {
      v = new Date(v.getTime() + delta);
    }
    out[k] = v;
  }
  return out;
}
function strip(o){ const c = {...o}; delete c.mesgNum; delete c.fields; delete c.key; return c; }

function decode(IN){
  const bytes = new Uint8Array(fs.readFileSync(IN));
  const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
  if (errors.length) console.error('decode warnings', IN, errors.slice(0,3));
  return messages;
}
const s1 = decode(SRC1), s2 = decode(SRC2);

// delta for activity2: 与段1同样平移 +60s，保留原始段间断开(约4分钟)作为暂停
const recs1 = (s1.recordMesgs||[]).map(r=>r.fields||r).sort((a,b)=>a.timestamp-b.timestamp);
const recs2 = (s2.recordMesgs||[]).map(r=>r.fields||r).sort((a,b)=>a.timestamp-b.timestamp);
const last1 = recs1[recs1.length-1].timestamp;
const first2 = recs2[0].timestamp;
const delta2 = GLOBAL_SHIFT;
console.log(`GLOBAL_SHIFT=${GLOBAL_SHIFT}ms  delta2=${delta2}ms (${(delta2/1000).toFixed(0)}s) 段间断开保留≈${((first2.getTime()-last1.getTime())/1000).toFixed(0)}s`);

// developer field descriptions
const devIds1 = s1.developerDataIdMesgs||[];
const fds1 = s1.fieldDescriptionMesgs||[];
const fieldDescriptions = {};
for (const fd of fds1){
  const k = fd.key!=null?fd.key:fd.fieldDefinitionNumber;
  const did = devIds1[fd.developerDataIndex]||devIds1[0];
  fieldDescriptions[k] = { developerDataIdMesg: did, fieldDescriptionMesg: fd };
}
const enc = new Encoder({ fieldDescriptions });

// file_id (src1) +60s
const fid = s1.fileIdMesgs[0]; const fidF = fid.fields||fid;
enc.writeMesg({ mesgNum: Profile.MesgNum.FILE_ID, ...shiftObj(strip(fidF), GLOBAL_SHIFT) });
// developer data id + field desc (before records)
for (const d of devIds1) enc.writeMesg({ mesgNum: Profile.MesgNum.DEVELOPER_DATA_ID, ...strip(d) });
for (const f of fds1) enc.writeMesg({ mesgNum: Profile.MesgNum.FIELD_DESCRIPTION, ...strip(f) });
// device_info (src1) +60s
const dev0 = (s1.deviceInfoMesgs||[])[0];
if (dev0) enc.writeMesg({ mesgNum: Profile.MesgNum.DEVICE_INFO, ...shiftObj(strip(dev0.fields||dev0), GLOBAL_SHIFT) });

// records + events interleaved by final timestamp
// activity2 的 record 距离必须整体 +活动1总距，否则拼接处距离从 26726 重置回 0（断层）
const a1Dist = recs1.length ? (recs1[recs1.length-1].distance || (sf.totalDistance||0)) : (sf.totalDistance||0);
const stream = [];
for (const r of (s1.recordMesgs||[])) stream.push({ts:(r.timestamp?r.timestamp.getTime():0)+GLOBAL_SHIFT, kind:'r', m:r, dOff:0});
for (const r of (s2.recordMesgs||[])) stream.push({ts:(r.timestamp?r.timestamp.getTime():0)+delta2, kind:'r', m:r, dOff:a1Dist});
for (const e of (s1.eventMesgs||[])) stream.push({ts:(e.timestamp?e.timestamp.getTime():0)+GLOBAL_SHIFT, kind:'e', m:e, dOff:0});
for (const e of (s2.eventMesgs||[])) stream.push({ts:(e.timestamp?e.timestamp.getTime():0)+delta2, kind:'e', m:e, dOff:0});
stream.sort((a,b)=>a.ts-b.ts);
for (const x of stream){
  const shifted = shiftObj(strip(x.m), x.ts - (x.m.timestamp?x.m.timestamp.getTime():0));
  if (x.kind==='r' && x.dOff){
    if (shifted.distance!=null) shifted.distance += x.dOff;
    if (shifted.enhancedDistance!=null) shifted.enhancedDistance += x.dOff;
  }
  const mn = x.kind==='r' ? Profile.MesgNum.RECORD : Profile.MesgNum.EVENT;
  enc.writeMesg({ mesgNum: mn, ...shifted });
}

// laps: src1 原样(+60s, messageIndex 0..n-1); src2 重编号 27.. + delta2
const laps1 = s1.lapMesgs||[];
const laps2 = s2.lapMesgs||[];
for (const l of laps1) enc.writeMesg({ mesgNum: Profile.MesgNum.LAP, ...shiftObj(strip(l), GLOBAL_SHIFT) });
for (const l of laps2){
  const c = strip(l);
  const f = l.fields||l;
  if (f.messageIndex!=null) c.messageIndex = f.messageIndex + laps1.length;
  enc.writeMesg({ mesgNum: Profile.MesgNum.LAP, ...shiftObj(c, delta2) });
}

// session: 复制 src1，修正总计 + 起止时间
const sess1 = s1.sessionMesgs[0]; const sf = sess1.fields||sess1;
const sess2 = s2.sessionMesgs[0]; const s2f = sess2.fields||sess2;
const lastRec2 = recs2[recs2.length-1].timestamp.getTime() + delta2;
const firstRec1 = recs1[0].timestamp.getTime() + GLOBAL_SHIFT;
const newSess = { ...strip(sf) };
newSess.startTime = new Date(firstRec1);
newSess.timestamp = new Date(lastRec2);
newSess.totalDistance = (sf.totalDistance||0) + (s2f.totalDistance||0);
newSess.totalTimerTime = (sf.totalTimerTime||0) + (s2f.totalTimerTime||0);
newSess.totalElapsedTime = (lastRec2 - firstRec1)/1000;
newSess.totalAscent = (sf.totalAscent||0) + (s2f.totalAscent||0);
newSess.totalDescent = (sf.totalDescent||0) + (s2f.totalDescent||0);
newSess.totalCalories = (sf.totalCalories||0) + (s2f.totalCalories||0);
newSess.maxHeartRate = Math.max(sf.maxHeartRate||0, s2f.maxHeartRate||0);
newSess.minHeartRate = Math.min(sf.minHeartRate||999, s2f.minHeartRate||999);
newSess.totalCycles = (sf.totalCycles||0) + (s2f.totalCycles||0);
newSess.totalStrides = (sf.totalStrides||0) + (s2f.totalStrides||0);
enc.writeMesg({ mesgNum: Profile.MesgNum.SESSION, ...newSess });

// activity (src1) +60s
for (const a of (s1.activityMesgs||[])) enc.writeMesg({ mesgNum: Profile.MesgNum.ACTIVITY, ...shiftObj(strip(a), GLOBAL_SHIFT) });

let outBuf = Buffer.from(enc.close());
// 协议字节改回 COROS 原生 0x20：必须同时重算 header CRC(字节0-11→存12-13) 与 file CRC
if (process.env.PROTO20 === '1') {
  outBuf[1] = 0x20;
  const headerCrc = CrcCalculator.calculateCRC(outBuf, 0, 12);
  outBuf[12] = headerCrc & 0xff;
  outBuf[13] = (headerCrc >> 8) & 0xff;
  const fileCrc = CrcCalculator.calculateCRC(outBuf, 0, outBuf.length - 2);
  outBuf[outBuf.length-2] = fileCrc & 0xff;
  outBuf[outBuf.length-1] = (fileCrc >> 8) & 0xff;
}
fs.writeFileSync(OUT, outBuf);

const d2 = new Decoder(Stream.fromBuffer(outBuf));
const ok = d2.checkIntegrity();
console.log(`已生成 ${OUT} (${outBuf.length} bytes) proto=0x${outBuf[1].toString(16)} integrity=${ok}`);
if(!ok) throw new Error('integrity 失败');
const m2 = d2.read({}).messages;
const s0 = m2.sessionMesgs[0].fields||m2.sessionMesgs[0];
const laps = m2.lapMesgs||[];
console.log(`  session.start(UTC+8)= ${new Date(s0.startTime.getTime()+8*3600*1000).toISOString().slice(0,19).replace('T',' ')}`);
console.log(`  laps=${laps.length} records=${(m2.recordMesgs||[]).length} events=${(m2.eventMesgs||[]).length}`);
console.log(`  lap5.dist=${laps[4]?(laps[4].fields||laps[4]).totalDistance:'?'} lastLap.dist=${laps.length?(laps[laps.length-1].fields||laps[laps.length-1]).totalDistance:'?'}`);
