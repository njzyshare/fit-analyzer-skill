---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明、高驰、颂拓等各大品牌 .fit 活动文件。已落地：合并分段活动、FIT 体检、官方 SDK 重建、TCX 导出、时间戳平移。支持 protocol=2 核心消息+设备信息注入。触发词：'合并fit'、'拆分fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'合并运动'。"
version: 1.0.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌（佳明、高驰、颂拓、Polar、华为等）。

## 环境

需要 Python 3.8+ 或 Node.js 18+（二选一即可）：

```bash
# Python 方案（合并、体检、TCX、时间戳、华为转换）
pip install fitdecode fitparse

# Node.js 方案（主力合并，实测佳明 Connect 兼容性最好）
npm install @garmin/fitsdk
```

## 快速使用

```bash
# 查看所有脚本
ls scripts/

# 合并分段活动 — 高驰/其他品牌首选
python scripts/fit_merge.py seg1.fit seg2.fit -o merged.fit

# 合并 — 佳明 Connect 首选（protocol=2 核心消息+设备信息）
node scripts/merge_fixed.mjs

# FIT 体检（上传前验证）
python scripts/fit_healthcheck.py merged.fit

# TCX 兜底导出
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 时间戳平移
python scripts/fit_shift_time.py input.fit --delta-hours -12

# 官方 SDK 重建
python scripts/fit_rebuild_sdk.py merged.fit -o rebuilt.fit

# 华为手表数据 → 高驰/佳明（修复海拔+步频+卡路里）
python scripts/huawei_convert.py 华为导出.json
```

## 脚本说明

| 脚本 | 功能 | 适用平台 |
|------|------|---------|
| `fit_merge.py` | 字节级拼接，保留全部原始消息（含私有） | 高驰等，佳明 ❌ |
| **`merge_fixed.mjs`** | **protocol=2 Encoder 核心消息，device_info 注入** | **佳明 ✅ 实测通过** |
| `fit_healthcheck.py` | 语义体检（时间/距离单调性、字段完整性） | 通用 |
| `fit_to_tcx.py` | FIT→TCX 导出 | 上传兜底 |
| `fit_shift_time.py` | 平移时间戳 | 规避去重 |
| `fit_rebuild_sdk.py` | 官方 Garmin SDK 重建 | 丢弃私有消息 |
| `huawei_convert.py` | 华为JSON→GPX/TCX（修复版） | 华为→高驰/佳明 |

**注意**：同一份合并文件在各平台表现不同。`fit_merge.py` 在高驰可正常上传，`merge_fixed.mjs` 在佳明 Connect 可正常上传。
华为数据转换 `huawei_convert.py` 修复了原脚本的海拔偏移、缺失卡路里/步频等问题，详见 `references/huawei_converter_analysis.md`。

## 华为 → TCX/GPX 使用说明

```bash
python scripts/huawei_convert.py 华为导出.json
```

输出到 `华为导出所在目录/converted_coros_v2/`，每条运动同时生成 GPX（高驰推荐）和 TCX（佳明推荐）。

### 运动类型识别规则

按优先级推断（基于969条实测数据的验证）：

| 条件 | 判定为 | 实测结果 |
|------|:------:|:--------:|
| **骑行/游泳**（无论配速步频） | **保留原始类型** | 110条全部保留 ✅ |
| 有GPS + dist≥500m + 有步频 + 配速≤10min/km | **Running** | 156+65=221条 ✅ |
| 有GPS + dist≥500m + 无步频 + 配速≤10min/km | **保留原始类型**（可能是骑行被标错） | 不影响骑行 ✅ |
| 有GPS + dist≥500m + 配速>10min/km | **Walking** | 349条步行+1条跑步改步行 ✅ |
| 无GPS + 无距离 + 有心率 | **Other**（纯心率监测） | 275+5+3=283条 ✅ |
| 其他（计划跑步/室内运动等） | **保留原始类型** | 2+2=4条 ✅ |

> 跑步和骑行划分的关键是**步频数据**：跑步一定有步频，骑行不一定有。所以有步频+配速合理=跑步，无步频+配速快保留原始类型（骑行），骑行/游泳不受配速规则影响。

### sportType 编号说明

华为手表导出的 JSON 中 `sportType` 编号有两套体系：

**体系A：手表端输出编号（你的数据）**
你的 969 条记录中实际出现的编号：

| 编号 | 中文名 | 数量 | 推断结果 |
|:---:|:------|:---:|:--------:|
| 4 | 🏃 户外跑步 | 157 | Running |
| 5 | 🚶 户外步行 | 417 | Walking |
| 3 | 🚴 户外骑行 | 110 | Cycling（保留） |
| 117 | ❓ 心率监测 | 275 | Other |
| 106 | ❓ 室内有氧 | 5 | Other |
| 281 | 🏃 室内运动 | 3 | Running（有步频） |
| 101 | 🏃 计划跑步 | 2 | Running |

**体系B：华为 Health Kit API（开发者文档）**
公开 API 使用的编号（与你数据不通用，仅供参考）：
- running=56, walking=90, cycling=13, swimming=81
- 详见：[华为运动健康文档](https://developer.huawei.com/consumer/cn/doc/HMsCore-Guides/introduction-fitness-record-data-0000001131831088)

> ⚠️ 脚本的推断规则（配速+步频+GPS）**优先级高于所有编号映射**。
> 即使手表编号标错了，实际运动类型也会被自动修正。

| sportType | 映射名称 | 数量 | 说明 |
|:---------:|---------|:---:|------|
| 4 | Running | 157 | 户外跑步（半马/日常跑） |
| 5 | Walking | 417 | 户外步行 |
| 3 | Cycling | 110 | 户外骑行 |
| 117 | Other(HR) | 275 | 仅心率记录，无GPS（静息心率等） |
| 101 | Other(Running) | 2 | 计划跑步/室内跑步，有GPS |
| 106 | Other(Running) | 5 | 室内跑步/虚拟运动，无GPS |
| 281 | Other | 3 | 室内跑步/力量训练 |
| 其余 | Running | — | 未识别类型安全 fallback 为 Running |

如果 `detect_actual_sport` 检测到走路配速快于 8min/km 且距离 >500m，自动修正为 Running。

### 已知问题

- sportType=117（275条）为纯心率记录（无GPS，dist=0），会输出 `_HRonly.tcx`
- 华为气压计海拔可能存在整体偏移（实测 -34m），脚本自动检测并修正
- `partTimeMap:{1.0:335.0}` 为非标准 JSON 格式，脚本会自动修补

详细实战踩坑记录见 `references/exp_20260720.md`。

## 爬升矫正技巧

当佳明 Connect 读取非佳明设备文件时，爬升数据可能不准（佳明会重算海拔）。注入 device_info 标记设备类型即可解决：

```python
enc.write_mesg({'mesg_num': 23, 'manufacturer': 'garmin',
  'product': 4536, 'serial_number': 3504654948, 'source_type': 'local'})
```

## 工作流

```
           ┌─ fit_healthcheck ──> .fit ──> 上传各平台
原始分段 ──┤
           └─ fit_to_tcx ──> .tcx ──> 上传兜底

佳明专用：
  merge_fixed.mjs ──> merged_activity_fixed.fit ──> Garmin Connect ✅
```
