# 工具适配

四种工具共用本仓库中的记忆与 skills，安装器为它们生成各自支持的入口。以下记录文件安装契约；本项目没有据此宣称已在四种客户端中完成实际加载测试。客户端版本、设置和更高优先级指令仍会影响加载行为。

## 用户范围

| 工具 | 规则入口 | Skills 位置 |
| --- | --- | --- |
| Codex | `$CODEX_HOME/AGENTS.md`，默认 `~/.codex/AGENTS.md` | `~/.agents/skills/` |
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/` |
| Cursor | 导出到 `~/.zhizhou/cursor-user-rules.md`，然后粘贴到设置页 | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/GEMINI.md` | `~/.agents/skills/` |

```bash
./zhizhou install --tools codex claude cursor gemini
./zhizhou install --tools codex claude cursor gemini --apply
```

可用 `--home PATH` 指定目标 home；Codex 的独立配置目录可用 `--codex-home PATH` 指定。工具内置 skills 仍由对应工具维护，不作为个人 skill 复制。

Cursor 用户规则通过应用设置维护，官方没有这里可直接写入的用户规则文件入口。安装后打开 Cursor 的 **Settings → Rules**，把导出文件内容粘贴到 User Rules；具体设置栏目名称可能随版本变化。导出文件本身不会自动成为 Cursor 用户规则。

## 项目范围

```bash
./zhizhou install --project /path/to/project --tools all
./zhizhou install --project /path/to/project --tools all --apply
```

| 选择 | 项目中生成的入口与资源 |
| --- | --- |
| Codex | `AGENTS.md`、`.agents/skills/` |
| Claude Code | `CLAUDE.md`、`.claude/skills/` |
| Cursor | `.cursor/rules/zhizhou.mdc`、`.agents/skills/` |
| Gemini CLI | `GEMINI.md`、`.agents/skills/` |
| 通用 `agents` | `AGENTS.md`、`.agents/skills/` |

`all` 在用户范围选择四种工具，在项目范围选择全部五种适配；显式 `agents` 只用于项目入口。Cursor 项目规则采用 `.mdc` 格式，普通 Markdown 文件不会因放进 `.cursor/rules/` 就成为规则。通用 `AGENTS.md` 便于支持该约定的其他工具读取，不能保证所有 AI 工具都实现相同语义。

安装器生成的入口包含核心工作约定、本机路径和明确的项目边界，并指向本仓库的 `memory/INDEX.md`。后续任务按范围读取 `confirmed` notes，避免一次加载全部经验。

## 更新和冲突

安装默认复制内容，未使用指向旧服务器的绝对软链。修改仓库中的核心规则或 skill 后，重新执行安装预览及 `--apply` 更新副本；新增 note 由后续任务按入口指引读取。

已有规则正文会保留，安装器追加带标记的管理区块，后续更新保留区块外的文字。管理区块被本机改动、skill 存在不同内容，或已有 Cursor 文件不符合管理方式时，安装器报告冲突并保留原内容。需要合并时，先复核两份内容及各自来源，再更新目标文件。历史项目指南不会被自动部署到项目中。

## 官方说明

以下链接于 2026-11-16 核对，用于确定文件路径和加载方式：

| 工具 | 官方文档 |
| --- | --- |
| Codex | [AGENTS.md](https://developers.openai.com/codex/guides/agents-md)、[Skills](https://developers.openai.com/codex/skills) |
| Claude Code | [Memory](https://code.claude.com/docs/en/memory)、[Skills](https://code.claude.com/docs/en/skills) |
| Cursor | [Rules](https://cursor.com/docs/context/rules)、[Skills](https://cursor.com/docs/context/skills) |
| Gemini CLI | [GEMINI.md](https://geminicli.com/docs/cli/gemini-md/)、[Skills](https://geminicli.com/docs/cli/skills/) |

安装后应在各客户端的新会话中核对已加载的规则或 skills。文件检查通过、客户端成功读取、后续任务遵守约束是不同层面的结果，报告时分别说明。
