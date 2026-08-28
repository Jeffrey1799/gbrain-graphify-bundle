# 安装 GBrain 与 Graphify

本仓库提供跟随官方最新版本、可验证的 GBrain 持久记忆与 Graphify 本地代码图谱安装流程。
两个 MCP 均使用本地 stdio，不开放端口、不配置 OAuth，也不创建常驻服务。

## One-shot 流程

向 Agent 发送：

> 我要安装 GBrain 和 Graphify。请读取仓库
> `https://github.com/Jeffrey1799/gbrain-graphify-bundle` 的 README，按指引操作。

Agent 必须克隆仓库、识别当前宿主、读取 setup skill，并且只执行当前宿主对应的
一个入口：

```powershell
# Windows Codex 示例
.\bootstrap.ps1 -Agent codex
```

```bash
# macOS/Linux Claude Code 示例
bash ./bootstrap.sh --agent claude
```

正式支持的宿主值为 `codex`、`claude`、`antigravity`、`workbuddy`、`cursor`、
`vscode`。bootstrap 会从当前
checkout 注册本地插件、安装官方最新版本工具、以无 embedding 模式初始化 GBrain、
配置宿主并运行严格诊断。

原始提示中的“按指引操作”授权干净环境的用户级安装。下列行为可能替换状态或改变
下载信任源，仍必须使用显式参数：

- `-Upgrade` / `--upgrade`
- `-ReplaceConflicts` / `--replace-conflicts`
- `-UseMirrorCN` / `--use-mirror-cn`

使用 `-DryRun` 或 `--dry-run` 执行零写入预检。已有冲突 MCP 配置默认失败关闭。
未指定镜像参数时只访问官方 GitHub 与 PyPI。

## 成功标准

只有以下检查全部通过，setup 才会报告成功：

- GBrain 与 Graphify 匹配官方最新发布版本（网络可用时校验）；
- 当前宿主中的 stdio 命令和参数完全正确；
- `gbrain doctor --json` 通过；
- `gbrain serve` 与 `graphify-mcp` 均完成 MCP `initialize` 和 `tools/list`。

成功后需要重启一次 Agent 会话以加载新 MCP。流程不会配置付费模型、API Key、
项目图谱或项目级规则文件。使用 `-Workspace <path>` / `--workspace <path>`
才会安装 Cursor 项目规则或 VS Code Copilot 项目指令；默认只写用户级 MCP 配置。

## 支持的文件型宿主

WorkBuddy 使用 `~/.workbuddy/mcp.json` 的 `mcpServers`，Cursor 使用
`~/.cursor/mcp.json` 的 `mcpServers`，VS Code 使用官方用户级 `mcp.json` 的
`servers` 根键。三个宿主均使用本地 stdio 和绝对可执行文件路径。独立
`codebuddy.so` 不在本轮支持范围内。

## 可选的项目初始化

重启后可在项目工作区运行 `project-knowledge-bootstrap`，构建 Graphify 图谱与
GBrain 项目记忆。该步骤会修改项目文件，因此不属于基础安装。

详细回退说明见 HTML 指南与
[TROUBLESHOOTING.md](./plugins/gbrain-graphify/TROUBLESHOOTING.md)。
