---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。能力：合并分段活动、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移、FIT 预览、注入真实佳明/高驰设备信息（防 Connect 重算爬升 / 防未知设备）、字节级设备身份替换（Fenix8↔COROS 互换）、跨品牌互转（佳明↔高驰，规范驱动+双关卡门禁）。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'、'预览fit'、'注入佳明设备'、'防重算爬升'、'改成高驰设备'、'改成佳明设备'、'改设备身份'、'换设备'、'互转fit'、'规范门禁'、'学模板'、'全维度比对'。"
version: 4.5.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集，覆盖佳明、高驰、颂拓、Polar、华为等品牌 .fit 文件。

## 目录
- [路线总览](#路线总览)
- [能力速览](#能力速览)
- [交付规范](#交付规范)
- [交付前强制检查清单](#交付前强制检查清单)
- [核心铁律](#核心铁律)
- [设备身份注入](#设备身份注入)
- [端到端工作流](#端到端工作流)
- [QA 工作流](#qa-工作流)
- [脚本索引](#脚本索引)
- [规范与文档索引](#规范与文档索引)

## 路线总览
- **路线① 本地成熟流程**：合并分段 / 注入设备 / FIT 预览 / 华为转换 / 时间戳平移 / QA。日常任务主力。
- **路线② 规范驱动**：跨品牌互转（佳明↔高驰）+ 11 节规范门禁 + 8 节全维度比对。换设备只换规范名，不改代码。

规范入库，模板不入库。工具一律读规范，缺失回退模板。规范含 base_type、布局、渐进节奏、设备公开型号，不含序列号。

## 能力速览
| 任务 | 核心命令 | 路线 |
|------|----------|------|
| 合并分段（高驰，保真保留源生 lap） | `merge_preserve.mjs`（PROTO20=1） | ① |
| 合并分段（佳明 Connect） | `merge_fixed.mjs` | ① |
| 合并分段（字节级拼接） | `fit_merge.py` | ① 高驰可用/佳明❌ |
| 注入真实佳明设备（防重算爬升） | `inject_garmin_device.mjs apply` | ① |
| 注入真实高驰设备（字节级防四不像） | `inject_coros.py apply` | ① |
| 设备身份互逆替换（Fenix8↔COROS） | `rebrand_device.py <src> <ref> <out>` | ① |
| FIT 预览（HTML） | `fit_preview.py input.fit` | ① |
| 华为→FIT/GPX/TCX | `huawei_convert.py 导出.json` | ① |
| 时间戳平移（SDK 保真版） | `shift_time_sdk.mjs in out -12` | ① |
| 协议字节修复（COROS 0x20） | `fix_proto.py in out` | ① |
| 跨品牌互转（规范驱动） | `fit_convert_by_template.py in out --to <规范>` | ② |
| 规范门禁 | `fit_conformance_check.py 产物 --temp X --src 源` | ② |
| 交付前全维度比对 | `fit_diff_vs_template.py 产物 --temp X --src 源` | ② |

## 交付规范
生成 FIT 合并/修改交付物，遵守：
1. 只交付一个 `.fit`，不附带预览页/压缩包。
2. 预览 HTML 先问后给，不默认甩出。
3. 压缩包默认不给，不主动打 zip。
4. 产物默认落在输入文件同目录；中间文件放 `%TEMP%` 或 workspace 临时目录。

## 交付前强制检查清单
门禁 PASS 仅代表已覆盖断言通过，非交付充分条件。交付前须完成：

| # | 检查项 | 命令 / 方法 | 不过怎么办 |
|---|--------|-------------|------------|
| 1 | 规范门禁 | `fit_conformance_check.py 产物 --temp X --src 源` | 有 FAIL 必须修，不得带 FAIL 交付 |
| 2 | 与真机全维度比对 | `fit_diff_vs_template.py 产物 --temp X --src 源` | 结构差异必须为 0；逐项看差异 |
| 3 | SDK 交叉验证 | `@garmin/fitsdk` 解析产物查 error 数 | `checkIntegrity=true` 且解码非空 |
| 4 | 条数守恒（与源比） | record/lap/event 条数 | 必须一一相等 |
| 5 | 值级核对 | 门禁 §11 自动做 | 规范有值的字段，产物不得是哨兵 |

三条硬规矩：① 与真机的差异必须逐项解释（数据量差异可接受，格式差异必须修）；② 发现差异先说清，别顺手抹平；③ 不得用「过程跑通」替代「结果正确」。

## 核心铁律
各域细则见 `references/` 下分支文档：华为转换 / 合并与重建 / 设备注入与身份 / 协议与时间戳 / 规范驱动互转。
1. 以官方 profile 为唯一事实源：每次修改/创建 FIT，字段名/类型码/scale/offset/单位一律查 `references/fit_profile_official.json`（辅以 `fit_format_spec.md`），禁止凭记忆或猜测字段含义；官方 profile 无定义的字段按未知/开发者字段处理，不得臆造语义。
2. 不篡改真实数据：去噪/缩放/伪造一律禁止。
3. 设备身份存私有区 `~/.workbuddy/private/fit_devices.json`，绝不写死；序列号不进任何公开文件/脚本。
4. 协议字节：回传 COROS 必须 `0x20`，传佳明用标准 `0x02`；改之须同时重算 header CRC + file CRC 两道（CRC 用 Garmin 半字节表）。
5. 高驰 device_info 非标准布局（product=294、无 manufacturer 字段）：跨品牌注入/互转一律字节级或规范拼接，绝不用 SDK Encoder 编高驰身份。
6. 合并高驰用 `merge_preserve.mjs` 保留源生 lap，禁用 `regenerate_laps`；佳明用 `merge_fixed.mjs`。
7. 门禁 PASS ≠ 与真机一致：交付前必跑 `fit_diff_vs_template.py` 穷举比对 + SDK 交叉验证。
8. 类型码看 `base_type` 不看 `type`；跨品牌比对任何字段前，先判两端是否都声明该字段。
9. 暂停不算进配速但计入 elapsed；每圈 `total_distance` 写本圈距离（end−start），绝不可写累计值。
10. SDK 是验证工具不是转换引擎；校验不过先怀疑检查器，用独立手段（SDK 解析 / 读原始字节）裁定，别急着改产物。
11. 精炼 ≠ 丢信息：规范里下游程序要读的字段一个不能省；能省的是给人看的冗余。

## 设备身份注入
### 注入真实佳明设备（防 Connect 重算爬升）
- Connect 校验 `(product, UnitID)`；无气压计设备会被 DEM 重算海拔。把 file_id+device_info 改成真实佳明带气压计设备 → 关校正。
- 工作流：`inject_garmin_device.mjs extract 真实佳明.fit --name fenix8` → `inject_garmin_device.mjs apply 第三方.fit --device fenix8 --out 高驰_fenix8.fit`。
- 约束：私人数据 `~/.workbuddy/private/garmin_devices.json`；`apply` 删原第三方 device_info 只留单条佳明、默认剥离第三方私有开发者字段（佳明不识别，重复 field_description 会被 Connect 拒收）。无真实佳明设备不可凭空编造。

### 注入真实高驰设备（字节级，防四不像）
- 高驰 device_info 非标准布局，SDK Encoder 编不出 → 必须字节级复制参考文件 file_id+device_info 原始字节。
- 工作流：`inject_coros.py extract 真实高驰.fit --name apex4` → `inject_coros.py apply 源.fit --device apex4 --out 源_coros.fit`（proto 默认 0x20 回传 COROS）。
- 约束：删源全部 device_info 只嵌单条高驰；协议翻 0x20；运动数据/私有字段 100% 保留。参考字节存 `~/.workbuddy/private/coros_<name>.fit`，不与脚本同走 GitHub。

### 设备身份字节级替换（rebrand：Fenix8↔COROS 互换）
- `rebrand_device.py <src.fit> <ref.fit> <out.fit>`：复制 ref 的 file_id+device_info 字节，local 号与活动时间戳用 src 自己的，其余逐字节拼接，重算 data_size+header CRC+file CRC。运动数据 100% 保留。
- 高驰源文件常带 10+ 条 device_info（传感器），只换第一条会留「四不像」——用 `inject_coros.py` 全删重嵌更稳。

## 端到端工作流
### A：高驰分段 → 回传 COROS（保真）
```
seg1,seg2 ──→ merge_preserve.mjs (PROTO20=1, 保留源生 lap)
   └─(若被 SDK 翻成 0x02)→ fix_proto.py 翻回 0x20
   └─→ fit_qa.py 合并.fit seg1 seg2 ──→ 回传 COROS（建议先删旧活动）
⚠️ 协议字节必须 0x20；绝不用 regenerate_laps。
```
### B：高驰分段 → 传 Garmin Connect
```
seg1,seg2 ──→ merge_preserve.mjs/fit_merge.py ──→ 合并.fit
   └─→ inject_garmin_device.mjs apply ──→ *_fenix8.fit (协议 0x02)
   └─→ fit_qa.py *_fenix8.fit ──→ 传 Connect
```
### C：华为 JSON → 高驰/佳明
```
华为JSON ──→ huawei_convert.py (默认 FIT / --format gpx|tcx|all) ──→ 平台
```
### D：佳明分段 → 每km重切圈 → 改高驰 → 回传 COROS
```
seg1,seg2(佳明) ──→ merge_fixed.mjs (段间重定基线 + 每km精确边界)
   └─→ inject_coros.py apply --device apex4 (proto 0x20)
   └─→ fit_qa.py 合并_coros.fit ──→ 回传 COROS（只交付一个 .fit）
⚠️ 佳明用 SDK 路线 merge_fixed.mjs；段间大时间差重定基线，否则出怪物圈。
```
### E：跨品牌互转（规范驱动 + 双关卡）
```
源.fit ──→ fit_convert_by_template.py --to <规范名> ──→ 目标.fit
   └─→ fit_conformance_check.py 目标.fit --temp <规范> --src 源   (门禁)
   └─→ fit_diff_vs_template.py 目标.fit --temp <规范> --src 源     (全维度比对)
   └─→ @garmin/fitsdk 解析 0 errors + 与源条数守恒 ──→ 交付
⚠️ 转换走「规范拼接字节」，绝不用 SDK Encoder 跨品牌；serialNumber 从私有区读。
```
首次新增设备规范：`fit_learn_template.py 真机.fit --name xxx` → `fit_distill_spec.py xxx` → 之后所有人复用。

## QA 工作流（合并/重建类任务强制）
凡是生成/修改 FIT（合并、重建、注入设备、时间戳平移），交付前必须跑 `fit_qa.py` 全绿。用例集（固化在 `scripts/fit_qa.py`）：

| 用例 | 校验点 |
|------|--------|
| T01 | header 合法（`.FIT` 魔数 + header CRC） |
| T02 | 文件 CRC 正确 |
| T03 | 无孤儿定义（每条 definition 后必有 ≥1 数据） |
| T04 | 字段 size 符合 base type（COROS event uint32 size=1 等源固有怪癖仅 WARN 不修） |
| T05 | device_info 唯一且被识别 |
| T06 | file_id 含 manufacturer + product |
| T07 | Effort Pace 私有字段保留（源本无则误报，可接受） |
| T08 | 计圈结构：无过大圈(>1.5km)/过短圈(<200m 非末位)、Σlap=session 总距、短圈≤2 |
| T09 | record 距离单调、末值=session 总距 |
| T10 | message_index 同类内唯一 |
| T11–T17 | 对照原始段：合并起止时间==段1首/段2末、record 时间戳多重集==段1∪段2、总时长==段2末−段1首、file_id.time_created/device_info 身份==段1 |

约束：源固有怪癖只 WARN，绝不篡改设备原始输出；每发现新常识错误往 `fit_qa.py` 加 T 用例；时间/身份类 bug 必须带原始段跑交叉校验（`fit_qa.py merged.fit seg1.fit seg2.fit`）才能证明对。

## 脚本索引
| 脚本 | 用途 | 路线/状态 |
|------|------|-----------|
| `fit_merge.py` | 字节级拼接，去重 dev/device_info，regenerate_laps 重切圈 | ① 高驰✅ 佳明❌ |
| `merge_preserve.mjs` | 高驰原生合并（保留源生 lap，协议翻 0x20） | ① 高驰推荐 |
| `merge_fixed.mjs` | 佳明合并（SDK，每km精确边界，暂停感知） | ① 佳明✅ |
| `fit_qa.py` | 合并/重建交付前回归测试（T01–T17） | ① 强制 |
| `fit_healthcheck.py` | 语义体检 | ① |
| `fit_preview.py` | FIT→交互式 HTML 预览 | ① |
| `fit_to_tcx.py` | FIT→TCX 兜底 | ① |
| `fit_shift_time.py` | 时间戳平移（字节级，原始/简单文件） | ① |
| `shift_time_sdk.mjs` | 时间戳平移（SDK 保真，含压缩时间戳消息） | ① |
| `fit_rebuild_sdk.py` | 官方 SDK 重建（丢私有消息） | ① |
| `huawei_convert.py` | 华为 JSON→FIT/GPX/TCX（默认 FIT） | ① |
| `huawei_batch_convert.py` | 华为 JSON 批量按类型分目录转换 | ① |
| `fit_encode.mjs` | FIT 编码器（huawei_convert 内部调用） | ① |
| `inject_garmin_device.mjs` | 注入佳明设备（extract/apply） | ① |
| `inject_coros.py` | 注入高驰设备（字节级 extract/apply） | ① |
| `inject_coros.mjs` | 注入 COROS 身份（SDK 版，反面教材，改用 inject_coros.py） | ① 弃用 |
| `rebrand_device.py` | 设备身份字节级替换（互逆，纯 Python） | ① |
| `fix_proto.py` | 协议字节修复 + 双 CRC 重算 | ① |
| `fit_lib.py` | 核心库：解析/编码/官方 profile/哨兵/换算 | ② 共用 |
| `fit_learn_template.py` | 真机→模板 JSON（学布局/节奏/类型码/身份） | ② |
| `fit_distill_spec.py` | 模板→规范（.md+.json，剔除 78~86% 噪声） | ② |
| `fit_convert_by_template.py` | 规范驱动双向转换（自动过门禁） | ② |
| `fit_conformance_check.py` | 11 节规范门禁（EXIT=1 有 FAIL） | ② 强制 |
| `fit_diff_vs_template.py` | 8 节全维度比对（交付前必跑） | ② 强制 |
| `export_profile.mjs` | 重导官方 profile（必须含 base_type） | ② |
| `extract_devices.py` | 抽设备身份入私有区 `fit_devices.json` | ② |
| `fit_to_coros_mapped.py` | 旧版硬编码高驰转换 | ② 兜底（已被 convert_by_template 取代） |
| `inject_coros_device.mjs` | 只换高驰设备身份（源已高驰格式时用） | ② |

调试/临时脚本（dump_fit / diag_* / rec_dump / count_types / session_diff / parse_lap_order / scan_all / dump_dev / _sdktmp / _check_integrity_tmp 等）属开发期探针，留存在 `scripts/` 顶层，非任务入口，计划归档至 `scripts/_scratch/`；正常任务勿调用。

## 规范与文档索引
- `references/fit_profile_official.json` — Garmin 官方 profile（含 base_type，一切为准）
- `references/fit_format_spec.md` — FIT 格式全要求（头/流/类型码/scale-offset/消息/校验/开发者字段/时间基准）
- `references/vendor_specifics.md` — 高驰/佳明差异枚举（文件级参数、消息集、record 布局、dev16≠speed、设备信息、互转清单）
- `references/conversion_workflow.md` — 互转流程总纲（三条原则/七步/反面教材）
- `references/format_spec_garmin_vs_coros.md`、`field_mapping_garmin_to_coros.md` — 两平台格式对照与字段映射
- `references/华为转换.md` — 华为转换铁律（缩放/爬升/去噪/计圈）
- `references/合并与重建.md` — 合并与重建铁律（预览/丢消息/佳明合并/暂停感知）
- `references/设备注入与身份.md` — 设备注入与身份铁律（佳明注入/私有区）
- `references/协议与时间戳.md` — 协议字节与时间戳铁律
- `references/规范驱动互转.md` — 规范驱动互转铁律（base_type/渐进布局/门禁/比对/精炼）
- `references/exp_20260720.md` — 早期实战记录
- `references/profiles/` — 入库规范：`coros_apex4.{md,json}`、`garmin_fenix8.{md,json}`（含公开型号，无序列号）

## 环境
```bash
pip install fitdecode fitparse   # Python 侧
npm install @garmin/fitsdk       # Node 侧（已随 skill 安装）
```
