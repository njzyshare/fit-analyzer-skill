---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。能力：合并分段活动、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移、FIT 预览、注入真实佳明/高驰设备信息（防 Connect 重算爬升 / 防未知设备）、字节级设备身份替换（Garmin↔COROS 互换）、跨品牌互转（佳明↔高驰，规范驱动+双关卡门禁）。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'、'预览fit'、'注入佳明设备'、'防重算爬升'、'改成高驰设备'、'改成佳明设备'、'改佳明'、'传Connect'、'改设备身份'、'换设备'、'互转fit'、'规范门禁'、'学模板'、'全维度比对'。"
version: 4.9.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析 / 修改工具集，覆盖佳明、高驰、颂拓、华为等品牌 `.fit` 文件。
**核心理念**：规范入库、模板不入库——工具读规范，不依赖样本 `.fit` 黑盒；品牌特有知识拆分支沉淀。

## 怎么选路线

按**交付去向**选，不按文件来源选：

| 你要什么 | 走哪条 | 主命令 |
|---|---|---|
| 传 Garmin Connect | **注入路线**（唯一可用）| `inject_garmin_device.mjs apply <源> --device fenix8 --out <出>` |
| 回传高驰 / 改高驰结构 | 规范重建 | `fit_convert_by_template.py <源> <出> --to coros_apex4` |
| 高驰分段回传高驰 | 保真合并 | `merge_preserve.mjs`（PROTO20=1）→ `fit_qa.py` |
| 佳明分段传 Connect | 佳明合并 + 注入 | `merge_fixed.mjs` → `inject_garmin_device.mjs apply` → `fit_qa.py` |
| 只换身份、数据不动 | 换皮 | `rebrand_device.py` / `inject_coros.py` / `inject_garmin_device.mjs` |
| 其他（预览 / 华为 / 平移 / TCX / 体检 / 学规范）| 单命令 | 见下方「单命令能力」 |

**两个禁令**：
- ❌ `--to garmin_watch` 的产物**禁止传 Connect**（布局比对件，proto=0x10、21 条 device_info，会被判未知设备并重算爬升）。
- ❌ 字节级合并产物**禁止直传 Connect**（私有消息会被拒收）；必须再过注入让 SDK 剥离。

## 单命令能力

| 任务 | 命令 |
|---|---|
| FIT 预览（HTML，先问后给）| `fit_preview.py input.fit` |
| 华为→FIT/GPX/TCX | `huawei_convert.py 导出.json` |
| 时间戳平移（字节级保真，f5 同移）| `fit_shift_time.py`（SDK 版 `shift_time_sdk.mjs`）|
| 协议字节修复（COROS 0x20）| `fix_proto.py in out` |
| 规范门禁 / 全维度比对 | `fit_conformance_check.py 产物 --temp X --src 源` / `fit_diff_vs_template.py 产物 --temp X --src 源` |
| FIT 体检 / QA | `fit_healthcheck.py` / `fit_qa.py` |
| 官方 SDK 重建 | `fit_rebuild_sdk.py` |
| 学新设备规范 | `fit_learn_template.py 真机.fit --name X` → `fit_distill_spec.py X` |

## 硬约束（动手前必读）

1. **官方 profile 是唯一事实源**：字段名/类型码/scale/offset/单位查 `references/fit_profile_official.json`，禁凭记忆；类型码看 `base_type` 不看 `type`。
2. **不篡改真实数据**：去噪/缩放/伪造一律禁止；源固有怪癖只 WARN，不修。
3. **设备身份存私有区，绝不写死**：`~/.workbuddy/private/garmin_devices.json`（佳明）/ `coros_devices.json`（高驰），旧 `fit_devices.json` 仅兼容；序列号不进任何公开文件/脚本。收集身份用 `extract <真机.fit> --name <key>`。
4. **协议字节按去向定**：回传 COROS 必须 `0x20`，传佳明必须 `0x02`；改字节须重算 header CRC + file CRC（Garmin 半字节表）。
5. **高驰 device_info 只用精简布局**：field 2=manufacturer=coros、无 product/serial，product 在 `file_id=814`；跨品牌注入/互转一律字节级或规范拼接，绝不用 SDK Encoder 编高驰身份。
6. **合并保真**：高驰用 `merge_preserve.mjs` 保留源生 lap、禁用 `regenerate_laps`；佳明用 `merge_fixed.mjs`。
7. **门禁 PASS ≠ 与真机一致**：交付必跑全维度比对 + SDK 交叉验证。
8. **跨品牌比对字段前先判两端是否都声明该字段**。
9. **计圈与配速**：暂停不算进配速但计入 elapsed；`lap.total_distance` 是本圈距离（end−start），不是累计值，取 raw/1000 别用差值倒推。
10. **SDK 是验证工具不是转换引擎**：校验不过先怀疑检查器，用独立手段裁定。
11. **精炼 ≠ 丢信息**：规范里下游要读的字段一个不能省；能省的是给人看的冗余。
12. **换皮效果只看「最快1KM」**：它取决于 record 是否按高驰规范重建（骨架干净、零 `unknown_*`）；CLEAN 骨架是充分条件、非必要条件。设备型号显示、等强配速属服务端/硬件侧判定，FIT 改不出来，别折腾。
13. **传 Connect 只认注入路线**：`inject_garmin_device.mjs apply`，三条交付判据缺一不可——
    - `protocol_version=0x02`
    - `device_info` **恰好 1 条**且 `sourceType=local`
    - `file_id.serialNumber` 为**真实 Unit ID**（`file_creator` 非必需）
    上传前删旧活动破缓存；Connect 的「装备」(Gear) 是手动关联项、FIT 无此字段。

规范细节与证据见 `references/coros_specifics.md` §九/§十、`garmin_specifics.md` 三、`cross_conversion.md` 四/五；
长期观测样本在工作区记忆 `best1km_ab_tracker.md`，不进 skill。

## 工作流

### A · 高驰分段 → 回传高驰
`merge_preserve.mjs`(PROTO20=1) → 若协议被翻成 0x02 用 `fix_proto.py` 翻回 → `fit_qa.py` → 回传。

### B · 高驰 / 第三方 → 传 Garmin Connect
`inject_garmin_device.mjs apply <源> --device fenix8 --out <出>` → 验硬约束 13 三判据 → `fit_qa.py` → 上传。
合并过的源也必须走这条：SDK 全量重编码会剥离第三方私有段（否则 Connect 拒收），并写入单条真实设备身份（否则 DEM 重算爬升）。
无真实佳明文件不可凭空编造 Unit ID；先用 `extract` 从真机收集。

### C · 佳明分段 → 每 km 重切圈 → 回传高驰
`merge_fixed.mjs` → `inject_coros.py apply --device apex4`(proto 0x20) → `fit_qa.py`。

### D · 跨品牌互转（规范驱动）
`fit_convert_by_template.py <源> <出> --to <规范>` → 门禁 → 全维度比对 → SDK 验证 → 交付。
`--to coros_apex4` 可回传高驰；`--to garmin_watch` 仅布局比对，不上传。用户说「改佳明 / 传 Connect」走 B，不走 D。

### E · 华为 JSON
`huawei_convert.py 导出.json`（默认 FIT）。

### 换皮（只换身份、数据不动）
- 任意 → 佳明：`rebrand_device.py <源> <佳明参考> <出>`
- 任意 → 高驰：`inject_coros.py apply --device <key>`
- 验身份：`inject_coros.py verify --src 源 --out 出`（一次出身份列表 + 条数守恒 + 双 CRC + proto）。

## 设备身份注入

- **佳明**：`inject_garmin_device.mjs extract <真机.fit> --name <key>` → `apply <第三方.fit> --device <key> --out <出>`。
  官方 SDK 全量重编码：保留运动数据、剥离第三方私有开发者字段、只留 1 条 `sourceType=local` 真实身份、proto=0x02。
  `apply` 日志里 `剥离第三方 developer 私有字段 (制造商=undefined ≠ …)` 是字段名映射误报，私有段确已剥离，不影响结果。
- **高驰**：`inject_coros.py extract <真机.fit> --name <key>` → `apply <源> --device <key> --out <出>`（proto 默认 0x20）。
  删源全部 device_info 只嵌单条高驰；运动数据/私有字段 100% 保留。
  私人库缺 `raw_identity` 时自动回退到已提交的 `references/profiles/coros_<name>_identity.json`，无需回头找源 FIT。
- 规范转换器 v4.8.1+ 三个库全读、按品牌线索 + 厂商码匹配、字符串 manufacturer 规范化为官方数值码；`--keep-identity` 时不读库。

## 交付检查（全过才交付）

| # | 检查 | 方法 | 判据 |
|---|---|---|---|
| 1 | 规范门禁 | `fit_conformance_check.py 产物 --temp X --src 源` | FAIL=0 |
| 2 | 全维度比对 | `fit_diff_vs_template.py 产物 --temp X --src 源` | 结构差异=0 |
| 3 | SDK 交叉验证 | `@garmin/fitsdk` 解析 | `integrity=true`、解码 0 error |
| 4 | 条数守恒 | record/lap/event 与源比 | 一一相等 |
| 5 | 值级核对 | 门禁自动做 | 规范要求有值的字段不得是哨兵 |
| 6 | 传 Connect 专项 | 硬约束 13 三判据 | 全中才算可上传 |

检查 1~5 只证明**文件内部自洽**，不证明**服务端认设备**；上传场景必须额外过第 6 条。

三条硬规矩：① 与真机差异必须逐项解释；② 发现差异先说清，别顺手抹平；③ 不得用「过程跑通」替代「结果正确」。
交付只给一个 `.fit`；中间文件放 `%TEMP%`；预览 HTML 先问后给。

## QA 工作流（生成/修改 FIT 强制）

`fit_qa.py` 全绿才能交付（T01–T19，固化在 `scripts/fit_qa.py`）：

| 用例 | 校验点 |
|------|--------|
| T01–T03 | header 合法 / 文件 CRC / 无孤儿定义 |
| T04 | 字段 size 符合 base type（源固有怪癖仅 WARN）|
| T05–T06 | device_info 唯一且被识别 / file_id 含 manufacturer + product |
| T07 | Effort Pace 私有字段保留（源本无则误报，可接受）|
| T08 | 计圈结构：无过大圈(>1.5km)、无过短圈(<200m 非末位)、Σlap=session 总距、短圈数 ≤2 |
| T09–T10 | record 距离单调且末值=总距 / message_index 同类内唯一 |
| T11–T17 | 对照原始段：起止时间/时间戳多重集/总时长/身份 == 段1∪段2 |
| T18–T19 | 每圈 avg_pace=扣暂停后 timer/距离 / 每圈 timer ≤ elapsed |

**T08 判 FAIL 时的分流**（短圈多不一定是真 bug）：
1. 用同一套取值口径比对**源与产物**的逐圈 `total_distance`；
2. 逐值一致 → 计圈来自源的训练结构（课表按步骤自动切圈、手动圈等），规则「短圈≤2」不适用，判**规则误报**，照常交付并在记录里注明；
3. 源 PASS 而产物 FAIL → 才是转换 bug，回去修。
   课表自动切圈的活动天然含多段不等长圈，别改数据去凑规则。

## 文档索引

| 文档 | 内容 |
|---|---|
| `references/fit_format_spec.md` | FIT 通用规范（头/CRC/类型码/scale/开发者字段/时间基准）|
| `references/coros_specifics.md` | 高驰：白名单消息、渐进布局、Effort Pace、最快1KM、平台限制、GAP 模型 |
| `references/garmin_specifics.md` | 佳明：私有消息、device_info、Connect 校验 |
| `references/cross_conversion.md` | 双向互转对照与差异处理 |
| `references/coros_mcp.md` | 高驰 MCP：部署、取数口径、`lapGroups` 判最快1KM |
| `references/garmin_mcp.md` | 佳明中国区 MCP：可迁移部署、版本坑、FIT 导出 |
| `references/华为转换.md` `合并与重建.md` `设备注入与身份.md` `协议与时间戳.md` `规范驱动互转.md` | 细分规则 |
| `references/field_mapping_garmin_to_coros.md` | 佳明→高驰字段映射全表 |

脚本在 `scripts/`；调试探针（`dump_*`/`diag_*`/`_scratch`）非任务入口。

## 环境

- Python：`C:/Python314/python.exe -m pip install --no-cache-dir --index-url https://pypi.org/simple fitdecode fitparse`（镜像常 403）。脚本一律绝对路径执行。
- 🔴 **受管 Python / Node 只吃 Windows 风格路径**（`C:/Users/<用户名>/...`）：Git Bash 不会把 `/c/...` 转换给它，会直接 `FileNotFoundError`；系统 `python3` 能吃 `/c/...`，受管 venv 不行。
- 🔴 脚本别命名 `inspect.py`（与标准库同名会静默崩）。
- fitdecode 0.11.0：用 `isinstance(m, FitDataMessage)` 区分 data 消息；`m.get_value("field")` 包 try/except。
- Node：`@garmin/fitsdk` 已随 skill 安装；`m.fields` 是 `FieldData` 列表（取 `.name`/`.value`/`.def_num`）。
- PowerShell stdout 本环境不回显，落盘（`Out-File`）再 Read。
