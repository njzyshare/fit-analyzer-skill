# 运动记录 FIT 分析器

处理 `.fit` 运动记录的工具集，覆盖佳明、高驰、颂拓、华为。核心是规范驱动——读规范文件，不靠样本黑盒；换机型只改规范名，不改代码。

## 两个转换方向

| 需求 | 命令 |
|---|---|
| 佳明 → 高驰，上传高驰 | `fit_convert_by_template.py in.fit out.fit --to coros_apex4` |
| 高驰 → 佳明，上传 Garmin Connect | `inject_garmin_device.mjs apply in.fit --device fenix8 --out out.fit` |

设备身份取自你自己的真实佳明文件，不是编造的。首次或换表时先读一次：

```bash
inject_garmin_device.mjs extract 真实佳明.fit --name fenix8   # 从真机读设备信息，存私有区
inject_garmin_device.mjs apply 高驰.fit --device fenix8 --out 佳明.fit
```

## 还能做什么

合并被误存成多段的同一次运动、平移开始时间、换设备身份、FIT 体检与 HTML 预览、华为 JSON 转 FIT/GPX/TCX、从高驰或佳明 MCP 直接取数导 FIT。命令与参数见 `SKILL.md`。

## 详细文档

`SKILL.md` 是规则与铁律总入口；`references/` 按主题拆了 FIT 格式、佳明/高驰分支、双向互转、两个 MCP、华为转换等细节。

字段定义以 `references/fit_profile_official.json` 为准。
