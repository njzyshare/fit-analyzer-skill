---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。核心是「模板驱动 + 规范门禁」：用真机文件学出目标平台模板（字段布局/渐进节奏/类型码/设备身份），再按模板重建，每次转换后自动跑 FIT 官方规范全量校验。已落地：跨品牌互转（佳明↔高驰，双向）、合并分段、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移、FIT 预览、注入真实设备信息防 Connect 重算爬升。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'、'预览fit'、'注入佳明设备'、'防重算爬升'、'改成高驰'、'改成佳明'、'改设备信息'、'apex'、'fenix'。"
version: 4.2.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌（佳明、高驰、颂拓、Polar、华为等）。

## 🔴 核心架构：规范驱动 + 双关卡（v4.1 定型）

**「模板」只是学习过程的临时中间产物，不是交付物。** 真正固化的资产是**规范**：
从真机文件学到格式规则 → 精炼成可读、可审、可入库的规范 → 转换/校验一律读规范。

```
① 学   真机 .fit ──→ templates/<name>.json       【中间产物，本地，不入库】
                      ↓ 精炼（剔除观测噪声）
② 定   规范                              【入库资产，跨设备可复用】
        references/profiles/<name>.md     可读文档（人看）
        references/profiles/<name>.json   机器可读规则
③ 用   convert / conformance / diff 三个工具一律读【规范】
       （规范缺失时才回退读模板，兼容旧流程）
```

| 脚本 | 作用 | 关键点 |
|---|---|---|
| ⭐ **`scripts/fit_lib.py`** | **唯一真相核心库** | DEF/MSG 解析、官方 profile、哨兵值、换算、编码器。所有脚本共用 |
| ⭐ **`scripts/fit_learn_template.py`** | **学**（中间步骤） | 真机 → 模板 JSON；含 dev 语义置信度推断、`single_message_values` 值快照 |
| ⭐ **`scripts/fit_distill_spec.py`** | **定规范** | 模板 → 规范（.md + .json）；**剔除 78~86% 的观测噪声** |
| ⭐ **`scripts/fit_convert_by_template.py`** | **转换** | 双向；**优先读规范**，回退读模板；转换后自动过门禁 |
| ⭐ **`scripts/fit_conformance_check.py`** | **规范门禁** | 11 节断言；FAIL 必须修，不得带 FAIL 交付 |
| ⭐ **`scripts/fit_diff_vs_template.py`** | **交付前全维度比对** | **门禁 PASS ≠ 与真机一致**；穷举比对结构+值+条数+逐点 |
| `scripts/export_profile.mjs` | 导出官方 profile | ⚠️ 必须同时导出 `base_type`（否则类型码检测全失效）|

### 🔴 为什么模板不入库（已实测验证）

| 事实 | 数据 |
|---|---|
| 模板体积 | 佳明 740KB / 高驰 63KB，其中 **78~86% 是逐点观测噪声** |
| 规范体积 | 佳明 102KB / 高驰 13KB（JSON）+ 9KB/3.4KB（可读 Markdown）|
| **规范自足性** | **移走模板目录后，转换+门禁+比对 3/3 全绿** |
| **产物等价性** | 规范路径与模板路径产出 **md5 完全相同** |

模板里含设备身份（manufacturer/product/productName），属私人数据；
规范里**只有格式规则**，设备身份也照写（那是公开的型号信息，非序列号）。
**结论：规范定干净了，根本不需要模板。**

### 标准工作流

```bash
# 0) 首次：若官方 profile 缺 base_type
node scripts/export_profile.mjs

# 1) 学 + 定规范（每台目标设备一次；规范入库后所有人可复用）
python scripts/fit_learn_template.py 真机.fit --name coros_apex4 --note "COROS APEX 4 42mm"
python scripts/fit_distill_spec.py coros_apex4          # 生成规范
python scripts/fit_distill_spec.py --all                # 精炼全部

# 2) 转换（读规范；换型号只换 --to）
python scripts/fit_convert_by_template.py 输入.fit 输出.fit --to coros_apex4

# 3) 规范门禁
python scripts/fit_conformance_check.py 输出.fit --temp coros_apex4 --src 输入.fit

# 4) ⚠️ 交付前全维度比对（必做！门禁 PASS 不等于与真机一致）
python scripts/fit_diff_vs_template.py 输出.fit --temp coros_apex4 --src 输入.fit
```

**换一台新表怎么办？** 学一次 → 精炼成规范，之后所有人复用。
**不需要改代码、不需要等我给参考文件**。

### ⚠️ 仓库里有什么、没有什么

| 内容 | 是否入库 | 原因 |
|---|---|---|
| **规范** `references/profiles/*.{md,json}` | ✅ **入库** | 只有格式规则，跨设备可复用、可评审 |
| 官方 profile `fit_profile_official.json` | ✅ 入库 | Garmin 官方定义，公开 |
| 工具脚本 `scripts/*.py` | ✅ 入库 | 通用能力 |
| **模板** `references/templates/*.json` | ❌ **不入库** | 学习过程的原始记录，78~86% 是观测噪声；含设备身份 |

**使用者拿到仓库后开箱即用**（规范已在库内）。若要支持新设备：

```bash
# 学 → 精炼（两步，之后规范可提交入库供他人复用）
python scripts/fit_learn_template.py 真机.fit --name coros_apex5 --note "COROS APEX 5"
python scripts/fit_distill_spec.py coros_apex5
```

⚠️ 若既无规范也无模板，转换/门禁/比对三个工具都会**显式报错并给出上述命令**，不会静默失败。

### 🔴🔴 交付前强制检查清单（缺一不可）

> 教训来源：2026-09-18 我只跑完门禁（PASS 114）就交付，少侠追问「是不是还有差异」，
> 一查果然有——`fileId.productName` 漏填。**门禁 PASS 只是必要条件，不是充分条件。**

| # | 检查项 | 命令 / 方法 | 不过怎么办 |
|---|---|---|---|
| 1 | **规范门禁** | `fit_conformance_check.py 产物 --temp X --src 源` | 有 FAIL 必须修，不得带 FAIL 交付 |
| 2 | **与真机全维度比对** | `fit_diff_vs_template.py 产物 --temp X --src 源` | 逐项看差异；结构差异必须为 0 |
| 3 | **SDK 交叉验证** | `_sdkcheck`（见经验 17）| 校验 `checkIntegrity=true` 且解码非空 |
| 4 | **条数守恒** | 与**源**比 record/lap/event 条数 | 必须一一相等；与真机比的是**数据量**差异，不算问题 |
| 5 | **值级核对** | 门禁 §11 自动做 | 规范里记为有值的字段，产物不得是哨兵 |

**三条硬规矩**：

1. **「与真机的差异」必须逐项解释**：要么是数据量差异（可接受），要么是格式差异（必须修）。
   不能只说「门禁过了」。
2. **发现差异先说清，别顺手抹平**：如果差异是合理的（如条数因活动长度不同），
   如实告知并给判据，不要含糊其辞。
3. **不得用「过程跑通了」替代「结果正确」** —— 接口 200 / 门禁 PASS 都不等于内容对。


## 🔴 三条不可违背的原则

1. **一切以官方 FIT 定义为准** —— 字段号/类型码/scale/offset 四样对齐。
   **字段号绝不靠记忆**（栽过多次）；**类型码查 `base_type` 而非 `type`**（逻辑类型会误导，见下）。
2. **照抄目标平台真机的写法，且由模板机械复刻** —— protocol/profile、消息集合、
   **渐进式布局节奏**、开发者字段声明顺序、设备身份，全部从模板读，不凭理解手写。
3. **绝不编造数据** —— 没有数据来源的字段一律留官方哨兵。**永不填推测值/经验值/气候值**。
   「真机有这个值」≠「我必须有」。

### 🔴 两个必须用 `base_type` 的场合（血泪）

官方 profile 每个字段有两个类型属性，**性质完全不同**：

| 属性 | 含义 | 用途 |
|---|---|---|
| `type` | **逻辑类型**（选 enum 表、显示用） | 判断语义、查枚举名 |
| `base_type` / `base_type_id` | **真实字节类型码**（写进 DEF 的那个） | ⚠️ **判类型码、比结构，只能用这个** |

早期导出只存了 `type` → 把官方的 `sint32` 误判成 `enum`，还派生出「高驰经纬度写 `0x00`」这个**错误结论**并以讹传讹。
2026-09-18 用 `@garmin/fitsdk` 交叉验证 + 全量比对：**两家的类型码都与官方完全一致，0 处偏离**。

### 🔴 铁律零：字段定义查官方 profile，绝不靠记忆

我给字段号和单位栽过多次跟头，最严重的一次：

| 我以为 | 官方定义 | 后果 |
|---|---|---|
| `f73` = 海拔 | **`f73` = enhancedSpeed** | 把速度当海拔 → 6000 米假海拔 |
| `f78` = 速度 | **`f78` = enhancedAltitude** | 漏掉真实海拔（6.6~16.2 米）|

**两条硬规则**：
1. **写映射前先查 `fit_profile_official.json`** —— 字段号、scale、offset 三样对齐数据才对
2. **优先取 enhanced 字段** —— 佳明的基础字段常是 `0xFFFF` 无效值，真值在 `enhancedXxx` 里
   （如 session `f14`/`f15` 无效，真值在 `f124`/`f125`；lap 同理在 `f110`/`f111`）

### 🔑 已实证的关键事实（勿再靠猜）

| 事实 | 结论 | 旧说法 |
|---|---|---|
| 渐进步局 | **高驰 6 种 DEF、佳明 3 种（27→29→30）**，两家都是渐进式 | ~~「佳明单一全字段」~~ ❌ |
| 类型码 | 两家均与官方一致，**无 `0x00` 特例**；`0x00` 实际在 record f42(activityType)，它本就是 enum | ~~「高驰经纬度写 0x00」~~ ❌ |
| dev16 | **≈ speed 但不等值**：中位绝对差 0.154 m/s，仅 33.6% 点位全等 → 判 `approx` | ~~「恒等于 f6」~~ ❌ |
| session.timestamp | 佳明 = 起始时间；高驰 = 结束时间。**两者都合法**，各有惯例 | — |
| 偏移哨兵 | 有符号类型哨兵是**该类型最大值右移一位**（S8=0x7F、S16=0x7FFF、S32=0x7FFFFFFF）；z 系列全 0；float 全 F | 曾把 S8 填 0xFF → 255℃ |
| 206 声明顺序 | 真机高驰把 206 放在首个用 dev 的 record **之后**，SDK 判合法 | 曾误判为违规 |

### dev16（Effort Pace）特别说明

- 它是**「最快 1KM / 最佳配速」的依赖通道**，缺失或错值会直接影响平台派生指标。
- **禁止**断言 `dev16 == speed`，也**禁止**用它反推 speed。
- 源文件无此字段时，转换器按模板的 `dev_semantics` 重建并标注置信度（`approx`），或留哨兵。
- 三种置信度：`faithful`（逐点全等）/ `approx`（形态一致、差值集中）/ `weak`（仅趋势一致）/<br>`none`（无依据，不用）。

## 能力速览

| 能力 | 命令 | 用途 |
|------|------|------|
| ⭐ **跨品牌互转** | **`fit_convert_by_template.py 输入.fit 输出.fit --to 模板名`** | **佳明↔高驰，模板决定布局，自动过门禁** |
| ⭐ **学目标平台模板** | **`fit_learn_template.py 真机.fit --name xxx`** | **新设备/新固件只需学一次** |
| ⭐ **规范门禁** | **`fit_conformance_check.py 文件.fit [--temp 模板] [--src 源]`** | **编辑与复查都必须跑** |
| 华为→FIT | `huawei_convert.py 导出.json` | 华为JSON→标准FIT（默认） |
| 合并分段 | `fit_merge.py / merge_fixed.mjs` | 多个FIT合为一个 |
| **FIT 预览** | **`fit_preview.py input.fit`** | **生成交互HTML，含地图+数据+计圈** |
| 体检 | `fit_healthcheck.py` | 上传前快速验证（语义层） |
| 导出TCX | `fit_to_tcx.py` | FIT→TCX兜底 |
| 改时间 | `fit_shift_time.py` | 字节级平移时间戳（原始/合并文件） |
| 改时间（SDK 保真版） | `shift_time_sdk.mjs` | SDK 解码→平移→重编码，保真保留设备信息+私有字段；处理压缩时间戳消息 |
| **注入佳明设备（防 Connect 重算爬升）** | **`inject_garmin_device.mjs`** | **第三方手表文件 → 真实佳明设备身份** |
| 只换身份不动布局 | `inject_coros_device.mjs apply 输入.fit` | 源本身已是高驰格式，仅改名称时用 |
| **抽取设备身份到私有区** | **`extract_devices.py`** | **从真实设备文件读身份，写入 `~/.workbuddy/private/fit_devices.json`** |
| 旧版单点转换（保留） | `fit_to_coros_mapped.py` | ⚠️ 硬编码高驰布局，仅作参考/兜底；**新任务请用 `fit_convert_by_template.py`** |

## 环境

```bash
# Python（数据解析、体检、时间戳平移、华为转换、模板学习与转换）
pip install fitdecode fitparse

# Node.js（官方 profile 导出、佳明兼容合并、FIT 编码）
npm install @garmin/fitsdk
```

## 快速使用

```bash
# 查看可用脚本 / 已有模板
ls scripts/
python scripts/fit_learn_template.py --list

# ⭐ 跨品牌转换（推荐路径）
python scripts/fit_learn_template.py 真机.fit --name coros_apex4 --note "COROS APEX 4 42mm"
python scripts/fit_convert_by_template.py 佳明活动.fit 高驰活动.fit --to coros_apex4
python scripts/fit_conformance_check.py 高驰活动.fit --temp coros_apex4 --src 佳明活动.fit

# 合并分段活动（Python 字节级，高驰可用）
python scripts/fit_merge.py seg1.fit seg2.fit -o merged.fit

# 合并分段活动（Node.js Encoder，佳明 Connect 兼容）
node scripts/merge_fixed.mjs

# FIT 体检（上传前验证）
python scripts/fit_healthcheck.py merged.fit

# FIT 预览（生成交互式 HTML 页面，含地图+全字段+计圈）
python scripts/fit_preview.py input.fit
python scripts/fit_preview.py input.fit -o preview.html

# TCX 导出（上传兜底）
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 时间戳平移（字节级，原始/简单合并文件）
python scripts/fit_shift_time.py input.fit --delta-hours -12

# 时间戳平移（SDK 重编码版，保真：适配含压缩时间戳消息的文件，
# 且保留已注入的佳明设备信息 + 第三方私有开发者字段）
node scripts/shift_time_sdk.mjs input.fit output.fit -12

# 官方 SDK 重建
python scripts/fit_rebuild_sdk.py merged.fit -o rebuilt.fit

# 华为手表 → FIT（默认）/ GPX / TCX
python scripts/huawei_convert.py 华为导出.json                     # 默认 FIT
python scripts/huawei_convert.py 华为导出.json --format gpx        # GPX
python scripts/huawei_convert.py 华为导出.json --format tcx        # TCX
python scripts/huawei_convert.py 华为导出.json --format all        # 全部三种

# 批量华为数据 → 按类型分目录输出 FIT
python scripts/huawei_batch_convert.py 华为导出.json --output-dir ./华为运动FIT
```

## 规范门禁覆盖范围（11 节）

`fit_conformance_check.py` 把 `references/fit_format_spec.md` 逐条实现为断言，
**不再靠人记得去查规范**。退出码 0 = 全 PASS（允许 WARN），1 = 存在 FAIL。

| 节 | 覆盖 | 要点 |
|---|---|---|
| §1 文件头 | header_size / protocol / profile_version / data_size / magic / 双 CRC | 头部 CRC 与尾部 CRC 都要 |
| §2 记录流结构 | DEF 结构（reserved 恒 0/endian/字段数）、local 分配、完整解析无 desync | `integrity()` 必须 True |
| §3 类型码 | 类型码合法性、size 与 base type 相容、**逐字段 vs 官方 `base_type`** | 官方字段偏离 → FAIL |
| §4 无效哨兵 | 声明未填值的字段应为哨兵；有符号类型不许出现 0xFF 族误填 | 厂商偶有特例 → WARN |
| §5 scale/offset | 物理量换算合理性（**按官方字段名**，不硬编码字段号）| 温度 255℃ 这类必被抓 |
| §6 消息顺序 | fileId 首条 / 207 先于 206 / 206 先于引用它的消息 | 真机个别顺序差异 → INFO |
| §7 开发者字段 | `ref_index` 必须指向已声明的 206；206 字段完整性 | 第三字节是 207 索引≠类型码 |
| §8 时间戳 | epoch 正确 / 单调不减 / 区间闭合 / session 语义 | 佳明=起点、高驰=终点都接受 |
| §9 跨字段一致性 | 距离单调、lap 合计≈session、平均速度自洽、**零速点** | 按官方字段名解析（enhancedSpeed/ speed） |
| §10 与源比对 | record 条数、海拔/速度逐点最大差异、**零速点可比区间** | ⚠️ 只在两端都有该字段的点位比对 |
| §11 与模板比对 | protocol/profile、消息集合、**渐进布局逐位一致**、dev 声明次数、**值级核对** | 布局一致 ≠ 值完整：模板有值的字段产物不得留哨兵 |

### ⚠️ 「缺消息」的判读规则（避免误报）

| 情形 | 判定 | 说明 |
|---|---|---|
| 源文件**也**没有该消息 | **INFO/OK** | 跨品牌必然，如高驰→佳明时的佳明私有 `gpsMetadata` |
| 源文件**有**、产物却丢了 | **FAIL** | 真丢数据，必须修 |

同理，「模板某字段无值」→ 写官方哨兵；「模板整条消息源无对应数据」→ 省略该消息，**不填哨兵占位**。
两者语义不同：「这条有该字段但无值」vs「这类数据不存在」。

## 实测验证结果（2026-09-18）

| 方向 | 产物 | 门禁结果 | 数据保真 |
|---|---|---|---|
| 佳明 fenix8 → 高驰 APEX 4 | 172,572 B | **PASS 111 / FAIL 0 / WARN 0** | 海拔逐点最大差 **0.000 m**；速度逐点最大差 **0.00000 m/s**；dev16 有效（0~4.507 m/s）；零速点 24 个保留 |
| 高驰 APEX 4 → 佳明 fenix8 | 687,694 B | **PASS 111 / FAIL 0 / WARN 0** | record 条数一致（10554）；3 种渐进布局逐位与模板一致 |

SDK 交叉验证：`@garmin/fitsdk` 解析产物 **0 errors**（与真机文件同级）。


## 为第三方手表文件注入真实佳明设备信息（阻止 Garmin Connect 重算爬升）

**问题**：高驰/华为/颂拓等第三方手表产出的 FIT 上传 Garmin Connect 后，爬升常被「二次加工」——要么显示「未知设备」，要么被用 DEM 地形数据替换每个轨迹点的海拔（高程校正）。

**原理（已实测验证）**：
1. Garmin Connect 对上传文件做**服务端校验** `(product, UnitID)` 是否匹配真实佳明设备；不匹配 → 显示「未知设备」。
2. 是否带**气压高度计**决定高程校正开关：带气压计 → 校正默认关、直接用设备记录海拔；不带 → 用 DEM 地形数据替换每个轨迹点 = 二次加工爬升。
3. 因此：**把 file_id + device_info 改成「真实佳明带气压计设备」**，Connect 即识别为可信设备，关掉校正 → 爬升按原始数据、不再重算。

**关键约束——设备信息存在私人区域，绝不写死在脚本/skill 里**：
- 私人设备文件：`~/.workbuddy/private/garmin_devices.json`（可用环境变量 `GARMIN_DEVICES_JSON` 覆盖路径）。
- 该文件**不随 skill 的 GitHub 更新而变动**，也不进任何公开仓库。Unit ID 属私人数据。
- 脚本 `inject_garmin_device.mjs` 运行时才读取该文件。

**工作流（两步）**：

```bash
# 0) 首次：从你自己的真实佳明活动 .fit 抽取设备信息，存进私人区域
#    （任意佳明手表的活动备份 / 导出的 .fit 均可，只要是真设备产出）
node scripts/inject_garmin_device.mjs extract 真实佳明.fit --name fenix8

# 1) 把私人区域里的设备信息注入到任意第三方手表 FIT
node scripts/inject_garmin_device.mjs apply 高驰.fit --device fenix8 --out 高驰_fenix8.fit
#    不写 --device 时取私人文件里的 default 项；不写 --out 时默认 <原名>_fenix8.fit

# 把 *_fenix8.fit 传到 Garmin Connect 即可（设备名正确 + 爬升不再被重算）
```

**说明**：
- `extract` 会取真实佳明文件中 `sourceType=local` 的主设备（manufacturer/product/serialNumber/softwareVersion 等）。
- `apply` 全量重编码：**保留全部原始数据（含第三方私有开发者字段，如高驰 Effort Pace），仅替换 file_id 设备身份、并把 device_info 改为单条佳明设备（删掉原第三方 device_info）**。
- 校验：输出 `integrity=true`、device_info 仅一条佳明、爬升原值保留。
- 一台佳明设备只需 `extract` 一次，之后所有第三方文件都能 `apply`。有多台佳明就 `extract --name xxx` 多次，apply 时用 `--device xxx` 选择。

**注意**：若手上没有真实佳明设备，无法凭空编造可信 Unit ID——Connect 会判为「未知设备」。务必用自己/朋友的佳明活动抽取。

## 🔑 另外三条铁律（每条都返工过）

**1. 设备身份从私有区域读，不写死**

私有区域：`~/.workbuddy/private/fit_devices.json`
（不随 GitHub 更新变动，不进公开仓库；Unit ID / serialNumber 属私人数据）

```bash
python scripts/extract_devices.py             # 抽取 / 刷新
python scripts/extract_devices.py --show      # 只看现有内容
```

`fit_learn_template.py` 会把学到的设备身份自动同步进私有区（**含 serialNumber**），
而公开的模板 JSON 里**只存 manufacturer/product/productName**，不含序列号。

**2. 爬升/下降直接搬源值，绝不重算、绝不拦截**

高驰 session `f22`=爬升、`f23`=下降（fitdecode 权威命名）。
源数据是多少就搬多少——**5 米也是真实值**（平坦路线），不要因为"看着小"就当占位值丢掉。

**3. 不要只靠 SDK 重编码跨品牌**

⚠️ `@garmin/fitsdk` 的 Encoder 按**佳明 profile** 写字段，产出**不符合高驰规范**。实测差异：

| global | SDK 产物 | 高驰规范 |
|---|---|---|
| `23` device_info | 6 字段（多了 deviceIndex/sourceType）| **3 字段** |
| `19` lap | 40 字段 | **24 + dev1** |
| `18` session | 51 字段 | **24 + dev1** |
| `20` record | 9 字段、顺序错 | **15 + dev1（6 段渐进）** |
| `0` file_id | 字段顺序不同 | 见模板 |

**✅ 正确做法**：走 `fit_convert_by_template.py`（按模板拼字节，不经过佳明 profile）。
SDK 在本 skill 里的定位是**交叉验证工具**（解析产物查 error 数），不是转换引擎。

## 脚本说明

| 脚本 | 功能 | 适用平台 |
|------|------|---------|
| **`fit_lib.py`** | **核心库：解析/编码/官方 profile/哨兵值（所有脚本共用）** | **通用** |
| **`fit_learn_template.py`** | **真机 → 模板 JSON（学布局/节奏/类型码/身份/dev语义）** | **通用；`--list` 看已有模板** |
| **`fit_convert_by_template.py`** | **跨品牌双向转换（模板驱动 + 自动门禁）** | **佳明↔高驰 ✅ 实测** |
| **`fit_conformance_check.py`** | **11 节 FIT 规范门禁；退出码 1 = 有 FAIL** | **通用，强制** |
| **`fit_diff_vs_template.py`** | **产物 vs 真机模板全维度比对（8 节）；交付前必跑** | **通用，强制** |
| `export_profile.mjs` | 从 `@garmin/fitsdk` 重导官方 profile（含 `base_type`）| 需 node |
| `fit_merge.py` | 字节级拼接，保留全部原始消息 | 高驰 ✅ / 佳明 ❌ |
| `merge_fixed.mjs` | **protocol=2 Encoder 核心消息+设备注入** | **佳明 ✅ 实测通过** |
| `fit_healthcheck.py` | 语义体检（时间/距离单调性、字段完整性） | 通用 |
| `fit_preview.py` | **FIT → 交互式 HTML 预览（地图+Session+全字段+计圈）** | **通用，浏览器打开** |
| `fit_to_tcx.py` | FIT → TCX 导出 | 上传兜底 |
| `fit_shift_time.py` | 平移时间戳 | 规避去重（字节级，原始/简单文件） |
| `shift_time_sdk.mjs` | SDK 解码→平移 timestamp→重编码，保真保留全部数据 | 适配含压缩时间戳消息的文件 |
| `fit_rebuild_sdk.py` | 官方 Garmin SDK 重建 | 丢弃私有消息 |
| `huawei_convert.py` | **华为 JSON → FIT/GPX/TCX（默认 FIT）** | **华为 → 高驰/佳明 ✅** |
| `huawei_batch_convert.py` | **批量华为 JSON → 按类型分目录输出 FIT** | **华为全量数据 → 高驰/佳明 ✅** |
| `fit_encode.mjs`（在 skill 根目录） | FIT 编码器（供 huawei_convert.py 等内部调用） | 依赖 @garmin/fitsdk |
| `inject_garmin_device.mjs` | 注入真实佳明设备信息（extract/apply），防 Connect 重算爬升 | 依赖 @garmin/fitsdk；身份读私有区 |
| `inject_coros_device.mjs` | 只换设备身份为高驰（字段布局不动） | 源本身已是高驰格式时用 |
| `fit_to_coros_mapped.py` | ⚠️ 旧版硬编码高驰转换 | **已由 `fit_convert_by_template.py` 取代**，仅留兜底 |
| `extract_devices.py` | 从真实设备文件抽取身份，写入私有区 | 通用 |

### 注意

- 同一份合并文件在各平台表现不同。`fit_merge.py` 在高驰正常上传，`merge_fixed.mjs` 在佳明 Connect 正常上传。
- 华为数据转换默认 FIT：固定 record 字段布局 + GCJ02→WGS84 + 无硬编码爬升，对任何解析器都健壮。
- GPX/TCX 可事后从 FIT 转换（`fit_to_tcx.py`），但会丢失计圈、训练效果等数据。
- **每次改完 FIT 必跑 `fit_conformance_check.py`**；跨品牌转换时加 `--temp` 与 `--src` 参数，
  才能同时校验「符合官方规范」和「忠实于源数据」。


## FIT 预览（通用能力）

一键将任意 FIT 文件生成为交互式 HTML 页面，在浏览器中查看轨迹和完整数据。

```bash
# 基本用法：生成 input_preview.html
python scripts/fit_preview.py input.fit

# 指定输出文件名
python scripts/fit_preview.py input.fit -o my_activity.html
```

预览页面包含：
- **轨迹地图** — 高德底图（国内可访问），WGS84→GCJ02 自动转换，起点/终点标记
- **8 项概要卡片** — 距离/时长/配速/心率/步频/卡路里/训练效果/数据量
- **设备信息** — 制造商/序列号/产品/类型/创建时间
- **Session 摘要** — 15 个字段含配速/速度/心率/步频/训练效果等
- **全字段统计** — 每个 record 字段的 min/max/avg + 有效点占比
- **计圈详情** — 表格展示每圈距离/时长/配速/心率/步频/卡路里

预览页面是纯静态 HTML，双击即可在浏览器打开，无需额外工具。

## 华为→FIT 核心规范

### 固定 record 字段布局

**规范**：所有 record 用完全相同的字段集合，缺失值用 FIT invalid 哨兵值（heartRate/cadence=255, enhancedAltitude=65535, speed=0）。避免多字段布局导致第三方解析器字段错位（轨迹"飘到国外"）。

### GCJ02→WGS84 转换

华为数据标记为 GCJ02（国测局加密），FIT/GPX/TCX 标准应使用 WGS84。生成前对每个 GPS 点做反算转换。

### 爬升/下降不自算

各平台（高驰/佳明/华为）去噪算法各异，写死会导致不一致。不在 session/lap 中写入 totalAscent/Descent，让平台用 record 的 enhancedAltitude 自行重算。

### manufacturer/product 遵从原始数据

**原则**：所有脚本的 manufacturer/product 继承自原始数据，**不默认写任何品牌**。
仅在用户**明确要求**改设备身份时才注入对应品牌信息：

| 用户要求 | 用什么 |
|---|---|
| 「改成高驰设备」 | `inject_coros_device.mjs`（身份读私有区 `coros_apex4`）|
| 「修复佳明 Connect 爬升显示」 | `inject_garmin_device.mjs`（身份读私有区 `garmin_fenix8`）|
| 未明确要求 | **不动设备信息**，继承原始数据 |

- 华为数据（无 ANT+ manufacturer ID）：默认 `0xFF (development)`，product=0
- 合并分段：从第一段原始文件的 file_id 读取 manufacturer/product 并继承
- 字节拼接（fit_merge.py）：不做修改，保留原始消息

### 华为 sportType 映射

详见脚本内 `SPORT_TYPE_NAMES` 字典。推断规则优先级高于编号映射：
- 骑行/游泳 → 保留原始类型
- 有步频 + 配速≤10 → Running
- 配速>10 → Walking
- 无GPS + 有心率 → Other

## 已知问题

- sportType=117（纯心率记录，无GPS）会输出 `_HRonly.tcx`
- 华为气压计海拔可能有整体偏移（实测 -34m），脚本自动检测并修正
- `partTimeMap:{1.0:335.0}` 为非标准 JSON 格式，脚本自动修补
- **华为数据转 FIT 的爬升偏高约 2 倍**：华为气压计相邻采样点存在 0.5~1m 的随机噪声，FIT 中 altitude 字段按逐点累加方式计算总爬升时会将噪声也计入。华为健康 APP 有自研降噪算法所以显示正常（如 80m），但导出的 FIT 中 altitude 是原始值，高驰/佳明等平台读到时同样会算出偏高值（如 162m）。这不是编码错误，是华为气压计原始数据精度问题。详见 SKILL.md 经验沉淀章节。

## skill 经验沉淀（2026-07-22）

### 1. altitude 字段的 FIT 缩放规则
- `altitude` 字段类型是 **sint16，单位 0.5m**。写入时必须 `Math.round(米值 * 2)`，不然 decode 后值减半。
  - 例：10m 海拔 → 写入 `20`，decode 后读取为 `20 * 0.5 = 10m`。
  - `enhancedAltitude` 字段类型 **uint16，单位 5m，偏移 500m**。但 @garmin/fitsdk 的 Encoder 自动处理缩放，直接写米值即可。
- `altitude` 的 invalid 值是 `0x8000` (32768 = sint16 最小负值)，不是 `65535`。
- **高驰 APP 读取 `altitude` 字段计算爬升，不认 `enhancedAltitude`**。如果只写了 `enhancedAltitude` 没写 `altitude`，爬升显示为 0。
- Session/Lap 的 `totalAscent/totalDescent` 写入后高驰会直接使用，不会自行计算。

### 2. 华为海拔数据噪声与爬升翻倍
- 华为气压计海拔有 0.5~1m 级别噪声（1239 个采样点中 293 次正差、288 次负差）。
- 逐点累加（每个正差都计为爬升）会把噪声也计入，导致爬升翻倍。
  - 环东半马实际爬升约 80m → FIT 内 altitude 逐点累出 162m（约 2 倍）。
  - 高驰使用 altitude 字段同样会算出 ~162m，因为它也做逐点累加。
- **华为原始 JSON 中有 `mTotalDescent: 944`，但这个值是华为自身的处理，不代表实际。**
- **结论：华为数据源的爬升放大是华为气压计精度限制导致的，不是编码错误。** 要让爬升准确，要么（1）在写入 altitude 前做去噪（不推荐，会篡改原始数据），要么（2）告诉用户华为数据爬升会偏高 ~2 倍。
- 跨平台爬升显示差异：华为健康 APP 显示 80m（有自己的降噪算法）→ FIT 显示 162m（逐点累加）→ 都是同一组原始数据不同处理方式。

### 3. 去噪不可取
- 用户明确要求**不篡改原始数据**。不要自作聪明做去噪、过滤、缩放修改。
- 华为原始海拔数据是多少就写多少，误差是华为自身精度问题，不是工具的问题。

### 4. 计圈距离：Haversine 替代线性插值
- 之前距离按时间比例分配（`total_dist * frac`），导致每圈偏小 3%（965m 而非 1000m）。
- 改用 **Haversine 逐点累加** 后，计圈精度提升到 998~1002m（偏差 <0.3%）。
- 在 `huawei_convert.py` 的 `export_fit` 函数中实现，同时重写了计圈逻辑为「按 1000m 距离触发切圈」。

### 5. FIT 预览页面 tab 不显示的已知 bug（已修复）
- `fit_preview.py` 的 HTML 模板中 panel 的 id 是 `ps`/`pf`/`pl`（缩写），但 JS 切换时拼的是 `p`+`data-tab` = `psession`/`pfields`/`plaps`。
- **这是 skill 模板本身的 bug**，与修改者无关。修复：统一使用长 ID `psession`/`pfields`/`plaps`。

### 6. 消息类型完整保留
- 使用 `@garmin/fitsdk` 的 `Encoder` 重建 FIT 时会丢弃私有消息类型（如 `gps_metadata`, `timestamp_correlation`），但标准消息（file_id, device_info, sport, event, record, lap, session, activity 等）全部保留。
- 如果接收平台做严格的消息类型校验（如某些 COROS 版本），需要确保 `laps`、`splits`、`event` 等消息都存在。

### 7. 第三方手表文件注入真实佳明设备信息，阻止 Connect 重算爬升（2026-08-01 实测）
- **现象**：高驰/华为等产出的 FIT 传 Garmin Connect 后爬升被二次加工（显示「未知设备」或用 DEM 重算海拔）。
- **根因**：Connect 服务端校验 `(product, UnitID)` 是否匹配真实佳明设备；且设备是否带气压高度计决定高程校正开关（带→关校正用设备海拔；不带→用 DEM 替换每个轨迹点）。
- **解法**：全量重编码，把 `file_id` + `device_info` 改成「真实佳明带气压计设备」。注意是**真实**——`serialNumber(Unit ID)` 必须来自真实佳明活动，编的会被判「未知设备」。
- **fenix 8 关键值**（示例，来自用户私人区域，勿写死）：manufacturer=`garmin`(1)、product=`4536`、带气压计 → 校正默认关。
- **实施要点**：
  - 设备数据存私人区域 `~/.workbuddy/private/garmin_devices.json`，**不进 skill/脚本**（Unit ID 属私人数据，且避免被 GitHub 更新覆盖）。
  - `extract` 从真实佳明 .fit 抽主设备信息入私人文件；`apply` 读取后注入第三方 FIT。
  - `apply` 必须**删掉原第三方 device_info**，只留单条佳明 device_info（否则 Connect 仍可能按无气压计设备处理、照常开校正）。
  - 保留全部原始数据含第三方私有开发者字段（decode 时用 `developerDataIdMesgs`+`fieldDescriptionMesgs` 构 `fieldDescriptions` 传给 `Encoder`）。
  - 写 devDataId/fieldDescription 时需 `delete o.key`（key 是 decode 加的伪字段）。
  - 脚本：`scripts/inject_garmin_device.mjs`（依赖 @garmin/fitsdk，已在 skill 目录 `npm install`）。
- **验证**：`checkIntegrity()=true`、device_info 仅一条佳明、爬升原值保留。

### 8. 字节级时间戳平移脚本在 SDK 重编码文件上会 desync（2026-08-01）
- **现象**：`fit_shift_time.py`（字节级定点修补）对 `inject_garmin_device.mjs` 产出的 SDK 重编码文件报「数据消息缺少定义 local=N」、偏移错位。
- **根因**：SDK 重编码产物含**压缩时间戳消息**（record/event 的 timestamp 字段 header bit7 置位，引用前面定义的 local 号）。字节级脚本按固定字段布局改写时间戳，遇到压缩消息时消息定义索引对不上 → desync。
- **解法**：用 `scripts/shift_time_sdk.mjs` 走 `@garmin/fitsdk` 解码→平移所有 Date 字段（timestamp/timeCreated/startTime）→重编码。保真且可靠，且天然保留 fenix8 设备信息、爬升原值、第三方私有开发者字段。
- **用法**：`node scripts/shift_time_sdk.mjs 输入.fit 输出.fit -12`（最后参数=小时，负=往前；不写输出默认 `<原名>_morning.fit`）。
- **经验**：凡是对「经 SDK 重编码（含 inject/merge_fixed 产物）」的文件做时间平移，一律用 SDK 版，不要字节级脚本。

## 工作流

```
① 学模板（每台设备一次）
   真机.fit ──→ fit_learn_template.py --name xxx ──→ references/templates/xxx.json

② 转换（模板决定一切，换型号只换 --to）
   源.fit ──→ fit_convert_by_template.py --to xxx ──→ 目标.fit ──→ 自动跑门禁

③ 门禁（编辑与复查都必须跑）
   任意.fit ──→ fit_conformance_check.py [--temp xxx] [--src 源.fit] ──→ PASS 才交付

其他路径：
   原始分段 ──→ fit_merge.py / merge_fixed.mjs ──→ .fit ──→ 上传各平台
                                                   └── fit_to_tcx.py ──→ .tcx（兜底）
   华为JSON ──→ huawei_convert.py ──→ .fit（默认，fixed layout+WGS84）──→ 高驰/佳明
                                     └── .gpx / .tcx（--format gpx/tcx）
```

## 经验沉淀（2026-09-18 架构重构批次）

### 9. 为什么从「硬编码转换」改成「模板驱动」

**旧架构的病根**（也是被明确指出的问题）：

| 症状 | 根因 |
|---|---|
| 换个高驰型号就转坏 | 字段布局硬编码成 `COROS_DEFS` 常量 |
| 只能单向（→高驰）| 反向转换没实现 |
| 校验只覆盖部分规范 | 检查项散落、靠人记得查 |
| 出问题要靠人工给参考文件对着改 | 没有「机器读真机」这一步 |

**新架构**：真机文件 → 模板 JSON（机器学）→ 语义层解码 → 按模板重建 → 自动门禁。
**换任何设备都只需学一次模板，不改代码。**

### 10. 类型码必须查 `base_type`，不是 `type`

一次误导性极强的坑：官方 profile 每个字段有 `type`（逻辑类型）和 `base_type`（真实字节类型码）。
早期导出脚本只存了 `type`，导致：
- 结构比对大面积误报「不在官方定义中」（佳明文件曾报 857 条）
- 派生出一个**错误结论**「高驰把经纬度类型码写成 `0x00` enum」，还写进了文档

修正后：**两家真机的类型码都与官方完全一致，0 处偏离**。
`0x00` 实际出现在 record `f42`(activityType) 上，它本来就是 enum —— 被错记成了经纬度。

🔑 **判据口诀**：判断「结构对不对」看 `base_type`/`base_type_id`；判断「语义是什么」看 `type`。

### 11. 渐进式布局两家都有，别只给高驰实现

经 `FitFile.layouts(20)` 实证：

| 设备 | record DEF 种类 | 字段数演进 |
|---|---|---|
| 高驰 APEX 4 | **6 种** | 3 → 6 → 10 → 11 → 14 → 15（+dev16）|
| 佳明 fenix 8 | **3 种** | 27 → 29 → 30 |

复刻节奏才能让解析器正确判断「这些字段从这一刻起才有值」，
否则可能跳过派生指标（最快 1KM / 最佳配速）。

### 12. dev16 ≠ speed（推翻旧结论）

用佳明 13.6km 与高驰同路段逐点对照：

| 指标 | 值 |
|---|---|
| 中位绝对差 | 0.154 m/s |
| 完全相等点位占比 | 33.6% |

→ 它是**更平滑、未量化的速度版本**，语义近似而非等值。
**禁止**断言等值、**禁止**反推 speed。缺失时按模板 `dev_semantics` 重建（标注 `approx`）或留哨兵。

### 13. 门禁的「缺消息」判读与「哨兵 vs 省略」区别

| 情形 | 正确动作 |
|---|---|
| 模板某字段，源消息存在但该字段无值 | 写**官方哨兵**（语义：这条有这字段，本次无值）|
| 模板整条消息，源完全没有对应数据 | **省略**该消息（语义：这类数据不存在，不造假占位）|
| 模板要的消息，**源文件也没有** | INFO/OK —— 跨品牌必然，不是转换错误 |
| 模板要的消息，**源文件有但产物丢了** | **FAIL —— 真丢数据，必须修** |

这条区分是 2026-09-18 修掉反向转换「缺 29 种消息」误报的关键。

### 14. 门禁自身也会出错 —— 校验不过先怀疑脚本

本次修掉的两个门禁缺陷（都是脚本问题，产物本身正确）：

| 现象 | 根因 | 修法 |
|---|---|---|
| 报「无速度=0 的点」 | §9 硬编码 `f.value(m, 6, ...)` 找 speed，但佳明模板用 `enhancedSpeed(73)`，永远读到 0 个点 | 改为**按官方字段名**解析（先 enhancedSpeed 再 speed）|
| 报「缺 29 种消息」FAIL | 没区分「源本身没有」与「转换丢了」 | 引入 `--src` 比对，源同缺 → OK/INFO |
| PASS 条目却打印失败文案（「应为 16，实际 16」）| `check()` 在 PASS 时也打 `detail`（该参数语义是失败原因）| PASS 只显示 `note` |

🔑 **教训**：报错先问「是产物错了还是检查器错了」，用独立手段（SDK 交叉验证、直接读原始字节）裁定，
别急着改产物。

### 15. SDK 的正确用法：交叉验证，不是转换引擎

`@garmin/fitsdk` 按佳明 profile 编码，直接拿来转高驰会写错布局。
但在本流程里它有两个不可替代的作用：

1. **导出官方 profile**（`export_profile.mjs`，注意要带 `base_type`）
2. **交叉验证产物**：解析产物看 error 数，与真机文件同级别 = 结构可信

实测：两个方向的产物 SDK 解析均 **0 errors**。

### 16. 零速点跨品牌对比必须在「可比区间」内做（假警报复盘）

**现象**：佳明 13.6km 转高驰后，SDK 统计零速点「源 12 个 → 产物 10 个」，看着像丢了 2 个。

**追查结论：不是数据丢失，是渐进式布局的固有结构差异。**

| 点位索引 | 佳明（27 字段布局起） | 高驰（3→6→10 字段布局） |
|---|---|---|
| 0 | 有 `enhancedSpeed` | 布局仅 3 字段，**无 speed** |
| 1、2 | 有 `enhancedSpeed`（值为 0）| 布局 6 字段，**无 speed** |
| ≥3 | 有 | 布局含 `speed` ✅ |

- 高驰真机前 3 个点位同样**没有 speed 数据**，这是它的布局定义，不是转换丢的。
- 佳明索引 1、2 的 `speed=0` 在高驰结构上**物理无处存放**（该布局没声明这个字段）。
- **可比区间（索引 ≥3）内：4071 点逐点完全一致，10 个零速点一个不差。**

🔑 **教训**：跨品牌比对任何字段前，必须先判断「两端该点位是否都声明了该字段」。
按索引硬对会把结构差异误读成数据丢失。已写进 §10（新增「速度逐点一致（可比区间 N 点）」
断言 + 显式告知多少点位不可比及原因）。

### 17. SDK 交叉验证的三个坑（会给出「假通过」）

用错 SDK 比报错更危险 —— 它会安静地返回空结果，让比对全部蒙混过关：

| 坑 | 错法 | 后果 | 正解 |
|---|---|---|---|
| 传参 | `new Decoder(buffer)` | `checkIntegrity()=false`、messages 空、**errors 也空**（异常被内部 catch 吞掉）| `new Decoder(Stream.fromBuffer(buf))` |
| 取消息 | `dec.read(); dec.messages` | 读不到（消息在 `read()` 返回值里）| `const res = new Decoder(...).read(); res.messages` |
| 比对 | `undefined vs undefined` 判相等 | **全 nil 也报「全部一致」** | 断言项必须 `a != null && b != null`，且先校验解码非空 |

🔑 **铁律：交叉验证脚本必须自带「解码非空」前置断言** —— 两端 record 条数为 0 时直接判不可信并退出，
绝不让「空 vs 空」蒙混过关。

### 18. 门禁 PASS 但第三方比对报差异时，先查「比较口径」

本次门禁 **PASS 113 / FAIL 0 / WARN 0**，而 SDK 逐点比对报出零速点不一致。
两者矛盾时按顺序排查：①产物错了？②门禁错了？③**比较口径错了**？——这次是第三种。

裁定手段：直接读原始字节 + 拿真机同构文件对照（不依赖任何一方）。
**别急着改产物** —— 错的可能只是判据。

### 19. 布局一致 ≠ 值完整（2026-09-18 追问「是不是还有差异」后揪出）

**触发**：少侠问「你这个和高驰的模板文件是不是还有差异」。我做全维度逐项比对，
发现门禁当时虽是 PASS，但确有一处真差异：

| 字段 | 产物（修复前）| 高驰真机 |
|---|---|---|
| `fileId` f8 `productName` | **None（哨兵）** | `COROS APEX 4 42mm` |

**根因**：`_make_fileid_src()` 只写了 manufacturer / product / serialNumber，
**从没写 productName**。高驰真机在 `fileId(f8)` 与 `deviceInfo(f27)` **两处**都写产品名，
我只写了后者。

**为什么门禁没抓到**：原 §11 只比「布局签名」（字段号 / 长度 / 类型码逐位一致）。
fileId 的布局**完全一致** —— 字段在、类型对，只是**填了哨兵**。布局比对天生看不到值。

**修法（三处）**：
1. `fit_convert_by_template.py`：`_make_fileid_src()` 补 `productName`
2. `fit_conformance_check.py` §11 新增**值级核对**：读模板的 `single_message_values`
   （真机有值字段快照），若模板该字段有值而产物是哨兵或缺失 → **FAIL**
3. `fit_learn_template.py`：学模板时一并采集 `single_message_values`
   （只收身份 / 名称类字段：manufacturer、product、productName、type、sport 等，
   刻意排除随活动变化的时间戳与统计量，避免误报）

**回归验证**（证明断言真有效，不是摆设）：
拿修复前的旧产物跑新门禁 → **EXIT=1**，精确报出
`g=0(fileId) 模板有值的字段产物未填 —— 1 个字段为空: f8(模板='COROS APEX 4 42mm' → 产物值为哨兵)`；
修复后重跑 → **PASS 118 / FAIL 0 / WARN 0**（断言数由 114 增至 118）。

🔑 **教训**：结构校验（布局 / 类型码）与内容校验（值是否填了）是**两个维度**，必须都有。
只比结构会漏掉一类「空洞」—— 字段都在，但关键值全是哨兵。
**门禁 PASS ≠ 与真机一致**，关键交付前还要做一次穷举式全维度比对。

### 20. 用 shell 传多行文本改 md 会被反引号劫持（工具链教训）

我用 `python -c "...长字符串..."` 往 SKILL.md 追加含反引号的 Markdown 段落，
shell 把反引号当命令替换执行 → 文本里的 `` `fileId` ``、`` `productName` ``
全被替换成空，段落变成残缺（`f8` 一行只剩空表格）。

**结论**：改文档一律用编辑工具（Edit / Write）直接写文件，
**不要**经 `python -c` 或 `echo` 拼接含反引号 / `$` / 引号的文本。
（本机 PATH 已坏，`grep`/`head`/`tail` 均不可用，管道也会踩坑 —— 复杂逻辑写 .py 文件再跑。）

### 21. 交付流程缺陷：跑完门禁就交付（2026-09-18 最该记的一条）

**问题**：本轮我先跑门禁拿到 PASS 114，就直接宣布完成并交付。少侠追问「是不是还有差异」
才发现 `fileId.productName` 漏填 —— **门禁根本没覆盖这个维度**。

**根因是流程缺失，不是某个 bug**：
- 我把「门禁 PASS」当成了「交付完成」的充分条件，但门禁只检查**我写进去的断言**；
  我没想到的维度，它永远查不到。
- 正确认知：**门禁是必要条件，不是充分条件**。交付前还必须做**穷举式**比对。

**固化措施**：新建 `scripts/fit_diff_vs_template.py`，把这次临时写的比对脚本变成常备工具，
并写进 SKILL.md 顶部的「交付前强制检查清单」（5 项，缺一不可）。
清单里三条硬规矩：①与真机的差异必须逐项解释；②差异合理就如实说并给判据；
③不得用「过程跑通」替代「结果正确」。

### 22. 写比对工具时的两个真 bug（同日踩到）

**① 生成器表达式当元组用 → 全部误报**

```python
# ❌ 错：圆括号是生成器，只能迭代一次，与 list 比较永远 False
tlays = [((f['num'], f['size'], f['base_type']) for f in lay['fields']) for lay in ...]
# ✅ 对：tuple(...)
tlays = [tuple((f['num'], f['size'], f['base_type']) for f in lay['fields']) for lay in ...]
```

后果：9 种消息布局**全部**报「与模板不符」假警报，而实际上逐位一致。
**教训**：比对工具自己也会撒谎，**必须做回归测试**（造正确样本 + 造有 bug 样本，看它能否区分）。

**② 条数守恒不能一刀切**

`deviceInfo(23)` 在跨品牌时条数**天然不同**（佳明 21 条含内置传感器，高驰模板 1 条），
不能算「丢数据」。已把守恒范围收窄为 fileId/session/lap/record/event/activity，
deviceInfo 单独按 INFO 说明。

### 23. 回归测试的标准做法（本轮实践，建议固化）

写完任何**校验/比对工具**，必须做双向回归，否则无法证明它有效：

| 步骤 | 做法 | 期望 |
|---|---|---|
| ① 造正确样本 | 正常转换一次 | 工具报 **0 差异**（EXIT=0）|
| ② 造有 bug 样本 | **打补丁让转换器漏写某字段**（如 `_make_fileid_src` 里 `vals.pop('productName')`）| 工具报 **DIFF 并定位到具体字段**（EXIT=1）|

⚠️ **造 bug 样本不要手工改字节**：我第一次直接把 `COROS APEX 4 42mm` 的位置抹 0，
结果字符串没抹干净，值变成 `'\x00...m'` 而**不是 None**，工具判定「有值」→ 漏报。
正解：**在转换器层打补丁**，让它自然产出「该字段为哨兵」的干净样本。

**已验证**：`fit_diff_vs_template.py` 对缺 productName 的样本报
`[DIFF] g=0(fileId) 模板有值但产物未填 —— f8(模板='COROS APEX 4 42mm' → 值为哨兵)`，
对正常样本报 0 差异。**工具可信。**

### 24. 模板 ≠ 交付物：规范才是（2026-09-18 认知纠正）

**少侠原话**：「模板为什么要发上去，你规范定干净了根本不需要模板」——**他是对的**。

我一开始的设计把 `templates/*.json` 当成核心资产，甚至想把它推进公开仓库（740KB）。
但模板只是**学习过程的原始记录**：逐点统计、`present_count`、`samples`、857 条
「官方无此字段」的重复噪声……**78~86% 的体积是观测过程，不是格式规则**。

真正该固化的是**规范**：文件头参数、消息白名单与顺序、每种消息的布局与渐进节奏、
字段官方名对照、开发者字段声明、语义推断结论。这些才是跨设备可复用、可评审、
可入库的东西。

**架构调整为两段**：

```
学（中间步骤）  真机 → templates/<name>.json        【本地，不入库】
定（交付资产）  模板 → profiles/<name>.{md,json}    【入库，跨设备复用】
用              三个工具一律读规范，缺失才回退读模板
```

**实测验证规范确实自足**（把模板目录整个移走）：

| 步骤 | 结果 |
|---|---|
| ① 转换 | EXIT=0，172572 bytes |
| ② 规范门禁 | **PASS 114 / FAIL 0 / WARN 0** |
| ③ 全维度比对 | **一致 26 / 差异 0** |
| **产物 md5 vs 模板路径** | **完全相同**（`16f440f5…`）|

→ **规范是模板的完全替代品**，且体积只有 1/7~1/5，还不含任何私人数据。

### 25. 精炼规范时踩到的两个「省体积省出 bug」

把模板精炼成规范时，我出于"精简"做了两处省略，结果**规范不自足、转换直接崩**：

| 省略 | 后果 | 修正 |
|---|---|---|
| 只有一种布局就省略 `layout_rhythm` | 转换器 `mi['layout_rhythm']` → **KeyError** | **节奏必须始终保留**；单布局补 `[[0, 大数]]` |
| 只收 206、漏收 207（developerDataId） | dev 链断裂 → 门禁报 `207 已声明 ×0`、引用无效 | **207 必须收**，且 `applicationId` 留 hex（16 字节前导零有意义，用 int 会丢） |

🔑 **教训**：**精炼 ≠ 丢信息**。凡是下游**程序要读**的字段，一个都不能省；
能省的是给人看的冗余（统计量、采样细节、重复条目）。
判断标准：**"删掉它，工具还能跑到 md5 一致吗？"** 不能就不许删。

另：`_dev_decl_map` 原本只认模板的 hex，读规范时崩。已改为
「有 hex 用 hex，没有就从结构化值按目标编码重建」（`_encode_dev_decl_field`）。

