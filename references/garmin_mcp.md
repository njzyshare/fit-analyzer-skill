# 佳明（Garmin Connect）MCP 数据采集——中国区可迁移部署

官方连接器市场**没有** Garmin connector。用社区开源 MCP：`Taxuspt/garmin_mcp`（PyPI 包 `garmin_mcp`）。
选它的唯一理由：带 `download_activity_file`，能把活动导成 **FIT / GPX / TCX / CSV** —— 这是「像高驰那样直接读 FIT」的关键工具。

> 中国区账号必须走 `GARMIN_IS_CN=true` / `--is-cn`（连 `garmin.cn`），否则连国际版接口，认证和数据全失败。

## 一、候选项目对比（为什么选这个）

| 项目 | 认证库 | FIT 下载 | 结论 |
|---|---|---|---|
| **`Taxuspt/garmin_mcp`** | garminconnect | ✅ `download_activity_file` | **采用** |
| `babeejin/garmin-cn-mcp` | garminconnect `is_cn=True` | ❌ 只有活动 JSON/splits，无 FIT 导出 | 不采用 |
| `anthony11122/garmin-cn-mcp` | garth (domain=garmin.cn) | 中转推 Intervals.icu，非通用 FIT 工具 | 不采用 |

## 二、🔴 头号坑：garminconnect 版本必须 ≥ 0.3.20

`garmin_mcp` 的 `pyproject` 把 `garminconnect` **钉死在 0.3.2**（其依赖声明 `garminconnect==0.3.2`）。
0.3.2 的致命缺陷：`--is-cn` **只切换 API 域名到 `garmin.cn`，但 SSO / DI 登录仍写死国际域名**：

| 域名 | 0.3.2 用的 | 国内可达性 |
|---|---|---|
| 登录 service | `mobile.integration.garmin.com` | ❌ **NXDOMAIN**（8.8.8.8 / 223.5.5.5 均查不到）|
| DI token 交换 | `diauth.garmin.com` | ❌ 仅 IPv6、国内不通 |

症状：`DI token exchange failed for all client IDs, falling back to JWT_WEB` → `Failed to perform, curl`。
**密码怎么输都过不去，不是操作问题。**

**解药：装完后强制升级 `garminconnect` 到 ≥ 0.3.20**（PyPI 最新，本文验证版本 0.3.20）。
新版重构出 `client/` 子模块，DI 主机改为 **domain-aware**：`client/__init__.py` 里
`self._di_token_url = f"https://diauth.{domain}/..."`，注释明确「CN users live on diauth.garmin.cn」。
升级后 `--is-cn` 下所有关键域名全是 `.cn`：

```text
_sso            = https://sso.garmin.cn
_connect        = https://connect.garmin.cn
_connectapi     = https://connectapi.garmin.cn
_portal_service = https://connect.garmin.cn/app
_di_token_url   = https://diauth.garmin.cn/di-oauth2-service/oauth/token
```

实测 `diauth.garmin.cn` 国内直连 TLS 通（空路径返 404 属正常）。
**换电脑务必先升级再登录**，否则一定卡在 curl。

## 三、环境搭建（换电脑完整步骤）

本机原先可能没有 uv / uvx / 独立 Git，下面是已验证可复现的顺序。所有路径用 `~`（Windows 即 `%USERPROFILE%`）。

### 1. 装 uv（提供 uvx）

```bash
pip install --user uv --no-cache-dir
```

- winget 安装 `Astral.uv` 在部分旧版 winget 会「找不到包」，**直接用 pip 最稳**。
- 装完 `uv.exe`/`uvx.exe` 落在 `~/AppData/Roaming/Python/Python3xx/Scripts/`（Windows），
  **需把该目录加入用户 PATH**，且**新开终端才生效**。

### 2. 确保 Git 可用

uv 从 `git+https://github.com/...` 拉包时调用系统 git。若机器只有某 IDE 内置的便携 Git，
把它的 `mingw64/bin` 与 `cmd` 目录也加入用户 PATH；否则报 `Git executable not found`。
（有标准 Git 安装则跳过。）

### 3. 建独立 venv 并装包

不用 `uvx` 直跑——它会套多层子进程，交互式密码/MFA 输入不稳。用固定 venv：

```bash
uv venv ~/.garmin-mcp-venv --python 3.12
uv pip install --python <venv>/Scripts/python.exe \
  "git+https://github.com/Taxuspt/garmin_mcp" \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
# 🔴 关键：升级到修复 CN 登录的版本
uv pip install --python <venv>/Scripts/python.exe \
  "garminconnect==0.3.20" \
  --index-url https://pypi.tuna.tsinghua.edu.cn/simple
```

- 入口脚本落在 `<venv>/Scripts/`：`garmin-mcp-auth.exe`（登录）、`garmin-mcp.exe`（server）。
- 网络：拉 GitHub 仓库需能访问 github.com；PyPI 走清华镜像即可。
- `<venv>` 是占位符，Windows 实际如 `C:/Users/<用户名>/.garmin-mcp-venv`。

## 四、登录（一次性，约 6 个月有效）

新开终端（PATH 已生效），跑：

```bash
<venv>/Scripts/garmin-mcp-auth.exe --is-cn
```

交互式提示：

| 提示 | 输入 | 是否回显 |
|---|---|---|
| `Email:` | 佳明中国区邮箱 | 回显 |
| `Password:` | 密码 | 🔴 **完全不回显**（Windows getpass，屏幕不动是正常的），盲输完回车 |
| `Enter MFA code:`（若开启）| 邮箱/手机验证码 | 回显 |

- 登录走 Garmin 官方 native mobile SSO，MFA 是两步握手，不是爬网页。
- token 存 `~/.garminconnect/garmin_tokens.json`（目录仅属主可读）；另有 base64 副本 `~/.garminconnect_base64`（server 不读）。
- 成功标志：`✓ Authentication successful!` + `SUCCESS: You can now use the Garmin MCP server!`
- 过期重登：加 `--force-reauth`；验 token：`--verify`；排查路径：`--diagnose`。
- **凭据不经 AI**：登录由用户在自己终端完成，账号密码/验证码不进对话、不写文档。

## 五、接入 WorkBuddy

配置文件 `~/.workbuddy/mcp.json`（与高驰 MCP 共用、并列在 `mcpServers` 下）。
若文件已存在，**追加** `garmin-cn` 条目，不要覆盖其他 server：

```json
{
  "mcpServers": {
    "garmin-cn": {
      "command": "<venv>/Scripts/garmin-mcp.exe",
      "env": { "GARMIN_IS_CN": "true" }
    }
  }
}
```

- 默认 stdio 传输，无需额外参数；server 启动后读 `~/.garminconnect` 的 token，**配置里不放账号密码**。
- 写入后需**重启 WorkBuddy** 才生效（新 server 不热加载）。
- 多账号：每个实例用独立 `GARMINTOKENS` 目录 + `--token-path` 登录，一个 server 绑一个账号。

## 六、能力（157 个工具，节选）

serverInfo 报 `Garmin Connect v1.0`（库版本字符串 1.30.0）。与 FIT 分析相关：

| 工具 | 用途 |
|---|---|
| `download_activity_file` | 🔴 **导出活动 FIT/GPX/TCX/CSV**（本 MCP 的核心价值）|
| `get_activity_fit_data` / `get_activity_fit_messages` | 直接读 FIT 字段/消息 |
| `get_activities` / `get_activities_by_date` / `get_activity` | 活动列表与详情 |
| `get_activity_splits` / `get_activity_split_summaries` | 每公里/分段配速 |
| `get_activity_weather` / `get_activity_gear` | 天气、装备关联 |
| `get_devices` / `get_primary_training_device` | 设备列表 |
| `get_hrv_data` / `get_training_status` / `get_training_load_trend` / `get_vo2max_trend` | 训练与健康 |
| 写类 | 排程/推送训练、改活动名、加水/体重等（本 skill 场景一般不用）|

完整列表用 MCP `tools/list` 取（实测 157 个）。

## 七、端到端验证（换电脑后必跑）

1. `--diagnose`：确认 token 目录解析正确、`garmin_tokens.json` 存在。
2. MCP 握手：发 `initialize`，应返回 `serverInfo.name = Garmin Connect v1.0`。
3. `tools/list`：应含 `download_activity_file`。
4. 实调 `get_activities({"limit":2})`：返回真实活动（有距离/时长/心率）即通。

⚠️ **stdio 调试坑**：用 `timeout N` 直接跑 server 调工具，进程被杀时响应来不及 flush，会拿到空 stdout。
改用「stdin 保持打开 + 轮询输出文件出现 `"id":N`」的方式取响应。真正接入后由 WorkBuddy 管理进程，无此问题。

## 八、与互转任务的关系

- **佳明 → 高驰**：用本 MCP `download_activity_file` 取佳明原始 FIT（替代手工从 Connect 导 zip），
  再走 `fit_convert_by_template.py --to coros_apex4`（规范重建），见 `SKILL.md` 路线 E。
- **高驰 → 佳明**：本 MCP 不参与；上传 Connect 仍走 `inject_garmin_device.mjs apply`（铁律 13）。
- 上传 Connect 后可用本 MCP `get_activities` 核对设备显示与爬升值（应无 287m 那种 DEM 重算）。

## 九、脱敏与可迁移清单

- ✅ 本文不含任何真实账号名、Unit ID、token、`labelId`、设备序列号；路径全用 `~` / `<venv>` 占位。
- ✅ 依赖版本、命令、域名、坑的原理都写明 → 换电脑按 §三~§五 顺序可完整复现。
- ⚠️ **token 文件（`~/.garminconnect*`）绝不入库、绝不进版本控制**，换电脑必须重新登录。
- ⚠️ 真实设备身份永远存私有区 `~/.workbuddy/private/garmin_devices.json`（SKILL 铁律 3），与本 MCP 的 OAuth token 是两回事，别混。
- ⚠️ 运行环境差异：Windows 用 `Scripts/`，macOS/Linux 用 `bin/`；venv 路径按实际系统替换。
