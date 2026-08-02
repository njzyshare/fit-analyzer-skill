#!/usr/bin/env node
// 用 @garmin/fitsdk 解码 -> 整体平移时间戳 -> 重编码（保真：保留全部原始数据 +
// 开发者私有字段 + 已注入的佳明设备信息）。解决 fit_shift_time.py 在含压缩时间戳
// 消息的 SDK 重编码文件上 desync 的问题。
import { Decoder, Encoder, Stream, Profile } from '@garmin/fitsdk';
import fs from 'fs';

const IN = process.argv[2];
const OUT = process.argv[3] || IN.replace(/\.fit$/i, '_morning.fit');
const delta = Number(process.argv[4] ?? -12) * 3600; // 小时，负=往前

function shiftObj(o, delta) {
  const out = {};
  for (const k of Object.keys(o)) {
    let v = o[k];
    if ((k === 'timestamp' || k === 'timeCreated' || k === 'startTime') && v instanceof Date) {
      v = new Date(v.getTime() + delta * 1000);
    }
    out[k] = v;
  }
  return out;
}
function strip(o) {
  const c = { ...o };
  delete c.mesgNum; delete c.fields; delete c.key;
  return c;
}

const bytes = new Uint8Array(fs.readFileSync(IN));
const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
if (errors.length) console.error('decode warnings:', errors.slice(0, 3));

const devDataIds = messages.developerDataIdMesgs || [];
const fieldDescs = messages.fieldDescriptionMesgs || [];
const fieldDescriptions = {};
for (const fd of fieldDescs) {
  const k = fd.key != null ? fd.key : fd.fieldDefinitionNumber;
  const did = devDataIds[fd.developerDataIndex] || devDataIds[0];
  fieldDescriptions[k] = { developerDataIdMesg: did, fieldDescriptionMesg: fd };
}
const enc = new Encoder({ fieldDescriptions });

// file_id
const fid = messages.fileIdMesgs[0];
const fidF = fid.fields || fid;
enc.writeMesg({ mesgNum: Profile.MesgNum.FILE_ID, ...shiftObj(strip(fidF), delta) });

// 开发者字段描述（必须在 record 前）
for (const d of devDataIds) enc.writeMesg({ mesgNum: Profile.MesgNum.DEVELOPER_DATA_ID, ...strip(d) });
for (const f of fieldDescs) enc.writeMesg({ mesgNum: Profile.MesgNum.FIELD_DESCRIPTION, ...strip(f) });

// device_info：保留源文件里的（已是 fenix8），平移 timestamp
const dev0 = (messages.deviceInfoMesgs || [])[0];
if (dev0) enc.writeMesg({ mesgNum: Profile.MesgNum.DEVICE_INFO, ...shiftObj(strip(dev0.fields || dev0), delta) });

// records + events interleaved by timestamp — 保留全部事件（含全部暂停/恢复），
// 不能只留首条 start/stop，否则 COROS 丢失暂停信息导致配速折线骤降、每圈配速错。
const recs = (messages.recordMesgs || []).map(r => ({
  ts: (r.timestamp instanceof Date) ? r.timestamp.getTime() : 0,
  type: 'r', m: r
}));
const evts = (messages.eventMesgs || []).map(e => ({
  ts: (e.timestamp instanceof Date) ? e.timestamp.getTime() : 0,
  type: 'e', m: e
}));
const stream = [...recs, ...evts].sort((a, b) => a.ts - b.ts);
for (const x of stream) {
  if (x.type === 'r') {
    enc.writeMesg({ mesgNum: Profile.MesgNum.RECORD, ...shiftObj(strip(x.m), delta) });
  } else {
    enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, ...shiftObj(strip(x.m), delta) });
  }
}

// laps
const laps = messages.lapMesgs || [];
for (let i = 0; i < laps.length; i++) {
  enc.writeMesg({ mesgNum: Profile.MesgNum.LAP, ...shiftObj(strip(laps[i]), delta) });
}

// session / activity
for (const s of (messages.sessionMesgs || [])) enc.writeMesg({ mesgNum: Profile.MesgNum.SESSION, ...shiftObj(strip(s), delta) });
for (const a of (messages.activityMesgs || [])) enc.writeMesg({ mesgNum: Profile.MesgNum.ACTIVITY, ...shiftObj(strip(a), delta) });

const outBuf = enc.close();
fs.writeFileSync(OUT, Buffer.from(outBuf));

const d2 = new Decoder(Stream.fromBuffer(outBuf));
const ok = d2.checkIntegrity();
console.log(`已生成 ${OUT} (${outBuf.length} bytes), integrity=${ok}`);
if (!ok) throw new Error('integrity 校验失败');
const m2 = d2.read({}).messages;
const s0 = m2.sessionMesgs[0].fields || m2.sessionMesgs[0];
console.log(`  新 session.start_time(UTC+8): ${new Date(s0.startTime.getTime() + 8*3600*1000).toLocaleString('sv')}`);
console.log(`  爬升 保留: ${s0.totalAscent}/${s0.totalDescent}`);
console.log(`  device_info: ${JSON.stringify((m2.deviceInfoMesgs||[]).map(x=>{const f=x.fields||x;return f.manufacturer+'/'+f.productName;}))}`);
console.log(`  records: ${(m2.recordMesgs||[]).length}, laps: ${(m2.lapMesgs||[]).length}`);
