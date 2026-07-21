# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌，覆盖佳明、高驰、颂拓、Polar、华为等所有产出 `.fit` 文件的运动设备。

## 能力

- **合并分段活动** — 把一次连续运动被存成的多个 .fit 合并回单个活动
- **华为手表 → FIT/GPX/TCX** — 华为 JSON 导出直接转换为标准运动文件，默认输出 FIT（完整数据、轨迹正确、规范合规）
- **FIT 体检** — 上传前语义验证，抓出平台可能拒收的隐藏问题
- **TCX 导出** — FIT → TCX 导出，作为上传兜底格式
- **时间戳平移** — 把整条运动的所有时间戳统一偏移
- **爬升数据修复** — 非佳明设备录制导入 Garmin Connect 后爬升不准的问题
- **官方 SDK 重建** — 用 Garmin 官方 SDK 重新编码，产出最标准文件

## 环境要求

```bash
# Python（数据解析、体检、时间戳平移、华为转换）
pip install fitdecode fitparse

# Node.js（佳明兼容合并、FIT 编码）
npm install @garmin/fitsdk
```

## 快速开始

```bash
# 查看所有可用脚本
ls scripts/

# 华为数据 → FIT（默认，推荐）
python scripts/huawei_convert.py 华为导出.json

# 华为数据 → GPX（想在高驰看轨迹）
python scripts/huawei_convert.py 华为导出.json --format gpx

# 华为数据 → TCX（佳明 Connect 兜底）
python scripts/huawei_convert.py 华为导出.json --format tcx

# 华为数据 → 全部三种格式
python scripts/huawei_convert.py 华为导出.json --format all

# 合并分段活动（高驰用 Python 版）
python scripts/fit_merge.py seg1.fit seg2.fit seg3.fit -o merged.fit

# 合并（佳明 Connect 用 Node.js 版）
node scripts/merge_fixed.mjs

# 体检验证
python scripts/fit_healthcheck.py merged.fit

# TCX 兜底导出
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 时间戳平移（改活动时间）
python scripts/fit_shift_time.py input.fit --delta-hours -12
```

## 平台兼容性

| 格式/脚本 | 高驰 (COROS) | 佳明 Connect | Strava |
|-----------|:------------:|:------------:|:------:|
| FIT（huawei_convert.py 输出） | ✅ 原生支持 | ✅ 原生支持 | ✅ |
| GPX（huawei_convert.py 输出） | ✅ 支持导入 | ✅ | ✅ |
| TCX（huawei_convert.py 输出） | ✅ | ✅ | ✅ |
| fit_merge.py（字节级拼接） | ✅ 直接可用 | ❌ 被拒 | 应可 |
| merge_fixed.mjs（Encoder） | ✅ 也可用 | ✅ 实测通过 | 应可 |

## 华为数据转换说明

华为手表 JSON → FIT 是默认输出格式，也是推荐的方案：

- **固定 record 字段布局**：所有 6189 个点用完全相同的 9 字段布局，缺失值用 FIT 哨兵值填充。避免第三方解析器字段错位。
- **GCJ02→WGS84 坐标系转换**：华为数据标记为国测局加密坐标，自动反算为 WGS84 标准。
- **爬升/下降不自算**：让导入平台（高驰/佳明）自行计算，避免与设备端算法不一致。
- **气压计海拔校准**：自动检测偏移并修正（华为手表常见 -30m 偏移）。
- **步频、卡路里、心率**：全部从华为原始数据提取，无漏缺。
- **运动类型智能推断**：配速+步频+GPS 综合判断，骑行/游泳不受配速规则影响。

## 技术原理

### merge_fixed.mjs（佳明主力方案）

- 用 `@garmin/fitsdk` Encoder 生成 protocol=2 的 FIT 文件
- 只写核心消息（fileId + deviceInfo + sport + event + record + lap + session + activity）
- Record 写入全部已知字段，单一定义消息布局
- 不写 gpsMetadata / timestampCorrelation（会被佳明拒收）

### huawei_convert.py（华为数据转换）

- 华为手表 JSON → FIT（默认）/ GPX / TCX
- 内部调用 `fit_encode.mjs`（Node.js @garmin/fitsdk）做 FIT 编码
- 海拔、步频、卡路里全部从华为原始 attribute 提取（非估算）
- GPX/TCX 走原生生成路径，无需 Node.js

## 爬升数据矫正

佳明 Connect 对非佳明设备上传的文件可能重算海拔。如需要让佳明显示爬升，注入 device_info 标记设备：

```python
enc.write_mesg({'mesg_num': 23, 'manufacturer': 'garmin',
  'product': 4536, 'serial_number': RANDOM_SN, 'source_type': 'local'})
```

## 目录结构

```
├── SKILL.md              # 入口文档（AI 工具使用）
├── README.md             # 本文件
├── fit_encode.mjs        # FIT 编码器（供 huawei_convert.py 调用）
├── package.json          # Node.js 依赖
├── scripts/
│   ├── huawei_convert.py   # 华为JSON→FIT/GPX/TCX（主力）
│   ├── merge_fixed.mjs     # 佳明兼容合并（主力）
│   ├── fit_merge.py        # 字节级拼接
│   ├── fit_healthcheck.py  # 语义体检
│   ├── fit_to_tcx.py       # FIT→TCX
│   ├── fit_shift_time.py   # 时间戳平移
│   └── fit_rebuild_sdk.py  # 官方 SDK 重建
└── references/
    └── exp_20260720.md   # 实战踩坑记录
```
