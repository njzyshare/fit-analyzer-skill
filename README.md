# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集，覆盖佳明、高驰、颂拓、Polar、华为等品牌 .fit 文件。

## 作用
- 合并分段活动（高驰保真 / 佳明 Connect 兼容）
- 注入真实设备信息（佳明防重算爬升 / 高驰防未知设备），运动数据 100% 保留
- 设备身份互逆替换（Fenix8↔COROS 字节级）
- **佳明换皮成高驰** —— 唯一正确路径，能救回「最快1KM」（见下方专章）
- 华为 JSON → FIT/GPX/TCX
- FIT 预览、时间戳平移、协议字节修复、官方 SDK 重建、TCX 兜底
- 跨品牌互转（佳明↔高驰，规范驱动 + 双关卡门禁）
- **高驰 MCP 数据采集**（运动/睡眠/恢复/训练负荷，约 40 接口）

## 环境
```bash
pip install fitdecode fitparse && npm install @garmin/fitsdk
```

## 快速开始
```bash
node scripts/merge_preserve.mjs            # 合并高驰分段（保留源生 lap）
node scripts/merge_fixed.mjs               # 合并佳明分段
python scripts/huawei_convert.py 导出.json  # 华为 → FIT
python scripts/fit_preview.py 活动.fit      # 生成 HTML 预览
node scripts/shift_time_sdk.mjs in.fit out.fit -12  # 时间平移（负=往前）
```

## 佳明换皮成高驰

把佳明记录改成高驰身份上传，**不是改个厂商名就行**。

### 核心结论

> **换皮能影响的数据只有「最快1KM」。**
> 设备型号显示、等强配速属高驰服务端/硬件侧判定，**FIT 文件改不出来**。
> 评估换皮是否成功，只看最快1KM 出没出。

### 决定性因素：record 骨架，不是字段齐不齐

| 做法 | 消息种类 | `unknown_*` | 最快1KM | 判定 |
|---|---|---|---|---|
| 只改 `file_id` / `device_info` | 35~37 | 11~12 个 | ❌ | **伪换皮** |
| 规范重建记录体 | 9~12 | **0** | ✅ | **真换皮** |

**为什么**：高驰按自己的定义去读 record 的逐点距离流。佳明布局原样搬过来时
字段号/字节长度/类型码全对不上，**速度列读出来是空的** → 不报错、静默跳过派生。
且一次性入库不重试，所以「上传那一刻就定死」。

**已证否**（别再查）：dev16、`max_speed`、`field_description`、lap 按 1km 切 —— 全都不是必要条件。
次要条件：必须有 `lap` 消息（骨架干净但 `lap=0` 也失败）。

### 正确做法

```bash
python scripts/fit_convert_by_template.py 佳明.fit 高驰.fit --to coros_apex4
python scripts/fit_conformance_check.py 高驰.fit --temp coros_apex4 --src 佳明.fit
python scripts/fit_diff_vs_template.py 高驰.fit --temp coros_apex4 --src 佳明.fit
```

### 自查清单

| 指标 | 成功 | 失败特征 |
|---|---|---|
| `file_id.manufacturer` | `coros` | `garmin` = 根本没换皮 |
| `file_id.product` | 具体型号（814/808）| `899` = 通用占位 |
| record `unknown_*` | **0** | ≥11 = 佳明布局残留 |
| 消息种类 | 9~12 | 35~37 = 没重建 |
| `gps_metadata`/`split` | 不应存在 | 存在 = 佳明专有消息残留 |

### 最快1KM 怎么核对

**它不等于 lap 里最快那一圈**，而是 record 距离流按 **1000m 滑动窗口**取最短用时。
用 lap 最快值会差 10~20 秒。

完整规范（含算法、平台限制证据、dev16 GAP 模型）见
`references/coros_specifics.md` §九/§十/§十一。

## 高驰 MCP

高驰官方 MCP，HTTP 流式传输、无需 API Key。配置 `~/.workbuddy/mcp.json`：

```json
{
  "mcpServers": {
    "coros-mcp": { "url": "https://mcp.coros.com/mcp", "transport": "http-stream", "disabled": false }
  }
}
```

写入后需到连接器管理页右上角「自定义连接器」点「信任」才生效。

能力：运动记录/详情/分段、训练负荷、恢复状态、睡眠（含 HRV）、静息心率、压力、
每日健康数据、设备列表、活动 FIT 下载、训练计划读写。

🔴 **取不到活动级设备型号**：`getActivityDetail` 只返回配速/心率/步频/功率/爬升等指标，
**没有任何设备字段**。要知道某条活动是哪台表跑的，只能读 FIT 的 `device_info`。
详见 `references/coros_mcp.md`。

## 跨品牌互转
```bash
python scripts/fit_convert_by_template.py 输入.fit 输出.fit --to coros_apex4
python scripts/fit_conformance_check.py 输出.fit --temp coros_apex4 --src 输入.fit
python scripts/fit_diff_vs_template.py 输出.fit --temp coros_apex4 --src 输入.fit
```

字段含义一律以 `references/fit_profile_official.json` 为准，完整规则见 `SKILL.md`。
