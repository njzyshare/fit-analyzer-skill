#!/usr/bin/env node
// 为 FIT 文件注入「高驰设备信息」，其余数据全部原样保留。
//
// 本脚本由 inject_garmin_device.mjs 照搬而来，仅把目标设备身份从佳明换成高驰：
//   - file_id / device_info 的 manufacturer 改为 coros
//   - product 改为 814（APEX 4）
//   - product_name 改为 "COROS APEX 4 42mm"
//   - 不写 serialNumber（高驰不存序列号）
// 重编码流程、私有开发者字段保留、消息重写顺序、integrity 校验等，全部与原脚本一致。
//
// 工作流（与原脚本同形）：
//   node scripts/inject_coros_device.mjs apply 输入.fit [--out 输出.fit]
//   node scripts/inject_coros_device.mjs apply 输入.fit --name "COROS APEX 4 46mm" --product 815
//
// 说明：apply 全量重编码——保留全部原始数据（含第三方私有开发者字段），
// 仅替换 file_id 设备身份、并把 device_info 改为单条高驰设备（删掉原 device_info）。

import { Decoder, Encoder, Stream, Profile } from '@garmin/fitsdk';
import fs from 'fs';

// 高驰身份默认值（对着真实高驰 APEX 4 记录观测所得）
const COROS_DEFAULT = {
  manufacturer: 'coros',        // 294
  product: 814,                 // APEX 4
  productName: 'COROS APEX 4 42mm',
};

// 把高驰设备信息应用到 FIT（保留全部原始数据含私有 dev 字段，删掉原 device_info）
function applyCorosDevice(srcFit, outFit, opts = {}) {
  const dev = {
    manufacturer: opts.manufacturer ?? COROS_DEFAULT.manufacturer,
    product: opts.product ?? COROS_DEFAULT.product,
    productName: opts.name ?? COROS_DEFAULT.productName,
  };
  // 高驰不存序列号，因此这里没有 serialNumber 校验（与佳明版唯一的行为差异）

  const bytes = new Uint8Array(fs.readFileSync(srcFit));
  const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
  if (errors.length) console.error('decode warnings:', errors.slice(0, 3));

  // 保留开发者字段（高驰 Effort Pace 等私有字段）
  const devDataIds = messages.developerDataIdMesgs || [];
  const fieldDescs = messages.fieldDescriptionMesgs || [];
  const fieldDescriptions = {};
  for (const fd of fieldDescs) {
    const k = fd.key != null ? fd.key : fd.fieldDefinitionNumber;
    const did = devDataIds[fd.developerDataIndex] || devDataIds[0];
    fieldDescriptions[k] = { developerDataIdMesg: did, fieldDescriptionMesg: fd };
  }
  const enc = new Encoder({ fieldDescriptions });

  const fid = messages.fileIdMesgs[0];
  const fidF = fid.fields || fid;
  // file_id -> 高驰设备
  enc.writeMesg({
    mesgNum: Profile.MesgNum.FILE_ID,
    type: fidF.type || 'activity',
    manufacturer: dev.manufacturer,
    product: dev.product,
    timeCreated: fidF.timeCreated,
    productName: dev.productName,
  });

  // 开发者字段描述（必须在 record 之前）
  for (const d of devDataIds) { const o = { mesgNum: Profile.MesgNum.DEVELOPER_DATA_ID, ...d }; delete o.key; enc.writeMesg(o); }
  for (const f of fieldDescs) { const o = { mesgNum: Profile.MesgNum.FIELD_DESCRIPTION, ...f }; delete o.key; enc.writeMesg(o); }

  // device_info：仅写一条高驰（删掉原 device_info）
  enc.writeMesg({
    mesgNum: Profile.MesgNum.DEVICE_INFO,
    timestamp: fidF.timeCreated,
    deviceIndex: 0,
    manufacturer: dev.manufacturer,
    product: dev.product,
    sourceType: 'local',
    productName: dev.productName,
  });

  // 其余消息原样重写
  const evs = messages.eventMesgs || [];
  const startEv = evs.find(e => e.event === 'timer' && e.eventType === 'start');
  const stopEv = evs.find(e => e.event === 'timer' && e.eventType === 'stop');
  const lapEvs = evs.filter(e => e.event === 'lap');
  const otherEvs = evs.filter(e => !(e.event === 'timer' && (e.eventType === 'start' || e.eventType === 'stop')) && e.event !== 'lap');
  if (startEv) enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, ...strip(startEv) });
  for (const r of (messages.recordMesgs || [])) enc.writeMesg({ mesgNum: Profile.MesgNum.RECORD, ...r });
  const laps = messages.lapMesgs || [];
  for (let i = 0; i < laps.length; i++) {
    if (lapEvs[i]) enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, ...strip(lapEvs[i]) });
    enc.writeMesg({ mesgNum: Profile.MesgNum.LAP, ...laps[i] });
  }
  for (const e of otherEvs) enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, ...strip(e) });
  if (stopEv) enc.writeMesg({ mesgNum: Profile.MesgNum.EVENT, ...strip(stopEv) });
  for (const s of (messages.sessionMesgs || [])) enc.writeMesg({ mesgNum: Profile.MesgNum.SESSION, ...s });
  for (const a of (messages.activityMesgs || [])) enc.writeMesg({ mesgNum: Profile.MesgNum.ACTIVITY, ...a });

  const outBuf = enc.close();
  fs.writeFileSync(outFit, Buffer.from(outBuf));

  // 校验
  const d2 = new Decoder(Stream.fromBuffer(outBuf));
  const ok = d2.checkIntegrity();
  console.log(`已生成 ${outFit} (${outBuf.length} bytes), integrity=${ok}`);
  if (!ok) throw new Error('integrity 校验失败，文件可能损坏');
  const m2 = d2.read({}).messages;
  const outFid = m2.fileIdMesgs[0].fields || m2.fileIdMesgs[0];
  console.log(`  file_id: ${outFid.manufacturer}/${outFid.product} "${outFid.productName}"`);
  const devs = (m2.deviceInfoMesgs || []).map(x => { const f = x.fields || x; return `${f.manufacturer}/${f.productName}`; });
  console.log(`  device_info: ${devs.length} 条 ${JSON.stringify(devs)}`);
  const s0 = m2.sessionMesgs[0].fields || m2.sessionMesgs[0];
  console.log(`  数据保留核对: 距离=${s0.totalDistance} 计时=${s0.totalTimerTime} 爬升/下降=${s0.totalAscent}/${s0.totalDescent} 心率=${s0.avgHeartRate}/${s0.maxHeartRate}`);
  console.log(`  record=${(m2.recordMesgs || []).length}  lap=${(m2.lapMesgs || []).length}`);
}

function strip(m) { const o = { ...m }; delete o.mesgNum; return o; }

// ---- CLI ----
const [mode, arg1, ...rest] = process.argv.slice(2);
const getOpt = (name) => { const i = rest.indexOf(name); return i >= 0 ? rest[i + 1] : undefined; };

try {
  if (mode === 'apply') {
    if (!arg1) throw new Error('apply 需要源 .fit 路径');
    const out = getOpt('--out') || arg1.replace(/\.fit$/i, '_coros.fit');
    applyCorosDevice(arg1, out, {
      name: getOpt('--name'),
      product: getOpt('--product') ? Number(getOpt('--product')) : undefined,
      manufacturer: getOpt('--manufacturer'),
    });
  } else {
    console.log(`用法:
  apply <输入.fit> [--out 输出.fit] [--name "COROS APEX 4 42mm"] [--product 814]

说明：只改设备信息（file_id + device_info），其余数据原样保留。
默认身份: coros / 814 / "COROS APEX 4 42mm"`);
  }
} catch (e) {
  console.error('错误:', e.message);
  process.exit(1);
}
