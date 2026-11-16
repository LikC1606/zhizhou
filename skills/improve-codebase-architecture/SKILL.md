---
name: improve-codebase-architecture
description: Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
---

# Improve Codebase Architecture

Surface architectural friction and propose **deepening opportunities**: refactors that turn shallow modules into deep ones. The aim is testability and AI-navigability.

This command is _informed_ by the project's domain model and built on a shared design vocabulary:

- Read the installed `codebase-design/SKILL.md` for the architecture vocabulary (**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**) and its principles (the deletion test, "the interface is the test surface", "one adapter = hypothetical seam, two = real"). Use this vocabulary where it clarifies a suggestion while preserving the project's established domain terms.
- Read the project's existing domain and decision records. Research projects may use a Protocol and `research/decisions/`; other projects may already use `GLOSSARY.md` or ADRs. These records give names to good seams and identify settled decisions. Follow project instructions rather than introducing a parallel record system.

## Process

### 1. Explore

**Scope before you scan: YAGNI.** Deepening a module pays off by making future changes to it easier, so put extra weight on the parts of the codebase that have recently changed. Decide *where* to look before you look:

- If the user named a direction (a module, a subsystem, a pain point), take it, and skip the inference below.
- Otherwise, walk back a good stretch of the commit history (`git log --oneline`) to find the codebase's hot spots, the files and areas that keep coming up, and let those paths pull your attention first. If the changes are scattered with no clear hot spot, widen the net.

Read the existing domain definitions and relevant decisions for the area you're touching first. Do not create missing glossary or ADR files just to conduct a review.

Explore the scoped codebase, delegating an independent read when useful and permitted. Don't follow rigid heuristics; note where you experience friction:

- Where does understanding one concept require bouncing between many small modules?
- Where are modules **shallow**, with an interface nearly as complex as the implementation?
- Where have pure functions been extracted just for testability, but the real bugs hide in how they're called (no **locality**)?
- Where do tightly-coupled modules leak across their seams?
- Which parts of the codebase are untested, or hard to test through their current interface?

Apply the **deletion test** to anything you suspect is shallow: would deleting it concentrate complexity, or just move it? A "yes, concentrates" is the signal you want.

### 2. Present candidates as an HTML report

Write the HTML report outside the repo. Resolve the temporary directory from `$TMPDIR`, falling back to `/data/lzh/default-storage/tmp` on this host (or `%TEMP%` on Windows), create it if needed, and write to `<tmpdir>/architecture-review-<timestamp>.html` so each run gets a fresh file. Give the user a clickable absolute file link. Open it with the host's browser opener when a graphical session is available.

The report uses **Tailwind via CDN** for layout and styling, and **Mermaid via CDN** for diagrams where a graph/flow/sequence reliably communicates the structure. Mix Mermaid with hand-crafted CSS/SVG visuals: use Mermaid when relationships are graph-shaped (call graphs, dependencies, sequences), and hand-built divs/SVG when you want something more editorial (mass diagrams, cross-sections, collapse animations). Each candidate gets a **before/after visualisation**. Be visual.

For each candidate, render a card with:

- **Files**: which files/modules are involved
- **Problem**: why the current architecture is causing friction
- **Solution**: plain English description of what would change
- **Benefits**: explained in terms of locality and leverage, and how tests would improve
- **Before / After diagram**: side-by-side, custom-drawn, illustrating the shallowness and the deepening
- **Recommendation strength**: one of `Strong`, `Worth exploring`, `Speculative`, rendered as a badge

End the report with a **Top recommendation** section: which candidate you'd tackle first and why.

**Use the project's existing vocabulary for the domain and `codebase-design` vocabulary for the architecture.** If its domain records define "Order," talk about "the Order intake module" rather than an unrelated implementation class.

**Decision conflicts**: if a candidate contradicts an existing decision, only surface it when the friction is real enough to warrant revisiting that decision. Mark the conflict and its reason in the card, referring to the actual record. Don't list every theoretical refactor a settled decision forbids.

See [HTML-REPORT.md](HTML-REPORT.md) for the full HTML scaffold, diagram patterns, and styling guidance.

Do NOT propose interfaces yet. After the file is written, ask the user: "Which of these would you like to explore?"

### 3. Grilling loop

Once the user picks a candidate, read `grilling/SKILL.md` and follow its decision tree: constraints, dependencies, the shape of the deepened module, what sits behind the seam, what tests survive. For research decisions, use `grill-with-docs` as the outer workflow. An architecture review does not authorize implementation of the proposed refactor.

Read `domain-modeling/SKILL.md` when definitions or scientific semantics change. Keep records within the user's write authorization and the project's established workflow:

- **Naming a new concept or sharpening a fuzzy term?** Record confirmed definitions in the existing domain document. Research semantics belong in the relevant Protocol; follow the amendment workflow for a Frozen Protocol. Do not create `GLOSSARY.md` by default.
- **The user settles a durable research tradeoff?** Follow `record-decision/SKILL.md` and the project's decision location. For non-research decisions, follow the project's established ADR or equivalent convention. Record only decisions that merit a durable explanation, never an unaccepted recommendation.
- **The user asks for a read-only review?** Present proposed record text in the conversation and leave project files unchanged.
- **Want to explore alternative interfaces for the deepened module?** Follow the design-it-twice approach in `codebase-design/SKILL.md`, delegating when useful and permitted.
