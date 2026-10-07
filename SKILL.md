---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。能力：合并分段活动、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移、FIT 预览、注入真实佳明/高驰设备信息（防 Connect 重算爬升 / 防未知设备）、字节级设备身份替换（Fenix8↔COROS 互换）、跨品牌互转（佳明↔高驰，规范驱动+双关卡门禁）。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'、'预览fit'、'注入佳明设备'、'防重算爬升'、'改成高驰设备'、'改成佳明设备'、'改设备身份'、'换设备'、'互转fit'、'规范门禁'、'学模板'、'全维度比对'。"
version: 4.8.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析 / 修改工具集，覆盖佳明、高驰、颂拓、华为等品牌 `.fit` 文件。
**核心理念**：规范入库、模板不入库——工具读规范，不依赖样本 `.fit` 黑盒；品牌特有知识拆分支沉淀。

## 文档结构（先读这里）

| 文档 | 性质 |
|---|---|
| `references/fit_format_spec.md` | **通用规范**：FIT 格式全要求（头/CRC/类型码/base_type/scale-offset/消息/开发者字段/时间基准）|
| `references/coros_specifics.md` | **高驰分支规范**：白名单消息、渐进布局、Effort Pace、device_info 精简布局、字段号映射 |
| `references/garmin_specifics.md` | **佳明分支规范**：私有消息、device_info 21 条、Connect 校验、enhanced 字段、配对传感器 |
| `references/cross_conversion.md` | **互转对照**：相同点合并 + 差异处理清单 + 换皮快捷路线 |
| `references/华为转换.md` | 华为 JSON→FIT/GPX/TCX 铁律 |
| `references/合并与重建.md` `设备注入与身份.md` `协议与时间戳.md` `规范驱动互转.md` | 细分铁律 |

## 路线总览

- **路线① 本地成熟流程**：合并分段 / 注入设备 / FIT 预览 / 华为转换 / 时间戳平移 / QA。日常主力。
- **路线② 规范驱动**：跨品牌互转（佳明↔高驰）+ 门禁 + 全维度比对。换设备只换规范名，不改代码。
- **换皮快捷路线**（只换设备身份、数据不动）：`inject_garmin_device.mjs` / `inject_coros.py` / `rebrand_device.py`，见 `cross_conversion.md` 五。

## 能力速览

| 任务 | 核心命令 | 路线 |
|------|----------|------|
| 合并分段（高驰，保真保留源生 lap）| `merge_preserve.mjs`（PROTO20=1）| ① |
| 合并分段（佳明 Connect）| `merge_fixed.mjs` | ① |
| 合并分段（字节级拼接）| `fit_merge.py` | ① 高驰✅ 佳明❌ |
| 注入真实佳明设备（防重算爬升）| `inject_garmin_device.mjs apply` | ① |
| 注入真实高驰设备（字节级防四不像）| `inject_coros.py apply` | ① |
| 设备身份互逆换皮（Fenix8↔COROS）| `rebrand_device.py <src> <ref> <out>` | ① |
| FIT 预览（HTML，先问后给）| `fit_preview.py input.fit` | ① |
| 华为→FIT/GPX/TCX | `huawei_convert.py 导出.json` | ① |
| 时间戳平移（SDK 保真版）| `shift_time_sdk.mjs in out -12` | ① |
| 协议字节修复（COROS 0x20）| `fix_proto.py in out` | ① |
| 跨品牌互转（规范驱动）| `fit_convert_by_template.py in out --to <规范>` | ② |
| 规范门禁 | `fit_conformance_check.py 产物 --temp X --src 源` | ② |
| 交付前全维度比对 | `fit_diff_vs_template.py 产物 --temp X --src 源` | ② |

## 交付规范

1. 只交付一个 `.fit`，不附带预览页/压缩包；预览 HTML 先问后给。
2. 压缩包默认不给；产物落输入文件同目录，中间文件放 `%TEMP%` 或 workspace 临时目录。
3. **不存样本 `.fit` 做参考**——格式解读进规范文档（见上表），真实设备身份存私有区 JSON。

## 交付前强制检查清单

| # | 检查项 | 命令 / 方法 | 不过怎么办 |
|---|--------|-------------|------------|
| 1 | 规范门禁 | `fit_conformance_check.py 产物 --temp X --src 源` | 有 FAIL 必须修 |
| 2 | 与真机全维度比对 | `fit_diff_vs_template.py 产物 --temp X --src 源` | 结构差异必须为 0 |
| 3 | SDK 交叉验证 | `@garmin/fitsdk` 解析产物 error 数 | checkIntegrity=true 且解码非空 |
| 4 | 条数守恒 | record/lap/event 条数与源比 | 必须一一相等 |
| 5 | 值级核对 | 门禁 §11 自动做 | 规范有值的字段不得是哨兵 |

三条硬规矩：① 与真机差异必须逐项解释；② 发现差异先说清，别顺手抹平；③ 不得用「过程跑通」替代「结果正确」。

## 核心铁律（11 条）

1. **官方 profile 为唯一事实源**：每次改/建 FIT，字段名/类型码/scale/offset/单位查 `references/fit_profile_official.json`，禁凭记忆。类型码看 `base_type` 不看 `type`。
2. 不篡改真实数据：去噪/缩放/伪造一律禁止。
3. **设备身份存私有区** `~/.workbuddy/private/fit_devices.json`（佳明 `garmin_devices.json`），绝不写死；序列号不进任何公开文件/脚本。
4. 协议字节：回传 COROS 必须 `0x20`，传佳明用标准 `0x02`；改之须重算 header CRC + file CRC（Garmin 半字节表）。
5. 高驰 device_info 标准精简布局（field 2=manufacturer=coros、无 product/serial，product 在 file_id=814）：跨品牌注入/互转一律字节级或规范拼接，绝不用 SDK Encoder 编高驰身份。详见 `coros_specifics.md` 五。
6. 合并高驰用 `merge_preserve.mjs` 保留源生 lap，禁用 `regenerate_laps`；佳明用 `merge_fixed.mjs`。
7. 门禁 PASS ≠ 与真机一致：交付前必跑 `fit_diff_vs_template.py` + SDK 交叉验证。
8. 跨品牌比对任何字段前，先判两端是否都声明该字段。
9. 暂停不算进配速但计入 elapsed；每圈 `total_distance` 写本圈距离（end−start），绝不可写累计值。
10. SDK 是验证工具不是转换引擎；校验不过先怀疑检查器，用独立手段裁定。
11. 精炼 ≠ 丢信息：规范里下游要读的字段一个不能省；能省的是给人看的冗余。

## 设备身份注入

- **注入真实佳明**（防 Connect 重算爬升）：`inject_garmin_device.mjs extract 真实佳明.fit --name fenix8` → `apply 第三方.fit --device fenix8 --out 出.fit`。默认剥离第三方私有开发者字段（佳明不识别，重复 field_description 会被拒）。无真实佳明不可凭空编造。
- **注入真实高驰**（字节级，防四不像）：`inject_coros.py extract 真实高驰.fit --name apex4` → `apply 源.fit --device apex4 --out 出.fit`（proto 默认 0x20）。删源全部 device_info 只嵌单条高驰；运动数据/私有字段 100% 保留。
  - **apply 无需先 extract**：若私人库 `coros_devices.json` 缺 `raw_identity`，自动回退到已提交的 `references/profiles/coros_<name>_identity.json`（无序列号设备），照常可跑——别再手去搜源 .fit。
  - **换皮后一键验收**：`inject_coros.py verify --src 源.fit --out 出.fit` → 一次出「设备身份列表 + 条数守恒(record/lap/session/event/activity) + 文件/header CRC + proto 字节」，输出 PASS 即身份正确替换、数据零改动。替代手搓脆弱 probe（COROS device_info 无 `garmin_product` 字段，手搓 `get_value` 会 KeyError）。
- 实战核对与「换皮只换身份、数据内核保留」认知：见 `cross_conversion.md` 五 + `coros_specifics.md` / `garmin_specifics.md`。
- 🔴 `lap.total_distance` 是「每圈分段距离」不是累计（易踩坑）：直接取 raw/1000，别用 d−prev 减。

## 端到端工作流

- **A 高驰分段→回传 COROS**：`merge_preserve.mjs`(PROTO20=1) → 若被翻 0x02 用 `fix_proto.py` 翻回 0x20 → `fit_qa.py` → 回传 COROS。
- **B 高驰分段→传 Garmin**：`merge_preserve.mjs`/`fit_merge.py` → `inject_garmin_device.mjs apply`(proto 0x02) → `fit_qa.py` → 传 Connect。
- **C 华为 JSON→高驰/佳明**：`huawei_convert.py`（默认 FIT）。
- **D 佳明分段→每km重切圈→改高驰→回传 COROS**：`merge_fixed.mjs` → `inject_coros.py apply --device apex4`(proto 0x20) → `fit_qa.py`。
- **E 跨品牌互转（规范驱动）**：`fit_convert_by_template.py --to <规范>` → 门禁 → 全维度比对 → SDK 验证 → 交付。
- **换皮双方向一步到位**：高驰→佳明 `rebrand_device.py <高驰源> <佳明参考> <出>`；佳明→高驰 `inject_coros.py apply`。均单命令 EXIT=0、输出经 fitdecode 严格解析 PASS 且 record/lap/session 条数守恒（设备身份正确替换）。

## QA 工作流（生成/修改 FIT 强制）

`fit_qa.py` 全绿才能交付（T01–T17，固化在 `scripts/fit_qa.py`）：

| 用例 | 校验点 |
|------|--------|
| T01 | header 合法（`.FIT` + header CRC）|
| T02 | 文件 CRC 正确 |
| T03 | 无孤儿定义 |
| T04 | 字段 size 符合 base type（源固有怪癖仅 WARN）|
| T05 | device_info 唯一且被识别 |
| T06 | file_id 含 manufacturer + product |
| T07 | Effort Pace 私有字段保留（源本无则误报，可接受）|
| T08 | 计圈结构：无过大圈(>1.5km)/过短圈(<200m 非末位)、Σlap=session 总距、短圈≤2 |
| T09 | record 距离单调、末值=session 总距 |
| T10 | message_index 同类内唯一 |
| T11–T17 | 对照原始段：起止时间/时间戳多重集/总时长/身份 == 段1∪段2 |

**T08 源固有判 FAIL**：若同一源单独跑也 FAIL（如 fenix8 一次 39 圈），则产物 FAIL 是继承源固有，不修、不 tamper。反之源 PASS、产物 FAIL 才是真 bug。

## 脚本索引

`scripts/` 下：`fit_merge.py` `merge_preserve.mjs` `merge_fixed.mjs` `fit_qa.py` `fit_healthcheck.py` `fit_preview.py` `fit_to_tcx.py` `fit_shift_time.py` `fit_rebuild_sdk.py` `huawei_convert.py` `huawei_batch_convert.py` `fit_encode.mjs` `inject_garmin_device.mjs` `inject_coros.py` `rebrand_device.py` `fix_proto.py` `fit_lib.py`（核心库）`fit_convert_by_template.py` `fit_conformance_check.py` `fit_diff_vs_template.py` `fit_learn_template.py` `fit_distill_spec.py` `export_profile.mjs` `extract_devices.py`。

调试探针（`dump_*`/`diag_*`/`_sdktmp`/`_check_integrity_tmp` 等）在 `scripts/_scratch/`，非任务入口。

## 环境（Python / Node 运行前必读）

- Python：`C:/Python314/python.exe -m pip install --no-cache-dir --index-url https://pypi.org/simple fitdecode fitparse`（tuna 等镜像常 403）。脚本一律绝对路径执行；Bash 工具 PATH 已坏，`ls/find/head` 等不可用，绝对路径二进制可跑。
- 🔴 **路径风格坑（高频踩）**：调用**受管** `python.exe`（`C:/Users/njzy/.workbuddy/binaries/python/envs/fitmerge/Scripts/python.exe`）时，**必须传 Windows 风格路径**（`C:/Users/...` 或反斜杠），本环境 Git Bash **不会**把 `/c/Users/...` 转换给它，会直接 `FileNotFoundError`。系统 `python3` 能吃 `/c/...`，但受管 venv 不行——统一用 `C:/...` 最稳。Node `node.exe` 同理。
- 🔴 脚本千万别命名 `inspect.py`（标准库被 dataclasses 间接 import，同名会静默崩）。
- fitdecode 0.11.0：`isinstance(m, FitDataMessage)` 区分 data 消息；读字段 `m.get_value("field")` 包 try/except。
- Node：`@garmin/fitsdk` 已随 skill 安装；`m.fields` 是 `FieldData` 列表（取 `.name`/`.value`/`.def_num`）。
- PowerShell stdout 本环境不回显，落盘（`Out-File`）再 Read。
