---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。已落地：合并分段活动、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移、FIT 预览、注入真实佳明设备信息防 Connect 重算爬升、字节级设备身份替换（Fenix8↔COROS 互换，运动数据原样保留）。支持 protocol=2 核心消息+设备信息注入。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'、'预览fit'、'注入佳明设备'、'防重算爬升'、'改成高驰设备'、'改成佳明设备'、'改设备身份'、'换设备'。"
version: 3.11.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌（佳明、高驰、颂拓、Polar、华为等）。

## 能力速览

| 能力 | 命令 | 用途 |
|------|------|------|
| 华为→FIT | `huawei_convert.py 导出.json` | 华为JSON→标准FIT（默认） |
| 合并分段 | `fit_merge.py / merge_fixed.mjs` | 多个FIT合为一个（regenerate_laps 重算圈） |
| 合并分段（高驰原生，推荐） | `merge_preserve.mjs` | 多个FIT合为一个，**保留两段源生 lap 消息**（不重算）、协议字节改回 0x20、保留段间断开为暂停、+60s 平移 |
| **FIT 预览** | **`fit_preview.py input.fit`** | **生成交互HTML，含地图+数据+计圈** |
| 体检 | `fit_healthcheck.py` | 上传前验证 |
| 导出TCX | `fit_to_tcx.py` | FIT→TCX兜底 |
| 改时间 | `fit_shift_time.py` | 字节级平移时间戳（原始/合并文件） |
| 改时间（SDK 保真版） | `shift_time_sdk.mjs` | SDK 解码→平移→重编码，保真保留设备信息+私有字段；处理压缩时间戳消息 |
| **注入佳明设备（防 Connect 重算爬升）** | **`inject_garmin_device.mjs`** | **第三方手表文件 → 真实佳明设备身份** |
| **注入高驰设备（字节级，防「未知设备」/ 四不像）** | **`inject_coros.py`** | **任意 FIT → 真实高驰设备身份：删源 device_info、只留单条高驰、协议翻 0x20、运动数据 100% 保留（私人库 `~/.workbuddy/private/coros_devices.json` + `coros_<name>.fit`）** |
| 注入 COROS 设备身份（SDK 重编码版，反面教材） | `inject_coros.mjs` | ⚠️ SDK Encoder 无法编出高驰非标准 device_info 布局，厂商码会被错放字段，高驰会拒收；**改高驰身份请用 `inject_coros.py`（字节级）** |
| **设备身份字节级替换（互逆，推荐）** | **`rebrand_device.py`** | **任意 FIT → 复制参考设备的 file_id+device_info 身份字节，运动数据 100% 保留；高驰↔佳明互换均稳** |
| 协议字节修复（COROS 时间错乱根因） | `fix_proto.py` | 改 header 协议字节 0x20/0x02 + 重算 header/file 双 CRC |

## 环境

```bash
# Python（数据解析、体检、时间戳平移、华为转换）
pip install fitdecode fitparse

# Node.js（佳明兼容合并、FIT 编码）
npm install @garmin/fitsdk
```

## 快速使用

```bash
# 查看可用脚本
ls scripts/

# 合并分段活动（Python 字节级，高驰可用）
python scripts/fit_merge.py seg1.fit seg2.fit -o merged.fit

# ⚠️ 交付前必跑：QA 测试员（开发→测试→修复→复测）
# 任一 ❌FAIL 都不许交付，必须回去改 fit_merge.py 复测到全绿（⚠️WARN 仅提示、不阻断）
python scripts/fit_qa.py merged.fit
#   --expect-devices 1   同设备合并期望的 device_info 数量（默认1）
#   --lap-km 1000        每个整圈目标距离(米)，默认1000
#   --slack-m 3          距离容差(米)，默认3

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
# 用法：node 脚本 输入.fit 输出.fit <小时>  （小时为负=往前）
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

## 为任意 FIT 注入真实高驰(COROS) 设备身份（字节级，阻止「未知设备」/ 四不像）

**问题**：把一份非高驰产出的 FIT（如佳明录的半马）改成高驰设备，上传高驰 app 后被识别异常或显示「未知设备」，或者被当成「四不像」（只换第一条 device_info、剩下一堆原设备传感器）。

**根因**：高驰 `device_info` 是**非标准布局**（`product` 字段=厂商码 `294`，无标准 `manufacturer` 字段）。Garmin SDK 的 `Encoder` 编不出这种布局（会把 294 错放字段 → 高驰拒收/判异常），所以**绝不能用 SDK 重编码**（`inject_coros.mjs` 那条路线已证实走不通，仅作反面教材保留）。唯一可靠做法 = **字节级复制参考高驰文件的 file_id + device_info 原始字节**，其余按源文件拼接。

**与 `rebrand_device.py` 的关键区别**（2026-08-09 实测）：`rebrand_device.py` 只替换「第一条」device_info，源文件其余 device_info 原样保留。但佳明源文件常带 **10+ 条 device_info**（手表+心率带+踏频器等传感器），只换第一条会留下一堆佳明设备 → 四不像。本流程**删除源文件全部 device_info，只注入单条高驰 device_info**，结构等同于一份纯高驰原生文件（1 个 file_id + 1 个 device_info）；并把协议字节翻回高驰原生 `0x20`（回传 COROS app 必须，否则时间被误读成凌晨）。

**工作流（两步，类比佳明注入）**：

```bash
# 0) 首次：从真实高驰活动抽取设备身份入私人区域（同时保存参考 .fit 字节）
node 不用；用 Python：
python scripts/inject_coros.py extract 真实高驰.fit --name apex4
#    -> 写入 ~/.workbuddy/private/coros_devices.json（mirror garmin_devices.json）
#    -> 复制参考字节到 ~/.workbuddy/private/coros_apx4.fit（字节级注入必需，不可省略）

# 1) 把私人区域里的身份注入任意 FIT（运动数据 100% 保留，只换设备身份）
python scripts/inject_coros.py apply 源.fit --device apex4 --out 源_coros.fit
#    不写 --device 时取私人文件里的 default 项
#    不写 --out 时默认 <原名>_coros.fit
#    --proto 0x02 可改标准协议（传 Garmin Connect 时用）；默认 0x20（传 COROS）
```

**说明**：
- `extract` 读取真实高驰文件中 `file_id`（manufacturer/product/product_name）与 `device_info`（product_name）身份，写入私人 JSON；并把整份参考 .fit 复制到私人目录（字节级注入需要原始身份字节，JSON 仅作元数据/文档）。
- `apply` 全量字节级拼接：**复制参考 file_id+device_info 的 def+data 字节，local 号用源文件自己的、time_created/timestamp 用源活动的（保留日期与压缩时间戳时间线）；删除源文件全部 device_info，只嵌单条高驰 device_info；重算 data_size + header CRC + file CRC；协议字节翻 0x20**。保留全部原始运动数据（轨迹/计圈/心率/私有开发者字段）。
- 校验：输出 `file CRC / header CRC match=True`、`device_info` 仅一条高驰、`records/laps/距离/时长` 与源文件一致、无孤儿定义。
- 一台高驰只需 `extract` 一次；多台就 `extract --name xxx` 多次，`apply` 用 `--device xxx` 选择。
- 私人数据（参考字节 + JSON）存 `~/.workbuddy/private/`，**不进 skill/脚本/共享文件**，不会被 GitHub 更新覆盖。

**注意**：若手上没有真实高驰设备，无法凭空编造可信身份——用自己/朋友的高驰活动抽取参考字节。

## 设备身份字节级替换（rebrand：高驰↔佳明 互换，运动数据原样保留）

**场景**：用户要把一个 FIT 的设备身份改成另一台设备（例如把 Garmin fenix8 的导出改成自己的高驰 APEX 4 42mm，或反过来），但**所有运动数据（轨迹/计圈/心率/私有字段）必须原样保留**——只换"这是谁产的"这层身份。

**为什么用字节级而不是 SDK 重编码**（2026-08-02/08-05 实测踩坑）：
1. SDK 重编码会丢私有/开发者消息类型，且对**压缩时间戳消息**（高位置位 0x80）容易 desync，导致产物无法被严格解析器读。
2. 高驰 `device_info` 是**非标准布局**：`product` 字段(2) 直接放厂商码 `294`（coros），**没有标准 `manufacturer`(1) 字段**，结构是 `[timestamp(253), product(2)=294, product_name(27)]`。Garmin SDK 的 `Encoder` 会把 294 错误地塞进 field 4（标准 product 位），高驰严格解析器直接把活动判为异常/拒收。
3. 因此唯一可靠做法：**复制参考设备身份的原始字节，只改本活动的时间戳，其余按原偏移拼接**。

**工作流**：

```bash
# src = 要改身份的文件；ref = 参考设备身份来源（真·该设备导出的 .fit）；out = 产物
python scripts/rebrand_device.py <src.fit> <ref.fit> <out.fit>

# 例1：fenix8 活动 → 改成高驰 APEX 4 42mm（ref 用一个真·高驰导出 .fit）
python scripts/rebrand_device.py fenix8活动.fit 高驰APEX4导出.fit 高驰活动.fit

# 例2：高驰活动 → 改成 fenix8（ref 用一个真·fenix8 导出 .fit）
python scripts/rebrand_device.py 高驰活动.fit fenix8导出.fit fenix8活动.fit
```

**脚本做了什么**（`rebrand_device.py`，纯 Python、无依赖）：
- 解析源文件，定位 `file_id`(global 0) 与 `device_info`(global 23) 的 definition + data 两条消息；参考文件同理。
- 把参考文件的 file_id/device_info 的 **def + data 字节原样复制**，但：
  - 两条消息的 **local 号强制设成源文件自己的**（避免与文件内其它 def 冲突）；
  - `file_id` field 4（time_created）与 `device_info` field 253（timestamp）**改成源活动自己的创建时间**（从源 file_id field 4 读），这样日期正确、压缩时间戳记录仍按同一时间线解码；
- 其余所有字节（轨迹/计圈/session/事件/私有开发者字段）按源文件原偏移 **逐字节拼接**；
- 重算并写入：`header` 的 `data_size`(偏移4) + `header CRC`(偏移12-13) + 文件尾 `file CRC`(末2字节)。

**铁律 / 关键坑（务必遵守）**：
- **CRC 必须用 Garmin 半字节表** `[0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400]`（脚本已内置）。网上常见的 CCITT 表算不出真实 FIT 的 CRC（26.7.fit 真实尾 CRC=0xE8ED，错表对不上）。
- **`find_pair` 返回 `(def, data)`**——解包时写成 `_, x = find_pair(...)` 会把 **data 当 def** 用，导致文件膨胀+结构错。要拿 def 取第一个元素。
- 替换后文件大小可能变化（高驰身份比 fenix8 精简约 12 字节），必须同步重算 `data_size` 字段（公式 `len(out_b) - header_size`，此时 CRC 尚未追加）。
- **不要动时间戳以外的数据**：用户要的是"换设备身份"，不是"平移时间"。只在身份消息里改时间，轨迹 record 的时间戳一律不动（除非用户明确要求平移，那走 `shift_time_sdk.mjs`）。

**验证（交付前必跑）**：
- `python -c "import ...; fit_crc16(open(out,'rb').read()[:-2])"` 应等于文件末2字节；header CRC 同理。
- 用 `@garmin/fitsdk` 的 `Decoder.read()` 解码 `errors.length === 0`，且 `fileIdMesgs[0]`/`deviceInfoMesgs[0]` 身份读成目标设备；record/lap/session/event 计数与源文件一致（运动数据未被触动）。
- 字节级对比：除身份区外，源文件与产物应逐字节相同（diff=0）。

## 脚本说明

| 脚本 | 功能 | 适用平台 |
|------|------|---------|
| `fit_merge.py` | 字节级拼接，保留全部原始消息（含每点私有字段字节）；自动去重 `developer_data_id`/`field_description`（保等强配速/Effort Pace）与 `device_info`（按设备身份去重，**连定义带数据一起丢**，防高驰显示「未知设备」）；计圈由 `regenerate_laps` 重写为整 1km 切分（末圈=全程余数），时间戳按 record 累计距离插值 | 高驰 ✅ / 佳明 ❌ |
| `merge_preserve.mjs` | **高驰原生合并（推荐用于 COROS）**：用 Garmin FIT SDK 解码→合并→重编码；**保留两段源生 lap 消息原样**（只重编号 messageIndex + 平移时间戳 + 保持连续距离），**不调用 regenerate_laps**；协议字节改回 COROS 原生 0x20（需 `PROTO20=1` 环境变量，并重算 header+file CRC）；段2 record 距离整体 +段1总距保证轨迹连续；段2 与段1 同样平移 +60s（保留原始段间断开≈数分钟作为暂停）；device_info/file_id/Effort Pace/62 条 timer 事件全部原样保留 | 高驰 ✅（避免 regenerate_laps 把尾巴圈错排） |
| **`fit_qa.py`** | **QA 测试员：合并文件交付前的自动化回归测试**（开发→测试→修复→复测）。覆盖 header/CRC、无孤儿定义、字段 size 符合 base type、device_info 唯一识别、file_id、Effort Pace 私有字段保留、计圈整 1km 结构、record 距离单调、message_index 唯一。任一 FAIL 必须回去修、复测到全绿** | 通用 ✅ |
| `merge_fixed.mjs` | **protocol=2 Encoder 核心消息+设备注入** | **佳明 ✅ 实测通过** |
| `fit_healthcheck.py` | 语义体检（时间/距离单调性、字段完整性） | 通用 |
| `fit_preview.py` | **FIT → 交互式 HTML 预览（地图+Session+全字段+计圈）** | **通用，浏览器打开** |
| `fit_to_tcx.py` | FIT → TCX 导出 | 上传兜底 |
| `fit_shift_time.py` | 平移时间戳 | 规避去重（字节级，原始/简单文件） |
| **`shift_time_sdk.mjs`** | **SDK 解码→平移 timestamp→重编码，保真保留全部数据** | **适配含压缩时间戳消息的 SDK 重编码文件（如 inject 产出的 *_fenix8.fit）；依赖 @garmin/fitsdk** |
| `fit_rebuild_sdk.py` | 官方 Garmin SDK 重建 | 丢弃私有消息 |
| `huawei_convert.py` | **华为 JSON → FIT/GPX/TCX（默认 FIT）** | **华为 → 高驰/佳明 ✅** |
| **`huawei_batch_convert.py`** | **批量华为 JSON → 按类型分目录输出 FIT** | **华为全量数据 → 高驰/佳明 ✅** |
| `fit_encode.mjs` | FIT 编码器（供 huawei_convert.py 等内部调用） | 依赖 @garmin/fitsdk |
| **`inject_garmin_device.mjs`** | **注入真实佳明设备信息（extract 抽取 / apply 注入），防 Connect 重算爬升** | **依赖 @garmin/fitsdk；设备数据读 ~/.workbuddy/private/garmin_devices.json** |
| **`inject_coros.py`** | **注入真实高驰设备信息（extract 抽取 / apply 注入，字节级）：参考高驰 .fit 的 file_id+device_info 原始字节复制进任意 FIT，删除源全部 device_info 只留单条高驰，协议翻 0x20；运动数据/私有字段 100% 保留** | **纯 Python 无依赖；设备元数据读 `~/.workbuddy/private/coros_devices.json`，参考字节读 `~/.workbuddy/private/coros_<name>.fit`** |
| `inject_coros.mjs` | 注入 COROS 设备身份：从参考 COROS 文件读 file_id+device_info（非标准布局：product 字段=294、无 manufacturer 字段），其余原始数据保留；修合并后「未知设备」 | 高驰 ✅（但 SDK 重编码版会把厂商码错放字段，改高驰身份请用 `inject_coros.py` 字节级） |
| **`rebrand_device.py`** | **设备身份字节级替换：复制参考设备的 file_id+device_info 字节，local 号与活动时间戳用源文件自己的，其余逐字节拼接；重算 data_size+header CRC+file CRC。运动数据 100% 保留** | **通用 ✅ 高驰↔佳明互换均稳（纯 Python 无依赖）** |
| `fix_proto.py` | **协议字节修复**：header 第 2 字节翻回 COROS 原生 0x20（或标准 0x02）+ 重算 header CRC(12-13) 与 file CRC(末2字节) 两道校验；解决 COROS 读 0x02 文件时间错乱(04:06) | 高驰 ✅（回传 COROS 必须保 0x20） |

### 注意

- 同一份合并文件在各平台表现不同。`fit_merge.py` 在高驰正常上传，`merge_fixed.mjs` 在佳明 Connect 正常上传。
- **合并后高驰不识别「等强配速 / Effort Pace」类私有字段**：根因是 `developer_data_id` 与 `field_description` 不在旧版的去重名单里，字节拼接后同一 `developer_data_index`（多为 0）被复制成多份，违反 FIT「dev_index 文件内唯一」规则，高驰严格解析器直接丢弃全部私有字段（连带可能误判设备身份）。已修复：`fit_merge.py` 将 `developer_data_id`/`field_description` 也按「只保留第一段副本」处理，合并结果在结构上与单个原始文件一致（1 个 developer_data_id + N 个 field_description），每点私有数据字节原样保留。若仍异常，先 `fit_healthcheck.py` 看 dev 定义计数是否为 1/去重后的值。
- **合并后计圈：⚠️ 高驰（COROS）必须用「保留源生 lap」（merge_preserve.mjs），不要用 regenerate_laps**：2026-08-02 实测，`fit_merge.py` 的 `regenerate_laps()` 把两段源生的两个尾巴圈（如 26.7km 段尾 0.727km + 4.4km 段尾 0.396km）压平成整 1km 圈、再在末尾造一个**假**的 0.122km 尾巴（31×1km + 0.122km）。高驰按 record 累计距离重推导圈时，这个被压平/错排的结构会让尾巴圈显示错位（用户报告「末尾计圈方式被挪到前面 / 某圈 0.12km」）。`merge_preserve.mjs` **原样保留两段源生 lap 消息**（只重编号 + 平移 + 保持距离连续），结构 = `[26×1km, 0.727段尾, 4×1km, 0.396段尾]`，与源文件逐圈一致，高驰渲染正确。
- **regenerate_laps 仍保留在 `fit_merge.py`**（2026-08-01 实测「整 1km + 余数末圈」是当时用户要的形态），但**对 COROS 会导致尾巴圈错排**，所以 COROS 合并一律改用 `merge_preserve.mjs`。regenerate_laps 的暂停感知计时仍是有价值的库函数，可用于需要重算圈且非 COROS 的场景。⚠️ 铁律：**每圈 `total_distance` 必须写「本圈距离」(end-start)，绝不可写累计值**——曾误写累计 26.7km，高驰直接显示「某圈二三十 km」。
- **合并后高驰显示「未知设备」**：根因是 seg2 的 **`device_info` 定义帧（DEF）被漏丢，成为孤儿定义**——旧逻辑只丢掉了 seg2 的 device_info 数据帧、却没丢它的定义帧，于是合并文件里出现「1 条 device_info 数据 + 1 条无数据的 device_info 定义（在 local=4 上重定义）」。数据帧计数虽是 1，但那帧悬空定义会让严格解析器（COROS）放弃设备识别、判为未知。已修复：`fit_merge.py` 对 `device_info` 按「全部非 timestamp 字段的原始字节」做设备身份去重（COROS 把 manufacturer 放在字段 2、product_name 放在字段 27，固定字段号会漏匹配），同一台设备**连定义带数据一起丢**，合并后无任何孤儿定义、结构等同于单个源文件。务必在交付前跑 `fit_qa.py` 的 T03（无孤儿定义）+ T05（device_info 唯一被识别）确认。
- **合并后高驰 app 计圈标记带 .7/.4 等小数**：属正常真实距离（26.7km+4.4km=31.1km 非整公里，段末/末圈本就非整）。只要段顺序正确、lap 保持单圈值、record 累计正确，标记就会是 1→2→…→26→26.7→27.7→…→31.1km，不会中段重置。若你早先看到「6.4、7.4」全是 .4，那是 **4.4km 段被放到了前面（错序）** 导致的，重新确认段顺序即可。
- **末圈形态（两种合并差异）**：`regenerate_laps`(fit_merge.py) 把 `total % 1000m` 作为**单个**末圈（如 31.122km → 0.122km 假尾巴）。**真实源数据有两个尾巴**：26.7km 段尾 0.727km + 4.4km 段尾 0.396km（`merge_preserve.mjs` 保留，结构 = `[26×1km, 0.727, 4×1km, 0.396]`）。若在高驰看到「某圈 0.12km」，要么是 regenerate 的假尾巴被错排、要么是旧活动缓存——用 `merge_preserve.mjs` 且删旧活动重传可解。
- **fitdecode 报 `invalid field size 1 ... uint32`（event 定义 @76062）：是 COROS 源文件自身怪癖，非合并损坏**。实测 `26.7.fit` 自身就报此警告（event 定义 field 3 `data` 被声明成 uint32 size 1），`4.4.fit` 没有；合并文件因原样保留 seg1 字节而继承同一警告。COROS app 读自己的文件无碍，无需修复（修复=篡改设备原始输出，违背「不修改真实数据」原则）。
- 华为数据转换默认 FIT：固定 record 字段布局 + GCJ02→WGS84 + 无硬编码爬升，对任何解析器都健壮。
- GPX/TCX 可事后从 FIT 转换（`fit_to_tcx.py`），但会丢失计圈、训练效果等数据。

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

**原则**：所有脚本的 manufacturer/product 继承自原始数据，不默认写任何品牌。
仅当用户明确要求"修复佳明 Connect 爬升显示"时才注入佳明设备信息。

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

### 9. 协议字节 0x20 vs 0x02：COROS 时间显示错乱的真正根因（2026-08-02）

- **现象**：合并/重编码后的文件在 COROS app 里「开始时间显示凌晨 04:06」，但 fitdecode 解析出的 session.start_time 明明是真实 09:36。时间戳值是对的，错在**协议版本字节（header 第 2 字节）**。
- **根因**：高驰原生文件协议字节=`0x20`（COROS 私有取值，非标准 2.0）；经 Garmin FIT SDK 解码→重编码的产物协议字节=`0x02`（标准 protocol 2.0）。COROS app 按它对 0x20 的私有规则解读 header，读到 0x02 时时间换算错乱 → 显示成凌晨 4 点多（偏移约 5.5h）。**时间戳字段本身没写错，是协议字节让 COROS 误读。**
- **规则**：
  - **回传 COROS 的文件：协议字节必须保 `0x20`**（merge_preserve.mjs 默认 `PROTO20=1` 就是做这件事）。
  - **传 Garmin Connect：用标准 `0x02`**（佳明按 UTC 时间戳解析，本地时区下显示正确，无此问题）。
- **修复工具 `fix_proto.py`**：只改协议字节这一处 + **同时重算两道 CRC**——header CRC（覆盖字节 0..11，写入 12..13）与 file CRC（覆盖字节 0..len-2，写入末尾 2 字节）。改协议字节会让两道 CRC 同时失效，**只重算 file CRC 不重算 header CRC 的话 checkIntegrity() 仍=false**。CRC 用 Garmin 自定义半字节查表算法（表 16 项，与 `@garmin/fitsdk/src/crc-calculator.js` 逐字节一致）。
  - 用法：`python scripts/fix_proto.py 输入.fit 输出.fit`（默认翻到 0x20）；要翻到标准 0x02 传佳明则 `... 0x02`。
- **教训**：凡是要回传 COROS 的合并/重编码产物，最后一步务必确认协议字节是 0x20，再交付；否则用户会在 COROS 上看到时间错乱，且这种错乱标准解码器完全复现不出来（因为标准解析器不依赖协议字节的私有分支），极易误判成「时间戳写错了」反复返工。

## 工作流

### 端到端 A：高驰(COROS) 分段 → 回传 COROS（保真）
```
原始分段(seg1,seg2) ──→ merge_preserve.mjs (PROTO20=1, 保留源生 lap)
        │
        ▼
   合并.fit（协议字节=0x20，无重算圈、尾巴圈在源生位置）
        │  （若中间被 SDK 重编码成 0x02 → fix_proto.py 翻回 0x20）
        ▼
   fit_qa.py 合并.fit seg1 seg2   ← 自校验 + 带原始2段交叉校验（时间/身份/计圈）
        │
        ▼
   回传 COROS（建议先删旧活动，避免「设备+日期」缓存）
⚠️ 关键：协议字节必须 0x20；且保留源生 lap（绝不用 regenerate_laps，否则尾巴圈错排到第5圈）
```

### 端到端 B：高驰(COROS) 分段 → 传 Garmin Connect
```
原始分段(seg1,seg2) ──→ merge_preserve.mjs / fit_merge.py ──→ 合并.fit
        │
        ▼
   inject_garmin_device.mjs apply --device <fenix8/...> ──→ *_fenix8.fit
        │   （真实佳明设备，防「未知设备」+ 防爬升被重算；输出协议=0x02）
        ▼
   fix_proto.py *_fenix8.fit ... 0x02   ← 确认是标准 0x02（佳明才认）
        │
        ▼
   fit_qa.py *_fenix8.fit  ──→ 传 Garmin Connect
⚠️ 关键：传佳明必须注入真实佳明设备 + 协议字节用 0x02；时间戳值本身正确，佳明按 UTC 解析显示正常
```

### 端到端 C：华为 JSON → 高驰/佳明
```
华为JSON ──→ huawei_convert.py ──→ .fit（默认，fixed layout+WGS84）──→ 高驰/佳明
                                  └── .gpx / .tcx（--format gpx/tcx）
```

---

原始分段 ──→ fit_merge.py / merge_fixed.mjs ──→ .fit ──→ fit_healthcheck.py ──→ 上传各平台
                                                    └── fit_to_tcx.py ──→ .tcx（兜底）

华为JSON ──→ huawei_convert.py ──→ .fit（默认，fixed layout+WGS84）──→ 高驰/佳明
                                  └── .gpx / .tcx（--format gpx/tcx）

## QA 工作流（开发 → 测试 → 修复 → 复测）—— 合并/重建类任务强制

**原则**：凡是生成/修改 FIT 文件（合并、重建、注入设备、时间戳平移等）的任务，**交付前必须跑 `fit_qa.py`，全绿才准交付**。不允许再出现「用户上传后才一个个挑刺」的情况。这是 2026-08-02 用户明确要求加的工作流。

```
开发者(本 agent)：
  fit_merge.py seg1.fit seg2.fit -o merged.fit
        │
        ▼
QA 测试员(同一 agent 切换到 QA 角色，跑 fit_qa.py)：
  fit_qa.py merged.fit seg1.fit seg2.fit     # 带原始2段=开启时间/身份交叉校验
        │
        ├── 全 PASS(含 WARN 仅提示) ──► 交付 ✅
        │
        └── 有 ❌FAIL ──► 切回开发者角色修 fit_merge.py
                            │
                            └──► 重新合并 ──► 再跑 fit_qa.py（循环直到全绿）
```

**QA 测试员的职责**（已固化在 `scripts/fit_qa.py`，自带测试用例，覆盖「今天踩过的全部常识性错误」+ FIT 规范）：

| 用例 | 校验点 | 对应踩过的坑 |
|------|--------|--------------|
| T01 | header 合法（`.FIT` 魔数 + header CRC） | — |
| T02 | 文件 CRC 正确 | — |
| T03 | **无孤儿定义**（每条 definition 后面必须有 ≥1 数据） | 本次：seg2 的 device_info 定义被漏丢成孤儿 → 高驰「未知设备」 |
| T04 | 字段 size 符合 base type 规范 | COROS event `uint32 size=1` 怪癖（源文件固有，仅 WARN 不修） |
| T05 | **device_info 唯一且被识别**（manufacturer/product_name 非空） | 本次：同 T03，设备不识别 |
| T06 | file_id 含 manufacturer + product | — |
| T07 | **私有字段 Effort Pace 保留**（field_description 未被整体丢弃） | 早期：dev 未去重被高驰丢弃 |
| T08 | **计圈结构**：无过大圈(>1.5km，防累计距离回退)、无过短圈(<200m 且不在末位，防尾巴圈被错排到第5圈)、Σlap=session 总距、短圈数量≤2（两段合并各一段尾圈） | 早期：误写成累计 → 每圈二三十 km；本次用户坑：regenerate_laps 把两段真尾巴(0.727+0.396)压平成整圈、在末尾造假 0.122km 尾巴 → 高驰错排；用 merge_preserve.mjs 保留源生 lap 修正 |
| T09 | record 距离单调递增、末值=session 总距 | — |
| T10 | message_index 同类内唯一 | — |
| T11 | **合并起始时间 == 段1 起始**（session.start_time） | 本次用户坑：「时间改坏、显示凌晨4点」——根源是 QA 此前没对照原始文件验证时间，无法证明/发现时间漂移 |
| T12 | **合并结束时间 == 段2 结束**（末 record timestamp） | 同上 |
| T13 | **record 时间戳多重集合 == 段1∪段2（无偏移/重复/丢失）** | 杀手锏测试：任何时间戳被改写/段错位都会在此报红 |
| T14 | 全部 record 时间戳落在 [段1首, 段2末] 区间内 | 同上 |
| T15 | 合并总时长 == 段2末 − 段1首 | 同上 |
| T16 | file_id.time_created == 段1（继承首段身份） | 同上 |
| T17 | device_info 身份(manufacturer,product) == 段1 | 同上 |

**约束**：
- QA 是「测试员自己会写/带测试用例」，不是拍脑袋说"看着没问题"。每次生成文件后由测试员独立跑这份用例集。
- 源文件固有怪癖（如 T04 的 uint32 size=1）只在报告里 WARN，**绝不为了过测而篡改设备原始输出**（违背「不修改真实数据」铁律）。
- 测试用例随踩坑持续扩充：每发现一类新常识性错误，往 `fit_qa.py` 加一条对应 T 用例，并更新上表。
- **时间/身份类 bug 必须用「对照原始段」模式复核**：`fit_qa.py merged.fit seg1.fit seg2.fit`（T11–T17）。2026-08-02 用户反馈「运动时间显示凌晨4点」后确认：合并文件本身时间戳完全正确（T11–T17 全绿），app 里看到的 4 点是**之前上传的旧活动/缓存**——与「未知设备」是同一类「看了陈旧导出」问题。教训：交付前必须带原始2段跑交叉校验，时间对不对要能被证明，不能靠肉眼。
- 也可用独立的 `fit-qa` 技能加载这套 QA 角色与工作流。
