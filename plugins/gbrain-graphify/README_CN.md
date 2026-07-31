# GBrain + Graphify 插件

正式支持 Codex、Claude Code、Google Antigravity、WorkBuddy、Cursor 与 VS Code。插件安装固定版本的本地
GBrain 和 Graphify，并通过 stdio MCP 注册。GBrain 数据保存在用户目录中；
不会创建 HTTP 服务、OAuth 流程或令牌。

请从仓库根目录运行当前宿主对应的 bootstrap。setup 仅在用户发出安装请求后修改
用户级工具、插件和 MCP 状态；配置冲突与版本升级默认失败关闭，必须显式授权。

独立 `codebuddy.so` 不在支持范围内。上游版本与许可证见 `THIRD_PARTY_NOTICES.md`。
