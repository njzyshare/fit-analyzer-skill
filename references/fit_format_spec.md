# FIT 文件格式规范（全枚举）

> **性质**：FIT 协议的完整格式要求清单，可直接当**校验表**逐条打勾。
> **来源**：Garmin FIT SDK v21.214（`@garmin/fitsdk`）+ 逐字节实测。
> **配套**：字段级明细见 `fit_profile_official.json`；高驰/佳明私有写法见 `vendor_specifics.md`。

---

## 一、文件级结构

### 1.1 文件头（14 字节标准头）

| 偏移 | 长度 | 字段 | 取值/要求 |
|---|---|---|---|
| 0 | 1 | header_size | **14**（标准）；12 表示无 CRC |
| 1 | 1 | protocol_version | 佳明 **16** / 高驰 **32**（最高位 0x80 表示支持 profile 版本）|
| 2 | 2 | profile_version | uint16 LE；佳明 **21213** / 高驰 **21158** |
| 4 | 4 | data_size | uint32 LE = 记录区字节数（**不含头、不含尾部 CRC**）|
| 8 | 4 | data_type | ASCII **`".FIT"`** = `2E 46 49 54` |
| 12 | 2 | header_crc | CRC16(字节 0..11)；header_size=12 时无此项 |

### 1.2 数据区与尾部

| 项 | 要求 |
|---|---|
| 数据区 | `[header_size, header_size + data_size)` 为记录流 |
| 尾部 CRC | 数据区后 **2 字节** CRC16，覆盖范围 `[0, header_size+data_size)` |
| 文件总长 | = `header_size + data_size + 2` |

### 1.3 CRC16 算法（FIT 专用）

```
初值 = 0
表 = [0x0000,0xCC01,0xD801,0x1400,0xF001,0x3C00,0x2800,0xE401,
      0xA001,0x6C00,0x7800,0xB401,0x5000,0x9C01,0x8801,0x4400]
对每字节 b：
  tmp = table[crc & 0xF];  crc = (crc >> 4) & 0x0FFF;  crc ^= tmp ^ table[b & 0xF]
  tmp = table[crc & 0xF];  crc = (crc >> 4) & 0x0FFF;  crc ^= tmp ^ table[(b >> 4) & 0xF]
```
- **头部 CRC**：算 `data[0:12]`
- **文件 CRC**：算 `data[0 : header_size+data_size]`

---

## 二、记录流结构（两种记录）

### 2.1 记录头（1 字节，bit 位语义）

| bit | 掩码 | 含义 |
|---|---|---|
| 7 | `0x80` | **1 = 压缩时间戳头**（Compressed Timestamp）|
| 6 | `0x40` | **1 = 定义消息（DEF）**；0 = 数据消息（MSG）|
| 5 | `0x20` | DEF 时：1 = 含开发字段定义 |
| 4 | `0x10` | DEF 时：保留 |
| 3-0 | `0x0F` | DEF：local 号（0-15）；MSG：local 号 |

**压缩时间戳头（bit7=1）**：
- bit 6 不用作 DEF 标志
- bit 5-4 = **local 号**（仅 2 位，即 0-3）
- bit 3-0 = 时间偏移量
- 真实时间 = 上一条的 timestamp + 偏移（回绕时 +5）

### 2.2 定义消息（DEF）结构

| 序号 | 字段 | 长度 | 说明 |
|---|---|---|---|
| 1 | reserved | 1 | **保留字节，恒 0x00**（易漏！漏了会解析崩）|
| 2 | architecture | 1 | `0` = 小端 LE，`1` = 大端 BE |
| 3 | global_msg_num | 2 | 消息类型号 |
| 4 | num_fields | 1 | 普通字段个数 |
| 5 | 字段定义 ×N | 3×N | 每个：`field_def_num(1) + size(1) + base_type(1)` |
| 6 | num_dev_fields | 1 | 开发字段个数（仅当 bit5=1）|
| 7 | 开发字段定义 ×N | 3×N | 同上结构 |

### 2.3 数据消息（MSG）结构

| 序号 | 字段 | 长度 | 说明 |
|---|---|---|---|
| 1 | 字段值 ×N | Σsize | 按**最近一次同 local 的 DEF** 顺序和长度排布 |

> ⚠️ **DEF 一旦出现即持续有效**，可被后续同 local 的 DEF 覆盖。

---

## 三、类型码（fitBaseType）全枚举

| 十六进制 | 十进制 | 名称 | 字节 | 无效值 | 说明 |
|---|---|---|---|---|---|
| `0x00` | 0 | enum | 1 | `0xFF` | 枚举 |
| `0x01` | 1 | sint8 | 1 | **`0x7F`** | 有符号 |
| `0x02` | 2 | uint8 | 1 | `0xFF` | 无符号 |
| `0x07` | 7 | string | 1 | `0x00` | 定长，NUL 补齐 |
| `0x0A` | 10 | uint8z | 1 | `0x00` | **0 也无效** |
| `0x0D` | 13 | byte | 1 | `0xFF` | 原始字节数组 |
| `0x83` | 131 | sint16 | 2 | **`0x7FFF`** | 有符号 |
| `0x84` | 132 | uint16 | 2 | `0xFFFF` | 无符号 |
| `0x85` | 133 | sint32 | 4 | **`0x7FFFFFFF`** | 有符号 |
| `0x86` | 134 | uint32 | 4 | `0xFFFFFFFF` | 无符号 |
| `0x88` | 136 | float32 | 4 | `0xFFFFFFFF` | IEEE754 |
| `0x89` | 137 | float64 | 8 | `0xFF...` | IEEE754 |
| `0x8B` | 139 | uint16z | 2 | `0x0000` | **0 也无效** |
| `0x8C` | 140 | uint32z | 4 | `0x00000000` | **0 也无效** |
| `0x8E` | 142 | sint64 | 8 | `0x7FFF...` | 有符号 |
| `0x8F` | 143 | uint64 | 8 | `0xFF...` | 无符号 |
| `0x90` | 144 | uint64z | 8 | `0x00...` | **0 也无效** |

### 🔴 无效值规则（按类型分，不可一律 0xFF）

| 类型族 | 无效哨兵 | 误填 0xFF 后果 |
|---|---|---|
| 无符号（U8/U16/U32/U64）| 全 1 | ✅ 正确 |
| **有符号（S8/S16/S32/S64）** | **最大值右移**（`0x7F` / `0x7FFF` / `0x7FFFFFFF`）| 读成 -1 或 127/255 |
| `z` 系列（uint8z 等）| **全 0** | 读成有效值 0 |
| string | 全 `0x00` | — |
| float32/64 | `0xFFFFFFFF` | NaN |

> **实测事故**：lap `f50 avgTemperature` 是 **S8**，源为 `127`（无效），
> 我误填 `0xFF` → 高驰显示 **255℃**。

---

## 四、物理量换算（scale / offset）

**公式**：`物理值 = 原始值 / scale - offset`

| 常见字段 | scale | offset | 单位 | 备注 |
|---|---|---|---|---|
| `altitude` / `enhancedAltitude` | **5** | **500** | m | `raw/5-500`；2530 → 6.0 m |
| `speed` / `enhancedSpeed` | **1000** | 0 | m/s | `raw/1000` |
| `distance` | **100** | 0 | m | `raw/100` |
| `positionLat/Long` | 1 | 0 | semicircles | 度 = `raw × 180 / 2^31` |
| `cadence` | 1 | 0 | rpm | **跑步需 ×2 = spm** |
| `heartRate` | 1 | 0 | bpm | |
| `power` | 1 | 0 | W | |
| `temperature` | 1 | 0 | ℃ | **sint8** |
| `timestamp`/`startTime` | 1 | 0 | s | 自 **1989-12-31 00:00:00 UTC** |
| `totalTimerTime`/`totalElapsedTime` | **1000** | 0 | s | `raw/1000` |
| `totalDistance`(session) | **100** | 0 | m | |
| `totalCalories` | 1 | 0 | kcal | |
| `stanceTime` / `avgStanceTime` | **10** | 0 | ms | |
| `stanceTimePercent` / `avgStanceTimePercent` | **100** | 0 | % | |
| `verticalOscillation` / `avgVerticalOscillation` | **10** | 0 | mm | |
| `verticalRatio` / `avgVerticalRatio` | **100** | 0 | % | |
| `stepLength` / `avgStepLength` | **10** | 0 | mm | |
| `normalizedPower` | 1 | 0 | W | |
| `trainingStressScore` | **10** | 0 | tss | |
| `intensityFactor` | **1000** | 0 | if | |
| `grade` 系列 | **100** | 0 | % | |

> ⚠️ **scale/offset 在官方 profile 里可能是数组**（如 `scale: [1000]`），取第一个元素。
> ⚠️ **部分字段的 scale 是"逐个 scale 值对应"**，需查 profile 确认。

---

## 五、消息清单（运动文件相关，11 个）

| global | 名称 | 官方字段数 | 高驰用 | 佳明用 |
|---|---|---|---|---|
| 0 | fileId | 7 | ✅ | ✅ |
| 12 | sport | 3 | ✗ | ✅ |
| 18 | session | 158 | ✅ | ✅ |
| 19 | lap | 124 | ✅ | ✅ |
| 20 | record | 84 | ✅ | ✅ |
| 21 | event | 19 | ✅ | ✅ |
| 23 | deviceInfo | 19 | ✅ | ✅（21 条）|
| 34 | activity | 8 | ✅ | ✅ |
| 49 | fileCreator | 2 | ✗ | ✅ |
| 206 | fieldDescription | 14 | ✅（2 条）| ✗ |
| 207 | developerDataId | 5 | ✅ | ✗ |

> SDK 共 **124 个消息 / 200 个类型**。运动文件只用到上表 11 个；
> 其余（如 `monitoring` 55、`hrv` 78、`segmentLap` 142、`split` 312、`climbPro` 317 等）用于其他场景。

### 消息出现顺序要求

1. `fileId`（必须第 1 条消息）
2. **`developerDataId`(207) 必须在 `fieldDescription`(206) 之前**
3. **`fieldDescription`(206) 必须在任何引用该开发字段的消息之前**
4. `activity` 通常紧随 `fileId`
5. `event` / `record` 交替
6. `lap` / `session` 通常在尾部

---

## 六、字段校验清单（逐条打勾）

### 6.1 结构校验

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | 头部大小 | 14 |
| 2 | protocol_version | 与目标平台一致 |
| 3 | `".FIT"` magic | 正确 |
| 4 | data_size | == 数据区实际字节数 |
| 5 | 完整解析 | 解析结束位置 == `header_size + data_size` |
| 6 | 头部 CRC | 计算值 == 文件值 |
| 7 | 文件 CRC | 计算值 == 尾部值 |
| 8 | DEF 结构 | 含 reserved 字节；字段定义 3 字节/个 |
| 9 | local 分配 | 0-15，不回绕冲突 |
| 10 | SDK 解码 | `@garmin/fitsdk` **0 error** |

### 6.2 数值合理性校验

| # | 字段 | 合理范围 | 说明 |
|---|---|---|---|
| 1 | altitude | 依地理位置；平原个位数~几十米 | 福建平原 6~16 m |
| 2 | speed | 0 ~ 8 m/s（跑步）| **含 0**（暂停）|
| 3 | heartRate | 50 ~ 220 bpm | |
| 4 | cadence | ×2 后 140 ~ 220 spm | |
| 5 | temperature | -40 ~ 60 ℃；**不能是 127/255** | 127 = S8 无效 |
| 6 | power | 0 ~ 800 W | |
| 7 | stanceTime | 150 ~ 400 ms | |
| 8 | verticalOscillation | 40 ~ 150 mm | |
| 9 | verticalRatio | 3 ~ 15 % | |
| 10 | stepLength | 500 ~ 2000 mm | |
| 11 | positionLat/Long | 与运动地点一致 | |
| 12 | **speed==0 点数** | 与源文件相当 | **决定最快 1KM 能否算出** |

### 6.3 一致性校验（产物 vs 源）

| # | 检查项 | 通过标准 |
|---|---|---|
| 1 | record 条数 | 与源一致（不丢点）|
| 2 | 海拔逐点 | 最大差异 = 0 |
| 3 | lap 圈数 | 与源一致 |
| 4 | session 汇总 | 距离/时间/卡路里与源一致 |
| 5 | 派生量 | lap 均速 = 距离÷时间；最大速度 = 圈内 record 最大值 |
| 6 | 消息构成 | global 集合与目标平台真机同构 |

### 6.4 时间戳校验

| # | 检查项 |
|---|---|
| 1 | 所有 timestamp 为**自 1989-12-31 起的秒数**（uint32）|
| 2 | `session.startTime` ≤ 所有 record timestamp ≤ `session.timestamp` |
| 3 | `lap.startTime` 与圈内首条 record 对应 |
| 4 | 采样间隔与源一致（跑步通常 1s）|
| 5 | 暂停处允许时间跳变（对应 event 的 stop/start）|

---

## 七、开发者字段（206 / 207）机制

### 7.1 声明顺序（强制）

```
1. developerDataId(207)：声明一个"应用"
2. fieldDescription(206)：声明该应用下的一个字段
3. record/lap/session：用 local 定义中的 dev 字段引用它
```

### 7.2 developerDataId（207）字段

| 字段号 | 名称 | 类型 | 说明 |
|---|---|---|---|
| 0 | developerId | byte[16] | 开发者 ID（GUID）|
| 1 | applicationId | byte[16] | 应用 ID |
| 2 | manufacturerId | uint16 | 厂商号 |
| 3 | developerDataIndex | uint8 | **索引**（206 用它关联）|
| 4 | applicationVersion | uint32 | 版本 |

### 7.3 fieldDescription（206）字段

| 字段号 | 名称 | 类型 | 说明 |
|---|---|---|---|
| 0 | developerDataIndex | uint8 | 关联 207 的索引 |
| 1 | fieldDefinitionNumber | uint8 | **该开发字段的编号**（record 里 dev 字段名）|
| 2 | fitBaseTypeId | uint8 | **数据类型**（如 `0x88` = float32）|
| 3 | fieldName | string[12] | 名称（如 `"Effort Pace"`）|
| 8 | units | string[4] | 单位（如 `"m/s"`）|
| 13 | fitBaseUnitId | uint16 | 基础单位 |
| 14 | nativeMesgNum | uint16 | 原生消息号 |
| 15 | nativeFieldNum | uint8 | 原生字段号 |

### 7.4 开发字段在消息中的写法

DEF 里开发字段定义的第三字节**不是类型码**，而是**引用 206 声明的索引**：

```
字段定义 = [field_num, size, dev_data_index]
                                    ↑ 这里是 206 的索引，通常 0
```

> **实测事故**：写成 `136`(=0x88, float32) 会让解析器读成 4 元组。

---

## 八、时间基准

| 项 | 值 |
|---|---|
| Epoch | **1989-12-31 00:00:00 UTC** |
| 换算 | `Unix = FIT + 631065600` |
| 涉及字段 | `timestamp`、`startTime`、`timeCreated`、`localTimestamp` |
| `localTimestamp` | 本地时间语义，与 timestamp 存在时区偏移 |

---

## 九、快速自检脚本

```bash
# 完整校验（结构 + 数值 + 一致性）
python scripts/fit_verify_coros.py <产物.fit> <源.fit> [目标平台真机.fit]

# 与官方定义逐字段比对（找偏离）
python scripts/fit_vs_official.py <文件.fit>

# 官方 SDK 解码（0 error 才算过）
node -e "
import('file:///<skill>/node_modules/@garmin/fitsdk/src/index.js').then(async ({Decoder, Stream}) => {
  const fs = await import('fs');
  const r = new Decoder(Stream.fromBuffer(fs.readFileSync('<file>'))).read();
  console.log('errors:', r.errors.length);
});"
```
