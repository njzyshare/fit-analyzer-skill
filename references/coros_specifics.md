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

> ⚠️ **dev16 ≠ speed**：中位绝对差 0.154 m/s、仅 33.6% 点位全等（判级 `approx`）。它是更平滑、未量化的速度版本。
> 🔴 ~~「最快 1KM / 最佳配速的依赖通道」~~ —— **已被实验推翻**：无 dev16 的文件照样能算出最快1KM（见 §九）。
> 禁止断言 dev16==speed，缺失时按 §十 GAP 模型重建或留哨兵。
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

## 九、最快1KM 派生条件（实验定案）

### 唯一判据：record 骨架，不是字段齐不齐

高驰算不算「最快1KM」，**只取决于 record 记录体是否按高驰规范真正重建**。

| 做法 | 消息种类 | `unknown_*` 字段 | 渐进布局 | 最快1KM |
|---|---|---|---|---|
| 只改 `file_id` / `device_info` | 35~37 | 11~12 个 | 2 种 | ❌ 不出 |
| 规范重建记录体 | 9~12 | **0** | **4~7 种** | ✅ 出 |

**机制**：高驰入库时扫 record 的逐点距离流，按 1000m 滑动窗口算最快1KM。
record 若是佳明布局原样搬过来，字段号/字节长度/类型码全按佳明语义排列，
高驰按自己的定义去读——**位置对不上，速度列读出来是空的**。
它不报错、只静默跳过派生，且**一次性入库、不重试**，所以「上传那一瞬间就定死，之后永不补算」。

### 已被实验证否的因素（不要再往这些方向查）

| 假设 | 判决 | 反证 |
|---|---|---|
| dev16（Effort Pace）必需 | ❌ | 有文件无 dev16，仍算出最快1KM |
| session `max_speed` 必需 | ❌ | 无 `max_speed` 也能算出 |
| `field_description` 必需 | ❌ | 同上 |
| lap 必须按 1km 切 | ❌ | 有 11 个标准 1km lap，仍算不出 |

**次要条件**：必须有 `lap` 消息（哪怕只有残圈）。骨架干净但 `lap = 0` 也失败。

### 最快1KM 的算法（可自算核对）

**它不等于 lap 里最快的那一圈**，而是 **record 距离流按 1000m 滑动窗口取最短用时**。

| 活动类型 | lap 最快圈 | 应用显示 | 按 record 自算 |
|---|---|---|---|
| 10km 日常跑 | 3:58（含末尾残圈）| **4:12** | **4:12.5** ✅ |
| 全马 A | 4:35 | **4:25** | **4:25.2** ✅ |
| 全马 B | 4:37 | **4:27** | **4:27.2** ✅ |

```python
pts = [(r.timestamp, r.distance) for r in records]   # distance 单位米
# 对每个 i，用插值取从 pts[i] 起走满 1000m 所耗秒数，取最小值
```

**核对某条记录的最快1KM 时用滑动窗口算，不要用 lap 最快值** —— 后者会差 10~20 秒。

## 十、平台侧限制（FIT 改不出来的两项）

经实验确认，下面两项**即使文件完全合规也不显示**，属服务端/硬件侧判定，不要在 FIT 上折腾。

| 项 | 为什么改不出来 |
|---|---|
| **设备型号显示** | 真高驰的 `device_info` 也只有 1 条 3 字段（timestamp/manufacturer/product_name），与合规产物**完全同构**。后台显示「手表+心率带」来自服务端对真机序列号/固件/蓝牙绑定的校验，FIT 不承载 |
| **等强配速** | dev16 定义与真机一致、数值已按 GAP 坡度修正（相关性 +0.807 vs 真机 +0.761~0.842）、record+session+lap 三层都写入 —— **仍不显示**。旁证：两场不同活动的 session EP 是 float32 位级相同的常量，不像计算结果 |

### 🔴 结论：换皮唯一能影响的数据是「最快1KM」

设备型号、等强配速都改不出来。**评估换皮是否成功，只看最快1KM 出没出。**

### 自查清单：这份文件算不算换皮成功

| 指标 | 成功 | 失败特征 |
|---|---|---|
| `file_id.manufacturer` | `coros` | `garmin` = **根本没换皮**，原始文件裸传 |
| `file_id.product` | 具体型号（814/808）| `899` 或 `COROS Wearables` = 通用占位 |
| record `unknown_*` 数量 | **0** | ≥11 = 佳明布局原样带过来 |
| 消息种类 | 9~12 | 35~37 = 没重建 |
| `gps_metadata` / `split` / `split_summary` | **不应存在** | 存在 = 佳明专有消息残留 |

## 十一、dev16 = GAP 坡度修正（重建模型）

即使平台不展示，dev16 仍应写入有意义的爬升修正值（正确语义，也是未来平台放开的前提）。
`fit_convert_by_template.py` 的 `_inject_gap_dev16()` 已内置，**源缺 dev16 时自动执行**，
并同步写 session / lap（`_inject_gap_summary()`）。源已有 dev16 时原样保留。

### 模型

```
C(i) = 155.4i⁵ − 30.4i⁴ − 43.3i³ + 46.3i² + 19.5i + 3.6      # Minetti 代谢代价，i = grade 小数
f(grade) = 1 + k · (C(i)/C(0) − 1)
EP = speed × f(grade)
```

**标定**（两场真机马拉松共 1696 段，50m 窗口线性回归求坡度）：

| 参数 | 值 |
|---|---|
| `k` | **0.80** |
| `C(0)` | 3.6000 J/kg/m |
| 拟合 RMSE | **0.066 m/s** |

**分箱验证**（误差全部 ≤0.033 m/s，仅 2~4% 陡坡 −0.153）：

| 坡度% | n | 实测 EP | 预测 EP | 实测 EP/speed |
|---|---|---|---|---|
| −6~−4 | 2 | 3.222 | 3.239 | 0.834 |
| −4~−2 | 19 | 3.281 | 3.272 | 0.881 |
| −2~−1 | 76 | 3.429 | 3.419 | 0.949 |
| −1~1 | 1495 | 3.513 | 3.510 | **0.9988** |
| 1~2 | 85 | 3.664 | 3.631 | 1.069 |
| 2~4 | 19 | 3.878 | 3.725 | 1.186 |

### 🔴 符号方向别搞反

`EP = speed × f` —— **上坡 EP 更大、下坡更小**。这与「修正后配速变慢」的字面直觉相反，
但真机实测如此，**照抄不改**。（按 `EP = speed / f` 写会得到 −0.806 的负相关，符号整个反。）

### 心率不参与

用两场真机 1696 段算残差 `EP − speed×f(grade)`，再与各变量求相关：

| 变量 | 与残差相关性 | 结论 |
|---|---|---|
| **心率** | **+0.017** | ≈0，**无独立贡献** |
| 功率 | +0.362 | 有一定相关，非主因 |
| 坡度 | +0.017 | 已解释干净（残差绝对值仅 0.041 m/s ≈ 1.2%）|

**结论：坡度模型已解释 EP 的 98.8%，不必做心率增强版。**

### session / lap 也要写

真机形态：session EP ≈ avg_speed；**lap 各圈等于同一个常量**（整场同值，非逐圈计算）。
只写 record 不写 session/lap，session 级指标仍会缺值。
