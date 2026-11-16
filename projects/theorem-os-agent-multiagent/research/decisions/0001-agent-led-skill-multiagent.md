---
id: "0001"
title: 以 Agent 自主组织协作为 Skill 化求解的主线
status: accepted
date: "2026-11-16"
decided_by: 用户（本次对话 Q1）
related:
  - docs/codex-skill-runtime.md
  - src/runtime/nativeDelegation.ts
  - src/solver/cooperation.ts
---

# 0001 — 以 Agent 自主组织协作为 Skill 化求解的主线

用户明确将 multiagent 作为新 Skill 化求解系统的核心，并在 Q1 选择：由 Lead Agent 自主拆题、派工和调整路线，共享 Skill 约定研究、协作与交付；宿主负责隔离、预算、持久化和独立 Lean 验收。研究组织策略交给 Agent，使该策略成为可研究的协作能力；保留宿主主导的既有任务图调度是本次考虑过的另一条路线。

决策时已有两条不同路径：cooperative 模式由 Lead 提交计划、宿主执行调度；原生 `theoremos_investigate` 仅提供批量只读调查，等待整批结果后返回。它们本身不代表上述目标已经完成。后续 team 实现与本地验收记录在 [PROTOCOL](../PROTOCOL.md)。

本次决定不确定子 Agent 的写权限、具体调度与通信工具、默认并发或评测标准，也不授权更改正在运行的题目、进程或策略。后续确认这些选择时分别补充记录。
