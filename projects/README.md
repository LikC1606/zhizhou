# 项目约束与科研记录

截至 2026-11-16，本目录保存 **11 个项目／独立 checkout 的 16 份指南、24 份项目 skill 快照，以及 8 份持久科研记录**。项目 skill 包含 12 种不同的完整内容；同名技能按来源项目保存，保留分支差异。

本轮查漏覆盖已识别的 `/home/lzh` 顶层项目与 `/data/lzh/workspace/projects` 中的主要项目入口，并按真实路径排除别名重复。它没有穷尽本机所有 Markdown，也没有收集具体数学题证明、原始会话、实验数据或运行日志。

## 项目指南

| 项目标识 | 指南快照 |
| --- | --- |
| `theorem-os` | [AGENTS.md](theorem-os/AGENTS.md) |
| `theorem-os-web-main` | [AGENTS.md](theorem-os-web-main/AGENTS.md) |
| `deepscientist` | [AGENTS.md](deepscientist/AGENTS.md)、[CLAUDE.md](deepscientist/CLAUDE.md) |
| `deepscientist-math` | [AGENTS.md](deepscientist-math/AGENTS.md)、[CLAUDE.md](deepscientist-math/CLAUDE.md) |
| `harbor-builder` | [AGENTS.md](harbor-builder/AGENTS.md)、[CLAUDE.md](harbor-builder/CLAUDE.md) |
| `deepscientist-finance` | [AGENTS.md](deepscientist-finance/AGENTS.md)、[CLAUDE.md](deepscientist-finance/CLAUDE.md) |
| `theorem-os-demo-video` | [AGENTS.md](theorem-os-demo-video/AGENTS.md)、[CLAUDE.md](theorem-os-demo-video/CLAUDE.md) |
| `theorem-os-agent-multiagent` | [AGENTS.md](theorem-os-agent-multiagent/AGENTS.md) |
| `theorem-os-huggingmath` | [AGENTS.md](theorem-os-huggingmath/AGENTS.md) |
| `theorem-os-native-workflow` | [AGENTS.md](theorem-os-native-workflow/AGENTS.md) |
| `theorem-os-native-workflow-main` | [AGENTS.md](theorem-os-native-workflow-main/AGENTS.md) |

原路径、采集日期和分支身份见 [project-guides.json](../sources/project-guides.json)。`deepscientist/finance` 是 `/home/lzh/DeepScientist_finance` 的别名，只保存一组；不同 Git checkout 即使指南相同，也保留各自身份。

这些指南是历史快照，可能包含原机器路径、模型配置或当时的实现状态。使用时先读取实际项目当前指南与代码。修改副本不代表源项目已更新；快照中的运行、提交或发布命令也不构成新的操作授权。

## 项目 skills

| 来源项目 | 保存的 skills 与差异 |
| --- | --- |
| `deepscientist`、`deepscientist-math`、`harbor-builder`、`deepscientist-finance` | 各 4 项：`architecture`、`bump-version`、`i18n`、`testing`。`bump-version` 有两种内容，按项目保留。 |
| `theorem-os-demo-video` | 4 项：[hyperframes](theorem-os-demo-video/skills/hyperframes/SKILL.md)、[hyperframes-cli](theorem-os-demo-video/skills/hyperframes-cli/SKILL.md)、[hyperframes-registry](theorem-os-demo-video/skills/hyperframes-registry/SKILL.md)、[media-use](theorem-os-demo-video/skills/media-use/SKILL.md)。 |
| TheoremOS 的 4 个新 checkout | 各保存 `theoremos-research`，完整内容有 3 种变体；`native-workflow` 与 `native-workflow-main` 相同。 |

项目技能位于 `projects/<项目标识>/skills/`，完整保留脚本、references 和资源，本轮共 274 个文件。来源、实际内容摘要及源码工作区状态见 [project-skills.json](../sources/project-skills.json)。源目录中的未提交修改一并保存，未修改或提交源项目。

默认全局安装仍使用仓库根目录的 `skills/`；本目录的项目技能按对应项目使用。不能因 `architecture` 或 `theoremos-research` 同名，就将不同项目的版本相互覆盖或施加到所有任务。

## 持久科研记录

| 来源项目 | 保存的记录与状态边界 |
| --- | --- |
| `theorem-os-native-workflow` | [PROTOCOL](theorem-os-native-workflow/research/PROTOCOL.md)、[决定 0001](theorem-os-native-workflow/research/decisions/0001-agent-led-skill-multiagent.md)、[决定 0002](theorem-os-native-workflow/research/decisions/0002-persistent-proof-workers.md)。源 Protocol 为 Draft，具体接口尚未冻结。 |
| `theorem-os-agent-multiagent` | [PROTOCOL](theorem-os-agent-multiagent/research/PROTOCOL.md)、[决定 0001](theorem-os-agent-multiagent/research/decisions/0001-agent-led-skill-multiagent.md)、[决定 0002](theorem-os-agent-multiagent/research/decisions/0002-persistent-proof-workers.md)。源 Protocol 记录隔离分支的本地功能验收，明确未启用真实求解。 |
| `deepscientist-finance` | [旧实验协议](deepscientist-finance/docs/research/finance-paper-experiment-protocol-20260921.zh-CN.md)与 [R&D-Factor 修订](deepscientist-finance/docs/research/finance-rd-factor-design-20260924.zh-CN.md)。后者替代后续 Protocol B 的安排；旧批次身份、结果与历史设计保持原样。 |

完整来源及替代关系见 [research-records.json](../sources/research-records.json)。采集这些文本不等于重新验证其中的实验或功能结论，也不把隔离分支状态改写为已部署。原文指向的代码、测试、机器协议和数据没有在这里全部打包；引用路径保留原项目语义。

## 后续使用

`install --project` 生成目标项目的通用记忆入口，不会自动部署本目录的历史指南、科研协议或 skill 变体。具体科研决定与 Protocol 继续以源项目的当前记录为依据。

新增经验可通过 `note --scope project:<id>` 记录，保留来源及确认状态。新增快照应记录具体来源与实际内容；工作区有未提交修改时，仅有 commit 不能完整代表采集内容。首批 7 份指南沿用首次采集记录，本轮新增材料额外保存源码 commit、branch 和 dirty 状态。
