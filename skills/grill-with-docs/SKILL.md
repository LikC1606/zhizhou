---
name: grill-with-docs
description: Proactively interview about consequential research plans, evaluation boundaries, scientific definitions, and research tradeoffs in an identified project, recording researcher-confirmed outcomes in its documents as they resolve. Use for “帮我想想这个研究方案”, “这个方向靠谱吗”, “评测怎么定”, or research decisions that should persist beyond chat; no explicit skill command is needed. Honor explicit read-only scope. Skip status/history checks, skill explanations, and settled routine fixes.
---

Use this workflow automatically for the matching project discussions. Briefly
say you are using `grill-with-docs`, then inspect the project and start the
material question round; do not ask whether to invoke the skill.

Read the current project's instructions and existing research records first.
Prefer project-local versions of the skills below when provided. Follow the
project's document locations and the user's current write authorization, including
any explicit read-only scope.

The user's proactive-use preference includes recording confirmed outcomes in
local project research documents as part of this workflow. Once the researcher
settles a material choice, record it without a separate permission question.
An agent's recommendation is not a settled choice. If the user explicitly asks
to discuss without writing, keep the interview read-only and present proposed
record text in the conversation. Project-specific restrictions and required
approvals continue to apply.

Invoke the `grilling` and `domain-modeling` skills before starting the interview, then run the interview by their rules.

Project-local rules override the upstream document destinations:

- Record each important research decision in `research/decisions/` as soon as it is resolved, using the `record-decision` skill.
- Record scientific semantics in the relevant `Protocol`, normally `research/PROTOCOL.md`.
- Do not create `GLOSSARY.md`, `docs/adr/`, or any other parallel ADR or status system unless the user explicitly asks for that upstream artifact.
