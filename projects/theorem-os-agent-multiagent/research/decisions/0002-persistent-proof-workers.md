---
id: "0002"
title: 子 Agent 在隔离工作区持续产出证明，先验收协作功能
status: accepted
date: "2026-11-16"
decided_by: 用户（本次对话 Q2、Q3）
related:
  - research/decisions/0001-agent-led-skill-multiagent.md
  - research/PROTOCOL.md
---

# 0002 — 子 Agent 在隔离工作区持续产出证明，先验收协作功能

用户选择允许子 Agent 在各自隔离的工作区持续研究、编写 Lean，并向 Lead 异步交付成果；Lead 决定采纳，宿主检查后整合。相较于主 Agent 单独写证明、子 Agent 仅提供只读调查，这条路线让多个 Agent 能共同产出正式证明，也要求保存各自的会话、源码版本和交付证据。

当前阶段先验收协作功能。单 Agent、独立并行与自主协作之间的效果评测后续再定；本次未接受同总 Token 比较作为当前验收门槛，也未确定未来评测的预算、指标或样本。

研究与交付语义记录在 `research/PROTOCOL.md`。本决定确定系统目标；实现完成、验证通过与运行启用分别报告。
