# 科研协作约定

状态：confirmed。范围：research。
来源：2026-11-16 收录的 [个人工作约定](working-agreements.md) 及既有科研 skills。本页提供导航，不声称新增了实验结论。

研究方案、评测边界、科学定义和有长期影响的权衡存在未决选择时，使用 `grill-with-docs` 组织讨论，按 `grilling` 提出具体问题和建议。先查项目已有记录，把事实查询交给 AI；明确的例行实现和状态查询无需重新盘问。

用户确认的重要科研决定记在相关项目的 `research/decisions/`，科学语义记在项目 Protocol。使用 `domain-modeling` 核对术语与代码语义，使用 `record-decision` 保存真实权衡。AI 建议在用户接受前保持待定；冻结 Protocol 的语义变更遵守项目的版本与决定记录流程。

| 任务 | 对应 skill |
| --- | --- |
| 研究方案与评测选择 | [grill-with-docs](../skills/grill-with-docs/SKILL.md)、[grilling](../skills/grilling/SKILL.md) |
| 科学术语与长期决定 | [domain-modeling](../skills/domain-modeling/SKILL.md)、[record-decision](../skills/record-decision/SKILL.md) |
| 资料检索与带来源的研究 | [deep-research](../skills/deep-research/SKILL.md) |
| AutoResearch 选题与优化面 | [paper-discovery](../skills/autoresearch-paper-discovery/SKILL.md)、[optimization-surface](../skills/autoresearch-optimization-surface/SKILL.md) |
| AutoResearch 工程题与验收 | [task-authoring](../skills/autoresearch-task-authoring/SKILL.md)、[task-qa](../skills/autoresearch-task-qa/SKILL.md)、[baseline-quality](../skills/autoresearch-baseline-quality/SKILL.md) |
| 实验隔离与交接 | [run-isolation](../skills/autoresearch-run-isolation/SKILL.md)、[conversation-handoff](../skills/autoresearch-conversation-handoff/SKILL.md) |
| 中文项目介绍与周报 | [feishu-project-report-writing](../skills/feishu-project-report-writing/SKILL.md) |

这些 skill 分别服务于研究、出题、只读质检或运行组织，按实际任务选择。读取它们不会扩展运行、外部写入或逐题干预授权。

TheoremOS 还必须遵守其 [系统维护与解题干预边界](projects/theorem-os.md)。实现完成、测试通过、已激活和原题通过分别报告；人工逐题协助不能计作系统自主能力。
