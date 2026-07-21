# 华为 → 高驰/佳明 转换脚本分析报告

## 来源

原 GitHub 仓库 `njzyshare/huawei-to-coros-garmin`（已删除），副本保存在本目录。

## 脚本概览

- 语言：Python 3（纯标准库，无第三方依赖）
- 输入：华为手表导出的 JSON 数据文件（通常 100MB+）
- 输出：GPX（高驰推荐）+ TCX（佳明推荐）
- 行数：701 行

## 异常清单（2025-12-21 厦门环东半马 TCX 实测）

测试文件：`20251221户外跑步.tcx` — 21.36km / 103.3min / 4:48配速

### 已确认的 Bug

| # | 问题 | 涉及行 | 严重程度 | 说明 |
|---|------|:------:|:-------:|------|
| 1 | **海拔全负值** | 332 | 🔴 高 | `if gp['alt'] > 0` 只过滤了海平面以下数据，但华为原始 GPS 海拔整体偏移了约 -30m（气压计未校准）。厦门沿海实际海拔约 0-30m 的数据显示为 -27~-42m |
| 2 | **海拔偏移无修正** | 332 | 🔴 高 | 没有对 GPS 海拔数据做整体偏移修正（加上海拔中位数差值） |
| 3 | **缺失卡路里** | 300-313 | 🟡 中 | `build_tcx` 的 Lap 元素中没有写入 `Calories` |
| 4 | **缺步频/步态数据** | 300-313 | 🟡 中 | TCX 格式支持 `Cadence` 和 `Extensions` 扩展字段，脚本未写入。如果华为原始数据有步频，转换后丢失 |
| 5 | **Sport 类型 fallback 不够安全** | 291 | 🟡 中 | `SPORT_TYPE_NAMES.get(sportType, 'Other')` 当华为 `sportType` 不在映射表中时写 "Other" |
| 6 | **心率时间窗口 5 秒** | 272, 336 | 🟢 低 | 心率匹配 GPS 点的时间窗口 5 秒，可能导致部分心率数据未匹配上 |
| 7 | **单圈（1 Lap）** | 300 | 🟢 低 | 整个活动只有 1 个 Lap，无分段信息。TCX 规范允许单圈，不影响导入 |
| 8 | **距离单位不一致** | 301-302 | 🟢 低 | `TotalTimeSeconds` 用标签 `text` 写入，`DistanceMeters` 用标签 `text` 写入，格式不一致但不影响解析 |

## 2026-07-21 实战纠错记录

本次用实际的厦门环东半马数据（2025-12-21）测试，暴露了更多旧脚本的问题：

### 🔴 新增 Bug 1：`parse_attribute` 只解析了 GPS 和 HR，漏掉了华为的其他独立数据流

华为手表的 attribute 字段包含**多种独立数据流**，旧脚本只解析了 `tp=lbs`（GPS）和 `tp=h-r`（心率），完全漏掉了：

| 数据类型 | 标签 | 数量 | 作用 | 旧脚本处理 |
|---------|:----:|:---:|------|:---------:|
| **气压计海拔** | `tp=alti` | 1239 | 独立的气压计海拔数据（GPS alt 字段恒为 0） | ❌ 未解析，写到 GPS 的 alt 里（永远 0） |
| **步频/节奏** | `tp=s-r` | 1239 | 跑步步频值（旧脚本搜的是 `rt-cadence`，华为不用这名字） | ❌ 未解析 |
| 心率变异性 | `tp=r-r-h` | 25 | RR 间隔 | ❌ 未解析 |
| 恢复状态 | `tp=rs` / `tp=sec` | 1239+22 | 恢复数据 | ❌ 未解析 |

**修复**：`parse_attribute` 新增 `alti_points` 和 `cadence_points`（从 `s-r` 提取）两个返回值。海拔从独立 `tp=alti` 读取而非 GPS 的 `alt` 字段。

### 🔴 新增 Bug 2：GPS 的 alt 字段恒为 0，旧脚本 `if gp['alt'] > 0` 条件导致永远不写海拔

华为的 GPS 点（`tp=lbs`）中的 `alt=0.000000` 始终为 0，海拔数据在同一条记录的 **`tp=alti`** 中。旧脚本 `if gp['alt'] > 0` 检查 GPS 海拔，永远不满足条件——这就是旧版 TCX 没有海拔数据的真正原因。

而旧版 TCX 中出现的 -27~-42m 海拔，来自另一个版本的脚本或者其他来源。

**修复**：改为从 `alti_sorted` 按 3 秒时间窗口匹配 GPS 点，然后在 Trackpoint 中写入 `AltitudeMeters`。

### 🟡 新增 Bug 3：`parse_attribute` 步频搜错字段名

旧脚本 `elif 'tp' in pt and pt['tp'] == 'rt-cadence'` 搜索的 `rt-cadence` 不是华为使用的字段名。华为步频数据的 `tp=s-r`（可能代表 "step rate"）。

**修复**：改为 `tp == 's-r'`。

### 🟡 新增 Bug 4：大 JSON 文件解析需要 fallback 链

华为导出的 JSON 文件包含 `partTimeMap:{1.0:335.0}` 这种非标准 JSON 格式。旧脚本只使用了 `extract_all_objects` 字符串提取模式。对于单条记录或小文件，可以先用 `json.loads` 尝试，失败后用 `fix_parttime_map` 修补再试，最后才用字符串模式。

**修复**：`process_file` 新增三阶段解析链：
1. `json.loads(content)` → 成功直接解析
2. `json.loads(fix_parttime_map(content))` → 修补后解析
3. `extract_all_objects(content)` → 字符串逐对象提取

### 🟢 补充改进

| # | 改进 | 说明 |
|---|------|------|
| 1 | **海拔校准** | `calibrate_altitude()` 从 alti_points 读取海拔，取中位数判断偏移，自动修正。本次半马偏移 -34.4m，修正 +44m 后得到正常海拔范围 2.5~17.8m |
| 2 | **卡路里优先华为原始值** | 检测华为 JSON 中的 `totalCalories`，直接除以 1000 使用（本次 1588000 cal → 1588 kcal），免去估算误差 |
| 3 | **Sport 类型安全 fallback** | 未识别的 sportType 默认 "Running" 而非 "Other" |
| 4 | **TCX 扩展字段** | Trackpoint 的 `Extensions/TPX` 中写入 `RunCadence`（步频），`ns3` 命名空间已声明 |
| 5 | **输出文件名** | 修正为 `20251221_075145_Running_21360m.tcx`，Sport 使用标准名称 |

## 数据流（v2.1 修复版）

```
华为 JSON (attribute 字段)
  ├─> parse_attribute()
  │   ├─> HW_EXT_TRACK_DETAIL@ 前缀去除
  │   ├─> GPS点: lat;lon;alt(0);t  → gps_points[]
  │   ├─> HR点: tp=h-r; k=ts; v=HR  → hr_points[]
  │   ├─> 步频: tp=s-r; k=ts; v=SPM  → cadence_points[]
  │   └─> 海拔: tp=alti; k=ts; v=meters  → alti_points[]
  │
  ├─> calibrate_altitude(alti_points)
  │   └─> 中位数检测偏移 → 自动修正
  │
  ├─> build_gpx(gps, hr, cadence, alti)     → .gpx
  └─> build_tcx(hr, gps, cadence, alti, cal) → .tcx

## 2026-07-21 全量数据扫描（969条）排查

从原始 100MB JSON 中提取全部 969 条运动记录，统计 sportType 分布：

### sportType 频率表

| sportType | 映射名称 | 数量 | 距离合计 | 特征 |
|:---------:|---------|:---:|:-------:|------|
| 5 | Walking | 417 | 715.9km | 户外步行 |
| **117** | **⚠️ HR only** | **275** | **0km** | **纯心率记录，无GPS——旧脚本输出为"Other"导入后可能被归类为"有氧运动"** |
| 4 | Running | 157 | 1451.4km | 户外跑步（含本次半马21.36km） |
| 3 | Cycling | 110 | 209.0km | 户外骑行 |
| **106** | **⚠️ HR only** | **5** | **0km** | **纯心率/室内跑步，无GPS** |
| **281** | **⚠️ Other** | **3** | **2.0km** | **室内跑步/力量训练，部分有GPS** |
| **101** | **⚠️ Other** | **2** | **15.3km** | **计划跑步/室内跑步，有GPS——会被漏掉！** |

### 隐患排查结果

#### 🔴 隐患 1：sportType=101 有实际距离但旧脚本认不出 → 被归类为"Other"

sportType=101 的 2 条记录合计 15.3km，且有 GPS 数据。旧脚本 `SPORT_TYPE_NAMES.get(101, 'Other')` 输出 `"Other"`，导入佳明/高驰后可能被识别为"有氧运动"而非"跑步"。

**修复**：sportType=101 在映射表中加入 `'IndoorRunning'` 或 fallback 为 `'Running'`。

#### 🔴 隐患 2：sportType=117/106 纯心率记录 → 数量巨大（280条），也被归类为"Other"

这 280 条记录没有 GPS，只有心率数据。旧脚本输出 `"Other"`，导入后显示为"有氧运动"。这些实际上是**静息心率、心率变异性等健康监测数据**，不应作为运动活动导入。

**修复建议**：对于 dist=0 且无 GPS 的记录，考虑跳过输出或在文件名中标注 `HRonly`（已实现）。

#### 🟡 隐患 3：sportType=281 有距离但旧脚本不识别

3 条记录合计 2km，可能是室内跑步或力量训练。同样被归类为 `"Other"`。

#### 🟡 隐患 4：旧脚本 `detect_actual_sport` 只修正 sportType=5（走路），不修正其他

如果华为把跑步标记为其他编号（如 0、8、9），旧脚本的 `if original_st != 5` 条件直接跳过，不做配速检测修正。

**修复**：新脚本虽然已加 `get_sport_name()` 的 Running fallback，但没有对所有类型做配速检测。

### 建议的映射表扩展

```python
SPORT_TYPE_NAMES = {
    1: 'Walking',          # 走路（慢走）
    2: 'Running',          # 跑步（可能室内）
    3: 'Cycling',          # 骑行
    4: 'Running',          # 户外跑步 ✅ 已验证
    5: 'Walking',          # 户外步行
    6: 'IndoorCycling',    # 室内骑行
    7: 'Swimming',         # 游泳
    101: 'Running',        # ⚠️ 计划跑步/室内跑步（有GPS）
    106: 'Running',        # ⚠️ 室内跑步/虚拟运动（无GPS）
    117: 'Other',          # ⚠️ 纯心率记录（无GPS，dist=0）
    281: 'Running',        # ⚠️ 室内跑步/力量
}
```
```

### 设计需改进处

| # | 改进点 | 说明 |
|---|--------|------|
| 1 | **TCX 增强字段** | 在 Trackpoint 扩展中写入 `Speed`（可帮助平台算配速） |
| 2 | **海拔零点校准** | 统计所有海拔数据的中位数，如果偏离正常范围（如厦门沿海应 >0），整体修正 |
| 3 | **配速/距离合理性检查** | 与正式比赛距离对比（半马 21.0975km），检查 GPS 漂移量 |
| 4 | **多圈支持** | 如果华为数据中有分段/计圈信息，在 TCX 中生成多个 Lap |

## 数据流

```
华为 JSON (attribute 字段)
  ├─> parse_attribute()
  │   ├─> HW_EXT_TRACK_DETAIL@ 前缀去除
  │   ├─> GPS点: lat;lon;alt;t  → gps_points[]
  │   └─> HR点: k(timestamp);v(HR) → hr_points[]
  │
  ├─> build_gpx()     → .gpx 文件（高驰推荐）
  └─> build_tcx()     → .tcx 文件（佳明推荐）
```

## 修复计划

1. **海拔校准**：统计 GPS 海拔中位数，加上偏移修正，使大部分数据在正常范围内
2. **校准验证**：对厦门/沿海地区自动检测海拔异常（全负值）
3. **补充字段**：写入 Calories、Cadence（如果华为数据有）、Speed
4. **Sport fallback**：未识别类型默认 "Running" 而非 "Other"
5. **文件体积**：TCX 单行输出（目前用 minidom 美化导致文件膨胀）
