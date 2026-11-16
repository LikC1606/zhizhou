# Derive Strategies and Learn from Strong Solutions

Read this when forming the first strategy, studying a stronger public solution, or escaping repeated local patches. The outcome is a mechanism-level explanation or a concrete implementation choice, according to the user's request. Reuse the current proposal/notes; no extra route inventory, report or experiment quota is required.

## Formulate the Problem Independently of the Code

The incumbent is a feasible witness and a source of engineering evidence. Its functions and neighborhoods need not define the next solution. Before following its call graph, describe what a good solution would look like in the problem's own terms. Use only the questions that change the strategy:

| Task fact | Reasoning it can unlock |
| --- | --- |
| Objective structure, symmetries, conservation laws or exact special cases | An ideal configuration or useful bound; a representation that makes the desired structure easy to construct |
| Difference between ideal structure and feasible outputs | A projection, decoder or joint allocation that preserves structure while satisfying constraints |
| Decisions coupled by a shared resource or constraint | Joint construction, decomposition with a coordinating variable, or a larger valid neighborhood |
| Penalties measured relative to a particular state or reference | Put that reference and cost into candidate generation; a final acceptance check alone may never generate the valuable compromise |
| Scores accumulated over time or repeated decisions | Price improvements by how long they can survive; identify which changes invalidate them and what information is legally available |
| A small change has limited dependencies | Maintain only affected terms or propagate a work queue until dependencies settle, rather than rescanning everything |
| Different regimes have different structure | Use an exact special case, specialized construction or selector where justified; check what applies outside that regime |

These are derivation prompts, not algorithms to apply to every contest. An idealized solution may be jointly infeasible; a bound or exact special case needs its assumptions. In learned systems, the analogous structural question may concern the statistical unit, missing signal, representation, or prediction target rather than geometric construction.

Compare the independent formulation with the incumbent: which useful outputs or information can it not currently express, and what coherent change would enable them? A profile can support a speed hypothesis, but cannot establish that the current representation is adequate. A structural conjecture needs a task-based argument and an observable consequence before implementation, not prior proof of a score gain. Use a diagnostic when it distinguishes competing explanations; otherwise prototype the mechanism.

For online prediction or planning, separate predicting the next event, estimating the lifetime of an improvement, and optimizing a robust action across plausible continuations. They require different evidence. Use only permitted observations and label assumptions about future events. A longer horizon can overpay for a fragile improvement or regress on short episodes; do not call a lifetime heuristic an accurate event predictor.

## Read a Strong Solution as a System

Start from the supplied writeup and its corresponding source/version when available. Read for the design chain: **task fact → simplifying assumption → representation → candidate construction → internal objective/pricing → maintenance and compute allocation**. Follow the score-affecting path far enough to understand interactions; avoid both exhaustive unrelated code reading and stopping at the first recognizable module.

Explain the central design in plain language: what choice becomes possible, why it addresses the objective, which approximation makes it affordable, and where it can fail. Distinguish the strategy from its implementation tricks and fitted constants. For each mechanism that matters to the comparison, identify:

- **Dependencies:** the construction, decoder, cost model, acceptance rule or update machinery it relies on. For example, a rebuild may need a retained-position reward and a matching move price; a copied search kernel alone does not test that design.
- **Actual difference:** whether the incumbent lacks the capability, implements it only in a restricted regime, or already has an equivalent. Different names and code size do not establish novelty.
- **Transfer conditions:** scale, information, constraints and resource assumptions that make the mechanism applicable. Preserve a strong incumbent specialization when the reference solves a different regime better.

Separate author-reported results, what inspected code establishes, and locally measured effects. A reported higher official score is a reason to learn the strategy, not proof that every module is superior. When the user supplies credible score context, use it without repeatedly making score verification the main task. Missing source or score details narrow the claim; they need not prevent explaining a well-described idea. Aggregate comparisons establish a system-level difference, not a component's causal contribution.

If asked to **learn the thinking**, deliver the central idea, how the task could have led to it, its interacting parts, and what changes in our approach. Do not substitute another benchmark campaign or a list of algorithms. If implementation is also authorized, use that explanation to choose the next complete candidate.

## Turn Understanding into a Complete Candidate

Choose the smallest implementation that preserves the proposed mechanism's dependencies. A different representation may need a decoder and valid moves; a model family may need different preprocessing; a trajectory policy may need a matching cost model. A standalone prototype behind the existing interface can be clearer than layering it on every old heuristic. Module replacement is useful when its prerequisites already hold or it answers a specific question; an incomplete transplant losing cannot reject the full method.

Name the observation that could distinguish the new capability from the incumbent. Use a trace or small mechanism experiment when it answers that question; then use matched full-objective evaluation for promotion and independent confirmation at delivery. Reuse trustworthy evidence. Add ablations only when component attribution would change the next decision. More tests refine the evidence for the proposed candidates; they cannot discover a representation that was never proposed.

## Generate Routes That Can Actually Disagree

When the task or history does not yet distinguish solution families, write a few compact, complete strategy hypotheses before committing code. Make them differ in representation, construction, optimization target, information use or coordination variable; changing a coefficient or operator name does not create a new route. At least one route should deliberately test the strongest structurally different idea, and a stalled search may need a route generated without the incumbent or its memory. Choose among routes by their plausible movement toward the target and applicable evidence, not by familiarity or proposal confidence alone. Do not force a fixed number of routes when the mechanism is already clear.

Keep score vectors, regimes or error cases when one scalar average would discard useful complementarity. Retain a strong specialist when it adds objective value on cases the current portfolio misses, and select parents or follow-up experiments that expose those differences. A lower-ranked candidate is useful only if its unique behavior can affect the task objective or unlock another route; diversity by itself is not progress.

Classify a tested route by the mechanism that reached the executed code. Check implementation fidelity separately from score: a partial or substituted implementation can be a useful candidate, but cannot establish that the proposed family failed. When speed and quality both matter, retain relevant tradeoffs under the actual objective and constraints; a simple complexity proxy needs its relationship to runtime checked before it drives selection.

Treat experience as a decision input, not an archive of prose. Compare a useful success with a relevant failure at the decision or operation that produced the outcome; extract a conditional rule, its scope and counterexample risk. Feed that rule into the next proposal and revisit it when new evidence conflicts. On stagnation, change the layer implicated by the failure: first the local construction or operator when its premise survives, then representation, decomposition or coordination when the reachable candidates are wrong, and a fresh strategy family when the current line's ceiling is credible. This escalation is a diagnostic choice, not an automatic ladder or a fixed patience threshold.

Before translating a nontrivial strategy into code, manually walk a small representative state or trajectory far enough to expose its invariant, coupling or failure mode. If that walk contradicts the mechanism, revise the strategy before coding; if the reasoning is sound but execution is weak, inspect translation, objective accounting and implementation behavior separately. A hand walkthrough can reveal a conceptual flaw but does not establish performance.

For concrete source-backed patterns and their limits, see [strategy-generation patterns](source-patterns.md). These examples are implementation leads, not rules to copy wholesale.

## Worked Example: Dynamic Circular Layout

In the Huawei fixed-timeslot task, updates change category quotas on a ring. Uniformity U rewards spacing, stability V charges additional changes relative to the layout at the current API call's entry, and quality accumulates over an update trajectory. These facts support the following reasoning independently of an existing swap optimizer:

| Task fact | Derivation | Candidate idea |
| --- | --- | --- |
| The final quota determines ideal spacing | Intermediate greedy gaps need not resemble the final layout | Construct targets for the final quota, then project jointly to legal vacancies when choices interact |
| Stability uses the call-entry layout | A good rebuild can be expensive unless old occupancy influences its construction | Reward retained positions while constructing the layout and evaluate movement against the same entry state |
| Layout improvements contribute across later updates | A fragile vacancy pattern and a persistent business pattern need not have the same benefit lifetime | Estimate survival of useful structure, or compare permitted continuation scenarios, when pricing current movement |
| A local mutation changes a limited set of same-category gaps | Most unaffected score terms need no new work | Seed incremental repair from the changed dependencies and propagate only as needed |

The [SlotWeave writeup](https://bbs.huaweicloud.com/forum/thread-02127227933062879438-1-1.html) and [inspected source version](https://github.com/XJU-ICTHUB/SlotWeave/tree/ae02dd527e757426b67015c5acc17dcb3584cc4c) illustrate construction, retained-position rewards, lifetime-based pricing and incremental maintenance working together. The local incumbent in that comparison, R36, also had DP, lookahead and geometric indices in some regimes; the useful comparison is their coverage and integration, not claiming those techniques were absent. A longer-horizon price is a heuristic about persistence, not a predictor of the next add/delete request.

For a speed objective, this reasoning may favor a better cheap construction or dependency-limited repair before caching another scan. For trajectory quality, it may favor joint placement or construction with movement-aware pricing. Which candidate wins still needs the task's actual evaluation. These are examples of deriving a strategy; the task's arithmetic restrictions, exact special cases and source constants are not general competition requirements.
