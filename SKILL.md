---
name: 运动记录fit分析器
description: "通用运动 FIT 记录分析/修改工具集。覆盖佳明/高驰/颂拓/华为等品牌 .fit 文件。已落地：合并分段活动、FIT 体检、官方 SDK 重建、华为JSON→FIT/GPX/TCX、时间戳平移。支持 protocol=2 核心消息+设备信息注入。触发词：'合并fit'、'分析fit'、'体检fit'、'导出tcx'、'改时间'、'华为转换'。"
version: 3.0.0
agent_created: true
---

# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌（佳明、高驰、颂拓、Polar、华为等）。

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

# 合并分段活动（Node.js Encoder，佳明 Connect 兼容）
node scripts/merge_fixed.mjs

# FIT 体检（上传前验证）
python scripts/fit_healthcheck.py merged.fit

# TCX 导出（上传兜底）
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 时间戳平移
python scripts/fit_shift_time.py input.fit --delta-hours -12

# 官方 SDK 重建
python scripts/fit_rebuild_sdk.py merged.fit -o rebuilt.fit

# 华为手表 → FIT（默认）/ GPX / TCX
python scripts/huawei_convert.py 华为导出.json                     # 默认 FIT
python scripts/huawei_convert.py 华为导出.json --format gpx        # GPX
python scripts/huawei_convert.py 华为导出.json --format tcx        # TCX
python scripts/huawei_convert.py 华为导出.json --format all        # 全部三种
```

## 脚本说明

| 脚本 | 功能 | 适用平台 |
|------|------|---------|
| `fit_merge.py` | 字节级拼接，保留全部原始消息 | 高驰 ✅ / 佳明 ❌ |
| `merge_fixed.mjs` | **protocol=2 Encoder 核心消息+设备注入** | **佳明 ✅ 实测通过** |
| `fit_healthcheck.py` | 语义体检（时间/距离单调性、字段完整性） | 通用 |
| `fit_to_tcx.py` | FIT → TCX 导出 | 上传兜底 |
| `fit_shift_time.py` | 平移时间戳 | 规避去重 |
| `fit_rebuild_sdk.py` | 官方 Garmin SDK 重建 | 丢弃私有消息 |
| `huawei_convert.py` | **华为 JSON → FIT/GPX/TCX（默认 FIT）** | **华为 → 高驰/佳明 ✅** |
| `fit_encode.mjs` | FIT 编码器（供 huawei_convert.py 内部调用） | 依赖 @garmin/fitsdk |

### 注意

- 同一份合并文件在各平台表现不同。`fit_merge.py` 在高驰正常上传，`merge_fixed.mjs` 在佳明 Connect 正常上传。
- 华为数据转换默认 FIT：固定 record 字段布局 + GCJ02→WGS84 + 无硬编码爬升，对任何解析器都健壮。
- GPX/TCX 可事后从 FIT 转换（`fit_to_tcx.py`），但会丢失计圈、训练效果等数据。

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

## 工作流

```
原始分段 ──→ fit_merge.py / merge_fixed.mjs ──→ .fit ──→ fit_healthcheck.py ──→ 上传各平台
                                                    └── fit_to_tcx.py ──→ .tcx（兜底）

华为JSON ──→ huawei_convert.py ──→ .fit（默认，fixed layout+WGS84）──→ 高驰/佳明
                                  └── .gpx / .tcx（--format gpx/tcx）
```
