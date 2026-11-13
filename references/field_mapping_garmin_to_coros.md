# 官方 FIT 定义驱动的字段映射（佳明 → 高驰）

> **基准来源**：`references/fit_profile_official.json`
> 由 `@garmin/fitsdk` v21.214 官方 Profile 导出，含 record/lap/session/device_info 等消息的
> 完整字段定义（字段号 / 名称 / 类型 / **scale** / **offset** / 单位）。
>
> **核心原则**：一切以官方定义为准。字段号、scale、offset 三样对齐，数据才对。
> 实测高驰与佳明**都严格遵循官方定义**，因此大部分字段可以「同号直搬」。

---

## 🔴 最重要的坑：字段号不能靠记忆，必须查官方定义

我在这上面栽过最大的跟头：

| 我以为 | 官方实际定义 | 后果 |
|---|---|---|
| `f73` = 海拔 | **`f73` = enhancedSpeed（速度）** | 把速度当海拔 → 算出 6000 米假海拔 |
| `f78` = 速度 | **`f78` = enhancedAltitude（海拔）** | 漏掉真实海拔 |

**实测验证**：`f78` 按官方 `(v/5-500)` 解码 = **6.6~16.2 米**，与「福建平原海拔个位数」完全吻合 ✅

> 📌 **务必先读 `fit_profile_official.json`，再写映射代码。**

## 🔴 坑中坑：「enhanced 系列」比基础字段更可信

FIT 有**一套基础字段 + 一套 enhanced 字段**，两者含义相同但 enhanced 精度更高：

| 基础字段 | enhanced 字段 | 说明 |
|---|---|---|
| `f2` altitude (u16) | **`f78` enhancedAltitude (u32)** | 精度更高 |
| `f6` speed (u16) | **`f73` enhancedSpeed (u32)** | 精度更高 |
| lap `f13` avgSpeed | **lap `f110` enhancedAvgSpeed** | |
| lap `f14` maxSpeed | **lap `f111` enhancedMaxSpeed** | |
| lap `f50` avgTemperature | — | |
| session `f14`/`f15` | **session `f124`/`f125` enhancedAvg/MaxSpeed** | |
| lap `f113`/`f114` | enhancedMin/MaxAltitude | |

**实测规律：佳明的基础字段常常是无效值（`0xFFFF` / `0xFFFFFFFF`），真值在 enhanced 字段里。**
例：佳明 session 的 `f14`/`f15` = `0xFFFF`，而 `f124`/`f125` = 3342 / 4507（= 3.342 / 4.507 m/s）✅

> ✅ **取值优先级：enhanced 字段 > 基础字段 > 从其它量推导。**

---

## 零、高驰 FIT 的「非官方」写法清单（照抄真机，别按官方 profile 硬套）

高驰**大体遵循 FIT 官方定义**，但在若干处有自己的固定写法。这些是**逐字节比对真机**得出的，
不照抄就可能被高驰 APP 判为「结构异常」而跳过派生指标计算。

| # | 项 | 高驰真机写法 | 说明 |
|---|---|---|---|
| 1 | `protocol_version` | **32**（佳明是 16）| 头部第 2 字节 |
| 2 | `profile_version` | **21158** | 头部第 3-4 字节 |
| 3 | 字段类型码 | **查模板 `base_type`** | ~~高驰写 0x00 enum~~ **【已证伪】**：两家真机类型码均与官方一致 |
| 4 | **record 渐进式布局** | 见下节 | **最重要，见专节** |
| 5 | `fieldDescription` | **声明 2 次**（local 0 + local 8，内容相同）| 只声明 1 次可能被无视 |
| 6 | `record` 的 `f2` 类型码 | 高驰写 **`uint16`** | 官方 altitude 是 `uint16(0x84)`，一致 |
| 7 | lap `f21/f22` 顺序 | `21` 在 `22` 之前 | 字段顺序照抄真机，别按字段号排序 |
| 8 | 无 `file_creator`(49) | 高驰不写 | 只有 `fileId` + `deviceInfo` |
| 9 | 无 `sport`(12) | 高驰不写独立 sport 消息 | sport 在 lap/session 里 |
| 10 | 无 GPS 元数据 | 不写 `gpsMetadata`(162) | 坐标只放 record 的 f0/f1 |

---

## 零点五、🔑 record 的「渐进式布局」——高驰的字段可用性声明

**这是高驰最有特色的写法，也是最容易漏的。**

### 现象

高驰真机**同一段 record 用 6 种不同 DEF**，前 9 条从少到多逐步增加字段：

| 顺序 | 字段集合 | 条数 |
|---|---|---|
| 1 | `[42, 253, 5]` | 1 |
| 2 | `[42, 253, 0, 1, 5, 3]` | 2 |
| 3 | `[42, 253, 0, 1, 5, 3, 6, 41, 39, 83]` + dev16 | 2 |
| 4 | `[42, 253, 0, 1, 5, 3, 2, 6, 41, 39, 83]` + dev16 | 2 |
| 5 | `[42, 253, 0, 1, 5, 3, 2, 6, 7, 29, 41, 39, 83, 85]` + dev16 | 2 |
| 6 | 全 15 字段 + dev16 | 余下全部 |

### 为什么重要

FIT 的 DEF 一旦出现就持续有效。高驰用「逐步增加字段」的写法，
相当于**逐段声明「这些字段从这一刻起才有值」**。

GPS 冷启动时前排数据（心率/步频/步态）本来就不可靠，
高驰用这个机制把「数据有效起点」表达出来。若一上来就全字段声明，
解析器会认为第一秒的步态数据就可用 —— 而这些值其实是 0/无效的垃圾，
可能导致**高驰跳过依赖这些数据的派生指标（如最快 1KM、最佳配速）**。

### 实现

脚本里 `PROG` 列表定义了这个节奏，用
`Writer.def_bytes_subset()` / `data_bytes_subset()` 按子集写 DEF + MSG。
**新增消息类型时同样要检查真机是否有渐进写法。**

---

## 零、通用排查方法论（遇「高驰不显示某指标」按此顺序）

1. **先读 `fit_profile_official.json` 确认字段语义**（别靠记忆）
2. **统计零值点**：`speed==0` 的点数是否与源相当（暂停识别）
3. **比对消息构成**：global 号集合、各消息数量是否与真机同构
4. **比对 DEF 布局序列**：高驰特有渐进写法是否复刻
5. **比对字段类型码**：`fitBaseTypeId` 是否逐字段一致
6. **比对「真机有值、我无效」的字段**（用 `fit_vs_official.py` 的思路反查）
7. **校验 CRC**：头部 CRC + 整文件 CRC
8. **用官方 SDK 解码**：`@garmin/fitsdk` 能否 0 error 解析

---

## 🔴🔴🔴 最高铁律：绝不编造数据（比留空更严重）

**这是所有错误里性质最恶劣的一种，必须置顶。**

### 我犯的错

我看到高驰真机 `lap.f50 avgTemperature = 34`，而佳明源是 `127`（无效），
于是**自己编了一套"按月份的气候中位数"**：

```python
_by_month = {1: 12, 2: 13, ..., 8: 31, 9: 28, ...}
src_temp = _by_month.get(_m, 24)      # ← 凭想象生成的假数据
```

同样地，`avgStanceTimePercent` / `avgStanceTimeBalance` 源是 `65535`（无效），
我看到真机是 `0`，就**也跟着写 0**。

**为什么这比留空严重得多**：
- 留无效值 = 诚实地说「我不知道」
- 编造值 = 伪造证据。用户看到"31℃"会以为这是手表测的，实际上是模型凭空造的。
- **数据类产物的可信度是底线，一旦掺假，整个产物作废。**

### 铁律

> **没有数据来源的字段，一律留无效哨兵。永不填推测值、经验值、气候值、平均值。**
> 「高驰真机有这个值」≠「我必须有这个值」。真机的值来自它自己的传感器/App/服务，
> 我拿不到就是拿不到。

### 自检问题

写每个字段前问自己：**这个值的原始来源是什么？**
- 源文件里的某个字段 → ✅ 可以搬（注意 scale/offset）
- 能从源数据确定性推导（如 lap 均速 = 距离/时间）→ ✅ 可以算
- **"大概是这个数吧"/"按经验应该是"/"按月份应该是" → ❌ 禁止写入**

### 已被我编造过、现已全部回退的字段

| 字段 | 我编造的值 | 正确做法 |
|---|---|---|
| `lap.f50` / `session.f57` avgTemperature | 按月份 12~31℃ | 源无温度通道 → 留 `127`（S8 无效） |
| `lap.f78` avgStanceTimePercent | 0 | 源为 `65535` → 留 `65535` |
| `session.f133` avgStanceTimeBalance | 0 | 源为 `65535` → 留 `65535` |

### 另一条相关教训：字段号必须查官方定义

我在查温度时又一次猜错：以为 record 的温度是 `f53`，**实际 `f53` 是 `fractionalCadence`（小数步频，值只有 0/64）**，
`f13` 才是 `temperature`。且实测本佳明文件**根本没有 f13 通道**（fenix 8 需外接温度计）。

> 📌 **任何字段号都要先查 `fit_profile_official.json` 再写代码。**

---

## 🔴🔴 第二重要的坑：速度的「0」是有效值，且必须信源不信任差分

**症状**：高驰 APP **不显示「最快 1KM」/ 最佳配速**，其它数据都正常。

**根因**：高驰靠 **`speed == 0`** 识别暂停/静止段 → 据此算**移动时间** →
移动时间没了，就切不出「连续 1 公里」，最快 1KM 整块空白。

我犯的两个错（同一根因的两面）：

| 错误写法 | 后果 |
|---|---|
| `if 0 < cand < 20` | 暂停点的 0 被当无效过滤掉 |
| 滑动中值平滑（窗口5） | 邻居正值把 0 抬起来，高驰看到「一路匀速、从不暂停」 |
| **距离差分优先于源速率** | ①暂停段 GPS 漂移 → 差分把 0 抬成正值；②起跑冷启动 → 差分算出 4.03 m/s，源实际只有 1.60 |

**正确做法（定稿）**：

1. **速度优先级**：源 `enhancedSpeed(f73)` 有效 → **一律采用**；源无效 → 才退回距离差分兜底。
2. **不做任何平滑**：源的 enhancedSpeed 是设备（气压/加速度/GPS 融合）已平滑过的结果，
   再平滑会破坏暂停点的 0 和起跑/冲刺的快速变化。
3. **写入端判空必须用 `is not None`**，绝不能用 `if spd_ms`（0 是假值会被丢）。
4. 零速要显式保留：`0 <= cand < 20`（含 0）。

**验证方法**：统计 `speed == 0` 的点数，应与源文件**数量相当**。

| | 高驰真机 | 修复前 | 修复后 |
|---|---|---|---|
| `speed==0` 点数 | 24 | **0** ❌ | **12** ✅（与源一致）|

> 💡 高驰真机验证：其 record 的 `dev16`（开发者字段「Effort Pace」）与距离差分的吻合率
> 只有 **65%** —— 说明它不是差分，而是**设备融合的平滑速率**。所以「信源、别信差分」是对的。

### 排查「高驰不显示最快 1KM」的检查顺序

1. **`speed==0` 点数是否为 0** ← 最常见根因，先查这个
2. lap 是否按 1km 划分（`f25 lapTrigger == 1`）
3. `record` 是否带 `dev16`（Effort Pace 通道，高驰靠它算成绩）
4. 设备身份（`device_info.f2 manufacturer=294`、`f27` 型号串）是否合规
5. GPS 字段（`f0/f1 positionLat/Long`）是否有值

---

## 一、record（global 20）字段映射

### 官方定义（关键字段）

| 字段 | 官方名称 | 类型 | scale | offset | 单位 |
|---|---|---|---|---|---|
| `f0` | positionLat | sint32 | 1 | 0 | semicircles |
| `f1` | positionLong | sint32 | 1 | 0 | semicircles |
| `f2` | **altitude** | uint16 | **5** | **500** | m |
| `f3` | heartRate | uint8 | 1 | 0 | bpm |
| `f4` | cadence | uint8 | 1 | 0 | rpm |
| `f5` | distance | uint32 | **100** | 0 | m |
| `f6` | **speed** | uint16 | **1000** | 0 | m/s |
| `f7` | power | uint16 | 1 | 0 | watts |
| `f29` | accumulatedPower | uint32 | 1 | 0 | watts |
| `f39` | verticalOscillation | uint16 | **10** | 0 | mm |
| `f41` | stanceTime | uint16 | **10** | 0 | ms |
| `f42` | activityType | enum | 1 | 0 | — |
| `f73` | **enhancedSpeed** | uint32 | **1000** | 0 | m/s |
| `f78` | **enhancedAltitude** | uint32 | **5** | **500** | m |
| `f83` | verticalRatio | uint16 | **100** | 0 | percent |
| `f85` | stepLength | uint16 | **10** | 0 | mm |
| `f253` | timestamp | dateTime | 1 | 0 | s |

### 映射：佳明 → 高驰

| 高驰 | 官方名 | 佳明来源 | 换算 |
|---|---|---|---|
| `f2` altitude | altitude | **`f78` enhancedAltitude** | ⚠️ **不是 f73**。`v/5-500` 得米 → 回写 `(米+500)*5` |
| `f6` speed | speed | **`f73` enhancedSpeed**（或距离差分） | `v/1000` = m/s → 回写 `m/s*1000` |
| `f3` heartRate | | 佳明 `f3` | 直搬 |
| `f4` cadence | | 佳明 `f4` | 直搬 |
| `f5` distance | | 佳明 `f5` | 直搬（cm）|
| `f0`/`f1` | | 佳明同号 | 直搬 |
| `f7` power | | 佳明 `f7` | 直搬 |
| `f29` accumulatedPower | | 佳明 `f29` | 直搬 |
| `f39` verticalOscillation | | 佳明 `f39` | 直搬（scale 10）|
| `f41` stanceTime | | 佳明 `f41` | 直搬（scale 10）|
| `f83` verticalRatio | | 佳明 `f83` | 直搬（scale 100）|
| `f85` stepLength | | 佳明 `f85` | 直搬（scale 10）|
| dev16 | Effort Pace | 速度 m/s | float32 |

### ⚠️ 佳明的私有字段（官方无定义）

佳明 record 里有 9 个字段**不在官方 profile 中**，是佳明私有开发者字段：

`f90` `f107` `f135` `f136` `f137` `f138` `f140` `f143` `f145`

→ **高驰不需要它们，重建时丢弃。**

---

## 二、lap（global 19）字段映射

高驰与佳明**同号字段在官方定义下完全一致**，因此**同号直搬即可**：

| 字段 | 官方名称 | scale | 单位 | 说明 |
|---|---|---|---|---|
| `f254` | messageIndex | 1 | — | 圈序号 |
| `f253` | timestamp | 1 | s | |
| `f2` | startTime | 1 | — | |
| `f8` | totalTimerTime | 1000 | s | |
| `f7` | totalElapsedTime | 1000 | s | |
| `f9` | totalDistance | 100 | m | |
| `f11` | totalCalories | 1 | kcal | |
| `f25` | sport | 1 | — | |
| `f16` | maxHeartRate | 1 | bpm | |
| `f63` | minHeartRate | 1 | bpm | |
| `f15` | avgHeartRate | 1 | bpm | |
| `f50` | **avgTemperature** | 1 | **℃** | ⚠️ **不是步频** |
| `f13` | avgSpeed | 1000 | m/s | |
| `f14` | maxSpeed | 1000 | m/s | |
| `f17` | avgCadence | 1 | rpm | ⚠️ 见下方步频说明 |
| `f18` | maxCadence | 1 | rpm | |
| `f120` | avgStepLength | **10** | mm | |
| `f22` | totalDescent | 1 | m | |
| `f21` | totalAscent | 1 | m | |
| `f19` | **avgPower** | 1 | **watts** | ⚠️ **不是垂直振幅** |
| `f79` | **avgStanceTime** | 10 | ms | ⚠️ **不是垂直步幅比** |
| `f78` | avgStanceTimePercent | 100 | % | |
| `f77` | **avgVerticalOscillation** | 10 | mm | ⚠️ **不是触地时间** |
| `f118` | **avgVerticalRatio** | 100 | % | |

### ⚠️ 佳明 lap 的速度在 `f110`/`f111`，不在 `f13`/`f14`

实测佳明 lap 的 `f13`/`f14` = `0xFFFF`（无效），真实速度在：

| 佳明 lap | 官方名 | scale | 高驰对应 |
|---|---|---|---|
| `f110` | enhancedAvgSpeed | 1000 | → `f13` |
| `f111` | enhancedMaxSpeed | 1000 | → `f14` |

> **所以「同号直搬」在速度这一项上不成立**，必须做字段号映射。

### 佳明 lap 私有字段（官方无定义，丢弃）

`f27` `f28` `f29` `f30` `f145` `f155` `f161` `f166` `f167` `f168` `f169`

---

## 三、session（global 18）字段映射

高驰与佳明同号字段一致，直搬：

| 字段 | 官方名称 | scale | 单位 |
|---|---|---|---|
| `f5` | sport | 1 | — |
| `f2` | startTime | 1 | — |
| `f253` | timestamp | 1 | s |
| `f7` | totalElapsedTime | 1000 | s |
| `f8` | totalTimerTime | 1000 | s |
| `f9` | totalDistance | 100 | m |
| `f10` | totalCycles | 1 | cycles |
| `f11` | totalCalories | 1 | kcal |
| `f16` | avgHeartRate | 1 | bpm |
| `f17` | maxHeartRate | 1 | bpm |
| `f18` | avgCadence | 1 | rpm |
| `f19` | maxCadence | 1 | rpm |
| `f20` | avgPower | 1 | watts |
| **`f22`** | **totalAscent** | 1 | **m** ✅ |
| **`f23`** | **totalDescent** | 1 | **m** ✅ |
| `f57` | avgTemperature | 1 | ℃ |
| `f64` | minHeartRate | 1 | bpm |
| `f14` | avgSpeed | 1000 | m/s |
| `f15` | maxSpeed | 1000 | m/s |
| `f89` | avgVerticalOscillation | 10 | mm |
| `f91` | avgStanceTime | 10 | ms |
| `f132` | avgVerticalRatio | 100 | % |
| `f133` | avgStanceTimeBalance | 100 | % |
| `f134` | avgStepLength | 10 | mm |

> ✅ **`f22`/`f23` = totalAscent/totalDescent 已由官方定义确认**（真机 332/345）。
> 这就是用户说的「累计爬升 5 米」（源文件的值）对应的字段。

---

## 四、步频的 scale（重要）

官方 `cadence` 的 scale = 1、单位 rpm。但实测**高驰与佳明的实际存储都是 ×2**：

- 高驰 record `f4`：原始 28~255，中位 84 → **真实步频 168 spm**（×2）
- 佳明 record `f4`：原始 75~94，中位 86 → 172 spm（×2）

**验证方法**（逐点交叉验证，吻合率 2971/2980 = 99.7%）：
```
步幅 = 速度 / (步频/60)
若用 f4×2：  吻合率 99.7% ✅
若用 f4 原值：吻合率 0%    ❌
```

> ⚠️ 这是**实际文件 vs 官方定义的一处偏离**（官方 scale=1，实际按 ×2 存）。
> 转换时若两边都是 ×2，**直搬即可**（不需要额外转换）。

---

## 五、以官方定义为准的转换检查清单

1. **先读 `fit_profile_official.json`**，确认每个字段的名称/scale/offset
2. 比对源文件与目标文件在**同号字段上的官方名称是否一致** —— 不一致就必须做字段号映射
3. **优先取 enhanced 字段**（基础字段常为无效值）
4. 检查是否有**官方无定义的字段**（私有字段）—— 见下方清单，通常应丢弃
5. 检查 scale 是否被实际文件偏离（如步频 ×2）—— 两边一致则直搬
6. 数值回写时**按官方 scale/offset 反算**，并校验范围（如 altitude 必须 0..65534）
7. **无效值按类型码填哨兵**（S8=127 / S16=0x7FFF / S32=0x7FFFFFFF / 无符号=全1）—— 见下方专节
8. 用「物理量是否合理」做最终校验（海拔个位数、配速 4~7 分、步频 160~180、**温度不能是 127/255**）

### 佳明私有字段清单（官方 profile 中不存在，重建时丢弃）

| 消息 | 私有字段 |
|---|---|
| `record` | `f90` `f107` `f135` `f136` `f137` `f138` `f140` `f143` `f145` |
| `lap` | `f27` `f28` `f29` `f30` `f145` `f155` `f161` `f166` `f167` `f168` `f169` |
| `session` | `f81` 等 |

> 这些是佳明私有的扩展字段，高驰用不上。判断方法：查官方 profile，查不到的即为私有。

### 🔴 无效值哨兵必须「按类型码」选，不能一律填 0xFF

FIT 的「无效值」不是统一的全 1，而是**按类型码分**：

| 类型 | 无效哨兵 | 误填 0xFF 的后果 |
|---|---|---|
| `U8` / `U16` / `U32`（无符号）| `0xFF` / `0xFFFF` / `0xFFFFFFFF` | ✅ 正确 |
| **`S8`** | **`0x7F`（127）** | 读成 `-1`，无符号解读就是 **255** |
| `S16` | `0x7FFF` | 读成 `-1` |
| `S32` | `0x7FFFFFFF` | 读成 `-1` |

**踩坑实录**：lap `f50`（`avgTemperature`，类型 **S8**）源文件是 `127`（=无数据）。我用一个 `ok8()` 把它过滤成 `None`，写入器对 `None` 一律填 `0xFF` → 高驰页面把温度显示成 **255℃**。

> 🔑 **通用做法**：对「源文件为无效」的字段，**直接透传源原始字节**（或按上表填对应类型的哨兵），
> 不要经过「值→None→重新编码」这条会丢失类型信息的路径。
> 校验时也要**按类型码读回**（S8 用 `struct.unpack('<b')`），否则检测不出这类错误。

### 校验脚本

```bash
# 1) 比对任意 FIT 文件 vs 官方定义（找偏离）
python scripts/fit_vs_official.py <文件.fit> [文件2.fit ...]

# 2) 校验产物是否符合高驰规范 + 数值是否合理
#    路径已参数化，禁止硬编码（硬编码会在换文件时静默校验错对象）
python scripts/fit_verify_coros.py <产物.fit> [源文件.fit] [高驰模板.fit]
```

