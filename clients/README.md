# 知舟的客户端专用资料

这里保留具有客户端适用范围的规则、agent 定义及插件快照。它们不自动成为所有 AI 工具的全局规则，也不由通用安装入口自动部署。采集日期为 2026-11-16。

来源、适用范围及内容摘要见 [client-assets.json](../sources/client-assets.json)；Claude 插件的版本、来源与核验边界见 [client-plugins.json](../sources/client-plugins.json)。

## Gemini / Antigravity

| 快照 | 原位置与用途 |
| --- | --- |
| [subagent-default.md](gemini-antigravity/rules/subagent-default.md) | `~/.gemini/config/rules/subagent-default.md`；AGY 的默认委托路由、worker 复用与指定模型处理约定 |
| [hydrogen-default.md](gemini-antigravity/agents/hydrogen-default.md) | `~/.gemini/config/agents/hydrogen-default.md`；相应的 worker 定义 |

两份文件保留原文。它们来自 Antigravity 环境，不把这些路径解释为官方 Gemini CLI 的通用加载入口。

恢复前先检查新机器的对应客户端是否支持这些配置。原规则中的 `/home/lzh/.local/bin/codex`、provider `my_codex` 和模型路由属于源机器环境，需要按目标机器的可用命令、provider 与授权适配；不复制登录态或密钥。这里的默认模型偏好只用于相应客户端，不能推导为 Codex、Claude 或其他工具的全局默认。

## Claude Code 插件

`document-skills@anthropic-agent-skills` 来自 `anthropics/skills`。插件声明启用 `xlsx`、`docx`、`pptx`、`pdf` 四项；缓存中的其他 skill 目录不因此视为启用。419 个可匹配文件与安装记录的提交逐字节一致，未观察到本地修改，因此仅记录版本和来源，不收录整份插件缓存。

`cloudflare@claude-plugins-official` 记录的安装版本为 `1.0.0`，插件 manifest 指向 `cloudflare/skills`。本地缺少可用于核对安装版本的 Git 历史，**是否存在本地修改仍为 unknown**。为保留可能的修改，收录 [Cloudflare 快照](claude/plugins/cloudflare/) 中全部 14 个 skill payload 和不含凭据的 [plugin.json](claude/plugins/cloudflare/plugin.json)。这些目录不会自动加入通用 `skills/`。

恢复插件时使用 Claude Code 官方插件安装流程，并按来源记录选择所需版本。Cloudflare 安装后先比较本快照，再决定恢复哪些本地修改。插件服务的登录授权、MCP 配置和外部依赖需要在目标机器另行设置；本目录不包含这些内容。

这些记录只证明文件采集与已说明的内容比较，不能证明新机器上的客户端已经加载或服务已经可用。
