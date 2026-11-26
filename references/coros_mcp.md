# 高驰（COROS）MCP 数据采集

高驰官方 MCP 服务，走 **HTTP 流式传输**，无需 API Key。
本文件讲「怎么接、怎么调、有哪些坑」。MCP 只负责**取数**，不改 FIT 文件。

## 一、部署配置（换电脑照做）

配置文件：`~/.workbuddy/mcp.json`（**不是** `.mcp.json`）。这是全局配置，与佳明 MCP 共用同一个文件、并列在 `mcpServers` 下。

```json
{
  "mcpServers": {
    "coros-mcp": {
      "url": "https://mcp.coros.com/mcp",
      "transport": "http-stream",
      "disabled": false
    }
  }
}
```

- 官方 URL 固定，无需登录/密钥，换电脑直接复制这段即可。
- 写入后**不会自动激活**：到连接器管理页右上角「自定义连接器」入口，点「信任」该 server，再重启客户端。
- 若同一文件里还有 `"garmin-cn"`（见 `garmin_mcp.md`），两个条目并列，不要互相覆盖。

## 二、能力边界

约 40 个接口，分四类：

| 类别 | 主要接口 |
|---|---|
| **运动与训练** | `querySportRecords`（可按日期/距离/时长/配速/地点筛）、`getActivityDetail`、`queryActivityLapData`、训练负荷评估、恢复状态、体能评估总览 |
| **健康与身体** | 睡眠概览、睡眠 HRV、静息心率、平均心率（含时序）、每日健康数据、压力等级与时序 |
| **设备与文件** | `queryDevices`、`getUserInfo`、`queryActivityFitFileDownloadUrls`（链接）、`downloadActivityFitFiles`（二进制）、路线文件上传 |
| **训练计划（可写）** | 计划库/详情、日程查询、创建/更新训练计划与课程、排期 |

## 三、🔴 关键限制：取不到活动级设备型号

`getActivityDetail` 的返回字段是**固定的**：时长、距离、配速、心率、步频、触地时间、
垂直振幅、步幅、功率、爬升、卡路里、训练负荷、有氧/无氧 TE、训练焦点、Performance。

**没有任何设备字段。** `queryDevices` 只能列出账号绑定的设备，无法关联到单条活动。

→ **「某条活动是哪台表跑的」这个问题，MCP 答不了，只能读 FIT 的 `device_info`。**
→ 同理，导入活动不显示设备型号/等强配速是**通道侧限制**，不是文件问题，别拿它判转换成败。
  **最快 1KM 与设备型号/等强配速不是一条链路**，后者不依赖设备绑定。

## 四、数据口径要点

| 项 | 规则 |
|---|---|
| 睡眠归属 | 按**醒来日**归属。某夜的睡眠记在 D+1。问「昨晚」→ 传**今天**的日期 |
| 运动类型码 | 必须传数字码，不能传名称。跑步 `[100 户外, 101 室内, 102 越野, 103 操场]` |
| 日期格式 | `yyyyMMdd`。不传区间默认最近 7 天 |
| FIT 下载额度 | 有**每日限额**（实测约 50 份/日），URL 方式与二进制方式共用同一额度。超限改走 OSS 直链（见 §六）|
| 力量训练动作名 | 返回英文；仍是 `T1275` 这类代号说明字典缺失，**不要猜** |
| `querySportRecords` | `limit` 够用即可（如 100），返回按日期倒序，含 `labelId` / 起止 Unix 秒 / 距离 / 地点 |

## 五、常用调用

工具通过 WorkBuddy 内置 MCP 通道直接调用（工具名即接口名），参数用 JSON：

```text
# 最近跑步活动列表
querySportRecords({"limit":100})

# 单条活动详情（含 Best Kilometer 字段）
getActivityDetail({"labelId":"<活动ID>","sportType":100})

# 服务端 1km 分段（判「最快1KM」是否生成）
queryActivityLapData({"labelId":"<活动ID>","sportType":100})

# 原始 FIT 直链（推荐，curl/Node 下载比二进制方式省上下文）
queryActivityFitFileDownloadUrls({"labelId":"<活动ID>","sportType":100})
```

⚠️ **参数坑（实际踩过）**：

| 接口 | 正确 | 错误（会报 Tool call anomalies）|
|---|---|---|
| `queryActivityFitFileDownloadUrls` | `labelId`（**单数**）+ `sportType` | `labelIds` 数组 |
| `downloadActivityFitFiles` | 同上 | 同上 |
| `getActivityDetail` / `queryActivityLapData` | 必须带 `sportType`，否则详情内容为空/结构不对 | 只传 `labelId` |

⚠️ 批量取数：详情接口一次只能取一条，几十条要分多轮。**优先 FIT 下载 + 本地解析**，比逐条调详情高效得多。

## 六、FIT 下载与本地解析

直链形如 `https://oss.coros.com/fit/v2/<用户目录ID>/<活动ID>_<hash>.fit`，**下载无需鉴权**，Node/curl 直接取：

```js
const b = Buffer.from(await (await fetch(url)).arrayBuffer());
if (b.slice(8,12).toString() !== '.FIT') throw new Error('bad magic');
```

- 校验 magic `.FIT`（偏移 8–12）再落盘，避免把错误页当 FIT。
- `/fit/v2/` 路径是 2026-10-29 后归档改版，**与活动来源（真机/导入）无关**，别据此判断来源。
- 云端归档 FIT 与上传字节一致，**无二次编码**——本地分析的产物指纹可直接用于台账。

## 七、🔴 取数口径：`lapGroups` 与最快 1KM

`queryActivityLapData` 返回的 `lapGroups` **组顺序不固定**，按 `lapDistance` / `type` 定位，别取第 0 组。

| 字段 | 含义 |
|---|---|
| `type=2` 组 | 服务端承认的分段统计组。**存在且 `fastLapIndexList` 非空 ↔ 显示最快 1KM**（跨 39 条 + 4 条新样本零反例）|
| `fastLapIndexList` | **0-based，直接 `laps[i]`，不要 `laps[i-1]`**。旧脚本按 1-based 取值会错一圈 |
| 末尾余圈 | `type=2` 组内最后一个常是不满 1km 的余圈，**别当整 1km 最快圈** |

**取值规则**：
1. `fast=[i]` → 直接取 `laps[i]`，用该圈的 `avgPace`（秒/公里）对账详情 `Best Kilometer`。
2. **不要用 `time / distance` 手算**：`laps[i].distance` 可能不是整 1000m（课表切圈），`avgPace` 才是折算后的每公里配速，与详情一致。
3. 对不上时先检查是否用了 `i-1`（最常见的错），再看 `avgPace` 是否被误当成 `time`。
   `adjustedPace` 逐圈全 0 是常态（等强配速不通过导入通道下发），符合 §三。

**`type=2` 圈数不等于整公里数**：它不代表「服务端一定按 1km 重切」。
- 源文件是整公里圈为主（如日常跑）→ 服务端可能重切成整 1km 组。
- 源文件是**课表按步骤自动切圈**（如「节奏跑 3×8:00」）→ 服务端原样保留 13 个不等长圈，
  `fast` 指向的圈可能是 930m 而非 1000m，但 `avgPace` 已折算成每公里配速。
- 判断圈来源**以活动名/课表名或用户说明为准，不要凭圈长分布猜**（手动圈 / 课表圈 / 自动 1km 都可能产生不等长圈）。

## 八、与换皮/互转任务的关系

MCP 只负责**取数 + 验结果**，不参与改文件。两处配合：

1. **取原始 FIT 做诊断**：判断某条活动能否算出最快1KM，下载 FIT 看 record 结构
   （消息种类数、`unknown_*` 数量、渐进布局种类），见 `coros_specifics.md` §九。
2. **验证上传结果**：改完上传后，`getActivityDetail` 看是否返回 `Best Kilometer` 字段
   —— 这是判断换皮是否成功的**唯一**验证口径。设备型号、等强配速不在这个接口里体现。

## 九、脱敏与可迁移清单

- ✅ 官方 URL 固定、无需密钥 → 换电脑复制 §一 配置即可。
- ⚠️ 本文所有 `<活动ID>` 为占位符；实跑产生的 `labelId`、OSS 用户目录 ID、账号信息**不写入 skill**。
- ⚠️ 本机曾用的临时 CLI 代理脚本依赖本地加密凭据缓存，属**本机临时工具、不可迁移**，不纳入 skill；换电脑直接用 WorkBuddy 内置 MCP 通道调工具。
- ⚠️ 涉及跨活动长期观测的样本台账存工作区记忆（`best1km_ab_tracker.md`），不进 skill。
