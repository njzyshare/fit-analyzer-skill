#!/usr/bin/env node
// 把任意第三方手表产出的 FIT 改写为「指定 COROS 参考设备」身份。
// 设备信息（file_id + device_info）从参考 COROS 文件（如 26.7.fit）读取，
// 其余全部原始数据（record/lap/session/event/开发者私有字段）原样保留。
//
// 关键：COROS 的 device_info 是非标准布局——product 字段(2) 放 294(coros 厂商码)，
// 没有 manufacturer(1) 字段，只有 product(2)+product_name(27)+timestamp(253)。
// 因此不能写 manufacturer，否则 SDK 会加出 field 1 破坏 COROS 解析。
//
// 用法: node inject_coros.mjs <源.fit> <参考COROS.fit> <输出.fit>

import { Decoder, Encoder, Stream, Profile } from '@garmin/fitsdk';
import fs from 'fs';

const [srcFit, refFit, outFit] = process.argv.slice(2);
if (!srcFit || !refFit || !outFit) {
  console.error('用法: node inject_coros.mjs <源.fit> <参考COROS.fit> <输出.fit>');
  process.exit(1);
}

const COROS_VENDOR = 294; // coros 厂商码，放在 device_info 的 product 字段(2)

// ---- 读取参考 COROS 设备身份 ----
const rb = new Uint8Array(fs.readFileSync(refFit));
const rdec = new Decoder(Stream.fromBuffer(rb)).read({});
const rFid = rdec.messages.fileIdMesgs[0].fields || rdec.messages.fileIdMesgs[0];
const rDev = (rdec.messages.deviceInfoMesgs || [])[0] || {};
const rDevF = rDev.fields || rDev;

const corosManufacturer = rFid.manufacturer && rFid.manufacturer !== 'coros' ? rFid.manufacturer : 'coros';
const corosProduct = rFid.product ?? 814;            // 机型码 (APEX 4 42mm = 814)
const corosProductName = rFid.productName || 'COROS APEX 4 42mm';

console.log(`参考设备: manufacturer=${corosManufacturer} product=${corosProduct} name=${corosProductName}`);

// ---- 读取源文件 ----
const bytes = new Uint8Array(fs.readFileSync(srcFit));
const { messages, errors } = new Decoder(Stream.fromBuffer(bytes)).read({});
if (errors.length) console.error('decode warnings:', errors.slice(0, 3));

// 保留开发者私有字段（高驰 Effort Pace / 佳明开发者字段等）
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

// file_id -> COROS 身份（保留原始 timeCreated）
enc.writeMesg({
  mesgNum: Profile.MesgNum.FILE_ID,
  type: fidF.type || 'activity',
  manufacturer: corosManufacturer,
  product: corosProduct,
  timeCreated: fidF.timeCreated,
  productName: corosProductName,
});

// 开发者字段定义（必须在 record 之前）
for (const d of devDataIds) { const o = { mesgNum: Profile.MesgNum.DEVELOPER_DATA_ID, ...d }; delete o.key; enc.writeMesg(o); }
for (const f of fieldDescs) { const o = { mesgNum: Profile.MesgNum.FIELD_DESCRIPTION, ...f }; delete o.key; enc.writeMesg(o); }

// device_info -> 仅 3 字段：timestamp + product(=294) + product_name。绝不写 manufacturer。
enc.writeMesg({
  mesgNum: Profile.MesgNum.DEVICE_INFO,
  timestamp: fidF.timeCreated,
  product: COROS_VENDOR,
  productName: corosProductName,
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
if (!ok) throw new Error('integrity 校验失败');
const m2 = d2.read({}).messages;
const oFid = m2.fileIdMesgs[0].fields || m2.fileIdMesgs[0];
console.log(`  file_id: ${oFid.manufacturer}/${oFid.productName} product=${oFid.product}`);
const devs = (m2.deviceInfoMesgs || []).map(x => { const f = x.fields || x; return { manufacturer: f.manufacturer, product: f.product, productName: f.productName }; });
console.log(`  device_info: ${JSON.stringify(devs)}`);

function strip(m) { const o = { ...m }; delete o.mesgNum; return o; }
