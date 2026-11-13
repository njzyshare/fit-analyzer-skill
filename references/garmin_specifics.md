# 佳明（Garmin）特有规范

> **性质**：佳明在 FIT 标准之外的私有约定清单。互转 / 注入 / 换皮时必须逐条处理。
> **来源**：逐字节实测佳明真机 `640810408_ACTIVITY.fit` / `623001702_ACTIVITY.fit`（fenix 8）、合并产物 `merged_fenix8.fit`。
> **配套**：通用规范见 `fit_format_spec.md`；高驰侧见 `coros_specifics.md`；互转对照见 `cross_conversion.md`。

---

## 一、文件级参数

| 项 | 佳明 |
|---|---|
| `header_size` | 14 |
| `protocol_version` | **16** |
| `profile_version` | **21213** |
| `".FIT"` magic | ✅ |
| 尾部 CRC | 同通用 |

🔴 转高驰必须改 `protocol_version` 16→32、`profile_version` 21213→21158，并重算 CRC。

## 二、消息集合（36 种，其中 27 种私有）

佳明除标准消息（fileId/session/lap/record/event/activity/fieldDescription/developerDataId/sport/fileCreator…）外，大量**官方 profile 中不存在的私有消息**，核心是「宽表拆分」——把 record 的附加数据拆到独立消息（每点一条）：

| global | 用途（实测推断）| 条数示例 |
|---|---|---|
| 2 | deviceSettings | 1 |
| 3 | userProfile | 1 |
| 7 | zonesTarget | 1 |
| 13 | trainingSettings | 1 |
| 147 | **配对传感器**（耳机/心率带，见第五节）| 2 |
| 160 / 233 / 534 / 325 / 326 / 327 | 逐点扩展（与 record 一一对应）| 数千条 |
| 162 | gpsMetadata | 6 |
| 216 | 逐圈扩展（与 lap 配对）| 21 |
| 312 | split（分段）| 6 |
| 313 | splitSummary | 4 |
| 其余 | 扩展 | 不等 |

> 💡 转高驰时整类丢弃（高驰只认白名单 9 种）。这些私有消息对高驰无害但会增肥，且高驰不解析。

## 三、device_info（21 条，含内置传感器）

| 项 | 佳明 |
|---|---|
| 条数 | **21**（手表 + 气压计 + GPS + 心率带等传感器各重复）|
| 是否含内置传感器 | ✅ |
| 主设备字段 | product(4)=**4536**(fenix 8)、serial(3)=**真实序列号（存私有区，不进公开文件）**、softwareVersion、hardwareVersion 等 |

🔴 **Connect 校验核心**：服务端校验 `(product, UnitID)` 是否匹配真实佳明设备；不匹配→显示「未知设备」且可能重算海拔。
**设备是否带气压高度计决定高程校正开关**：带气压计→校正默认关、用设备记录海拔；不带→用 DEM 地形数据替换每个轨迹点（二次加工爬升）。故注入「真实佳明带气压计设备」即可彻底解决。
🔴 **序列号 / 私人设备数据一律存 `~/.workbuddy/private/garmin_devices.json`，绝不写死进 skill / 脚本 / 共享文件**（见 `coros_specifics.md` 五，高驰同样无 serial）。

## 四、file_id

| 字段 | 值 |
|---|---|
| 0 type | 4（activity）|
| 1 manufacturer | **1**（garmin）|
| 2 product | **4536**（fenix 8）|
| 4 timeCreated | 导出时间 |
| 8 productName | 通常无（佳明不写 productName）|

## 五、配对传感器（私有 `global 147`）

佳明把配对外设放在**非标准消息 `global 147`**（不是 deviceInfo）：

| 字段 | 含义 | 示例 |
|---|---|---|
| f2 string[24] | 显示名 | `"OpenDots ONE by Shokz"` |
| f73 sint16 | 类型码 | 4（耳机）/ 2（心率带）|
| f50 byte[6] | **蓝牙 MAC** | `d4:44:3f:e2:0c:a0` |

> 转高驰时整条丢弃（高驰配件由 App 管理，不写进活动文件）。

## 六、速度 / 海拔 / 温度 / 步频

| 项 | 佳明 | 备注 |
|---|---|---|
| record 速度 | **`f73`** enhancedSpeed（uint32, `raw/1000`）| 🔴 f73=速度、f78=海拔，极易搞反 |
| record 海拔 | **`f78`** enhancedAltitude（uint32, `raw/5-500`）| |
| lap 平均/最大速度 | `f110`/`f111` enhanced（f13/f14 常无效）| |
| session 平均/最大速度 | `f124`/`f125`（f14/f15 常无效）| |
| lap/session 温度 | `f50`/`f57`（**S8**）| |
| record 温度 | **无温度通道**（fenix 8 需外接温度计）| 真机值常 `127`（无效）|
| 步频 | 同高驰（rpm，×2=spm）| |

## 七、activity(34) 私有字段

| 字段 | 佳明 |
|---|---|
| f8（byte[64]）| ✅ 全 0 |
| f6/f7/f9/f10/f12 | 佳明私有（常 `255` 无效）|

转高驰时省略（高驰 activity 不含这些）。

## 八、转高驰注意（详见 `cross_conversion.md`）

- 消息白名单：只留高驰 9 种，其余私有消息省略。
- 速度 `f73`→`f6`；海拔 `f78`→`f2`；lap/session 速度取 enhanced 字段。
- device_info 21 条→1 条（manufacturer=294, product=814）。
- 新增 207 + 206×2 声明 Effort Pace（field_def_num=16, float32）。
- 温度源无→留哨兵。
- 重算 CRC。
