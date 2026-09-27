# 高驰（COROS）特有规范

> **性质**：高驰在 FIT 标准之外的私有约定清单。互转 / 注入 / 换皮时必须逐条处理。
> **来源**：逐字节实测高驰真机 `480277519283552261.fit`（APEX 4）、`480624443926806730.fit`（APEX 4 42mm，2026-09-26 导出）。
> **配套**：通用规范见 `fit_format_spec.md`；佳明侧见 `garmin_specifics.md`；互转对照见 `cross_conversion.md`。

---

## 一、文件级参数

| 项 | 高驰 |
|---|---|
| `header_size` | 14 |
| `protocol_version` | **32** |
| `profile_version` | **21158** |
| `".FIT"` magic | ✅ |
| 尾部 CRC | 同通用（见 `fit_format_spec.md` 一.3） |

🔴 转佳明必须改 `protocol_version` 32→16、`profile_version` 21158→21213，并重算头部 + 文件 CRC。

## 二、消息集合（白名单，9 种，全在官方定义内）

| global | 名称 | 说明 |
|---|---|---|
| 0 | fileId | 1 条 |
| 18 | session | 1 条 |
| 19 | lap | 逐圈 |
| 20 | record | 逐点 |
| 21 | event | timer 起停等 |
| 23 | deviceInfo | **1 条**（精简）|
| 34 | activity | 1 条 |
| 206 | fieldDescription | **2 条**（Effort Pace 声明）|
| 207 | developerDataId | 1 条 |

🔴 高驰**不写** `sport`(12)、`fileCreator`(49)、GPS 元数据(162) 等。转高驰时丢弃源里非上表消息（省略整条，不填哨兵占位）。

## 三、record 渐进式布局（6 段 DEF，最易漏）

高驰同一段 record 用 **6 个不同 DEF**，前 9 条从少到多递增（GPS 冷启动标记数据有效起点）：

| 序号 | 字段集合 | 条数 |
|---|---|---|
| 1 | `[42, 253, 5]` | 1 |
| 2 | `[42, 253, 0, 1, 5, 3]` | 2 |
| 3 | `[42, 253, 0, 1, 5, 3, 6, 41, 39, 83]` **+dev16** | 2 |
| 4 | `[42, 253, 0, 1, 5, 3, 2, 6, 41, 39, 83]` **+dev16** | 2 |
| 5 | `[42, 253, 0, 1, 5, 3, 2, 6, 7, 29, 41, 39, 83, 85]` **+dev16** | 2 |
| 6 | `[42, 253, 0, 1, 5, 3, 2, 6, 4, 7, 29, 41, 39, 83, 85]` **+dev16** | 余下 |

**字段号 → 官方名全枚举**：

| 字段号 | 官方名 | 类型 | 换算 |
|---|---|---|---|
| 42 | activityType | enum | 恒 1（running）|
| 253 | timestamp | uint32 | s |
| 0 | positionLat | sint32 | semicircles |
| 1 | positionLong | sint32 | semicircles |
| 5 | distance | uint32 | cm（scale 100 → m）|
| 3 | heartRate | uint8 | bpm |
| 2 | altitude | uint16 | `raw/5-500` = m |
| 6 | speed | uint16 | `raw/1000` = m/s |
| 4 | cadence | uint8 | **×2 = spm** |
| 7 | power | uint16 | W |
| 29 | accumulatedPower | uint32 | W |
| 41 | stanceTime | uint16 | scale 10 → ms |
| 39 | verticalOscillation | uint16 | scale 10 → mm |
| 83 | verticalRatio | uint16 | scale 100 → % |
| 85 | stepLength | uint16 | scale 10 → mm |
| **dev16** | Effort Pace（开发者）| float32 | m/s |

> 🔴 类型码一律查 `base_type`（`0x85` sint32 等），高驰与官方**0 处偏离**（旧记「经纬度写成 0x00」是 `fit_profile_official.json` 漏 base_type 的误读，已更正）。

## 四、开发者字段：Effort Pace（dev16）

| 消息 | 字段 | 实测值 |
|---|---|---|
| developerDataId(207) | f1 applicationId | `00…00 47`（末字节 `0x47`='G'，COROS 特征）|
| | f2 manufacturerId | **294**（COROS）|
| | f3 developerDataIndex | 0 |
| fieldDescription(206)×2 | f0 developerDataIndex | 0 |
| | f1 fieldDefinitionNumber | **16** |
| | f2 fitBaseTypeId | **136**（`0x88` = float32）|
| | f3 fieldName | `"Effort Pace"` |
| | f8 units | `"m/s"` |

> ⚠️ **dev16 ≠ speed**：中位绝对差 0.154 m/s、仅 33.6% 点位全等（判级 `approx`）。它是更平滑、未量化的速度版本，是**最快 1KM / 最佳配速的依赖通道**。禁止断言 dev16==speed，缺失时留哨兵。
> ⚠️ `@garmin/fitsdk` 解析 developer_data_id 时字段名映射脆弱：脚本读 `manufacturer_id ?? manufacturer` 可能得 `undefined`，但文件实际 `manufacturer_id=294` 确凿——剥离/保留判断要以字节为准。

## 五、device_info（标准精简布局）

实测 APEX 4 42mm device_info 仅 3 字段：`timestamp(253)`、`manufacturer(2)`、`product_name(27)`。

- **manufacturer 标准字段号即 2**，值 294=coros 是**标准写法**（非"非标准"）。
- **无 product 字段**：机型码 `product=814`（APEX 4 42mm）在 `file_id`，不在 device_info。
- **无 serial_number**：高驰导出默认不泄序列号（隐私设计）。

> 🔴 旧记忆「高驰 device_info 非标准、无 manufacturer 字段、field 2 错放 product 位」是**误读**——把 file_id 的字段号(1=manufacturer) 误套到 device_info 上。device_info 的 manufacturer 本就在 field 2。
> 互转 / 注入：**device_info 字节原样复制**；绝不许手搓 def / 改 field 值 / 加 product / 加 serial 字段（会让 COROS 解析器误判，圈距渲染错乱）。

## 六、file_id

| 字段 | 值 |
|---|---|
| 0 type | 4（activity）|
| 1 manufacturer | **294**（COROS）|
| 2 product | **814**（APEX 4 42mm）|
| 4 timeCreated | 导出时间 |
| 8 productName | `"COROS APEX 4 42mm"` |

## 七、速度 / 海拔 / 温度 / 步频

| 项 | 高驰 | 备注 |
|---|---|---|
| record 速度 | `f6` speed（uint16, `raw/1000`）| 含 0 = 暂停 |
| record 海拔 | `f2` altitude（uint16, `raw/5-500`）| |
| lap 平均/最大速度 | `f13` / `f14` | |
| session 平均/最大速度 | `f14` / `f15` | |
| lap/session 温度 | `f50` / `f57`（**S8**）| 源无数据→留 `127`（S8 无效），**绝不编造** |
| 步频 | `f4` record、`f17`/`f18` lap、`f18`/`f19` session | 均 rpm，真实 = `raw×2`（spm）|

## 八、转佳明注意（详见 `cross_conversion.md`）

- 删 206/207 + 各消息 dev 字段（或按目标保留）。
- 速度 `f6`→`f73`(enhancedSpeed)；海拔 `f2`→`f78`(enhancedAltitude)。
- device_info 1 条→匹配佳明布局的 1 条主设备（内置传感器源无数据→省略）。
- 温度有值可搬，无则留哨兵。
- 重算 CRC。
