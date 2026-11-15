# 高驰 ↔ 佳明 互转对照

> **性质**：两平台差异的处理清单。「相同点」合并在此，平台特有细节分别在 `coros_specifics.md` / `garmin_specifics.md`。
> **执行（按用途分流）**：
> - 布局一致性研究 / 回传 COROS → 模板转换器 `fit_convert_by_template.py --to <规范>`（自动跑规范门禁）。
> - 🔴 **传 Garmin Connect → `inject_garmin_device.mjs apply <源> --device fenix8 --out <出>`**（第五节）。
>   模板转换器的 `--to garmin_watch` 产物是 21 条 `device_info` + proto=0x10，
>   Connect 实测判未知设备并 DEM 重算爬升，**不能拿来上传**。
>
> 手写对照改 = 回到「出问题再补」的老路。
> **配套**：通用规范 `fit_format_spec.md`；分支 `coros_specifics.md` / `garmin_specifics.md`。

---

## 一、相同点（合并，无需特殊处理）

| 项 | 说明 |
|---|---|
| 头部/CRC 算法 | 完全一致（见通用规范一、三）|
| 时间基准 | 均 UTC，epoch 1989-12-31；`timestamp`/`startTime` 自该时起秒数 |
| 躯干消息 | fileId / session / lap / record / event / activity 两平台共有且字段语义对齐 |
| record 布局 | **两家都是渐进式**（非「高驰渐进、佳明全字段」）；类型码均遵循官方 `base_type`，0 偏离 |
| 海拔换算 | `raw/5-500` = m，两家同公式 |
| 步频 | 均存 rpm，真实 = `raw×2`（spm）|
| 速度 / 海拔物理含义 | 同（仅字段号不同，见下）|

## 二、差异总表（处理时逐项）

| # | 维度 | 高驰 | 佳明 | 动作 |
|---|---|---|---|---|
| 1 | `protocol_version` | 32 | 16 | 按目标改写 |
| 2 | `profile_version` | 21158 | 21213 | 按目标改写 |
| 3 | 消息集合 | 白名单 9 种 | 36 种（27 私有）| 取目标白名单；源有多余→省略整条消息 |
| 4 | device_info 条数 | 1 | 21 | 目标 1 条主设备（佳明传感器源无→省略）|
| 5 | 开发者字段 | 207+206×2（Effort Pace）| 无 | 转佳明：剥离或按目标保留；转高驰：补声明 |
| 6 | record 速度字段号 | `f6` | `f73` enhancedSpeed | 映射搬运 |
| 7 | record 海拔字段号 | `f2` | `f78` enhancedAltitude | 映射搬运 |
| 8 | lap/session 速度 | `f13`/`f14` | `f110`/`f111`、`f124`/`f125` | 取 enhanced |
| 9 | 配对传感器 | 无 | `global 147` | 转高驰：整条丢弃 |
| 10 | file_id 身份 | mfr=294, product=814 | mfr=1, product=4536 | 按目标重写 |
| 11 | 温度 | `f50`/`f57` S8，源无留 127 | 同上；record 无通道 | 源无→哨兵，绝不编造 |

## 三、佳明 → 高驰 处理清单

| # | 处理项 | 动作 |
|---|---|---|
| 1 | `protocol_version` | 16 → **32** |
| 2 | `profile_version` | 21213 → **21158** |
| 3 | 消息白名单 | 只留高驰 9 种；源有、模板无→**省略**（不填哨兵占位）|
| 4 | record 渐进布局 | 复刻高驰 6 段 DEF 节奏（local 号 9）|
| 5 | 字段类型码 | **一律照高驰 `base_type`**（无 0x00 特例）|
| 6 | 新增 207 + 206×2 | 声明 Effort Pace（field_def_num=16, float32）|
| 7 | record 速度 | 取源 `f73`(enhancedSpeed)，**含 0，不平滑** |
| 8 | record 海拔 | 取源 `f78`(enhancedAltitude)，`raw/5-500` |
| 9 | lap/session 速度 | 取源 `f110`/`f111`、`f124`/`f125` |
| 10 | device_info | 21 → **1**（manufacturer=294, product=814）|
| 11 | file_id | manufacturer=294, product=814, name=`"COROS APEX 4 42mm"` |
| 12 | 丢弃 sport/fileCreator/gpsMetadata/配对传感器 | 源有模板无→省略 |
| 13 | 温度 | 源无→留哨兵 |
| 14 | CRC | 重算头部 + 文件 CRC |

## 四、高驰 → 佳明 处理清单（规范布局件）

> 🔴 **本节只保证「布局与佳明规范逐项一致」，不保证产物能上传 Garmin Connect。**
> 2026-11-15 实测：按本节清单重建的产物门禁 115/0、diff 22/0、QA 11/0、
> 官方 SDK 0 error + integrity=true，上传 Connect 后仍判「未知设备」，
> 且 `session.total_ascent=81m` 被 DEM 地形数据重算成 **287m**
> （record 海拔逐点无阈值上升只有 83.0m，287m 不来自文件）。
> 补 21 条 `device_info` 的 `source_type=local` / `device_index` /
> `software_version`，再从真机抠 `file_creator` 插入，**仍然不行** ——
> 根因是整条路线（21 条 device_info + proto=0x10），不是缺标记。
> **传 Connect 请走第五节注入路线**，并验三条判据：`proto=0x02` /
> `device_info` 恰好 1 条且 `sourceType=local` / `file_id.serialNumber` 为真实 Unit ID。

| # | 处理项 | 动作 |
|---|---|---|
| 1 | `protocol_version` | 32 → **16** |
| 2 | `profile_version` | 21158 → **21213** |
| 3 | 消息补齐 | 模板 36 种；源无对应数据的 29 种私有消息**省略**（不造假占位）|
| 4 | 丢弃开发者字段 | 删 206/207 + 各消息 dev 字段 |
| 5 | 字段类型码 | **照佳明 `base_type`** |
| 6 | 速度字段映射 | `f6` → `f73`；lap `f13`/`f14` → `f110`/`f111` |
| 7 | 海拔字段映射 | `f2` → `f78` |
| 8 | device_info | 1 条 → 匹配佳明布局的 1 条主设备（内置传感器源无→省略）|
| 9 | activity 私有字段 | 按模板补 |
| 10 | 温度 | 有值可搬，无则留哨兵 |
| 11 | file_id 身份 | manufacturer=1, product=4536, SN 取私有区真实值 |
| 12 | CRC | 重算 |

> 📌 **「省略」vs「哨兵」**：模板用了但源完全没有该消息类型 → **省略整条消息**；模板某字段源有消息但该字段本次无值 → 该字段写官方**哨兵**（如温度 S8 填 127）。语义不同。

## 五、换皮（只换设备身份，数据不动）的快捷路线

完整格式互转很重；多数需求只是「把任意运动文件伪装成某平台标准设备」：

- **任意 → 佳明**：`inject_garmin_device.mjs apply <源> --device garmin --out <出>`（剥离第三方私有段、重写 file_id/device_info 为真实 garmin、防 Connect 重算爬升）。
- **任意 → 高驰**：`inject_coros.py apply <源> --device apex4 --out <出>`（字节级嵌入高驰 device_info、proto 翻 0x20）。
- **两平台互逆换皮**：`rebrand_device.py <src> <ref> <out>`（复制 ref 的 file_id+device_info 字节，src 的 local 号+时间戳，运动数据 100% 保留）。

> 换皮只换设备身份，核心运动数据不变；平台专属指标（如高驰 Effort Pace）在换皮到对方时按对方规则剥离/保留。

### 五之一、任意 → 佳明（传 Garmin Connect）实证与判据

`inject_garmin_device.mjs` 用官方 SDK 全量重编码，与第四节「规范重建」是两条不同路线，
不要把第四节的布局要求套到这里：

| 项 | 规范重建（第四节）| **注入路线（传 Connect 用）** |
|---|---|---|
| `protocol_version` | 16 / 0x10 | **2 / 0x02**（SKILL.md 铁律 4）|
| `device_info` | 21 条、字段多为哨兵 | **恰好 1 条**，`sourceType=local`、`deviceIndex=creator` |
| `software_version` | `0xFFFF` 无效 | 真机值（本机 22.41）|
| `file_creator`(g=49) | 0 条（补了也没用）| 0 条 —— **非必需** |
| `file_id.serialNumber` | v4.8.1 起自动带真实 Unit ID | 真实 Unit ID（Connect 服务端校验 `(product, UnitID)`）|
| 私有 dev 段 | 剥离 | 剥离（日志 `制造商=undefined` 是 SDK 字段名映射误报，不影响）|
| 运动数据 | 逐点守恒 | 逐点守恒（实测 7173 timestamp / distance、7172 HR、6748 GPS、7158 海拔、7169 速度全 0 差异）|
| Connect 结果 | ❌ 未知设备 + 287m | ✅ 显示 fenix8、`total_ascent=81m` 保留 |

**三条交付判据（缺一不可）**：`proto=0x02` / `device_info` 恰好 1 条且 `sourceType=local` /
`file_id.serialNumber` 为真实 Unit ID。门禁 / QA / SDK 全绿**不能**替代这三条。

**排查口径**：
- 「累计爬升被改」先算文件内 record 海拔逐点无阈值上升。若与
  `session.total_ascent` 一致而平台显示值远大于它 → DEM 重算，不是文件数据错。
- DEM 重算与「未知设备」是**同一个根因**（没被认成带气压高度计的真实设备），别分开查。
- Connect「装备」(Gear) 是跑鞋等手动关联项，FIT 无此字段；设备型号在「设备」栏。
- 重传前必须删旧活动破缓存；若删干净重传仍异常，才考虑 Connect 网页版
  「海拔校正」开关（平台侧，FIT 改不动）。
