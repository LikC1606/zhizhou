<!-- README_SYNC: source=bb1571b65bc930204b1d4648f5a1c3eed1646bd6; updated=2026-11-18 -->

简体中文 · [English](./README_EN.md)

# 知舟 · Zhizhou

把 AI 协作的工作约定、科研经验、项目指南和整套技能留在 Git 里。换机器或客户端时，先看安装器会改哪些路径，再为 Codex、Claude Code、Cursor 和 Gemini CLI 生成入口。

如果这套组织方式适合你，可以 [Star 收藏](https://github.com/LikC1606/zhizhou/stargazers)。

[![Stars](https://img.shields.io/github/stars/LikC1606/zhizhou)](https://github.com/LikC1606/zhizhou/stargazers)
[![Last commit](https://img.shields.io/github/last-commit/LikC1606/zhizhou)](https://github.com/LikC1606/zhizhou/commits/main/)
[![Python](https://img.shields.io/badge/runtime-Python%203-3776AB)](./zhizhou)
[![MIT for original code](https://img.shields.io/badge/original%20code-MIT-2ea44f)](./LICENSE)

![可拆装模块和便携收纳盒的概念插画](./docs/assets/zhizhou-readme-cover-image26.webp)

## 先检查，再安装

需要 Git 和 Python 3，安装器只用标准库。仓库中有维护者的个人规则和项目经验；把它作为参考或维护自己的副本时，先看[记忆索引](./memory/INDEX.md)，按自己的工作方式取舍。

```bash
git clone https://github.com/LikC1606/zhizhou.git
cd zhizhou
./zhizhou check
./zhizhou install
```

`check` 核对记忆、Skill 和已登记快照，`install` 显示将写入的路径。看过预览并确认合适后再应用：

```bash
./zhizhou install --apply
```

安装的用户级或项目入口会引用本仓库的记忆索引。本地路径移动后，需要重新安装更新引用。也可以只预览安装指定工具、项目或用户目录：

```bash
./zhizhou install --tools codex claude
./zhizhou install --project /path/to/project --tools all
./zhizhou install --home /path/to/user-home
```

## 不同客户端安装到哪里

| 客户端 | 用户规则 | Skills |
| --- | --- | --- |
| Codex | `$CODEX_HOME/AGENTS.md`，默认 `~/.codex/AGENTS.md` | `~/.agents/skills/` |
| Claude Code | `~/.claude/CLAUDE.md` | `~/.claude/skills/` |
| Cursor | 导出到 `~/.zhizhou/cursor-user-rules.md`，需粘贴到 User Rules | `~/.agents/skills/` |
| Gemini CLI | `~/.gemini/GEMINI.md` | `~/.agents/skills/` |

项目级可以生成 `AGENTS.md`、`CLAUDE.md`、`GEMINI.md` 和 Cursor 的 `.mdc` 文件。项目快照仍按原范围使用，不会批量部署。跨磁盘时用 `--machine` 指定路径配置，外部工具和服务登录在新机器另行配置。详见[适配说明](./docs/adapters.md)和[迁移说明](./docs/migration.md)。安装后从客户端新开会话，确认实际读到了所需规则。

## 记录可复用的经验

先查已有记录，再写来源、适用范围和确认状态。全局习惯用 `global`，科研方法用 `research`，局部约束用 `project:<id>`。`note` 默认记为 `pending`；用户明确确认后才标 `confirmed`，被替代的记录保留来由。示例中的英文内容只是命令参数，记录可用中文。

```bash
rg -n 'keyword' memory skills projects clients
./zhizhou note 'Record review scope' \
  --scope project:example \
  --source 'Design review notes' \
  --body 'Use the agreed review scope for this project.'
```

把改好的本地 Skill 连同脚本和资源导回来时，先预览，以免覆盖仍在用的版本：

```bash
./zhizhou import-skills /path/to/skills
./zhizhou import-skills /path/to/skills --apply
./zhizhou check
git diff
```

安装器保留自己的管理区块之外的内容，在已有区块或技能有本地冲突时停止写入。同步需要显式通过 Git 或已有备份流程完成，登录态、密钥和大体积运行产物不随知识库迁移。详见[维护约定](./memory/maintenance.md)。

## 从哪里查内容

| 入口 | 收录内容 |
| --- | --- |
| [记忆](./memory/INDEX.md) | 通用协作、科研导航和有来源的经验 |
| [Skills](./skills/) | 通用工作流程、脚本和资源 |
| [项目](./projects/README.md) | 指南、专用 Skill、研究协议和快照 |
| [客户端](./clients/README.md) | 专用规则、Agent 定义和插件恢复资料 |
| [来源](./sources/)与[机器配置](./machines/) | 上游版本、内容摘要和机器存储布局 |
| [收录说明](./docs/coverage.md)与[验证记录](./docs/verification.md) | 收录范围、隔离测试和迁移验证 |

```bash
./zhizhou check
python3 -m unittest discover -s tests -v
```

启动器优先使用 `/usr/bin/python3`，也可设置 `ZHIZHOU_PYTHON`；旧 `./lzh-memory` 和安装状态仍兼容。验证文件级迁移，不等于验证各客户端加载和遵循规则。

## 版权与引用

原创安装器、测试和原创说明文档采用 [MIT License](./LICENSE)，适用文件见 [NOTICE.md](./NOTICE.md)。收录的 skills、快照与素材遵循各自许可，署名和来源见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)。维护者署名和推荐引用见 [CITATION.cff](./CITATION.cff)。

有可复现的迁移或客户端入口问题，欢迎[开 Issue](https://github.com/LikC1606/zhizhou/issues)。
