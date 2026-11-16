# Skill 化多 Agent 协作协议

Version: v1
Status: Implemented（隔离分支的本地功能验收；未启用真实求解）
Updated: 2026-11-16

## 已确认的目标

核心是多个 Agent 围绕同一冻结原题持续协作、共同产出证明。Lead 自主拆题、派工和调整路线，共享的固定版本 Skill 约定研究方法与交付方式；宿主负责隔离、预算、持久化和独立 Lean 验收。

依据：[决策 0001](decisions/0001-agent-led-skill-multiagent.md)、[决策 0002](decisions/0002-persistent-proof-workers.md)。

## 角色与成果语义

| 对象 | 职责与含义 |
| --- | --- |
| Lead Agent | 决定数学分解、分工、后续任务、路线调整及成果采纳。 |
| 子 Agent | 在独立隔离工作区持续研究、编写 Lean、保存笔记并交付成果；可以继续接收后续任务。 |
| 宿主 | 执行 Agent 提出的合法协作操作，保存状态并检查源码、预算和交付证据；独立检查后整合成果和验收原题。 |
| 异步交付 | 一份成果就绪后即可向 Lead 提供，无需等待同批其他 Agent 全部结束。 |
| 已检查的局部成果 | 针对固定源码版本、完整声明及环境产生的当前检查证据；整题目标可能仍未完成。 |
| 整题通过 | 宿主对全部冻结原始目标完成独立验收。 |

讨论、笔记和 Agent 自报结论作为研究材料保留；证明复用须绑定实际源码与检查证据。Lead 的采纳决定交由宿主执行检查与整合。

## 当前阶段与最小功能验收场景

当前先验收协作功能。以下场景由已确认目标和既有验收保证导出；本地验证使用受控会话和实际协议进程，不调用真实模型。

1. Lead 可派发至少两个并行研究任务；子 Agent 有各自的会话和可写工作区，能保存不同的 Lean 证明。
2. 一个子 Agent 先完成时，Lead 可接收它的交付并安排后续工作，另一子 Agent 可继续研究。
3. 子 Agent 能接收后续消息或任务并继续工作；已保存源码、笔记和交付状态支持恢复。
4. 一个子 Agent 的成果经当前检查后可供另一个 Agent 继续使用，最终由宿主整合并验收原题。
5. 错误证明和不匹配的源码版本被正确拒绝并返回可处理的反馈；进程停止、预算记账和原题冻结保留现有保证。

验证应区分实际进程、会话通信、源码修改和真实 Lean 检查，与模拟模型回复的范围。功能测试通过不构成数学解题效果或效率提升的结论；比较评测后续另定。

## 实现与接口

新增 `--research-mode skill --skill-delegation team --skill-max-agents 3`，总容量含 Lead，接受 2–4、默认 4。该路径使用一个宿主 Lead（`--workers 1 --coordination independent`），当前依赖 Codex 动态工具和 Linux bubblewrap。既有 cooperative 和 read-only 调查路径继续独立保留。

`theoremos_team` 的九个操作为 `spawn`、`assign`、`message`、`poll`、`wait`、`inspect`、`submit`、`adopt`、`stop`。完整参数见[固定 Skill 协作约定](../skills/theoremos-research/references/parallel-work.md)，运行入口见[运行文档](../docs/codex-skill-runtime.md)。

子 Agent 保留独立 Git worktree、原生 thread、任务与消息；每次交付均先停止写者，再冻结源码、检查精确 theorem/lemma 声明并保存证据。Lead 可以查看交付的声明、源码片段和检查证据，再选择采纳到自己或空闲子 Agent。Lead 采纳在其返回并释放写者后执行，整合使用临时 worktree 和新的 Lean 检查，不覆盖正在写入的工作区。此操作不授予整题验收。

宿主保存 PID namespace 身份，恢复前确认旧进程已停止。已排队任务可继续；已经运行但未完成的任务记为 interrupted，保留源码和 thread，须由 Lead 显式继续派工，不重放未知模型请求。交付检查与整合保留待恢复身份；FF 前的持久化 intent 允许识别合并前后退出并幂等完成原转换。预算累计 Lead 与所有子 Agent 的实际用量；缺失 receipt 保留为未知。

未交付或被拒绝的源码草稿保留原交付基线，后续派工纠正证明后仍能完整转移改动。Lead 采纳完成时同时保存下一步 freeze；恢复完整原题候选的验收不需要新的模型轮次。成员若有尚未交付的源码改动，先完成交付，再接收其他成员的采纳。子 Agent 的待检查交付和待整合采纳均在后续派工开始写入前完成；基础设施失败保留原 expectedCommit，允许重试。

## 本地验收证据

| 范围 | 验证 |
| --- | --- |
| 持续协作 | [管理层测试](../tests/agentResearchTeam.test.ts)：真实 Git/Lean，受控会话；覆盖异步到达、线程跟进、消息、成员复用、预算、恢复、错误反馈与停写。 |
| 正式交付 | [证明测试](../tests/agentTeamProof.test.ts)：真实 Git/Lean；覆盖精确声明、未授权改动、冲突、过期证据、来源变更及合并前后退出恢复。 |
| 原生执行 | [协议端到端测试](../tests/agentTeamSolver.test.ts)：实际 Codex adapter、动态工具 RPC、bwrap 和四份冻结 bundle；双子 Agent 提交 helper，Lead 两次恢复并采纳。实际 CLI 入口完成 Lead/子 Agent 依赖准备、环境投影、全部原目标的独立 S3 Lean 验收及结果保存。回复由本地协议 peer 控制，健康检查仅访问临时本机服务。 |
| 生命周期 | [工具测试](../tests/agentTeamTools.test.ts)：调用绑定、并发、取消、停止与宿主 SIGKILL 后后台写者退出。 |
| 接入 | [CLI 测试](../tests/skillSolver.test.ts)、[观察记录测试](../tests/inspection.test.ts)、[上下文测试](../tests/skillContextContinuation.test.ts)：配置冻结、恢复、能力限制、全员用量及历史观察的验收边界。 |

进程退出检查已覆盖读取 stat 后、读取 namespace 前退出的窗口，使用可丢弃的真实进程验证，并确认仍存活但 namespace 不可读时继续隔离。早期端到端测试曾出现一次 `slow` 停写确认失败，当时未保留详细 reason；后续未复现，不能据此认定其原因已经定位。当前用例会在失败时保存停止原因及进程状态诊断。

实现位于隔离工作树 `theorem-os-agent-multiagent`，未合并或部署，未切换现有解题进程。这些证据验证工程功能；模型自主组织的质量、真实题目的成功率和协作效率留待后续评测。
