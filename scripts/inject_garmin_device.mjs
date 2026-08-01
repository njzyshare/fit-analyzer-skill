#!/usr/bin/env node
// 为第三方手表（高驰/华为/颂拓等）产出的 FIT 注入「真实佳明设备信息」，
// 让 Garmin Connect 识别为带气压计的佳明设备，从而关闭高程校正、不再重算爬升。
//
// 关键：设备信息来自【私人数据区域】，绝不写死在脚本里。
// 私人数据文件默认：~/.workbuddy/private/garmin_devices.json
//   （可用环境变量 GARMIN_DEVICES_JSON 覆盖路径）
//
// 工作流：
//   1) extract：从你自己的真实佳明活动 .fit 抽取设备信息，存入私人区域
//      node scripts/inject_garmin_device.mjs extract 真实佳明.fit --name fenix8
//   2) apply：把私人区域里的设备信息应用到任意第三方 FIT
//      node scripts/inject_garmin_device.mjs apply 第三方.fit --device fenix8 --out 第三方_fenix8.fit
//
// 原理（已实测）：Garmin Connect 对上传文件做服务端校验 (product, UnitID) 是否匹配真实佳明设备；
// 不匹配则显示「未知设备」且可能照常重算海拔。同时，设备是否带气压高度计决定高程校正开关
// （带气压计→校正默认关、用设备记录海拔；不带→用 DEM 地形数据替换每个轨迹点=二次加工爬升）。
// 因此注入「真实佳明带气压计设备」信息即可彻底解决。

import { Decoder, Encoder, Stream, Profile } from '@garmin/fitsdk';
import fs from 'fs';
import os from 'os';
import path from 'path';

const DEFAULT_STORE = path.join(os.homedir(), '.workbuddy', 'private', 'garmin_devices.json');
const storePath = () => process.env.GARMIN_DEVICES_JSON || DEFAULT_STORE;

function loadStore() {
  const p = storePath();
  if (!fs.existsSync(p)) return { devices: {}, default: null };
  try { return JSON.parse(fs.readFileSync(p, 'utf8')); }
  catch (e) { throw new Error(`私人设备文件解析失败 ${p}: ${e.message}`); }
}
function saveStore(obj) {
  const p = storePath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(obj, null, 2));
  console.log(`已写入私人设备文件: ${p}`);
}

// 从真实佳明活动抽取主设备信息
function readDeviceFromFit(fitPath) {
  const bytes = new Uint8Array(fs.readFileSync(fitPath));
  const { messages } = new Decoder(Stream.fromBuffer(bytes)).read({});
  const fid = messages.fileIdMesgs[0].fields || messages.fileIdMesgs[0];
  // 主设备：sourceType=local 且 manufacturer=garmin 的 device_info
  let dev = (messages.deviceInfoMesgs || [])
    .map(m => m.fields || m)
    .find(f => f.sourceType === 'local' && (f.manufacturer === 'garmin' || f.manufacturer === 1));
  if (!dev) dev = (messages.deviceInfoMesgs || [])[0]?.fields || {};
  return {
    manufacturer: (fid.manufacturer === 'garmin' || fid.manufacturer === 1) ? 'garmin' : fid.manufacturer,
    product: fid.product ?? dev.product,
    productName: fid.productName || dev.productName || 'fenix 8',
    serialNumber: fid.serialNumber ?? dev.serialNumber,
    softwareVersion: dev.softwareVersion ?? 0,
    hardwareVersion: dev.hardwareVersion ?? 0,
  };
}

// 把私人区域里的设备信息应用到第三方 FIT（保留全部原始数据含私有 dev 字段，删掉原第三方 device_info）
function applyDevice(srcFit, key, outFit) {
  const store = loadStore();
  const dev = store.devices?.[key] || store[key];
  if (!dev) throw new Error(`私人设备文件中找不到设备 "${key}"。可用: ${Object.keys(store.devices || {}).join(', ') || '(空)'}。先运行 extract。`);
  if (!dev.serialNumber) throw new Error(`设备 "${key}" 缺少 serialNumber(Unit ID)，无法让 Connect 正确识别。`);

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
  // file_id -> 真实佳明设备
  enc.writeMesg({
    mesgNum: Profile.MesgNum.FILE_ID,
    type: fidF.type || 'activity',
    manufacturer: dev.manufacturer,
    product: dev.product,
    serialNumber: dev.serialNumber,
    timeCreated: fidF.timeCreated,
    productName: dev.productName,
  });

  // 开发者字段描述（必须在 record 之前）
  for (const d of devDataIds) { const o = { mesgNum: Profile.MesgNum.DEVELOPER_DATA_ID, ...d }; delete o.key; enc.writeMesg(o); }
  for (const f of fieldDescs) { const o = { mesgNum: Profile.MesgNum.FIELD_DESCRIPTION, ...f }; delete o.key; enc.writeMesg(o); }

  // device_info：仅写一条佳明（删掉第三方原 device_info）
  enc.writeMesg({
    mesgNum: Profile.MesgNum.DEVICE_INFO,
    timestamp: fidF.timeCreated,
    deviceIndex: 0,
    manufacturer: dev.manufacturer,
    product: dev.product,
    serialNumber: dev.serialNumber,
    sourceType: 'local',
    productName: dev.productName,
    ...(dev.softwareVersion ? { softwareVersion: dev.softwareVersion } : {}),
    ...(dev.hardwareVersion ? { hardwareVersion: dev.hardwareVersion } : {}),
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
  console.log(`  file_id: ${outFid.manufacturer}/${outFid.productName} sn=${outFid.serialNumber}`);
  const devs = (m2.deviceInfoMesgs || []).map(x => { const f = x.fields || x; return `${f.manufacturer}/${f.productName}`; });
  console.log(`  device_info: ${JSON.stringify(devs)}`);
  const s0 = m2.sessionMesgs[0].fields || m2.sessionMesgs[0];
  console.log(`  爬升 ascent/descent 保留: ${s0.totalAscent}/${s0.totalDescent}`);
}

function strip(m) { const o = { ...m }; delete o.mesgNum; return o; }

// ---- CLI ----
const [mode, arg1, ...rest] = process.argv.slice(2);
const getOpt = (name) => { const i = rest.indexOf(name); return i >= 0 ? rest[i + 1] : undefined; };

try {
  if (mode === 'extract') {
    if (!arg1) throw new Error('extract 需要真实佳明 .fit 路径');
    const key = getOpt('--name') || 'garmin';
    const dev = readDeviceFromFit(arg1);
    const store = loadStore();
    store.devices = store.devices || {};
    store.devices[key] = dev;
    if (!store.default) store.default = key;
    saveStore(store);
    console.log(`设备 "${key}" 已提取:`, JSON.stringify(dev));
  } else if (mode === 'apply') {
    if (!arg1) throw new Error('apply 需要源 .fit 路径');
    const store = loadStore();
    const key = getOpt('--device') || store.default || 'garmin';
    const out = getOpt('--out') || arg1.replace(/\.fit$/i, '_fenix8.fit');
    applyDevice(arg1, key, out);
  } else {
    console.log(`用法:
  extract <真实佳明.fit> [--name fenix8]           从真实佳明活动抽取设备信息，存入私人区域
  apply   <第三方.fit> [--device fenix8] [--out 输出.fit]   注入设备信息到第三方 FIT

私人设备文件: ${storePath()}
（路径可用环境变量 GARMIN_DEVICES_JSON 覆盖）`);
  }
} catch (e) {
  console.error('错误:', e.message);
  process.exit(1);
}
