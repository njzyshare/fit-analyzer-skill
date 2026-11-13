# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌，覆盖佳明、高驰、颂拓、Polar、华为等所有产出 `.fit` 文件的运动设备。

## 它解决什么问题

你的一次跑步被手表误存为多个 `.fit` 文件？想把它们合并回一个完整活动？需要一个在各运动平台（佳明 Connect、高驰、Strava 等）都能正常上传的合并文件？这个 skill 帮你做。

## 能力

- **合并分段活动** — 把一次连续运动被存成的多个 .fit 合并回单个活动
- **FIT 体检** — 上传前语义验证，抓出平台可能拒收的隐藏问题
- **TCX 导出** — FIT → TCX 导出，作为上传兜底格式
- **时间戳平移** — 把整条运动的所有时间戳统一偏移，**让一条已有运动变成发生在任意时间**。如果平台有每日跑步打卡任务、或者想调整活动时间在日历上更整齐，这个功能就是为你准备的。不改时长、不改数据，只改时间。
- **爬升数据修复** — 非佳明设备（高驰、颂拓等）录制的运动导入 Garmin Connect 后，平台可能重算海拔导致爬升数据严重异常。通过在 FIT 文件中注入佳明设备信息，让 Connect 信任设备自带的气压计数据，恢复真实爬升。
- **官方 SDK 重建** — 用 Garmin 官方 SDK 重新编码，产出最标准文件

FIT 格式支持丰富的运动数据——GPS 轨迹、心率、功率、步频、触地时间、垂直振幅、步幅、温度、训练效果、功率区、心率区等。这套工具可以在保留数据完整性的前提下自由编辑这些内容，**发挥你的想象力**：补全缺少的设备信息让平台正确识别、为旧文件附加训练效果数据、调整运动类型、合并多次间歇训练的成绩汇总……只要你想得到，FIT 能承载的数据，这套工具就能改。

## 环境要求

```bash
# Python 方案（合并、体检、TCX、时间戳）
pip install fitdecode fitparse

# Node.js 方案（主力合并协议，佳明兼容性最好）
npm install @garmin/fitsdk
```

## 快速开始

```bash
# 1. 把分段文件放到位
ls seg*.fit

# 2. 合并（高驰/其他品牌用 Python 版）
python scripts/fit_merge.py seg1.fit seg2.fit seg3.fit -o merged.fit

# 合并（佳明 Connect 用 Node.js 版）
# 先编辑 scripts/merge_fixed.mjs 中的文件路径，然后：
node scripts/merge_fixed.mjs

# 3. 体检验证
python scripts/fit_healthcheck.py merged.fit

# 4. 同时导出 TCX 兜底
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 5. 上传
# - merged.fit → 上传各平台
# - merged.tcx → 如果 FIT 被拒，用 TCX
```

## 平台兼容性

| 平台 | fit_merge.py(字节级拼接) | merge_fixed.mjs(Encoder核心消息) |
|------|:----------------------:|:-------------------------------:|
| **高驰** | **✅ 直接可用，无需特殊处理** | **✅ 也可用** |
| **佳明 Connect** | ❌ 被拒 | **✅ 实测通过（protocol=2 + 设备信息注入）** |
| Strava | 应可 | 应可 |

## 脚本清单

| 脚本 | 用途 | 语言 |
|------|------|:----:|
| `scripts/fit_merge.py` | 字节级拼接合并，保留全部原始消息 | Python |
| `scripts/fit_healthcheck.py` | 语义体检 | Python |
| `scripts/fit_to_tcx.py` | FIT→TCX 导出 | Python |
| `scripts/fit_shift_time.py` | 时间戳平移 | Python |
| `scripts/fit_rebuild_sdk.py` | Garmin 官方 SDK 重建 | Python |
| **`scripts/merge_fixed.mjs`** | **佳明兼容合并（主力方案）** | Node.js |
| **`scripts/huawei_convert.py`** | **华为JSON→GPX/TCX（修复版）** | Python |
| `scripts/merge_fit_v10.mjs` | Encoder 全消息合并（备选） | Node.js |
| `scripts/merge_light.mjs` | Encoder 最小合并（备选） | Node.js |

## 爬升数据矫正

佳明 Connect 对非佳明设备上传的文件可能重算海拔，导致爬升数据异常。

解决方法：在 FIT 文件中注入 device_info 消息标记设备为佳明：

```python
enc.write_mesg({'mesg_num': 23, 'manufacturer': 'garmin',
  'product': 4536, 'serial_number': RANDOM_SN, 'source_type': 'local'})
```

详细踩坑记录见 `scripts/merge_fixed.mjs` 文件注释和 `references/exp_20260720.md`。

## 技术原理

### merge_fixed.mjs（佳明主力方案）

- 用 `@garmin/fitsdk` Encoder 生成 protocol=2 的 FIT 文件
- 只写核心消息（fileId + deviceInfo + sport + event + record + lap + session + activity + timeInZone）
- `totalTimerTime` 从各段原始 session 累加（不含暂停）
- `totalAscent/Descent` 从各段原始 session 累加（不从 GPS 算）
- Record 写入全部已知字段（含 verticalOscillation、stanceTime、stepLength 等步态数据）

### huawei_convert.py（华为数据转换）

- 华为手表 JSON → GPX（高驰） + TCX（佳明）
- 自动校准海拔偏移（修复华为气压计未校准导致的负值问题）
- 从华为原始数据提取步频并写入
- 估算卡路里（基于心率和距离）
- Sport 类型未识别时默认 Running

## 相关文件

```
运动记录fit分析器/
├── SKILL.md              # 入口文档
├── README.md             # 本文件
├── scripts/              # 全部可执行脚本
│   ├── fit_merge.py      # 字节级拼接
│   ├── merge_fixed.mjs   # 主力方案（佳明）
│   ├── fit_healthcheck.py
│   ├── fit_to_tcx.py
│   ├── fit_shift_time.py
│   ├── fit_rebuild_sdk.py
│   ├── merge_fit_v10.mjs
│   ├── merge_light.mjs
│   ├── merge_v0_replica.mjs
│   └── huawei_convert.py   # 华为JSON→GPX/TCX
└── references/           # 参考文档
    └── exp_20260720.md   # 实战踩坑记录
    └── huawei_converter_analysis.md  # 华为转换脚本分析
    └── huawei_to_coros.py  # 原脚本（已从GitHub删除，留档）
```
