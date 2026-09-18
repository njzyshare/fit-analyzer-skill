// 从 @garmin/fitsdk 导出 FIT 官方 profile 为 JSON（权威定义源）。
//
// 为什么必须有这个脚本：
//   官方 profile 里每个字段有两层类型信息：
//     - `type`     ：逻辑类型名（如 "file" / "manufacturer" / "date_time" / "sint32"）
//     - `baseType` ：真正的 fitBaseType（enum / uint16 / sint32 ...）
//   早先的导出只存了 `type`，导致用 "file" 去查 fitBaseType 查不到 → 误报
//   「官方 profile 无此字段」。转换与校验都必须以 `baseType` 为准。
//
// 用法：
//   node scripts/export_profile.mjs [输出路径]
//   默认写到 references/fit_profile_official.json

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.dirname(__dirname);

const sdkPath = path.join(skillDir, 'node_modules', '@garmin', 'fitsdk', 'src', 'profile.js');
const Profile = (await import('file://' + sdkPath.replace(/\\/g, '/'))).default;

const outPath = process.argv[2] || path.join(skillDir, 'references', 'fit_profile_official.json');

// fitBaseTypeId 映射（FIT 协议固定表）
const BASE_TYPE_ID = {
  enum: 0x00, sint8: 0x01, uint8: 0x02, string: 0x07, uint8z: 0x0a, byte: 0x0d,
  sint16: 0x83, uint16: 0x84, sint32: 0x85, uint32: 0x86, float32: 0x88, float64: 0x89,
  uint16z: 0x8b, uint32z: 0x8c, sint64: 0x8e, uint64: 0x8f, uint64z: 0x90,
};

function cleanField(f) {
  return {
    num: f.num,
    name: f.name,
    type: f.type,              // 逻辑类型名
    base_type: f.baseType,     // 🔴 真正的 fitBaseType
    base_type_id: BASE_TYPE_ID[f.baseType] ?? null,
    array: !!f.array,
    scale: normalize(f.scale),
    offset: normalize(f.offset),
    units: normalize(f.units),
    components: f.components || [],
    sub_fields: (f.subFields || []).map((s) => ({
      name: s.name,
      type: s.type,
      base_type: s.baseType,
      scale: normalize(s.scale),
      offset: normalize(s.offset),
      units: normalize(s.units),
      ref_field_name: s.refFieldName,
      ref_field_value: s.refFieldValue,
      raw_values: s.rawValues,
    })),
  };
}

function normalize(v) {
  if (Array.isArray(v)) return v;
  return v === undefined || v === '' ? v : v;
}

const out = {
  _source: '@garmin/fitsdk',
  _version: `${Profile.version.major}.${Profile.version.minor}.${Profile.version.patch}`,
  _version_type: Profile.version.type,
  common_fields: Profile.CommonFields,
  messages: {},
  types: {},
  base_type_ids: BASE_TYPE_ID,
};

for (const [num, m] of Object.entries(Profile.messages)) {
  const fields = {};
  for (const [fnum, f] of Object.entries(m.fields || {})) {
    fields[fnum] = cleanField(f);
  }
  out.messages[num] = {
    num: m.num,
    name: m.name,
    messages_key: m.messagesKey,
    field_count: Object.keys(fields).length,
    fields,
  };
}

for (const [tname, tv] of Object.entries(Profile.types || {})) {
  const map = {};
  for (const [k, v] of Object.entries(tv)) {
    if (!['name', 'baseType', 'values'].includes(k)) map[k] = v;
  }
  // types 的结构是 { name, baseType, values: {值: 名} }
  out.types[tname] = tv.values || map;
  if (tv.baseType) {
    out.types[`_baseType_of_${tname}`] = tv.baseType;
  }
}
// 去掉辅助键，types 只留纯净的「枚举名 -> {值:名}」
for (const k of Object.keys(out.types)) {
  if (k.startsWith('_baseType_of_')) delete out.types[k];
}

fs.writeFileSync(outPath, JSON.stringify(out, null, 1), 'utf8');

const msgCount = Object.keys(out.messages).length;
const typeCount = Object.keys(out.types).length;
console.log(`✅ 已导出 profile v${out._version} -> ${outPath}`);
console.log(`   消息 ${msgCount} 个 / 枚举 ${typeCount} 个`);
console.log(`   示例 fileId.f0: type=${out.messages[0].fields[0].type} ` +
  `base_type=${out.messages[0].fields[0].base_type} ` +
  `id=0x${out.messages[0].fields[0].base_type_id.toString(16)}`);
