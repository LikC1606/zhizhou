# 知舟 · Zhizhou

载着工作经验、科研约定和可复用技能，继续下一项工作。

把 lzh 与 AI 协作时积累的工作约束、科研方法、skills 和项目经验保存在一个 Git 仓库里。换服务器后，从同一份内容恢复常用工具的工作方式；后续明确的新偏好和纠正也持续记在这里。

## 内容入口

| 位置 | 用途 |
| --- | --- |
| [memory/INDEX.md](memory/INDEX.md) | 记忆索引、适用范围和来源 |
| [memory/working-agreements.md](memory/working-agreements.md) | 已有个人工作约定 |
| [memory/maintenance.md](memory/maintenance.md) | AI 如何继续记录和使用记忆 |
| [memory/research.md](memory/research.md) | 科研约束及对应 skills 入口 |
| `memory/notes/` | 带来源、范围、确认状态的新经验 |
| `skills/` | 当前 59 个通用 skill 的完整内容 |
| [projects/README.md](projects/README.md) | 项目指南、专用 skills 与科研记录的历史快照 |
| [clients/README.md](clients/README.md) | 客户端专用约束、agent 定义和插件恢复资料 |
| `machines/` | 各机器的存储路径配置 |
| `sources/` | 原文件出处、Lark 安装来源锁及导入记录 |

当前通用 skills 约 43.6 MiB，包含第三方资源和本地修改。Lark 来源锁记录了 17 个有本地修改的 skill，恢复时保留当前内容；这些内容不能全部称为自研。

项目内的专用 skills 与客户端插件另按范围保存，不计入 59 个通用 skill，也不会自动部署为全局规则。本轮查漏范围和结果见 [收录范围](docs/coverage.md)。

## 新服务器安装

远程保存在 [LikC1606/zhizhou](https://github.com/LikC1606/zhizhou)，为私有仓库。新服务器使用有访问权限的 GitHub 账号取回：

```bash
git clone https://github.com/LikC1606/zhizhou.git
cd zhizhou
./zhizhou check
./zhizhou install
./zhizhou install --apply
```

`install` 默认只预览，`--apply` 才写入。默认目标为当前用户，工具为 Codex、Claude Code、Cursor、Gemini CLI。安装采用复制，保留这个仓库作为记忆来源；修改核心规则或 skills 后，重新运行安装命令更新副本。

私有远程仓库及首次推送由用户于 2026-11-16 明确授权。后续通过 Git 保存与同步变化；只留在本机、尚未提交推送的新增经验仍需及时同步。

```bash
# 仅安装选定工具
./zhizhou install --tools codex claude --apply

# 给指定项目生成入口；同样先预览
./zhizhou install --project /path/to/project --tools all
./zhizhou install --project /path/to/project --tools all --apply

# 本机 node01 使用原有数据盘路径；其他服务器可提供自己的 JSON
./zhizhou install --machine machines/node01.json
```

新机器默认使用 `~/workspace/projects`、`~/workspace/outputs`、`~/Downloads`、`~/.cache/zhizhou/tmp`。安装器不会把 node01 的 `/data/lzh` 路径当作所有机器的默认值；已有项目继续使用自己的路径。

已有规则正文会保留，安装器追加自己的管理区块；后续仅更新未被本机改动的管理区块。Skill 或管理区块存在冲突时先报告，不覆盖本机变化。具体路径及 Cursor 的设置步骤见 [工具适配](docs/adapters.md)，完整迁移步骤见 [迁移说明](docs/migration.md)。

## 持续积累

AI 可以直接记录用户明确表达的偏好、纠正和已确认结论，并保留来源及适用范围；AI 自己提出的建议记为 `pending`。已确认记录可以由后续任务按需读取，待确认建议不能当作约束执行。

```bash
./zhizhou note '新增经验标题' \
  --scope global \
  --source '用户在本次对话中明确要求：……' \
  --body '准确、可执行的经验内容。' \
  --status confirmed

# 未指定 status 时默认 pending
./zhizhou note '待讨论的研究建议' \
  --scope research --source 'AI 建议，尚未获用户确认' \
  --body '建议内容及待确认问题。'

# 从已安装位置导入后续修改，先看预览
./zhizhou import-skills /path/to/skills
./zhizhou import-skills /path/to/skills --apply

rg -n '关键词' memory skills projects
git diff
```

范围可用 `global`、`research` 或 `project:<项目标识>`。具体项目的结论保留项目范围，不因被记入此仓库就成为所有任务的规则。记录流程见 [维护约定](memory/maintenance.md)。

## 同步与边界

`git status`、`git diff`、`git add`、`git commit` 用于查看和保存变化。配置自己的远程后，在干净工作区运行 `git pull --ff-only` 取回更新，再安装到本机；向远程推送由你按自己的流程执行。项目不自动提交或推送。

本项目提供文件导出和安装。各客户端是否实际加载还需在客户端核对；Cursor 用户规则需要粘贴到设置页。内置 skills 由工具提供，Lark CLI、登录凭据和其他外部依赖需要在新机器另行配置。`stop-that-shit` 当前保存的是 skill 文本，不能据此声称具有 Guard 的机器拦截能力。

启动器优先使用 `/usr/bin/python3`，可通过 `ZHIZHOU_PYTHON` 指定其他解释器，避免本机默认 `python3` shim 改变文件视图。

首次迁移及后续查漏的验证结果见 [验证记录](docs/verification.md)。
