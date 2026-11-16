# LLM and Agent Competition Playbook

Use this when the submitted system trains or runs a language model for classification, generation, reasoning or multi-turn interaction. Read the sections that can change the next implementation. These are conditional mechanisms and adapter requirements; this repository does not supply an executable LLM trainer or interactive evaluator. Continue through the existing [strategy](strategy-design.md), [proposal/result archive](iteration-trace.md) and [adapter contract](adapter-contract.md).

## Establish the Executable Task

Identify what is submitted and what actually runs: model weights, a training recipe, generated answers, a retrieval pipeline or an interactive policy. Separate permitted offline teacher/training compute from online inference limits. A contest inference deadline does not create a new cap on optimization work.

Keep the following decision-relevant identities in the existing recipe, task contract and raw results, without introducing a parallel ledger:

- Base/checkpoint and adapter versions, tokenizer vocabulary and special tokens, chat template, prompt construction, truncation, generation/decoding configuration, answer parser and engine version.
- Training, retrieval, teacher and synthetic-data sources; generation/filtering code; split/group identity; teacher access to labels; and the actual fitted artifacts. Different stochastic outputs from one unchanged recipe remain repeated measurements.
- The official scoring boundary, case/episode aggregation and failure treatment, including malformed output, unfinished tool use and timeout. Compare local and official implementations on known examples when available; investigate tokenization and special-token differences when they affect the score.
- The execution environment, permitted observations/tools, hardware and actual time/memory/query limits. Include loading, retrieval, prefill, decoding, tool execution and packaging where the contest charges them.

Group validation by the underlying problem, prompt, source document or episode when that matches the intended test distribution. Derive synthetic variants after splitting their source groups. Audit overlap with [the split checker](validation-split.md) where applicable, then inspect the actual generation and fitting path. A small or saturated public set may fail to distinguish candidates; construct a more informative development set without consuming independent confirmation. Preserve uncertainty rather than promoting a one-question fluctuation as a reliable gain.

## Choose the Layer from Evidence

| Observation | Mechanism to consider | What the comparison must establish |
| --- | --- | --- |
| Training loss improves while the contest metric stays flat | Inspect validation saturation, distribution, scoring/parser behavior and supervision target | Comparable development outcomes under the actual scoring boundary |
| The student lacks distinctions a larger offline model can express | Soft-label or trajectory distillation; targeted synthetic coverage | Permitted teacher/data provenance, held-out isolation and student gain including deployment cost |
| RAG succeeds only with clean supplied context | Train on realistic retrieved contexts and improve corpus parsing/recall | End-to-end results with the actual retriever and its noise |
| Correctness improves but long outputs exhaust the deadline | Length-aware preference training, decoding or verified stopping | Correctness and completed workload under the same time limit |
| Pairwise decisions change when inputs are swapped | Symmetric training/scoring or order-swap test-time augmentation | Correct label/probability remapping, official aggregate metric and doubled inference cost |
| Throughput or memory limits useful sampling | Engine, batching, prefix/KV caching or quantization changes | Actual task quality and total runtime on the target hardware |
| Different models solve different cases | A confidence-based cascade, fixed ensemble or permitted selector | A selection rule available at prediction time, combined overhead and fresh confirmation |
| Single-step accuracy is high but episodes fail after an error | Recovery trajectories, explicit state or deterministic components | Full-episode success, failure modes and all interaction costs |

Select a complete candidate that tests the implicated mechanism. These rows do not require trying every layer. Use reported winning recipes as leads, inspect their prerequisites, and preserve source-bound conclusions. A useful local refinement need not become an architecture rewrite.

## Synthetic Data, Teachers and Recovery

Distillation moves expensive offline computation into a deployable student. For classification, soft probabilities can preserve teacher uncertainty; for generation, retain verified answers or trajectories appropriate to the student's task. Record teacher checkpoints, prompts, sampling and filtering along with the student recipe. Keep held-out labels out of teacher fitting and training-data decisions. If contest rules permit test inputs or supplied few-shot examples, record that permission and the exact use; do not generalize one competition's allowance.

Generate coverage deliberately: vary task-relevant instructions, difficulty, length or input regimes, and inspect concentration by source/group. Where the task was generated by a known model/template, test whether matching that process matters. Verify synthetic pairs and answers with a task-appropriate checker; teacher agreement or failure to solve is not itself ground truth. A residual pool left after removing easy solved problems may concentrate malformed or mislabeled cases. Inspect that possibility before treating the pool as valuable hard training data.

For RAG, preserve useful formulas, tables and numbers during corpus processing and compare retrieval plus answering together. A model trained only on perfect contexts may fail on the deployed retriever's distractors and missing evidence. Compare realistic retrieved contexts with the current training regime before attributing errors solely to model size.

For multi-turn recovery, include a failed or unexpected prefix followed by a valid correction. When using token cross-entropy with the `-100` ignore index, mask the prefix/actions that should condition the correction without being imitated, and supervise the intended recovery. Match masks and role boundaries to the actual trainer. Put terminal tokens at genuine completion boundaries; an accidental EOS after a nonterminal tool error can teach premature termination. Keep ordinary successful trajectories as well, and evaluate recovery in complete episodes.

## Post-Training and Model Composition

Choose a starting checkpoint that carries relevant capability. Preference or quality classification may benefit from a compatible reward-model checkpoint; a specialized language/domain may favor another pretrained distribution. Compare tokenized lengths and zero/few-shot behavior where they affect context coverage and throughput. Inspect the output head and task mapping before reusing a checkpoint.

Treat SFT, distillation, preference training and online RL as different mechanisms with different data/verifier and compute requirements. A successful recipe in one contest does not establish that another method is universally ineffective. For example, correct short/long answer pairs can motivate a length-aware preference candidate, whose test must check both retained correctness and reduced online cost. Do not replace the task objective with brevity.

QLoRA target modules, precision and other settings belong to an implemented training hypothesis. Attention plus MLP adaptation can be worth testing when attention-only updates miss the required capability; there is no universal rank, layer list or winning LoRA variant. Four-bit training does not establish that four-bit inference preserves reasoning quality. Specialized interventions such as output soft-capping changes require the matching architecture and loss path. Dedicated parameter/merge-weight sweeps still require the user's explicit tuning request under `SKILL.md`.

Keep prediction blending, adapter composition and full-model weight merging distinct. For compatible low-rank adapters, use tooling that combines the actual scaled weight updates; independently averaging their A and B factors can introduce unintended cross terms. Full-model interpolation requires compatible parameter layouts and semantic alignment. Record bases, coefficients and merger implementation, then evaluate the produced model as a complete candidate. A merge can change accuracy, output length and runtime; it is not an established gain merely because no extra model call is added.

## Inference Budgets and Test-Time Compute

Measure the deployed system under the actual competition limit. Engine, quantization, batch shape, sequence length, cache precision and concurrency interact; a faster kernel or isolated tokens/s result does not establish a better submission. Distinguish cold loading, prefill, decoding and tool/retrieval costs where the distinction changes the next implementation. Test accuracy on the target task when changing precision, especially for long reasoning. Preserve the full workload and timeout outcomes.

Use saved compute for a justified policy: more samples, a stronger model on uncertain inputs, order-swap augmentation or a verified answer-selection mechanism. Select routing features and thresholds on development evidence using information available at inference time. Uncertainty alone does not prove that a larger model will repair the case. Count every routed model and selector cost in the end-to-end comparison.

Stopping can occur within a sample or across samples for one question. Define what constitutes a complete valid answer/tool result, and test whether stopping at that point changes correctness. The first answer-looking string is not necessarily the final answer. Majority-based early stopping needs the declared voting rule and remaining sample budget; global saved time can be reallocated only by a policy the submitted system actually executes.

Keep token counts, throughput, memory and failure diagnostics in raw results as needed. The existing optional `resource_profile` accepts one actual lower-is-better consumed resource under a fixed measurement protocol; tokens/s is not a direct input. Use measured inference seconds or another applicable consumption metric when opting in. No resource profile or score improvement can be inferred from the orchestration's total elapsed time.

## Replay Only What the Recorded Trajectories Support

The archive's `iteration-trace` is an optimization proposal-to-result chain. For inference-policy diagnostics, a task adapter may separately record case/sample IDs, generated sequences, answer-extraction results, timestamps or token positions, tool events, completion status and measured costs. Preserve the generation/environment identities and enough ordering to answer the proposed replay question; do not log private hidden reasoning that the model interface does not expose.

On a fixed set of recorded generations, replay can compare supported vote rules, sample subsets and eligible output-prefix stopping rules without regenerating everything. Label this as cached-trajectory evidence, with the assumptions and omitted costs. A truncated prefix must still produce a valid answer under the parser. Confirmation evidence remains isolated from this policy search.

The supplied [fixed-answer vote replay tool](inference-vote-replay.md) implements a narrow diagnostic: plurality voting and irreversible-lead stopping on an ordered development cache, with failures consuming sample slots. It reports exact-match correctness, recorded-pool coverage and selected sample counts; optional cached costs are not new runtime measurements. It does not implement within-generation truncation, model generation or interactive replay.

Changing quantization, model weights, prompts, engine, batching or a tool action can alter the generated path or runtime. Adaptive routing also changes workload and cache contention. Old trajectories cannot establish those counterfactual outputs, exact timing or new interactive outcomes. Run the affected candidate on the real adapter, with matched full fidelity before promotion. An offline replay is neither generally O(1) nor an exact submission simulator.

## Multi-Turn Agents and Final Delivery

Separate language interpretation from operations that have a reliable explicit representation. A model can parse an utterance into a validated action/state update while deterministic code enforces inventory, arithmetic, legal moves or state transitions. Search, lookup or decision trees may handle a well-defined subproblem; test their coverage and interface errors rather than assuming that replacing the model always helps.

Keep permitted observations, tool results and useful explicit state/history available across turns using the model interface's supported context handling. Evaluate summarization/truncation by retained task state and episode outcomes; do not assume inaccessible internal reasoning can be preserved or inspected. Include tool failures, malformed actions and recovery in development scenarios. A step budget, history policy or tool set is a candidate mechanism when it changes what the agent can accomplish.

Inspect repeated unproductive calls and choose a concrete alternate query, tool or strategy when the evidence warrants it. Avoid copying a fixed retry count or tool-step quota from another benchmark. Measure complete episodes under matched scenarios and the declared score aggregation, including calls, timeouts and failures; high next-action accuracy alone is insufficient.

Freeze the selected recipe, parser, policy, model and required data before independent confirmation under the existing delivery rule. When the contest runs offline, execute the actual package with the required offline dependencies and resource limits, then verify the packaged artifact identities. This guide does not authorize starting an unattended campaign or making an official submission.

## Source and Evidence Scope

The motivating source is limzero's Xiaohongshu note [扒完10场Kaggle LLM竞赛金牌总结的夺金公式](https://www.xiaohongshu.com/explore/6af82879000000001c031e58), read on 2026-11-16 through its note text and complete subtitle track. Relevant subtitle windows are 03:26–08:11 (validation/scoring), 08:18–15:40 (data/distillation/recovery), 15:47–23:29 (post-training/composition), 23:39–30:44 (inference/test-time compute), and 30:52–36:31 (agents/delivery).

The video's contest scores, percentage attributions and individual ablations were not independently checked against the original winning writeups/code. They are not archived local outcomes or universal defaults. This playbook converts its method leads into conditional task decisions without importing those numerical claims. For a consequential recipe choice, retrieve the relevant original rules, writeup and matching code through [source-driven strategy learning](strategy-design.md#read-a-strong-solution-as-a-system). Attach actual candidate results through the existing archive; use [conditional learning](iteration-trace.md#carry-conditional-learning-into-the-next-construction) only with its required measured evidence and scope.
