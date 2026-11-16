# 知舟 · Zhizhou

把与 AI 协作时积累的工作习惯、科研约定和 skills，带到下一台服务器。

知舟由 lzh 维护，用来保存与 AI 协作时积累的工作经验。工具目录里的 skills、项目中的 `AGENTS.md`、科研协议和已确认的偏好，在这里保留完整内容、来源与适用范围。换服务器或换工具时，可以取回同一份积累，继续更新。

Portable working memory for AI coding and research. Keep working agreements, scoped notes, and complete skills in Git, then restore them into Codex, Claude Code, Cursor, and Gemini CLI.

可以参考这套组织方式，或 Fork 后维护自己的知识库。首次安装前先阅读 `memory/`，按自己的工作方式调整偏好与项目约束，再用 `machines/` 配置目标机器的目录。

[快速开始](#快速开始) · [记录经验](#记录经验) · [维护与同步](#维护与同步) · [目录导航](#目录导航) · [版权与引用](#版权与引用)

## 保存了什么

当前收录情况截至 2026-11-16：

| 内容 | 收录情况 |
| --- | --- |
| 个人工作约定 | 任务完成标准、沟通偏好、授权边界与记忆维护方式 |
| 科研协作方法 | 方案讨论、术语定义、评测边界和研究决定的记录约定 |
| 通用 skills | 59 项，保留完整脚本、references 和资源 |
| 项目资料 | 11 个项目／独立 checkout，16 份指南、24 份专用 skill 快照、8 份科研协议与决定记录 |
| 客户端资料 | Gemini／Antigravity 的个人规则和 agent 定义，2 个 Claude 插件的恢复信息及必要快照 |
| 来源与机器配置 | 原始位置、采集日期、提交与修改状态、内容摘要和各机器的存储路径 |

Skills 覆盖资料检索、科研方案讨论、AutoResearch、竞赛优化、代码与前端工作、飞书操作等流程，包含第三方内容和本地维护版本。来源与收录范围见 [收录说明](docs/coverage.md)。

## 快速开始

需要 Git 和 Python 3。仓库已公开，可直接克隆；安装器只使用 Python 标准库。

```bash
git clone https://github.com/LikC1606/zhizhou.git
cd zhizhou

./zhizhou check
./zhizhou install
./zhizhou install --apply
```

`check` 检查记忆、skill 入口和已登记快照。`install` 预览将写入的位置，添加 `--apply` 后才执行安装。默认安装到当前用户，为 Codex、Claude Code、Cursor 和 Gemini CLI 生成入口。

安装后，工具入口会引用本仓库的记忆索引。请保留仓库在本机的路径；移动后重新安装即可更新引用。

### 工具入口

| 工具 | 用户级规则 | Skills 位置 |
| --- | --- | --- |
| Codex | `$CODEX_HOME/AGENTS.md`，默认 `~/.codex/AGENTS.md` | `~/.agents/skills/` |
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/` |
| Cursor | 导出到 `~/.zhizhou/cursor-user-rules.md`，粘贴至 Settings → Rules → User Rules | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/GEMINI.md` | `~/.agents/skills/` |

Cursor 的用户规则需要手动粘贴；其项目规则可以直接生成。安装后在客户端的新会话中核对加载结果，工具本身及 Lark CLI 等外部依赖、服务登录在新机器另行配置。

### 选择工具或项目

```bash
# 只安装 Codex 和 Claude Code
./zhizhou install --tools codex claude
./zhizhou install --tools codex claude --apply

# 为指定项目生成全部适用入口
./zhizhou install --project /path/to/project --tools all
./zhizhou install --project /path/to/project --tools all --apply

# 预览安装到另一个用户目录
./zhizhou install --home /path/to/user-home
```

项目入口包括 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 和 Cursor 的 `.mdc` 规则。项目指南、研究协议、客户端专用规则及项目 skill 变体保存在对应目录，按来源范围使用，不会被通用安装器自动部署。

新机器的默认项目与输出目录位于 `~/workspace/`。需要指定磁盘布局时，用 `--machine` 提供路径 JSON；现有 `machines/node01.json` 记录 node01 的数据盘配置。详细选项见 [工具适配](docs/adapters.md) 和 [迁移说明](docs/migration.md)。

## 记录经验

记录会影响以后工作的明确偏好、用户纠正、已确认结论，以及可以复用的经验。每条记录保留来源、日期、状态和适用范围，说明后续任务应在什么条件下采用它。

| 范围 | 用途 |
| --- | --- |
| `global` | 跨项目的工作方式与沟通偏好 |
| `research` | 科研方法与研究协作约定 |
| `project:<id>` | 指定项目的局部约束与经验 |

用户明确表达的要求可以直接记录为 `confirmed`；AI 提出的建议默认记为 `pending`，等用户接受后再确认。被后续记录替代的内容标为 `superseded`，保留修订来由。

```bash
# 记录已经确认的要求；source 填写可定位的对话或文档来源
./zhizhou note '实验报告格式' \
  --scope research \
  --source '用户明确确认该要求的对话或文档位置' \
  --body '已确认的具体要求，以及适用条件。' \
  --status confirmed

# 未指定 status，默认作为待讨论建议保存
./zhizhou note '待讨论的评测改进' \
  --scope project:example \
  --source '本次讨论中的 AI 建议，尚未确认' \
  --body '建议内容、依据与尚待确认的问题。'
```

写入前先检索已有记录，避免重复或留下相反约束：

```bash
rg -n '关键词' memory skills projects clients
```

工具入口会引导 AI 按范围读取已确认记录。新增 note 保存后即可供后续任务读取；核心规则和 skills 采用安装副本，修改后需要重新安装。重要科研定义与决定继续以所属项目的 Protocol、`research/decisions/` 为依据。完整流程见 [记忆维护约定](memory/maintenance.md)。

## 维护与同步

日常直接在仓库中维护内容。已在工具目录里修改过的 skill，可以连同脚本和资源完整导入：

```bash
./zhizhou import-skills /path/to/skills
./zhizhou import-skills /path/to/skills --apply
./zhizhou check
git diff
```

导入会展开来源软链，保留脚本、资源和本地修改。安装时保留已有规则正文，只管理自己的区块；遇到已被本机修改的区块或技能，会报告冲突并停止写入，供人工合并。

检查变化后，按实际修改的文件保存到 Git：

```bash
git add memory/ skills/ projects/ clients/ sources/ machines/
git commit -m "Update working knowledge"
git push
```

在另一台机器上，先保存当地修改，再取回更新并预览安装：

```bash
git pull --ff-only
./zhizhou check
./zhizhou install
./zhizhou install --apply
```

Git 同步需要显式执行。尚未提交、推送的经验仍只保存在当前机器。登录态、密钥和实验大产物不随知识库迁移。

## 目录导航

| 目录 | 内容入口 |
| --- | --- |
| [`memory/`](memory/INDEX.md) | 工作约定、科研导航与带来源的经验记录 |
| [`skills/`](skills/) | 可安装的通用 skills |
| [`projects/`](projects/README.md) | 项目指南、专用技能、科研协议与分支快照 |
| [`clients/`](clients/README.md) | 客户端专用规则、agent 定义与插件恢复资料 |
| [`sources/`](sources/) | 来源清单、版本、摘要与上游安装记录 |
| [`machines/`](machines/) | 各服务器的路径配置 |
| [`docs/`](docs/) | [工具适配](docs/adapters.md)、[迁移说明](docs/migration.md)、[收录范围](docs/coverage.md)、[验证记录](docs/verification.md) |

安装器已通过 17 项隔离测试和完整迁移验证，覆盖配置保留、冲突处理、旧名称兼容和移动后的路径更新。文件安装完成后，仍需在客户端的新会话中核对加载结果。

启动器优先使用 `/usr/bin/python3`，可通过 `ZHIZHOU_PYTHON` 指定解释器。旧 `./lzh-memory` 命令及安装状态保留兼容，历史来源保持原样。

## 版权与引用

作者与维护者：[Zhenhao Liu（lzh / LikC1606）](https://github.com/LikC1606)。Copyright © 2026 Zhenhao Liu。

知舟的原创安装器、测试和原创说明文档采用 [MIT License](LICENSE)，允许使用、修改和商用，分发时须保留许可证中的版权与许可声明。具体适用文件见 [版权范围说明](NOTICE.md)。

收录的 skills、项目快照和素材遵循各自的许可，不因进入本仓库而改为 MIT。[第三方来源与版权说明](THIRD_PARTY_NOTICES.md) 列出了已核实署名、素材 credits 和仍未确认的许可信息。

研究或文章中使用知舟时，欢迎通过 GitHub 的 **Cite this repository** 或 [CITATION.cff](CITATION.cff) 获取引用信息。引用第三方 skill 或素材时，也请注明其原作者；学术引用建议不增加 MIT 许可之外的使用条件。
