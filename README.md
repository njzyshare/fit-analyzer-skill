# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集。不限品牌，覆盖佳明、高驰、颂拓、Polar、华为等所有产出 `.fit` 文件的运动设备。

## 核心：规范驱动 + 双关卡

**「模板」只是学习过程的中间产物，真正固化的资产是规范**：

```
① 学   真机.fit ──→ templates/<name>.json    【中间产物，本地，不入库】
                      ↓ 精炼（剔除 78~86% 的观测噪声）
② 定   规范                                  【入库资产，跨设备复用】
        references/profiles/<name>.md        可读文档（人看）
        references/profiles/<name>.json      机器可读规则
③ 用   convert / conformance / diff 三个工具一律读规范
④ 比对 fit_diff_vs_template.py（8 节全维度比对，交付前必跑）
```

**换一台新设备不需要改代码** —— 学一次 → 精炼成规范，之后所有人复用。

⚠️ **仓库里已有规范，开箱即用**。`references/templates/` 不入库
（它是学习时的原始记录，体积大且含设备身份）。
若要支持新设备：

```bash
python scripts/fit_learn_template.py 你的设备.fit --name coros_apex5 --note "COROS APEX 5"
python scripts/fit_distill_spec.py coros_apex5
```

⚠️ **门禁 PASS ≠ 与真机一致**：门禁只检查已写好的断言，做不了穷举。
交付前必须再跑一次 `fit_diff_vs_template.py` 做全维度比对（结构 + 值 + 条数 + 逐点）。

## 能力

- **跨品牌互转** — 佳明 ↔ 高驰（双向实测通过），换型号只需换模板名
- **学目标平台模板** — 一行命令从真机文件提取字段布局、渐进节奏、类型码、设备身份
- **FIT 规范门禁** — 11 节断言覆盖文件头/结构/类型码/哨兵/换算/顺序/开发者字段/时间戳/一致性/源比对/模板比对
- **FIT 预览** — 一键生成交互式 HTML 预览页面（轨迹地图 + Session 摘要 + 全字段统计 + 计圈详情），双击浏览器打开
- **等强配速写入** — 给任意 FIT 添加 Effort Pace（V2 融合方案：Minetti 坡度基准+心率修正），高驰 APP 可识别显示
- **合并分段活动** — 把一次连续运动被存成的多个 .fit 合并回单个活动
- **华为手表 → FIT/GPX/TCX** — 华为 JSON 导出直接转换为标准运动文件，默认输出 FIT
- **FIT 体检** — 上传前语义验证，抓出平台可能拒收的隐藏问题
- **TCX 导出** — FIT → TCX 导出，作为上传兜底格式
- **时间戳平移** — 把整条运动的所有时间戳统一偏移
- **爬升数据修复** — 非佳明设备录制导入 Garmin Connect 后爬升不准的问题
- **官方 SDK 重建** — 用 Garmin 官方 SDK 重新编码，产出最标准文件

## 环境要求

```bash
# Python（数据解析、体检、时间戳平移、华为转换、模板学习与转换）
pip install fitdecode fitparse

# Node.js（官方 profile 导出、佳明兼容合并、FIT 编码）
npm install @garmin/fitsdk
```

## 快速开始

```bash
# 查看所有可用脚本 / 已有模板
ls scripts/
python scripts/fit_learn_template.py --list

# ⭐ 跨品牌转换（推荐路径）
python scripts/fit_learn_template.py 真机.fit --name coros_apex4 --note "COROS APEX 4 42mm"
python scripts/fit_convert_by_template.py 佳明活动.fit 高驰活动.fit --to coros_apex4

# ⭐ 规范门禁（编辑与复查都必须跑）
python scripts/fit_conformance_check.py 高驰活动.fit --temp coros_apex4 --src 佳明活动.fit

# ⭐ 交付前全维度比对（必跑！门禁 PASS 不等于与真机一致）
python scripts/fit_diff_vs_template.py 高驰活动.fit --temp coros_apex4 --src 佳明活动.fit

# FIT 预览（一键生成 HTML，浏览器打开即可查看）
python scripts/fit_preview.py my_activity.fit

# 华为数据 → FIT（默认，推荐）
python scripts/huawei_convert.py 华为导出.json

# 华为数据 → GPX（想在高驰看轨迹）/ TCX（佳明 Connect 兜底）/ 全部三种
python scripts/huawei_convert.py 华为导出.json --format gpx
python scripts/huawei_convert.py 华为导出.json --format tcx
python scripts/huawei_convert.py 华为导出.json --format all

# 华为数据 → 按运动类型批量转换全部记录
python scripts/huawei_batch_convert.py 华为导出.json -o ./华为FIT

# 合并分段活动（高驰用 Python 版；佳明 Connect 用 Node.js 版）
python scripts/fit_merge.py seg1.fit seg2.fit seg3.fit -o merged.fit
node scripts/merge_fixed.mjs

# 体检验证
python scripts/fit_healthcheck.py merged.fit

# TCX 兜底导出
python scripts/fit_to_tcx.py merged.fit -o merged.tcx

# 时间戳平移（改活动时间）
python scripts/fit_shift_time.py input.fit --delta-hours -12
```

## 实测验证（2026-09-18）

| 方向 | 门禁结果 | 数据保真 |
|---|---|---|
| 佳明 fenix 8 → 高驰 APEX 4 | PASS 113 / FAIL 0 / WARN 0 | 海拔逐点最大差 0.000 m；速度 0.00000 m/s；24 个零速点保留 |
| 高驰 APEX 4 → 佳明 fenix 8 | PASS 111 / FAIL 0 / WARN 0 | record 条数一致；3 种渐进布局与模板逐位一致 |

两方向产物经 `@garmin/fitsdk` 解析均 **0 errors**（与真机文件同级）。


## 平台兼容性

| 格式/脚本 | 高驰 (COROS) | 佳明 Connect | Strava |
|-----------|:------------:|:------------:|:------:|
| FIT（huawei_convert.py 输出） | ✅ 原生支持 | ✅ 原生支持 | ✅ |
| GPX（huawei_convert.py 输出） | ✅ 支持导入 | ✅ | ✅ |
| TCX（huawei_convert.py 输出） | ✅ | ✅ | ✅ |
| fit_merge.py（字节级拼接） | ✅ 直接可用 | ❌ 被拒 | 应可 |
| merge_fixed.mjs（Encoder） | ✅ 也可用 | ✅ 实测通过 | 应可 |
| fit_preview.py（预览器） | ✅ 浏览器打开 | ✅ 浏览器打开 | ✅ 浏览器打开 |

## 华为数据转换说明

华为手表 JSON → FIT 是默认输出格式，也是推荐的方案：

- **固定 record 字段布局**：所有 6189 个点用完全相同的 9 字段布局，缺失值用 FIT 哨兵值填充。避免第三方解析器字段错位。
- **GCJ02→WGS84 坐标系转换**：华为数据标记为国测局加密坐标，自动反算为 WGS84 标准。
- **爬升/下降写入辅助字段**：写入 `altitude` 字段（sint16，×2 缩放）以及 session/lap 的 `totalAscent/Descent`，帮助高驰等平台识别。注意：华为气压计原始数据有 0.5~1m 级别噪声，逐点累加后爬升会比实际偏高约 2 倍。这是华为传感器精度限制，非编码错误。
- **气压计海拔校准**：自动检测偏移并修正（华为手表常见 -30m 偏移）。
- **步频、卡路里、心率**：全部从华为原始数据提取，无漏缺。
- **运动类型智能推断**：配速+步频+GPS 综合判断，骑行/游泳不受配速规则影响。
- **manufacturer/product 遵从原始数据**：不默认写任何品牌。默认 `0xFF (development)`。仅用户要求修复佳明爬升时才注入佳明设备信息。
- **批量转换**：`huawei_batch_convert.py` 一次处理华为 JSON 中全部运动记录，按类型分目录输出，文件名含年月日+时间
  
## 脚本清单

### 核心三件套（跨品牌转换）

| 脚本 | 作用 |
|---|---|
| `scripts/fit_lib.py` | 核心库：FIT 解析/编码/官方 profile/哨兵值/换算，所有脚本共用 |
| `scripts/fit_learn_template.py` | 真机 .fit → 模板 JSON（布局/渐进节奏/类型码/设备身份/dev 语义/值快照） |
| `scripts/fit_convert_by_template.py` | 模板驱动双向转换，转换完自动跑门禁 |
| `scripts/fit_conformance_check.py` | 11 节 FIT 规范门禁，退出码 1 = 有 FAIL |
| `scripts/fit_diff_vs_template.py` | **交付前全维度比对（8 节）**，退出码 1 = 有结构差异 |
| `scripts/export_profile.mjs` | 从 `@garmin/fitsdk` 重导官方 profile（**必须含 `base_type`**）|

### merge_fixed.mjs（佳明主力方案）

- 用 `@garmin/fitsdk` Encoder 生成 protocol=2 的 FIT 文件
- 只写核心消息（fileId + deviceInfo + sport + event + record + lap + session + activity）
- 不写 gpsMetadata / timestampCorrelation（会被佳明拒收）

### huawei_convert.py（华为数据转换）

- 华为手表 JSON → FIT（默认）/ GPX / TCX
- 内部调用 `fit_encode.mjs`（Node.js @garmin/fitsdk）做 FIT 编码
- 海拔、步频、卡路里全部从华为原始 attribute 提取（非估算）
- GPX/TCX 走原生生成路径，无需 Node.js

## 目录结构

```
├── SKILL.md              # 入口文档（AI 工具使用）
├── README.md             # 本文件
├── fit_encode.mjs        # FIT 编码器（供 huawei_convert.py 调用）
├── scripts/
│   ├── fit_lib.py                  # ⭐ 核心库（解析/编码/官方profile）
│   ├── fit_learn_template.py       # ⭐ 学目标平台模板
│   ├── fit_convert_by_template.py  # ⭐ 模板驱动双向转换
│   ├── fit_conformance_check.py    # ⭐ 11 节规范门禁
│   ├── fit_diff_vs_template.py     # ⭐ 交付前全维度比对（8 节）
│   ├── export_profile.mjs          # 重导官方 profile（含 base_type）
│   ├── huawei_convert.py           # 华为JSON→FIT/GPX/TCX（主力）
│   ├── huawei_batch_convert.py     # 华为JSON→按类型批量FIT
│   ├── merge_fixed.mjs             # 佳明兼容合并（主力）
│   ├── fit_merge.py                # 字节级拼接
│   ├── fit_healthcheck.py          # 语义体检
│   ├── fit_preview.py              # FIT→交互式HTML预览
│   ├── fit_to_tcx.py               # FIT→TCX
│   ├── fit_shift_time.py           # 时间戳平移
│   └── fit_rebuild_sdk.py          # 官方 SDK 重建
└── references/
    ├── templates/                  # ⭐ 学到的真机模板（coros_apex4 / garmin_fenix8）
    ├── fit_profile_official.json   # 官方字段定义（一切以此为准）
    ├── fit_format_spec.md          # FIT 格式全要求
    ├── vendor_specifics.md         # 高驰/佳明差异枚举
    ├── conversion_workflow.md      # 流程总纲
    └── exp_20260720.md             # 实战踩坑记录
```

## 爬升数据矫正

佳明 Connect 对非佳明设备上传的文件可能重算海拔。让佳明显示原始爬升，需注入真实佳明设备身份
（Unit ID 必须来自真实设备，编造的会被判「未知设备」）：

```bash
node scripts/inject_garmin_device.mjs extract 真实佳明.fit --name fenix8   # 抽取一次
node scripts/inject_garmin_device.mjs apply 高驰.fit --device fenix8       # 之后反复用
```

