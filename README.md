# 运动记录 FIT 分析器

通用运动 FIT 记录分析/修改工具集，覆盖佳明、高驰、颂拓、Polar、华为等品牌 .fit 文件。

## 作用
- 合并分段活动（高驰保真 / 佳明 Connect 兼容）
- 注入真实设备信息（佳明防重算爬升 / 高驰防未知设备），运动数据 100% 保留
- 设备身份互逆替换（Fenix8↔COROS 字节级）
- 华为 JSON → FIT/GPX/TCX
- FIT 预览、时间戳平移、协议字节修复、官方 SDK 重建、TCX 兜底
- 跨品牌互转（佳明↔高驰，规范驱动 + 双关卡门禁）

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

## 跨品牌互转
```bash
python scripts/fit_convert_by_template.py 输入.fit 输出.fit --to coros_apex4
python scripts/fit_conformance_check.py 输出.fit --temp coros_apex4 --src 输入.fit
python scripts/fit_diff_vs_template.py 输出.fit --temp coros_apex4 --src 输入.fit
```

字段含义一律以 `references/fit_profile_official.json` 为准，完整规则见 `SKILL.md`。
