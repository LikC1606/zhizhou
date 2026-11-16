---
name: grilling
description: Stress-test plans, research directions, architectures, and consequential choices through rounds of questions with recommendations. Use proactively for proposal evaluation or unresolved goals, acceptance criteria, or tradeoffs, including “帮我想想这个方案”, “这个方向靠谱吗”, “怎么选”, “有没有漏洞”, “grill me”, “盘问我”, and “拷问我”. Skip status/history checks, explanations of the skill itself, and clear routine implementation or fixes.
---

# Grilling

Challenge unsupported assumptions and contradictions until the material decisions
are clear enough for the user's task. Map them as a **design tree**: decisions
branch into the decisions that depend on them.

## When to start

Use this workflow for consequential planning and proposal evaluation even when
the user does not name the skill. Briefly say you are using `grilling`, inspect
the available context, and begin the first question round. Reading this file,
describing the workflow, or offering to start later is not an interview.

For an identified project's research plans, evaluation semantics, or durable
research tradeoffs, use `grill-with-docs` as the outer workflow so confirmed
outcomes reach project records. When this skill is already being invoked by
that wrapper, run the interview rules below directly.

An explicit “grill me” request uses the current proposal as its subject when
the conversation identifies one. Otherwise ask for the missing subject. A request
to inspect or explain the skill, such as “看一下 grill me”, stays an explanation.
An implementation request with settled material decisions stays implementation.

## Work the tree in rounds

First check the conversation and relevant local evidence. Keep established facts,
settled decisions, open user choices, and pending lookups distinct. Finding facts
is your job: look them up rather than asking the user. Delegate independent
lookups when useful and permitted, without making delegation a prerequisite.

Challenge choices that materially change the goal, acceptance criteria, approach,
budget, or authorization. Make the consequences concrete and recommend an answer
from the available evidence. Resolve routine reversible details using project
conventions and reasonable defaults. Do not invent a comprehensive checklist of
minor decisions merely to keep questioning.

The **frontier** is every material open user decision whose prerequisites are
settled. Ask the whole frontier in one round. A question whose answer depends on
another open answer belongs to a later round. Pending fact-finding likewise delays
only the questions that depend on it.

Number each question and provide a recommended answer with a short reason. Word
questions so “yes” accepts the recommendation. Use an available structured question
tool when appropriate, including the recommendation in each question. For text,
use this format:

```
❓ **Q1 — <decision>**: <concrete question and the consequence of the choice>

➡️ 建议：<recommended answer and why>。回答“是”即可接受。

---

❓ **Q2 — <independent decision>**: <question whose prerequisites are settled>

➡️ 建议：<recommended answer and why>。回答“是”即可接受。
```

Wait for answers before settling those choices, then recompute the frontier.
Continue independent work that is already authorized while waiting. Silence is
not an answer, and a recommendation does not settle a material user decision.

## Finish at the agreed scope

Finish when the material frontier is empty. Briefly state the settled decisions
and any remaining limits. A review or interview remains read-only unless the user
requests implementation. If implementation is already authorized, proceed once
its necessary choices are settled; do not demand a separate confirmation of
“shared understanding” or repeat an approval already given. Respect any existing
action-specific approval requirements.
