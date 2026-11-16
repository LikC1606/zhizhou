# Work with exact declarations

Inspect the actual Lean type and surrounding namespace, variables, instances and imports before applying a similarly named lemma. Use the run's declaration and library search tools to narrow candidates, then inspect the source or exact type. A name match alone is insufficient.

When elaboration fails, isolate the failing expression in a small probe using the same environment. Check implicit arguments, coercions, notation, universe levels and instance requirements as indicated by the real diagnostic. Recompile after a meaningful change; retain the exact error rather than replacing it with a broad claim that the mathematics is impossible.

Computational examples can refute a proposed intermediate claim or guide a conjecture. A successful finite search or numerical experiment does not prove an unrestricted statement. Keep executable experiment code, parameters and output if it informs a route decision.

A reusable helper needs its full type, explicit assumptions and required source context. Prefer a declaration that can be checked independently of the still-open original target. If it depends on an unresolved hypothesis or draft axiom, preserve that dependency and do not describe it as unconditional knowledge. Use the host declaration-delivery interface shown in the generated tool help when that interface is enabled.

Before a final submission, run an appropriate real Lean check and address its actual errors. The host independently freezes and verifies candidates, including all original targets and trusted-source constraints. A locally passing file or a previous receipt does not authorize weakening the frozen problem or changing its environment.
