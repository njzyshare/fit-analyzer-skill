# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集，覆盖佳明、高驰、颂拓、Polar、华为等所有产出 `.fit` 的设备。

## 能力

| 能力 | 命令 |
|---|---|
| 佳明 → 高驰（规范重建，回传 COROS 用这个）| `fit_convert_by_template.py in.fit out.fit --to coros_apex4` |
| 高驰 → 佳明（规范布局比对件，⚠️ **不可直接传 Connect**）| `fit_convert_by_template.py in.fit out.fit --to garmin_watch` |
| **高驰/任意 → 佳明（传 Garmin Connect，✅ 推荐）**| `inject_garmin_device.mjs apply in.fit --device fenix8 --out out.fit` |
| 华为 → FIT / GPX / TCX | `huawei_convert.py 导出.json [--format gpx\|tcx\|all]` |
| 华为 → 批量按类型输出 | `huawei_batch_convert.py 导出.json -o ./out` |
| 任意 → TCX（兜底）| `fit_to_tcx.py in.fit -o out.tcx` |
| 换高驰设备身份（字节级）| `inject_coros.py apply` |
| 注入真实佳明设备（防重算爬升）| `inject_garmin_device.mjs apply` |
| 设备身份互逆换皮 | `rebrand_device.py <src> <ref> <out>` |
| 合并分段（高驰，保留源生 lap）| `merge_preserve.mjs` |
| 合并分段（佳明 Connect）| `merge_fixed.mjs` |
| 合并分段（字节级）| `fit_merge.py` 高驰✅ 佳明❌ |
| FIT 预览（HTML，地图+计圈）| `fit_preview.py 活动.fit` |
| 时间戳平移（SDK 保真）| `shift_time_sdk.mjs in.fit out.fit -12` |
| 协议字节修复（COROS 0x20）| `fix_proto.py in.fit out.fit` |
| FIT 体检 / QA | `fit_healthcheck.py` / `fit_qa.py` |
| 官方 SDK 重建 | `fit_rebuild_sdk.py` |
| 新设备学规范 | `fit_learn_template.py 真机.fit --name X` → `fit_distill_spec.py X` |
| 高驰 MCP 取数 | 见 [`references/coros_mcp.md`](references/coros_mcp.md) |

跨品牌互转两个方向都过 11 节规范门禁 + 全维度比对，数据保真（速度/海拔逐点差 0.00000）。
**换新型号只需换 `--to` 后的规范名，不改代码。**

## 环境

```bash
pip install fitdecode fitparse && npm install @garmin/fitsdk
```

## 快速开始

```bash
# 佳明 → 高驰（含门禁与比对，三步走）
python scripts/fit_convert_by_template.py 佳明.fit 高驰.fit --to coros_apex4
python scripts/fit_conformance_check.py 高驰.fit --temp coros_apex4 --src 佳明.fit
python scripts/fit_diff_vs_template.py  高驰.fit --temp coros_apex4 --src 佳明.fit

# 高驰 → 佳明（规范布局比对件；⚠️ 不要拿去传 Garmin Connect，见下节）
python scripts/fit_convert_by_template.py 高驰.fit 佳明.fit --to garmin_watch

# 高驰 → 佳明（传 Garmin Connect 的正确路线，单条真实设备身份）
node scripts/inject_garmin_device.mjs apply 高驰.fit --device fenix8 --out 高驰_fenix8.fit

# 华为 → FIT
python scripts/huawei_convert.py 导出.json

# 合并分段 / 预览 / 平移
node scripts/merge_preserve.mjs
python scripts/fit_preview.py 活动.fit
node scripts/shift_time_sdk.mjs in.fit out.fit -12
```

## ⚠️ 传 Garmin Connect：别用规范重建

两条路线都叫「高驰 → 佳明」，用途完全不同：

| | `fit_convert_by_template.py --to garmin_watch` | `inject_garmin_device.mjs apply --device fenix8` |
|---|---|---|
| 目标 | 与目标规范**布局逐项一致**（门禁 / 全维度比对 / 研究）| 让 Connect **认设备**、不重算爬升 |
| `protocol_version` | 0x10 | **0x02** |
| `device_info` | 21 条（含传感器条目，字段多为哨兵）| **1 条**，`sourceType=local` |
| `file_id` | 真实 Unit ID（v4.8.1 起自动带）| 真实 Unit ID |
| 门禁 / QA / SDK | 全绿 | 全绿 |
| Connect 实测 | ❌ 未知设备 + DEM 重算爬升 | ✅ 设备显示 fenix8、爬升保留 |

**实证（2026-11-15，COROS PACE 4 Pro 21.48 km 活动）**：文件
`session.total_ascent=81m`，record 海拔逐点无阈值上升 83.0 m；规范重建产物上传后
Connect 显示 **287 m 累计爬升** —— 不是文件算出来的，是 Connect 拿 DEM 地形数据
替换了轨迹点海拔，因为它把该文件判成「不带气压高度计的设备」。
给 21 条 `device_info` 补齐 `source_type=local` / `device_index` /
`software_version`、再从真机抠 `file_creator` 插入，**仍然不行**；
回退到注入路线后立即正常。所以问题不在缺标记，在整条路线。

🔴 **传 Connect 前的三条交付判据（逐条验，缺一不可）**：

1. `protocol_version = 0x02`（不是 0x10 / 0x20）
2. `device_info` **恰好 1 条**，`sourceType=local`、`deviceIndex=creator`
3. `file_id.serialNumber` 为**真实 Unit ID**（编造的会被服务端 `(product, UnitID)` 校验判「未知设备」）

`file_creator`(g=49) **不是必需** —— 历史成功产物没有它，Connect 照样识别。
门禁 PASS / QA 全绿 / SDK 0 error **都不能**替代这三条：它们只校验文件内部自洽，
不校验服务端认不认设备。

另：Connect 的「装备」(Gear) 指跑鞋等手动关联项，FIT 里没有这个字段；
设备型号在「设备」栏。重传前必须先删旧活动破缓存。
细节见 [`references/garmin_specifics.md`](references/garmin_specifics.md) 三节、
[`references/cross_conversion.md`](references/cross_conversion.md) 四 / 五节。

## 换皮：只改身份 vs 规范重建

最容易踩的坑，单独说清。

| 做法 | 消息种类 | `unknown_*` | 高驰「最快1KM」 |
|---|---|---|---|
| 只改 `file_id`/`device_info`（`inject_coros.py`）| 35~37 | 11~12 个 | ❌ 不出 |
| 规范重建（`fit_convert_by_template.py`）| 9~12 | **0** | ✅ 出 |

**原因**：高驰按自身定义读 record 的逐点距离流。佳明布局原样搬过去时，
字段号/字节长度/类型码全对不上，**速度列读空** → 不报错、静默跳过派生，
且一次性入库不重试（上传那刻就定死）。

**平台限制**：设备型号显示、等强配速改不出来（服务端靠真机序列号/固件校验）。
→ **评估换皮是否成功，只看「最快1KM」出没出。**

细节见 [`references/coros_specifics.md`](references/coros_specifics.md) §九~§十一。

## 文档索引

| 文档 | 内容 |
|---|---|
| [`references/fit_format_spec.md`](references/fit_format_spec.md) | FIT 格式通用规范（头/CRC/类型码/scale/开发者字段）|
| [`references/coros_specifics.md`](references/coros_specifics.md) | 高驰分支：白名单消息、渐进布局、Effort Pace、最快1KM、平台限制 |
| [`references/garmin_specifics.md`](references/garmin_specifics.md) | 佳明分支：私有消息、device_info 21 条、Connect 校验 |
| [`references/cross_conversion.md`](references/cross_conversion.md) | 双向互转对照与差异处理 |
| [`references/coros_mcp.md`](references/coros_mcp.md) | 高驰 MCP 部署与取数口径 |
| [`references/华为转换.md`](references/华为转换.md) | 华为 JSON → FIT/GPX/TCX |
| `合并与重建.md` `设备注入与身份.md` `协议与时间戳.md` `规范驱动互转.md` | 细分铁律 |

字段含义一律以 `references/fit_profile_official.json` 为准，完整规则与铁律见 `SKILL.md`。
