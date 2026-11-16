# DeepScientist V2 Agent Guide

This file is the working guide for AI agents and human contributors inside this repository. Follow it together with [CONTRIBUTING.md](CONTRIBUTING.md) and [CONTRIBUTING.zh.md](CONTRIBUTING.zh.md).

## Scope, Repository Identity, And Change Discipline

- This guide applies to the whole repository unless a deeper `AGENTS.md` overrides it. The vendored guide under `resources/skills/vendor/deepscientist-1.6.0/` applies only inside that subtree.
- Before reading or editing, run `git rev-parse --show-toplevel` and `git status --short`. This checkout is `DeepScientist_V2`; do not silently redirect work to similarly named sibling checkouts such as `DeepScientist-Pro`, `AionUi-git`, or another worktree.
- Follow, in order: the user's current request, the nearest applicable `AGENTS.md`, this root guide, contributor docs, then established source patterns. Product PRDs describe intent but do not override newer source behavior or an explicit owner decision.
- The worktree may already contain user changes. Preserve them, ignore unrelated files, and never reset, clean, regenerate, or reformat outside the requested scope.
- Prefer the smallest coherent change. Do not combine product work with broad refactors, dependency upgrades, branding cleanup, generated assets, translation churn, or formatting sweeps unless they are required by the same behavior.
- Treat current source, `package.json`, build configuration, and executable tests as the operational truth. When documentation disagrees, verify the implementation before editing either side.
- Do not commit, push, publish, operate real Lark/Feishu resources, run write-enabled external smoke tests, or modify real user data unless the user explicitly requests that action.

## Autonomy, Clarification, And Completion

- Within the user's authorized scope, continue through the necessary investigation, implementation, verification, and delivery. Follow existing conventions for noncritical preferences; ask only when a material decision cannot be resolved from context or authorized read-only investigation.
- While awaiting a decision or approval, pause only the dependent steps and continue independent authorized work. A limitation of one skill is not by itself a blocker for work covered by the user's request; use the appropriate repository workflow.
- These rules do not waive any explicit approval requirement, including submission, publication, live data operations, and redistribution approval. Keep required previews and approvals; apply a domain's stated approval-validity rules when resuming an approved operation.
- Diagnose failed checks and fix problems caused by the current change within the authorized scope. Do not bypass required checks or expand into unrelated repairs. Report completed work, verification that could not run, concrete blockers, and actions awaiting approval separately; a skipped check is not a pass.

## Project Core

DeepScientist V2 is an Electron + React desktop app and standalone WebUI shell around a bundled Rust backend binary named `deepscientist-core`.

The important mental model:

- The TypeScript/Electron code owns the app shell, renderer UI, packaging, WebUI static server, Electron/Web bridge, config client, type contracts, migrations from legacy stores, bundled MCP scripts, and local process lifecycle.
- `deepscientist-core` owns most runtime business APIs: auth, users, providers, conversations, messages, MCP, cron, agents, remote agents, teams, assistants, settings, and realtime events.
- The renderer almost never talks to Electron main directly for business data. It calls the backend through `ipcBridge`, which is now mostly HTTP/WebSocket wrappers over `/api/*` and `/ws`.
- Electron desktop and standalone WebUI share the same renderer bundle, but differ in transport and auth. Desktop injects a backend port through preload. WebUI uses same-origin `/api/*`, `/login`, `/logout`, and `/ws` proxied by `@deepscientist/web-host`.
- Desktop-local Lark automation, project-agent coordination, science artifact report storage, medical evidence report storage, and Codex memory are TypeScript-owned exceptions. They live under `packages/desktop/src/deepscientist_lark/` and are exposed through narrow Electron bridges; do not assume standalone WebUI parity.
- Structured Science and Medical Evidence payloads are contracts, not presentation-only JSON. Their schemas live under `packages/desktop/src/common/chat/`, are reconciled in conversation message hooks/list state, and may open specialized Preview workspaces.

When something is not implemented in TypeScript, check whether it is an `deepscientist-core` API surface before adding duplicate frontend/main-process logic.

## Repository Map

Top-level layout:

- `packages/desktop/`: Electron app, renderer, preload, main process utilities, shared TS contracts.
- `packages/desktop/src/modes/`: built-in mode manifests, registries, conversation detection, and Guid runtime assembly.
- `packages/desktop/src/deepscientist_lark/`: desktop-local Lark project automation plus Codex memory, science artifact report, and medical evidence report stores/services.
- `packages/web-host/`: starts or attaches to `deepscientist-core`, serves `out/renderer`, proxies `/api/*`, `/login`, `/logout`, `/ws`, and `/api/stt/stream`.
- `packages/web-cli/`: CLI helpers for browser opening and WebUI admin password flow.
- `packages/shared-scripts/`: shared release/setup helpers, including bundled `deepscientist-core` preparation/verification.
- `scripts/`: build, packaging, WebUI launch, migrations, debug, i18n, and release utilities.
- `resources/bundled-deepscientist-core/<platform>-<arch>/`: expected location for the `deepscientist-core` binary in dev/package flows.
  This directory is gitignored and usually absent in a fresh worktree.
- `docs/contributing/`: contributor setup and structure rules. Some references in `docs/README.md` point to directories not present in this clone, so prefer source when docs disagree.
- `docs/prds/`: product requirements. Do not reorganize product-owned docs without explicit permission.
- `examples/`: extension examples, including ACP adapters, channels, assistants, skills, themes, and settings tabs.
- `mobile/`: a separate Expo/React Native client with its own package and validation commands; root desktop checks do not prove mobile compatibility.
- `tests/unit/`, `tests/integration/`, `tests/regression/`, `tests/e2e/`: Vitest unit/DOM/integration coverage and single-worker Electron Playwright flows.
- `.claude/skills/`: repository-local skills. Use them when their trigger conditions apply.
- `out/`, `dist/`, `release/`, `output/`, coverage, Playwright results, `screenlog.*`, and temporary runtime state are generated artifacts. Do not edit or treat them as source.

## Runtime Architecture

Desktop startup:

1. `packages/desktop/src/index.ts` runs first. It configures Chromium/app paths before any `app.getPath('userData')` call, enforces single-instance behavior, fixes GUI PATH, initializes Sentry/logging, starts storage, starts `deepscientist-core`, creates the main window, and wires Electron lifecycle/tray/deep-link/WebUI behavior.
2. `packages/desktop/src/process/index.ts` initializes platform registration, storage, bridges, and main-process i18n.
3. `@deepscientist/web-host` `BackendLifecycleManager` resolves `deepscientist-core` via `packages/desktop/src/process/backend/binaryResolver.ts`, spawns it, waits for health/listening, and stores the backend port on `globalThis.__backendPort`.
4. `packages/desktop/src/preload/main.ts` exposes the Electron bridge and backend startup state to the renderer.
5. `packages/desktop/src/renderer/main.tsx` initializes config/i18n/theme, installs the browser bridge adapter, prefetches detected agents, and mounts the React app.

Standalone WebUI startup:

1. `scripts/webui.ts` optionally runs `bun run package`, resolves renderer assets, resolves `deepscientist-core`, chooses a data dir and port, then calls `startWebHost`.
2. Default WebUI ports are dev `25809`, multi-instance dev `25810`, production `25808`.
3. Default standalone data dirs are `~/.deepscientist-web-dev`, `~/.deepscientist-web-dev-2`, or `~/.deepscientist-web`; they intentionally do not collide with Electron's default data dir.
4. `packages/web-host/src/static-server.ts` is a static server and reverse proxy only. Do not put business routes there.

Backend spawning:

- `packages/web-host/src/backend-launcher.ts` builds `deepscientist-core` args: `--port`, `--data-dir`, optional `--parent-pid`, `--log-level`, `--app-version`, `--managed-resources-mode bundled`, `--log-dir`, `--work-dir`, and `--local`.
- It injects `DEEPSCIENTIST_CACHE_DIR`, `DEEPSCIENTIST_WORK_DIR`, and `DEEPSCIENTIST_LOG_DIR` so backend `/api/system/info` matches Electron-managed directories.
- It cleans registered child agent processes through `runtime/agent-process-registry.json` before backend startup.
- It skips Fetch-forbidden ports and validates startup with health checks.

## Local Backend Resources

`deepscientist-core` is not built from this TypeScript repository during normal app startup. The desktop app expects a prebuilt backend bundle at:

```text
resources/bundled-deepscientist-core/<process.platform>-<process.arch>/
- deepscientist-core[.exe]
- manifest.json
- managed-resources/
```

Important workflow facts:

- `resources/bundled-deepscientist-core` is intentionally ignored by git. A new `git worktree add ... HEAD` will not contain it.
- If the renderer shows "missing required local resources" or logs `DeepScientist Core startup failed while resolving backend binary`, first check this directory before changing frontend code.
- For the current macOS arm64 setup, the expected runtime key is `darwin-arm64`.
- The pinned backend version is `package.json#deepScientistCoreVersion`; in this checkout it is `v0.1.50`.
- Codex and Claude Code are deliberate managed-resource overlays. Bundle preparation selects `package.json#managedCodexAcpVersion` plus `managedCodexCliVersion`, and `managedClaudeAcpVersion`, while retaining the Core-required compatibility slots from `managedCodexAcpCompatibilityVersion` and `managedClaudeAcpCompatibilityVersion`. The selected top-level manifests, entrypoints, package versions, platform executables, and legacy validation paths must agree. For Codex, the platform package, `codex` executable, and sibling `codex-code-mode-host` executable are one atomic runtime: the verifier and Web host must reject a bundle if any one is missing, has the wrong exact platform version, or lacks execute permission. The native platform `bin` directory must be the first managed `path_entries` item and `node_modules/.bin` the second, so a stale user `~/.local/bin/codex` cannot separate the CLI from its host. Offline smoke must verify this PATH contract and start both executables, including the Code Mode host, before publishing a package. Do not remove those paths or bump Core independently without checking every `/api/agents`, conversation runtime, config-option, and message-pagination contract.

Ways to restore the bundle:

```bash
# Preferred when another local checkout already has a working bundle.
cp -a /path/to/working/DeepScientist-git/resources/bundled-deepscientist-core resources/

# Or download/prepare the pinned backend bundle.
node scripts/prepareDeepScientistCore.js
```

To compile the pinned AionCore submodule instead of downloading a release binary:

```bash
git submodule update --init --recursive
bun run core:build:source
```

Source preparation is explicit and native-only because the newly built binary must run to prepare managed resources. It publishes the same verified runtime layout and cache as the download path; later `bun run dist` can reuse it. Use `DEEPSCIENTIST_CORE_SOURCE_DIR` only for an intentional local source override. See [docs/guides/build-aioncore-from-source.md](docs/guides/build-aioncore-from-source.md) for macOS, Windows, and Linux prerequisites and manual commands.

Verify before launching Electron:

```bash
node - <<'NODE'
const { verifyBundledDeepScientistCoreResources } = require('./packages/shared-scripts/src/verify-bundled-deepscientist-core-resources');
const result = verifyBundledDeepScientistCoreResources({
  resourcesDir: process.cwd() + '/resources',
  electronPlatformName: process.platform,
  targetArch: process.arch,
});
console.log(JSON.stringify(result, null, 2));
if (result.missing.length) process.exit(1);
NODE

resources/bundled-deepscientist-core/darwin-arm64/deepscientist-core --help
```

Desktop dev launches the backend with `--port 0`, so do not assume a fixed backend port. Read the actual port from logs such as `backendManager.start ready (port=...)`, `globalThis.__backendPort`, or the preload-injected `window.__backendPort`.

Backend startup triage:

- `Failed to start DeepScientist Core ... resolving backend binary`: missing binary or wrong `resources/bundled-deepscientist-core/<runtimeKey>` layout.
- Installation integrity dialog about missing local resources: same root cause in packaged or package-like contexts.
- `fetch failed` immediately after launch: often means backend did not start, not that the renderer route is broken. Check the `deepscientist-core` startup lines first.
- Runtime component failures after backend is healthy, especially around Node/ACP tools, usually relate to `managed-resources/` or the backend runtime preparation flow rather than `ipcBridge`.

## Cross-Process And API Boundaries

Hard boundaries:

| Layer         | Path                                                             | May use                                      | Must not use                                      |
| ------------- | ---------------------------------------------------------------- | -------------------------------------------- | ------------------------------------------------- |
| Electron main | `packages/desktop/src/index.ts`, `packages/desktop/src/process/` | Node.js, Electron main APIs, child processes | DOM APIs, React                                   |
| Preload       | `packages/desktop/src/preload/`                                  | `contextBridge`, `ipcRenderer`               | business logic, filesystem-heavy work             |
| Renderer      | `packages/desktop/src/renderer/`                                 | React, DOM, browser APIs                     | Node.js APIs, Electron main APIs                  |
| Common        | `packages/desktop/src/common/`                                   | pure/shared types, mappers, adapters         | code that assumes only one runtime unless guarded |
| Web host      | `packages/web-host/src/`                                         | Node/Bun HTTP, backend process lifecycle     | app business routes                               |

API bridge:

- `packages/desktop/src/common/adapter/httpBridge.ts` defines `httpGet`, `httpPost`, `httpPut`, `httpPatch`, `httpDelete`, `wsEmitter`, backend URL resolution, and structured `BackendHttpError`.
- `packages/desktop/src/common/adapter/ipcBridge.ts` is the main typed API surface consumed by renderer code. Most entries map to `deepscientist-core` routes, not Electron IPC handlers.
- `packages/desktop/src/common/adapter/browser.ts` adapts `@office-ai/platform` bridge calls to Electron IPC in desktop mode or WebSocket in WebUI mode.
- `packages/desktop/src/common/adapter/main.ts` broadcasts bridge events to Electron BrowserWindows and WebSocket clients.
- `packages/desktop/src/common/config/configService.ts` reads and writes `/api/settings/client`; it is the renderer-facing settings cache.

When adding a new backend-backed UI feature, first add or reuse a typed wrapper in `ipcBridge.ts`, then call it from renderer hooks/components. Only add Electron bridge handlers in `packages/desktop/src/process/bridge/` for true desktop-only capabilities such as dialogs, windows, tray, OS paths, notifications, updates, and app lifecycle.

Renderer code must capability-detect desktop-only methods. A feature that uses local files, `lark-cli`, native dialogs, system reveal/open, secure credentials, or Electron webviews needs either a WebUI fallback or an explicit unsupported state; a shared React component does not by itself provide runtime parity.

Desktop-local Lark rules:

- Renderer calls go through `ipcBridge.larkAutomation` or `ipcBridge.larkProjectAgent`; React components must not spawn `lark-cli`, read profile files, or construct shell commands.
- Process bridges own native authentication, CLI lifecycle, event listeners, and external writes. Keep argument arrays typed and validate untrusted ids, paths, URLs, and JSON at that boundary.
- Live task, comment, attachment, completion, or project mutations affect real Feishu/Lark data. Unit tests must mock the process/CLI boundary; live writes require explicit authorization and disposable targets.
- The current Web Host does not automatically proxy these Electron providers. Do not claim standalone WebUI support without adding and reviewing an authenticated transport.

Unified project Agent protocol:

- New Feishu-backed Leader, branch-Leader, and Worker conversations use the built-in `ds-team-project` MCP and its single `ds_team` tool. Role-scoped actions are the public contract; renderer code must not infer authority from labels or prompt text.
- Core Team Runtime owns live Agent conversations, slots, streaming output, retries, and receipts. Feishu tasklists/tasks own project membership, assignment, hierarchy, dependencies, decisions, and durable public progress. Local project-agent state stores only bindings, event cursors, idempotency keys, and caches.
- Legacy `deepscientist-lark-project-agent`, `project_graph`, `project_run`, and `project_task` support is read/execute compatibility for frozen conversations only. New prompts, Skills, Assistants, and tests must select `ds_team`; remove legacy paths only after persisted conversation snapshots no longer reference them.
- Remote Agents are projected into the same Team presentation model as local subagents, but a projected remote item must retain its Feishu task GUID, source device/user, visibility policy, and real conversation binding when one exists. Never fabricate a local conversation id to make the UI render.
- A scoped Worker receives a task-graph projection, not a second project truth. The projection may include only the assigned node, its required ancestors, structurally necessary root/delivery anchors, and an authorized child branch; readiness checks for joins must still use the authoritative graph so hidden predecessors cannot make work appear ready.
- A branch Leader may fully operate only its assigned child graph. It may propose a parent-graph patch or request a parent decision, but it cannot decide an approval whose review graph belongs to an ancestor, inspect a sibling branch, or mutate the root graph directly. Conflicting task/graph/delegation locators fail closed.
- Remote task Agents run in a fresh task-scoped isolated workspace. Only explicitly authorized ordinary files are copied; `.deepscientist`, VCS metadata, credentials, and secret-like files are excluded. Deliverables must be submitted through `ds_team`; an isolated copy is never an implicit source-worktree mutation.
- Remote task retries reuse the same isolated workspace only when the capability/file-rule fingerprint is unchanged; a changed authorization scope discards the old copy before intake. This preserves resumable work without allowing a broader retry scope to inherit files.
- `state.json` and the local TOML sidebar cache are shared by the desktop listener and standalone MCP subprocesses. Writes use the shared advisory lock, temp-file replacement, and timestamp/ID merges for task records, delegations, bindings, collaboration inputs, graph/approval/presence, and `eventReceipts`; do not add a direct write path that bypasses this protocol.
- A restricted `get_project_snapshot` returns the scope-filtered delegations and collaboration inputs when the corresponding read capabilities are present. `graph.explain_node` may report only visible edge IDs; hidden blockers are represented by a generic `hiddenDependenciesPending` flag rather than internal edge IDs or counts.
- A `team_worker` graph node may omit `targetSlotId` only when it supplies a readable target name. The ds-team runtime then creates a scoped Worker (maximum eight local teammates per project Team), binds the returned slot to the graph node, and gives it only the Worker MCP/Skill surface. Do not create an unscoped generic Team Agent as a fallback.
- Feishu assignment, comment, answer, and handoff retries must be idempotent. Connection failures preserve the durable task and record a retryable blocked/failed state; they must not silently drop work or create a second task.
- Collaboration `user_input` from a downstream Worker or branch Leader must include and server-verify `sourceTaskGuid`, `sourceRole`, `sourceDelegationId`, and the real source conversation. Answers resume that exact scoped conversation rather than always waking the root Leader.
- Bounded Team waiting is a Lead-only observation surface, not a generic Agent sleep primitive. Research Team Leads use `research_team(action="status", wait_level="1m"|"5m"|"10m")`; Challenge Leads use `challenge_wait` with the same tiers. Workers deliver once and let Core events wake the Lead. Preserve legacy `wait_seconds=0..30` diagnostics and exact `60/300/600` compatibility, but reject arbitrary longer polling loops.

Recommended feature flow:

1. Identify the backend owner and route shape in `deepscientist-core`/`ipcBridge.ts`.
2. Add or extend common DTOs/mappers under `packages/desktop/src/common/` when the renderer shape differs from the backend shape.
3. Keep data fetching in hooks or page-level modules; keep presentational components thin.
4. Subscribe to realtime changes through `wsEmitter`/`wsMappedEmitter` when the backend already emits events, instead of polling or inventing local state.
5. Add focused tests for mapper/pure logic first, then DOM/E2E coverage only when behavior spans the UI.

## Important Domains

Agents and ACP:

- Agent metadata comes from `/api/agents`; the frontend type is `AgentMetadata` in `packages/desktop/src/renderer/utils/model/agentTypes.ts`.
- `ipcBridge.acpConversation` prefers the unified `/api/agents` catalog and backend-key health check. It may fall back to `/api/agents/management` plus `/api/agents/{id}/health-check` only when Core explicitly returns a route-missing 404. Keep disabled or uninstalled rows out of picker results, preserve them in the management view, and do not treat this compatibility path as permission to bump Core without checking the remaining conversation APIs.
- Agent-provided `handshake.available_models` is authoritative for model ids, labels, and the current selection. The maintained Codex model list is a pre-handshake fallback only; merge runtime entries first and do not replace a runtime current model with the static default.
- Execution engine kinds are defined in `packages/desktop/src/common/types/agent/detectedAgent.ts`: `acp`, `remote`, `codex`, `openclaw-gateway`, and `nanobot`.
- ACP capability/config/mode/model/permission/session update types live in `packages/desktop/src/common/types/platform/acpTypes.ts`.
- ACP conversation API wrappers are under `ipcBridge.acpConversation`.
- ACP MCP startup is asynchronous in codex-acp: AionCore must arm a bounded
  first-turn startup barrier after `session/new`/`session/load`, wait before
  sending the first `session/prompt`, and reuse the same ACP process for later
  turns. `session/cancel` may cancel the current turn and its pending barrier,
  but must not be treated as permission to kill the ACP process; process
  teardown belongs to `session/close` or an explicit runtime replacement.
- The built-in IOAI/Research Team MCP must resolve the current Core from the
  runtime-injected `AIONUI_BASE_URL` first. The persisted
  `DEEPSCIENTIST_IOAI_CORE_BASE_URL` value is only a standalone-launch fallback;
  never let it override the ephemeral Core port after an app restart. Team
  dispatch restores the Team session and retries transient local transport or
  429/5xx failures with a bounded timeout; 4xx contract or permission errors
  remain terminal and must be surfaced to the Lead.
- `team_send_message.to` accepts an exact Agent `slot_id`, the stable `leader`
  alias, or `*` for broadcast. Never pass `team_id` or a display name as an
  Agent recipient, and never reinterpret an invalid recipient as a broadcast.
- Built-in and detected ACP CLIs include Claude Code, Codex, OpenCode, Qwen, Cursor Agent, Hermes Agent, Snow CLI, and others when available in PATH or contributed by extensions.
- Agent settings must use `/api/agents?include_disabled=true`; pickers should use `/api/agents` so disabled agents do not leak into normal selection.

Conversations:

- Conversation/message types live in `packages/desktop/src/common/config/storage.ts` and `packages/desktop/src/common/chat/chatLib.ts`.
- Renderer conversation UI is under `packages/desktop/src/renderer/pages/conversation/` with subareas for messages, preview, workspace, runtime, hooks, platform-specific views, and utilities.
- Database history requests are wrapped in `ipcBridge.database`, but persistence is handled by `deepscientist-core`.

Performance profiles:

- `system.performanceProfile` is the single renderer setting for resource usage. The shared policy lives in `packages/desktop/src/common/config/performanceProfile.ts`; do not duplicate profile-specific constants in individual pages or hooks.
- The compatibility default is `high`, so an existing installation keeps the previous conversation behavior until the user explicitly selects another profile. `high` displays five recent conversation turns, `balanced` displays three, and `low` displays one; the "earlier" action still loads older turns on demand.
- Profiles affect only newly provisioned Team pools and background/UI work. High keeps the user's current Team limits, balanced caps new pools at six Workers/three reasoning lanes, and low caps them at four/two. Existing Team runs are never terminated or resized when the setting changes.
- Background work is progressively reduced: collaboration WebViews are resident only while the collaboration route is open, hidden-page confirmation polling is skipped outside high mode, preview refresh is 1s/3s/10s, and Guid animation is 30fps/20fps/off for high/balanced/low. Realtime events remain immediate in every profile.
- Conversation history is compacted for rendering only; Core remains the source of truth and explicit pagination must remain available. Never use a performance profile to delete messages, truncate persisted output, or hide a failed/approval-required state.

Conversation workbench, files, and previews:

- `Messages/components/MessageText.tsx` owns assistant/user text presentation and parses both `APP_FILES_MARKER` (`[[DEEPSCIENTIST_FILES]]`) and the legacy `[[AION_FILES]]` marker. Preserve backward compatibility when changing the marker protocol.
- `renderer/components/Markdown/` owns Markdown anchors, inline code rendering, local-file chips, line/column references, URL behavior, and copy affordances. `Messages/components/MessageOutputFiles.tsx` owns the consolidated output-file list below a response. Do not let these two paths develop incompatible file-reference parsers.
- Every rendered Markdown link or recognized local-file reference must remain actionable. Route eligible links through the existing Preview callback; when Preview is unavailable or rejects the operation, retain an explicit system-browser/system-app fallback instead of leaving decorative or inert link text.
- Workspace-relative references must resolve against the active conversation workspace. Normalize Windows and POSIX separators, decode encoded file URLs safely, reject unrelated schemes and traversal outside the workspace, and preserve a clear missing/unreadable-file state.
- `Preview/context/PreviewContext.tsx` is the source of truth for preview tabs, active identity, dirty content, deduplication, persistence, and close/switch behavior. File-backed identity should prefer canonical `file_path`; Science artifact identity also includes conversation/run/artifact/version metadata. Do not create a second tab registry inside a message or viewer component.
- Treat panel visibility and tab lifetime as separate state. A collapse/hide action must preserve tabs, active identity, dirty content, and scroll positions so the workbench can be reopened; only an explicit close-tab/close-all action may discard them. Do not wire a toolbar collapse control to the destructive `closePreview()` path without first splitting those semantics.
- URL tab identity must use the normalized URL, never only its display label or hostname. Different links with the same human-readable title remain different tabs, while repeated references to the same normalized URL reuse one tab.
- `Preview/hooks/useLocalFilePreview.ts` owns file metadata lookup, Science artifact path fallback, content-type selection, large-text truncation, missing-file behavior, and the final `openPreview` call. Reuse it rather than duplicating file IO in messages.
- `Workspace/index.tsx` intentionally defaults to the `files` tab, and `ScienceFilesView.tsx` intentionally defaults to compact `list` mode. Grid is an explicit user-selected inspection mode, not the initial state. A file single-click opens the replaceable browse preview through `{ replace: true }`; double-click currently adds the file to chat. Treat those semantics as a user contract and cover any change with DOM tests.
- `PreviewPanel` already supports multiple tabs, source/preview modes, split/fullscreen/half-panel layout, Office/PDF/image/code viewers, and Science Artifact Workspace. Extend the existing workbench instead of introducing another preview shell or editor state store.
- Delimited files use the bounded native table viewer. Excel workbooks should prefer the backend `document.convert` `excel-json` path and render only the selected sheet with bounded rows/columns; fall back to `OfficeWatchViewer` for formats the converter rejects. Never store converted workbook payloads in `PreviewContext` or localStorage.
- `ScienceArtifactWorkspace` and `science_report` are specialized structured views. Generic file-tab or styling work must preserve artifact selection, project-root resolution, provenance/history actions, report opening, and workspace/fullscreen modes.
- If final-response files are auto-opened, trigger once after the assistant turn has finished, never on every streaming token. Canonicalize and deduplicate first; order deterministically; prefer explicit artifact role metadata, then report/final-report naming; open secondary items without stealing focus from the highest-priority report.
- Auto-opening every external `http(s)` link is not a local-file feature. External URLs remain directly clickable, but automatic network navigation must be a separate opt-in because it can trigger requests, tracking, downloads, or authenticated endpoints.
- A metadata-only background URL tab is not the same as navigation. When a product flow asks to prepare every final-response link, create deduplicated tabs through `PreviewContext`, keep inactive `URLViewer` instances unmounted, and perform the first network request only after the user selects the tab. Never prefetch, probe, resolve favicons for, or follow redirects from inactive tabs.
- Extract automatic URL candidates only from completed assistant prose and explicit Markdown anchors. Do not scrape fenced/inline code, command output, tool JSON, hidden protocol markers, or user-authored text into automatic tabs. A direct user click may still use the normal guarded URL-preview path.
- Default activation order is: an explicit structured report; an explicitly typed report artifact or report/final-report file; a final/summary document; a table or image result; a general webpage; then other files. Open every accepted secondary candidate in the background and keep the highest-priority report active. Prefer contract metadata over filename heuristics whenever both exist.
- Automatic batch preview applies only to the newly completed assistant turn, never to historical turns merely because a conversation was opened or rerendered. Prepare all accepted candidates as deduplicated tabs, activate exactly one highest-priority candidate, and lazy-mount inactive remote pages. When an explicitly enabled auto-display flow contains only safe `http(s)` URL candidates, activating the first ranked URL is the single permitted initial navigation; it must still occur once, after completion, with no background prefetch of the remaining URLs.
- Reuse the existing local-preview loader and open final-response batches sequentially so the same artifact is not decoded or read by competing paths. If large batches become common, move background tabs to metadata-first lazy loading or add a documented bound with an overflow path before introducing more eager reads.
- Required focused coverage for this area includes local absolute and workspace-relative references, encoded paths, line locations, missing files, duplicate references, streaming completion, report priority, background-tab focus, dirty-tab preservation, inactive-URL no-request behavior, code/command/user-text URL exclusion, Files default selection, and Science workspace regression.

Providers and models:

- Provider management wrappers are `ipcBridge.mode.*`, backed by `/api/providers`.
- Shared API client/conversion helpers are in `packages/desktop/src/common/api/`.
- Do not store API keys in logs. `httpBridge` already redacts sensitive log keys; preserve that behavior.

MCP and skills:

- MCP server management is under `ipcBridge.mcpService`, backed by `/api/mcp/*`.
- Built-in MCP scripts are compiled by `scripts/build-mcp-servers.js` and included through `packages/desktop/electron.vite.config.ts` plus `electron-builder.yml`.
- Built-in image generation MCP code is in `packages/desktop/src/process/resources/builtinMcp/`.
- Skill marketplace/config UI lives in settings/capabilities areas; extension-contributed skills are surfaced through `/api/extensions/skills`.
- Treat per-conversation Skills and MCP controls as multi-select state, not one-shot menu commands. Their picker must stay open across consecutive toggles, make the whole option row a single toggle target, preserve search position, and close only through an explicit back/close action, Escape, or outside click.
- Mode-required Skills and MCP servers are locked runtime dependencies. Show them as required/default, merge them with user choices by stable id/name, and never let a generic clear/toggle action remove them from the effective conversation snapshot.
- Keep the Guid capability picker usable with hundreds of Skills: provide search, a bounded scrolling region, stable row dimensions, and an observable empty result. Do not restore nested `Menu.Item` submenus for large checkbox collections; Arco dropdown menus close on item selection by design.
- `[LOAD_SKILL: name]` is a runtime display marker, not `[SKILL_SUGGEST]`: parse complete markers only in assistant text, suppress a trailing partial marker while streaming, remove the protocol marker from Markdown, deduplicate names case-insensitively, and render the skill entry as a separate compact row.
- Resolve a loaded skill by exact name through the runtime skill index plus external-skill discovery. Never interpolate marker text into a filesystem path. Support built-in, custom, extension, auto-injected, and detected external sources; preserve an explicit unavailable state when no indexed match exists.
- A loaded skill opens `SKILL.md` by default. Enumerate its directory lazily, keep folders collapsed until requested, and open child files through `useLocalFilePreview` so file identity, missing-file handling, tab deduplication, and workspace authorization stay consistent.
- Loaded-skill preview metadata is generic Preview UI state. It must remain independent from mode pills, `science_report`, Science Artifact Workspace, Medical Evidence, and Lab Skill Deposition payloads, and it must be stripped from persisted preview tabs.
- Required coverage for loaded-skill markers includes multiple and duplicate markers, user-message exclusion, incomplete streaming markers, invalid names, indexed and external paths, missing skills, missing `SKILL.md`, collapsed folder navigation, tab deduplication, and Science/Medical preview regression.
- External science Skills are imported through `scripts/materialize-science-skills.mjs`, its pinned source metadata, and an explicit allowlist. Keep the corresponding source snapshot and license under `resources/skills/vendor/`; do not copy an upstream Skill directly into the runtime pack or silently expand the allowlist.
- `deepscientist-scientific-visuals` is advisory. It may recommend a report chart, research diagram, publication figure, verified source image, or conceptual image-generation path, but it must not impose a figure quota or block a scientifically complete answer because no illustration was produced. Prefer grayscale structure with one restrained semantic accent for generated SVG/vector assets unless the task or source material requires color.
- The materialized OpenAI4S AlphaFold2, Boltz, and scGPT Skills are optional capability routers, not bundled model runtimes. Check local binaries/checkpoints, hardware, model/data licenses, sequence or feature preprocessing, and privacy constraints before running them; preserve provenance and compare learned representations against an appropriate baseline.

Project Git workspace:

- `project_workspace` is the shared Git entry point for every mode. When an unbound conversation receives an explicit user-approved HTTPS or SSH repository URL, use `project_workspace(action="clone")` once with `payload.remoteUrl` plus `payload.destination` or `payload.baseDir`; after a successful clone, read `status` before editing or checkpointing.
- Clone only into a new or empty directory. Reject local/file remotes, embedded URL credentials, unsafe refs, and non-empty destinations; never overwrite a checkout, change an existing remote, push automatically, or persist credentials/query secrets in conversation metadata. Authentication belongs in the system Git credential manager or SSH configuration.
- The desktop Project workbench must remain available before a binding exists. Its empty state offers local-folder import and remote clone, writes the resulting `project_git` binding to the real ACP conversation, refreshes conversation caches, and then reuses the same Git files/progress/history surfaces and mode plug-ins.
- Local folder import is a separate user gesture. Existing repositories are attached without relocation; a selected non-Git folder may be initialized through the existing `current-worktree` preparation contract. Agents must not emulate this UI path by running an untracked `git init` or raw `git clone` command.
- Cover clone changes with service safety tests, MCP prompt/schema tests, compact activity presentation tests, an unbound-preview test, a real shallow-clone smoke test when network is available, TypeScript validation, and a production Electron build.

Mode plugins:

- Mode plugin manifests live in `packages/desktop/src/modes/builtin.ts`; shared types and registry helpers live in `packages/desktop/src/modes/types.ts`, `packages/desktop/src/modes/registry.ts`, `packages/desktop/src/modes/guidRuntime.ts`, and `packages/desktop/src/modes/conversation.ts`.
- A mode manifest is the source of truth for id, icon, labels, default enabled state, default skills, required MCP servers, conversation `extra` markers, and optional settings route. Do not duplicate those details in sidebar/search/header components.
- To create a new primary mode:
  1. Add a manifest in `BUILTIN_MODE_PLUGINS` with a stable `id`, `runtimeModeId` when there is a backend/runtime marker, `exclusiveGroup: 'guid-capability'`, `defaultSkillIds`, `requiredMcpNames`, `extraKeys`, and an icon name that exists in `DeepScientistIcon`.
  2. Add prompt/extra assembly in `buildGuidModeRuntime` if the mode changes the system prompt, conversation metadata, or per-mode config. Keep config reads in the caller and pass typed config into the runtime helper.
  3. Add or reuse typed helpers under `packages/desktop/src/common/chat/` for the mode payload schema. A mode should write a unique conversation extra key, for example `science`, `medical_evidence`, or `lab_skill_deposition`.
  4. If the mode emits a custom report/artifact panel, add the parser and renderer in `packages/desktop/src/renderer/pages/conversation/Messages/` and keep the message payload schema under `common/chat`.
  5. Add a settings route only when the mode has real user-configurable options. Wire it through `packages/desktop/src/renderer/pages/settings/` and list it via `settingRoute`.
  6. Add focused tests in `tests/unit/modes/` for manifest registration, required MCP resolution, runtime prompt/extra output, and conversation-extra detection.
- To disable or expose modes, use the Mode Plugins settings page (`/settings/modes`) and the `modes.enabled` client config key. The Guid page hides disabled primary modes and falls back to an enabled primary mode when needed.
- New Guid conversations use one primary mode plus zero or more overlays. Persist that selection in the versioned `mode_stack` conversation extra and continue writing the existing `science`, `medical_evidence`, `financial_factor`, `lab_skill_deposition`, and `loop_goal` fields for old readers and specialized renderers.
- Overlay modes, such as goal mode and Knowledge Deposition used during another workflow, are additive. Switching the primary mode must not silently disable compatible overlays; incompatibility must come from an explicit manifest/runtime rule and be visible to the user.
- Compose mode runtime contributions centrally and deterministically: primary prompt first, overlay prompts after it, Skills deduplicated by id, MCP servers deduplicated by name, and conversation extras owned by their schema key. Mode plugins must not import or special-case one another in UI handlers.
- Knowledge Deposition has distinct standalone and overlay prompt semantics. The overlay must preserve the primary workflow, capture only sources actually observed in the conversation/project, and must never publish or install a Skill without explicit user confirmation, including during Goal auto-continuation.
- Conversation UI capabilities must be detected independently from the full active mode set. Do not derive Science, Medical Evidence, or Knowledge Deposition renderers from a single mutually exclusive mode value; the primary mode is only for primary labeling/routing.
- Backward compatibility is required: when `mode_stack` is absent, infer active plugins from legacy extra markers; when it is present, treat it as the ordering/role source of truth while retaining legacy payloads for existing components.
- For E2E smoke, prefer a narrow spec that opens `/settings/modes`, verifies the registered mode cards, opens the Guid `+` capability menu, and verifies the primary mode entries are present. Toggle/hide/show tests are useful follow-ups, but restore defaults in the same test. Full conversation-send E2E is slower and depends on local agent availability.
- Mode-composition coverage must include Science + Goal, Science + Knowledge Deposition, and Science + Knowledge Deposition + Goal, plus legacy conversations without `mode_stack`, duplicate Skill/MCP dependencies, and the user-confirmation boundary for deposition publishing.

Mathematical Research overlay:

- `mathematical-research` is an optional overlay under Science Mode, not a second chat or a replacement for Science Artifact, Science Report, or the shared Project Git workspace. Its typed conversation extra is `mathematical_research`, its stable artifact is `mathematics_portfolio`, and its project mirror is `mathematics/portfolio.json`.
- Keep the proof boundary explicit: informal statements, formal statements, computational examples, and Lean-kernel results are different evidence levels. Only a successful `formal_verifier` result from the bound project and matching proof/statement/commit hashes can support `kernel_verified`; `sorry`, `admit`, explicit source axioms, unavailable toolchains, stale commits, and unreviewed assumptions must remain non-verified.
- For mathematics, the bound project Git tree is the only durable memory. `math_portfolio`, Science Artifact, Preview state, and MCP in-memory runs are projections or provisional state and must be rebuildable from committed files. On resume, read `project_workspace` status and the committed mathematics portfolio, attempts, evidence, reviews, and replay metadata before reasoning.
- Require supporting or refuting evidence before promoting a conjecture: every evidence item must identify the exact problem/statement hash, scope, inputs, outputs, command or source, reproducibility information, and Git commit. Terminal `verified` requires reproducible supporting evidence, a matching Lean-kernel receipt, and a passed independent review on the same committed revision; terminal `refuted` requires reproducible refuting evidence plus a linked minimal counterexample or formal negation. A bounded test, external solver result, or failure to find a counterexample cannot support a universal proof without formal reconstruction.
- Treat the evidence as two visible lanes, not as a single score. The shared readiness result exposes `decision.basis` (`supporting_evidence`, `refuting_evidence`, `conflicting_evidence`, or `insufficient_evidence`) and a machine-readable reason. Every terminal report must state the scope/result of both lanes; if both lanes are decisive for the same statement hash, the only allowed disposition is `inconclusive` until the conflict is reconciled.
- The mathematics Preview must expose an evidence ledger and two decision lanes (proof/refutation), including the exact statement hash and missing gates. It must read `mathematics/portfolio.json` on resume so the UI does not silently fall back to an empty bootstrap projection.
- Keep source identity readable in the Preview: show the evidence observation first, keep command/path/hash details collapsed, and resolve linked Science Evidence ids to their title/source type when available. Do not show raw internal enum values as the only explanation of a result.
- Keep discovery candidates separate from proof attempts. A reproducible witness refutes the exact statement and must be preserved; mixed or bounded evidence remains candidate/inconclusive. Any changed statement, assumption, import, proof, or toolchain makes downstream attempts, verification, and review stale.
- Use `math_portfolio` for problem/attempt/example/verification/review state, `formal_verifier` for bounded Lean execution, `science_artifact` for evidence/files/reports, and `project_workspace` for source Git checkpoints. Do not create a second math preview or mutate the math portfolio through generic artifact actions.
- The durable SOP is in [`resources/skills/deepscientist-mathematics/SKILL.md`](resources/skills/deepscientist-mathematics/SKILL.md). It defines Git-backed recovery, discovery/proof lanes, evidence and counterexample gates, replay manifests, independent review, and renewable bounded epochs. Do not add MCP tools or schema fields merely to provide memory; use the existing Git, Artifact, portfolio, and verifier contracts.
- Research references for LeanDojo-v2, miniF2F, and AlphaProof-style formal proving are kept in [`resources/skills/deepscientist-mathematics/references/formal-proving-evidence.md`](resources/skills/deepscientist-mathematics/references/formal-proving-evidence.md). Treat them as strategy guidance and benchmark provenance, never as proof of a local conjecture.
- Add focused tests for evidence scope/refutation handling, Git resume/checkpoint rules, portfolio validation, verifier failure states, and the shared preview plugin before changing the mathematics schema.

Financial Mode and financial research:

- The current runtime still exposes the legacy `financial-factor` manifest/runtime id and `financial_factor` conversation extra. Treat `packages/desktop/src/common/chat/financialFactor.ts`, `FinancialFactorWorkspace/`, `factor_registry`, and `resources/skills/wq-alpha-research/` as the compatibility surface; do not rename or remove them without a migration and legacy-read tests.
- New factor-mining runs use a single visible submission path: the Lead selects one or more catalogued XAlpha roles (or creates a bounded generic role), workers report through `research_team`, and the Lead publishes exactly one `factor_submit` payload. `factor_search` and `factor_registry` remain legacy-read/compatibility tools only; they must not be added to new prompts, default Team lanes, or completion gates. Every assigned role must return its exact Git `projectRoot`, `baseCommit`, `branch`, and `headCommit`; evidence and falsification details are recommended for research claims but are optional for implementation, visualization, data-preparation, or blocked work. The durable submission bundle is `factor-research/submissions.json`, while `factor-research/campaign.md` records the human-readable campaign memory.
- The intended product boundary is one user-visible Financial Mode with the existing factor workflow as a `factor-research` plugin. The implementation plan and contract matrix live in [docs/specs/alpha-dojo-finance-plugin-plan.zh-CN.md](docs/specs/alpha-dojo-finance-plugin-plan.zh-CN.md); until its P1 migration lands, do not claim that the rename is implemented. The planned `financial-mode` router may load `wq-alpha-research` for factor discovery/evaluation/backtests and an optional `alpha-dojo-finance` provider for market, event, company, simulated-portfolio, holdings-diagnosis, and monitoring tasks. Do not create a second finance chat, Dashboard, Agent Loop, Memory, or Git project.
- Every Financial Mode task must be bound to a project through `project_workspace` before a finance tool writes anything. Read `status` first; checkpoint only material, verified changes with explicit `includePaths`; record `no_material_change` instead of creating an empty commit. Skills must not run `git init` or stage unrelated user work.
- Keep the four persistence layers distinct: Project Git is the human-editable research record; `.deepscientist/artifact-git` is the managed structured snapshot/Evidence/Provenance ledger; the local report store is a recovery index; `PreviewContext` is transient UI state. A published result must bind the Project Git head/checkpoint to the Artifact Git commit/snapshot in one manifest.
- Science `card_ref` is a cross-cutting contract, not merely a renderer detail. When extending it, carry cards through run state, hydrate/build-panel, persistence, MessageList fingerprinting, Artifact Git snapshots, report-store reload, and Markdown/HTML/LaTeX export. Validate ids, snapshot/version/hash references, freshness, completeness, and capability reasons; never silently turn an unknown or dangling card into a paragraph.
- Financial SOPs must declare their required MCP receipts, Artifact kinds, Report sections/cards, confirmation points, and acceptable `partial`/`blocked` outcomes. When the planned `financeTaskContracts.ts` registry is introduced, it is the machine-readable source shared by the router, Skill references, adapters, preflight and tests; do not implement the same requirements as unrelated string lists. A run is `completed` only after a preflight manifest verifies the selected contract id/version/hash, `project_workspace` status, tool receipts, `asOf`/coverage, Evidence, Artifact/card/section references, and any required checkpoint. Agent prose alone is not completion evidence.
- AlphaDojo result semantics may be rebuilt as bounded Science Report modules (for example market themes, event impact, company snapshot, simulated performance, risk, monitoring, and factor result). Do not turn every upstream navigation/settings/input component into a new Report card, and do not copy the upstream React SPA. Each adopted result component needs one module id, one selector, one Artifact/Evidence provenance path, one Preview target, and a focused contract test.
- AlphaDojo is an optional, isolated data/calculation provider. Keep its sidecar loopback-only and whitelist-only; do not expose its Agent Loop, Memory, Dashboard, Cron, shell, arbitrary code execution, account sync, or real-trading tools. Rebuild meaningful upstream components with the existing Arco/ECharts/React Flow/Preview/Science contracts rather than copying its React SPA.
- Every financial result must retain `asOf`, `retrievedAt`, source/provider, upstream revision or content hash, coverage/missing symbols, stale/partial status, and research-simulation/`tradeCapability: disabled` labeling. Do not turn correlation into causality or simulated performance into investment advice.
- Financial Mode changes require focused coverage for mode migration, Skill/MCP routing, receipt/preflight rejection, card persistence/export, Project Git + Artifact Git binding, WebUI capability fallbacks, and legacy factor Viewer behavior. Do not use a passing Factor Viewer showcase as evidence that the production Preview/report path is wired.

Structured research artifacts:

- Science contracts and parsers live in `packages/desktop/src/common/chat/science.ts`; Medical Evidence contracts live in `packages/desktop/src/common/chat/medicalEvidence.ts`. Keep schema/version parsing pure and backward compatible.
- `Messages/MessageList.tsx` reconciles text messages, tool output, persisted report records, and structured panels. It is already a high-complexity coordination layer; extract and test pure selection/reconciliation logic instead of adding more inline condition chains.
- Science and Medical report stores under `packages/desktop/src/deepscientist_lark/` are local indexes/persistence for desktop workflows. Preserve conversation id, run id, source message id, artifact id/version, and timestamps so panels can be reconstructed and deduplicated.
- Artifact previews must not imply that a result is final, persisted, or reproducible unless the payload/store says so. Preserve provenance, missing/stale states, and explicit version identity.

Team mode:

- Team APIs are in `ipcBridge.team`, backed by `/api/teams/*`.
- Team UI lives in `packages/desktop/src/renderer/pages/team/`.
- Team persisted structures are typed in `packages/desktop/src/common/types/team/`.
- The database schema/migrations include `teams`, `mailbox`, and `team_tasks`; runtime orchestration is backend-owned.

Remote agents:

- Remote agent APIs are in `ipcBridge.remoteAgent`, backed by `/api/remote-agents/*`.
- Remote agent configs include protocol, auth, device identity, and `allow_insecure` fields.

Extensions:

- Extension APIs are under `ipcBridge.extensions` and `ipcBridge.hub`.
- Examples in `examples/hello-world-extension/` show contributed assistants, agents, ACP adapters, MCP servers, skills, themes, settings tabs, scripts, and assets.

Cron and channels:

- Scheduled task pages are under `packages/desktop/src/renderer/pages/cron/`.
- Cron persistence/runtime is backend-owned, surfaced through `/api/cron/*` wrappers in `ipcBridge.ts`.
- Channel assistant settings are represented in config keys such as `assistant.lark.*`, `assistant.dingtalk.*`, `assistant.weixin.*`, and `assistant.wecom.*`.

Desktop pet:

- Renderer pet pages live under `packages/desktop/src/renderer/pet/`.
- Preloads are `packages/desktop/src/preload/pet*.ts`.
- Main-process pet management is under `packages/desktop/src/process/pet/`.

## Data And Paths

Important path behavior:

- Electron data path is resolved by `getDataPath()` in `packages/desktop/src/process/utils/utils.ts`.
- On macOS, Electron creates CLI-safe symlinks such as `~/.deepscientist-dev` and `~/.deepscientist-config-dev` to avoid spaces in `Application Support` paths breaking external CLIs.
- Standalone WebUI intentionally defaults to `~/.deepscientist-web-dev` so it does not pre-create or block Electron's symlink targets.
- Legacy JSON/base64 file storage still exists in `packages/desktop/src/process/utils/initStorage.ts` for migration and some local config. New user-facing settings should normally go through backend `/api/settings/client`.
- SQLite schema helpers and legacy migration code under `packages/desktop/src/process/services/database/` are not the full backend database implementation. Treat them as compatibility/migration support unless the code path proves otherwise.
- Conversation workspaces contain user files. Renderer code should pass `path` plus `workspace` through typed bridges; it must not use Node filesystem APIs or trust message text as an unrestricted absolute path.
- Preview tabs persist only bounded text content in browser storage. Large binary/base64, Office, PDF, Science structured workspaces, secrets, and missing-file payloads must not be serialized into localStorage.
- Local Lark/project-agent state lives below the app data directory, not inside source folders. Schema changes need backward-compatible parsing or an explicit migration and tests using temporary directories.

## Security And External Side Effects

- Never log, render, persist, commit, or include in screenshots API keys, passwords, authorization headers, JWTs, Lark tokens/profile secrets, cookies, signed URLs, or complete external error payloads that may contain them. Redact secret-like message content before diagnostics.
- Treat Markdown and agent-produced file/URL references as untrusted input. Validate scheme, decode failures, path ownership, MIME/extension assumptions, response size, redirects, and missing files at the appropriate bridge/helper boundary.
- Do not weaken Electron `contextIsolation`, preload exposure, navigation guards, webview partitioning, remote WebUI binding/auth, or CSP to make preview behavior easier. Expose the smallest typed capability.
- External URL previews and Office/PDF viewers must not silently bypass origin/navigation controls. Local file previews should not fall back to opening an arbitrary URL when resolution fails.
- Long-lived listeners, timers, subscriptions, WebSockets, CLI children, and Electron/webview handlers need idempotent cleanup on unmount, conversation change, logout, or app shutdown.
- Live Lark/Feishu, provider, remote-agent, channel, cron, and filesystem writes must be attributable and safe under retries. Do not run them as routine validation.
- Use isolated dev data for test instances. Never point automated tests, migrations, cleanup scripts, or destructive diagnostics at the user's default app data or active research workspace.

## Development Commands

Requirements:

- Node.js `>=22 <25` for this project. The app can fail in surprising ways on Node 25+ even if dependencies install.
- Bun is the package manager/runtime.
- Python 3.11+ is needed for native module compilation.
- A working `resources/bundled-deepscientist-core/<platform>-<arch>` bundle is needed for Electron/WebUI startup unless you set `DEEPSCIENTIST_CORE_BIN` to a valid backend binary.

Common commands:

```bash
bun install
bun start                 # Electron dev app
bun run start:multi       # second isolated Electron dev instance
bun run webui             # standalone WebUI, builds first unless skipped
bun run webui -- --no-build --no-open
bun run package           # build main/preload/renderer to out/
bun run resetpass         # reset WebUI/admin password
```

For an isolated second development instance, run from that worktree and use the managed multi-instance mode:

```bash
DEEPSCIENTIST_MULTI_INSTANCE=1 bun run start:multi
```

When two development checkouts are running, expect ports to shift. The first free Vite renderer port is commonly `5173`, CDP starts at `9230`, and `start:multi` uses isolated dev data such as `~/.deepscientist-dev-2`. Inspect the process cwd before stopping a port or service; do not terminate a sibling checkout by port number alone.

Build/package commands:

```bash
bun run dist
bun run dist:all-tools
bun run dist:mac
bun run dist:win
bun run dist:linux
node scripts/build-with-builder.js auto --pack-only --skip-native
```

### Desktop Build Profiles

For a current-source Linux x64 full-offline `.deb` from a macOS maintainer machine, use the single release entry:

```bash
bun run dist:linux:full-offline -- --approve-alphaschema-redistribution
```

`scripts/build-linux-full-offline-one-shot.js` owns source synchronization into the `linux-build` Colima profile, resumable toolchain verification, a network-isolated `linux-unpacked` build, resumable FPM compression, exact-package installation in the no-system-Xvfb/no-network image, atomic publication to `output/linux`, updater metadata, and `full-offline-build-report.json`. Do not replace it with a hand-maintained sequence of guest commands. The approval switch is not a convenience default: pass it only when the release owner has approved redistribution of the pinned AlphaSchema snapshot. The one-shot builder deliberately preserves the last verified package until the new package passes smoke and refuses publication if the host source changes during the build. If the Colima VM itself exits during a native build, it may restart it at most twice, revalidate the unchanged source fingerprint, resynchronize that exact source, and resume from persistent caches; ordinary guest build failures must still stop immediately.

On Apple Silicon, the `linux-build` profile is x86_64 QEMU/TCG emulation rather than native virtualization. The one-shot entry starts a stopped profile with a conservative 2-vCPU/10-GiB envelope and limits compression plus uv preparation concurrency. Do not raise that default merely to shorten a build: prolonged high-concurrency TCG work can trigger macOS thermal emergency sleep and terminate the host session. Prefer a native x86_64 Linux builder for frequent releases.

For an explicitly supervised release build, `--vm-cpus <count|all>` and `--vm-memory <GiB>` opt into a larger Colima envelope. The one-shot builder must resize a running profile only when either override is present, retain the persistent build volume, and make the Linux guest's `make`, xz, and bounded uv worker counts follow the CPUs actually visible inside the guest. For example, `bun run dist:linux:full-offline -- --approve-alphaschema-redistribution --vm-cpus all --vm-memory 32` uses every host core while leaving memory for macOS. This is an owner-controlled high-load path, not a new default.

The conservative Apple Silicon path uses xz preset 1 with two threads for the multi-gigabyte Debian payload; an explicit VM CPU override scales that thread count to the guest CPU count. This is a deliberate TCG build-time/size tradeoff. The Linux AlphaSchema launcher must expose a package-relative `libgomp.so.1` alias from the Science Python wheel directory. A system `libgomp`, system Xvfb, or runtime package installation is not an acceptable full-offline dependency.

`DEEPSCIENTIST_BUILD_PROFILE` is the single distribution profile selector. Accepted values are `standard`, `offline-core`, `offline-science`, `collaboration-ready`, and `full-offline`; invalid names stop the build. `full-offline` requires the complete local tool contract: managed Core Codex and Claude Code plus packaged OpenCode, portable Git, `lark-cli`, browser assets, document tools, Lean, a scientific Python runtime, a separate biomedical Python runtime, and a separately prepared Origene runtime. Linux `full-offline` additionally requires the bundled portable virtual-display runtime.

The CLI shortcut `--all-tools` selects `full-offline`; `--profile <name>` and `--build-profile=<name>` select another profile. Build-profile arguments are consumed by `build-with-builder.js` and must never leak into electron-builder arguments.

`bun run dist:all-tools` is the current-host shortcut. Append native electron-builder target arguments after `--` when needed, for example `bun run dist:all-tools -- --mac --arm64`; still provide the trusted platform toolchain source and its SHA-256.

For a local build, provide one trusted platform pack in addition to selecting the profile:

```bash
DEEPSCIENTIST_BUILD_PROFILE=full-offline \
DEEPSCIENTIST_BUNDLED_TOOLS_SOURCE=/trusted/toolchains/darwin-arm64.tar.gz \
DEEPSCIENTIST_BUNDLED_TOOLS_SHA256=<64-hex> \
bun run build-mac:arm64
```

On Apple Silicon, maintainers can assemble that pack from the reviewed native inputs with
`bun run toolchain:prepare:full-offline`. The assembler writes
`~/DeepScientist-toolchains/full-offline/full-offline-darwin-arm64.tar.gz` and an adjacent JSON file containing the
archive SHA-256. It supports `--resume true` after an interrupted download/install, but it still re-hashes and verifies
the complete runtime before publishing the archive. This is a release-engineering utility, not an end-user first-run
installer; it may use the network while creating the immutable pack, whereas consuming the resulting pack with
`DEEPSCIENTIST_BUILD_OFFLINE=1` must not.

In GitHub Actions, repository administrators own `DEEPSCIENTIST_BUNDLED_TOOLS_BASE_URL` and `DEEPSCIENTIST_BUNDLED_TOOLS_SHA256S`; once those immutable source settings exist, a manual builder selects only `build_profile=full-offline`. Each archive is resolved as `<base-url>/<profile>/<runtimeKey>.tar.gz`. Never expose the source URL or hash as an untrusted workflow input, and never put long-lived credentials in a URL.

Build-profile rules:

- Codex and Claude Code are verified `managed-resources` inside the pinned DeepScientist Core bundle. OpenCode is a separate `bundled-tools` resource. Do not duplicate Codex/Claude in the toolchain archive or treat a manifest declaration as evidence that Core contains them.
- `standard` needs no separate toolchain archive. `offline-core` adds portable Git; `offline-science` adds Git, browser/document tools, Lean, scientific and biomedical runtimes, and Origene; `collaboration-ready` adds Git and `lark-cli`; `full-offline` is their union plus OpenCode and, on Linux, the portable virtual display.
- A Linux `full-offline` toolchain must obtain `virtual-display` from the reviewed Ubuntu 20.04 baseline root supplied through `DEEPSCIENTIST_TOOLCHAIN_VIRTUAL_DISPLAY_ROOT`. It must package Xvfb, xauth, xkbcomp, their fixed non-system shared-library closure, XKB data, fallback fonts, and the complete reviewed license set. The assembler must reject package-version drift, library-inventory drift, missing notices, non-ELF payloads, and requirements above `GLIBC_2.30`; do not replace these checks with an inventory label. Resume mode must revalidate the actual executables, launchers, libraries, inventories, and notices before reusing this cache. `virtual-display/bin/Xvfb` is the relocatable launcher, `Xvfb.real` is the reviewed ELF, and the launcher must load `virtual-display/lib/libXfont2.so.2` without a host `LD_LIBRARY_PATH` or system `libXfont2`; package smoke must prove the mapped path through `/proc/<pid>/maps`, not merely match an `LD_DEBUG` search attempt. Never satisfy this profile with host `/usr/bin/Xvfb`, `xvfb-run`, or a runtime `apt install`. The installed `.deb` exposes `/usr/bin/deepscientist-web`; package smoke must invoke that public symlink without overriding the application path. It listens on loopback by default; add `--remote` only when the deployment has an intentional network-access boundary.
- Xvfb is not a credential store. A license-enforced headless Linux deployment also needs a stable non-root account and persistent `HOME`, an active user D-Bus session, and an unlocked Secret Service or KWallet backend. Keep rejecting Chromium `basic_text`; do not put keyring passwords, device private keys, license codes, or encryption keys in packages, service units, command-line arguments, or environment variables. Exit status `78` proves only that a pristine locked artifact reached the activation gate, not that its WebUI rendered or is deployable without those prerequisites.
- Finance Skills and the TypeScript Financial Mode ship with the app and do not need a second `finance` runtime. Live quotes, paid datasets, remote searches, and provider accounts are still online services. Mathematics Skills use the isolated Lean pack and scientific Python/SymPy; Mathlib is not part of the current pack contract. Biology/target-discovery Skills use separate scientific, biomedical, and prepared Origene runtimes.
- Never merge the Python environments or put their `bin` directories on the shared PATH. Science, biomedical, and Origene have incompatible Python/native dependency contracts. A prepared Origene pack uses `DEEPSCIENTIST_ORIGENE_PREPARED_ROOT`; first use may copy it to user cache but must not resolve or download dependencies.
- Scientific commands must use `DEEPSCIENTIST_SCIENCE_PYTHON` when it is present. Bio Tools are launched with `DEEPSCIENTIST_BIO_TOOLS_PYTHON` and `DEEPSCIENTIST_BIO_TOOLS_SERVER_ROOT`; never replace either prepared interpreter with a host `python3` default or install packages into a packaged environment at runtime.
- Every non-Core resource needs a pinned version/license reference, deterministic resource SHA-256, and at least one executable probe. The build verifier rejects profile/runtime mismatches, traversal, escaping symlinks, missing resources, hash drift, wrong probe types, invalid JSON probes, and non-executable Unix probes; it verifies the source, staging copy, and final `afterPack` output. A probe validates packaged layout, not actual tool startup, so each native runner still needs version/startup smoke tests.
- A hard-offline package build must set `DEEPSCIENTIST_BUILD_OFFLINE=1` and use only local, verified inputs. Set `DEEPSCIENTIST_HUB_SOURCE` to a complete local Hub snapshot when the normal source is unavailable. `DEEPSCIENTIST_ELECTRON_DIST` may point to the installed Electron `dist` directory; otherwise the builder resolves that directory from the local Electron package and must fail instead of downloading it.
- `build-with-builder.js` gives only the `electron-vite` child process an 8192 MB default old-space limit and preserves an explicit caller limit. Keep repository `out/` as a real directory because it is also the source of `app.asar` entries. On low-space builders, move only Electron Builder's distributable output with `--config.directories.output=<path>`; never replace the complete `out/` directory with a symlink. A large Linux `.deb` build also needs `TMPDIR` on a filesystem that can hold at least one additional unpacked application copy. Hard-offline Debian packaging must use a locally verified complete FPM bundle through `CUSTOM_FPM_PATH`, set `NO_UPDATE_NOTIFIER=1` and `ELECTRON_DOWNLOAD_CACHE_MODE=1`, and run with an empty network namespace. `XZ_DEFAULTS=-T0` enables native xz threads without being overwritten by Electron Builder's compression-level `XZ_OPT`.
- After packaging, run `scripts/smoke-packaged-full-offline.sh <path-to-DeepScientist.app>` on macOS or `scripts/smoke-packaged-full-offline-linux.sh <path-to-extracted-or-installed-app>` on Linux under a network-denied OS sandbox. The Linux smoke must run with no system Xvfb/xvfb-run available, prove that the packaged Chromium renderer loads a local page on the bundled X11 display, and start the packaged Electron WebUI through the bundled launcher. An activated or intentionally unlocked test artifact must answer its local HTTP endpoint; a pristine locked release must instead reach the dedicated activation-gate exit status, clean its Xvfb lock, and never have license enforcement disabled merely to make the smoke pass. Both smokes must execute tools from the final application resources, including Codex, Claude Code, OpenCode, Git, Lark CLI, browser rendering, Lean, Pandoc, scientific and biomedical Python, Bio Tools, and Origene; testing the source archive alone is insufficient.
- Build and test archives on their native OS and architecture. Do not reuse Python environments, browser downloads, native CLIs, or Electron native modules across Darwin/Windows/Linux or x64/ARM64.
- `full-offline` means no network is required for installation, first-launch dependency setup, or declared local tools. It does not bundle credentials, login sessions, cloud model weights/inference, Feishu/Lark services, online MCPs, live finance feeds, or remote literature/biomedical data.

Expert overrides remain available through `DEEPSCIENTIST_BUNDLE_*` flags and use strict boolean parsing (`1/0`, `true/false`, `yes/no`, or `on/off`). The strict `full-offline` profile rejects every disabling override; choose another profile for a deliberately smaller artifact. These capability flags define verification requirements; they do not necessarily strip every transitive file from Core.

`DEEPSCIENTIST_BUILD_LICENSE_ENFORCEMENT` remains an independent immutable artifact property. It defaults to enabled; `0` creates an internal desktop artifact that does not open the activation flow. Never publish such an unlocked artifact to production or auto-update channels. Changing environment variables after installation cannot alter a compiled artifact, and the standalone WebUI has a separate security boundary.

The profile, capability overrides, and license flag are part of Vite and resource cache fingerprints. Do not bypass a mismatch with `--skip-vite`. See [docs/guides/build-desktop-installers.md](docs/guides/build-desktop-installers.md) and the checked schema-v1 example at [docs/specs/bundled-tools-manifest.schema-v1.example.json](docs/specs/bundled-tools-manifest.schema-v1.example.json).

Quality commands:

```bash
bun run lint
bun run lint:fix
bun run format
bun run format:check
bunx tsc --noEmit
bun run test
bun run test:coverage
bun run test:integration
bun run test:contract
bun run playwright:check
bun run test:e2e
```

When changing i18n:

```bash
bun run i18n:types
node scripts/check-i18n.js
```

Before pushing, use `just push` rather than raw `git push`; it runs the project checks before pushing.

Mobile checks run from the separate package:

```bash
cd mobile
bun run ts:check
bun run lint
bun run test
```

## Testing Guidance

Vitest 4 is configured in [vitest.config.ts](vitest.config.ts):

- Node tests: `tests/unit/**/*.test.ts`, `tests/integration/**/*.test.ts`, `tests/regression/**/*.test.ts`.
- DOM tests: `tests/unit/**/*.dom.test.ts(x)` under jsdom.
- Coverage includes `packages/desktop/src/**/*.{ts,tsx}` and `packages/**/src/**/*.{ts,tsx}` by default, with explicit exclusions for entrypoints, declarations, static assets, types, and JSON.

Playwright E2E is configured in [playwright.config.ts](playwright.config.ts):

- Test dir: `tests/e2e`
- Workers: `1` because Electron tests share an app instance.
- Use targeted E2E commands when possible, especially for team mode.

Write tests around observable behavior and failure paths. For new logic, separate pure logic from IO so it can be tested without launching Electron or `deepscientist-core`.

Testing selection:

- Mapper, parser, config migration, and startup-classification changes: targeted Vitest unit tests.
- Renderer layout/state changes: DOM tests when selectors and state transitions matter; avoid E2E for pure styling.
- Electron startup, backend bridge, WebUI proxy, team/conversation flows: targeted Playwright E2E.
- DeepScientist Core bundle availability: run the resource verifier above and a `/health` smoke using the actual binary.
- i18n-visible renderer changes: regenerate i18n types and run `node scripts/check-i18n.js`.

Minimum verification by change type:

| Change                                                             | Minimum focused verification                                                                                     |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------- |
| Documentation only                                                 | Format/check the changed Markdown, verify referenced paths/commands, inspect the final diff                      |
| Pure parser, mapper, or helper                                     | Targeted Vitest with an invalid/failure case, focused lint, `bunx tsc --noEmit`                                  |
| React component, hook, Preview, or Workspace state                 | Matching `*.dom.test.tsx`, focused lint/typecheck; Playwright only for a real user workflow or responsive layout |
| Preload, process bridge, Web Host, backend startup, or packaging   | Adapter/bridge tests, desktop and WebUI capability checks, `bun run package` when bundling changed               |
| Config key, migration, persisted tab/report record, or local store | Fresh-state and old-fixture/restart coverage, malformed-data recovery, typecheck                                 |
| Science/Medical structured payload                                 | Schema/parser tests plus message reconciliation and specialized Preview regression                               |
| Lark automation or project agent                                   | Mock CLI/process tests, malformed payload and cleanup coverage; no live write without explicit authorization     |
| Mobile                                                             | Run the mobile package's typecheck/lint/Jest commands; root Vitest is not sufficient                             |

Testing quality rules:

- Assert observable behavior and stable contracts, not private function calls or translated copy alone.
- Every new behavior group needs at least one degraded case: missing file, rejected bridge call, malformed payload, duplicate event, stale id, empty data, or unavailable capability as appropriate.
- Use temporary directories, isolated stores, and deterministic ids/clocks. Never use the default app data directory in tests.
- Prefer condition-based waits and existing E2E helpers over fixed sleeps. Electron E2E uses one worker because instances share ports and runtime resources.
- If a required check cannot run because a backend binary, platform capability, credential, or service is unavailable, report it explicitly; a skip is not a pass.

## Code Conventions

File and directory structure:

- New modules must keep each directory to at most 10 direct children and split by responsibility before adding the 11th item. Local maintenance, including focused additions, in existing directories may follow their established layout even when it exceeds that limit; do not move unrelated files just to meet the count. Schedule broader structural cleanup separately.
- Do not create single-file directories.
- Use the `architecture` skill before creating files/modules or changing placement.
- Renderer component/feature directories use PascalCase when they represent a specific component/module. Categorical directories (`components`, `hooks`, `utils`, `services`, `pages`) are lowercase.
- Non-renderer directories are lowercase.
- Platform directories such as `acp`, `codex`, `gemini`, `nanobot`, and `openclaw` are lowercase everywhere.

Naming:

- React components/classes: PascalCase.
- Hooks: camelCase with `use` prefix.
- Utilities/helpers: camelCase.
- Types/constants/config files: camelCase.
- Constants inside files: UPPER_SNAKE_CASE.
- Unused parameters: prefix with `_`.
- Prefer `type` over `interface` unless extending/merging or matching existing interface-heavy code.

TypeScript:

- Strict mode is expected.
- Avoid `any`; use `unknown`, typed DTOs, or local narrowing.
- Use aliases such as `@/`, `@common/`, `@renderer/`, `@process/`, and `@worker/`.
- Respect dependency direction: renderer may depend on common contracts/facades, preload may depend on common plus Electron IPC, process may depend on common, and common must not import renderer/process runtime code.
- Validate untrusted HTTP, CLI, WebSocket, persisted JSON, extension, message, and artifact payloads at their boundary. A TypeScript cast is not runtime validation.
- Config changes must keep `configKeys.ts`, storage compatibility types, defaults/migrations, renderer usage, all configured locales, and tests aligned. Do not create a parallel localStorage setting for convenience.
- Long-lived effects need stable dependencies and idempotent disposers. Streaming messages, workspace switches, preview tabs, and event listeners are especially sensitive to duplicate effects.
- Keep comments in English for code comments. Existing Chinese comments may remain; avoid adding new mixed-language implementation comments unless needed for nearby consistency.

Formatting:

- Single quotes.
- Trailing commas in multi-line arrays/objects.
- Single-element arrays that fit on one line stay inline.
- Use `oxfmt`/`oxlint`; do not manually fight the formatter.
- Do not hand-edit generated i18n declarations, build output, lockfile sections, packaged manifests, or bundled backend resources when a project script owns them.

## UI And Styling Rules

- Use `@arco-design/web-react` components for interactive UI. Do not use raw `<button>`, `<input>`, `<select>`, `<textarea>`, or custom interactive primitives unless there is a specific low-level reason.
- Use `@icon-park/react` for icons. The Vite IconPark plugin wraps icon imports through `IconParkHOC`.
- Prefer UnoCSS utility classes for simple styles.
- Markdown is rendered inside `ShadowView`; document-level UnoCSS and component-library descendant selectors may not cross that boundary. Layout-critical Markdown controls need explicit Shadow DOM CSS, including `min-width: 0`, wrapping, overflow, and focus behavior.
- Prefer CSS Modules for new complex reusable components. Existing feature-scoped stylesheets such as `PreviewPanel/preview.css` and `Workspace/workspace.css` may be extended narrowly; do not migrate unrelated styles during a feature change.
- Do not hardcode colors in normal component styles. Use semantic Uno tokens from [uno.config.ts](uno.config.ts) or CSS variables. Theme preset files are the exception because they define tokens.
- Global CSS belongs only under `packages/desktop/src/renderer/styles/`.
- Component-specific Arco overrides should normally live in CSS Modules using `:global(...)`. Truly shared Arco theme overrides belong in the existing renderer style layer; do not create ad hoc global override files.
- All user-facing text must use i18n. Read `packages/desktop/src/common/config/i18n-config.json` before changing locale files and add keys to every supported language.
- Shared renderer views must remain coherent in Electron and standalone WebUI. Guard native file/system actions and present an explicit fallback when a bridge is unavailable.
- Conversation, Preview, and Files are an operational workbench, not a marketing surface. Favor compact rows, predictable hierarchy, stable panel dimensions, restrained borders, useful empty/error states, and scan-friendly typography over decorative cards or oversized headings.
- Reuse the existing Preview tabs, toolbar, viewers, fullscreen/half-panel controls, Workspace tree, and Science Artifact Workspace. A VSCode-like refinement should come from clearer tab identity, density, selection, path context, and keyboard behavior, not by cloning an activity bar, terminal, command palette, or docking framework.
- Preserve layout ownership in `ChatLayout`: chat and Preview share the center region while Files remains the right workspace sider. Any width, collapse, fullscreen, or responsive change must be checked with Preview closed/open, Files expanded/collapsed, PDF, and Science workspace states.
- Do not put page sections inside decorative nested cards. Keep card use for repeated artifacts, modals, and genuinely framed tools. Avoid large radius changes that make dense workbench surfaces feel like floating marketing panels.
- Text and controls must not overlap at narrow widths. Use fixed toolbar/tab heights, bounded labels with ellipsis/tooltips, and explicit min/max widths rather than viewport-scaled fonts.
- Primary workbench actions such as Open report, Files, and Export must use stable, non-shrinking button dimensions in every supported locale. When Preview opens or the viewport narrows, let the content/title region wrap, truncate, or yield width before compressing the action group.
- Icon-only controls need accessible names/tooltips. Preserve keyboard activation and focus visibility for file rows, tabs, close controls, menus, and preview actions.

## Local Skills

Use these repository skills when their triggers apply:

- `architecture`: creating files/modules, placing code, changing architecture, adding services/bridges/agents/workers.
- `i18n`: adding or changing user-facing text or locale modules.
- `testing`: writing tests, changing tested logic, or before claiming feature work is complete.
- `bump-version`: release version bump flow only.

Skill files are under `.claude/skills/`. If a skill references additional files, read them before acting.

## Common Pitfalls

- Do not edit a similarly named sibling checkout. Confirm the repository root before every write-oriented task and again before reporting changed files.
- Do not add business logic to `packages/web-host/src/static-server.ts`; it is a proxy/static server.
- Do not bypass `ipcBridge.ts` from renderer code for backend business calls unless the local pattern already does so for a narrow reason.
- Do not import `@process/*` into renderer code.
- Do not call `lark-cli`, inspect Lark profile state, or perform external project writes from React. Use the typed desktop bridge and mock it in tests.
- Do not create separate local-file parsers in Markdown, message output cards, Files, and Science views. Share canonical resolution rules while allowing each surface to own presentation.
- Do not auto-open files on every streaming render, repeatedly recreate the same tab, replace a dirty tab, or let secondary artifacts steal focus from a selected report.
- Do not automatically navigate arbitrary external URLs merely because local output files are auto-previewed.
- Do not treat `science_report`, Science Artifact Workspace, or Medical Evidence panels as generic Markdown/file previews; preserve their structured identity and provenance.
- Do not assume `docs/architecture/overview.md` exists in this clone; inspect source and current docs together.
- Do not share Electron and standalone WebUI default data dirs unless the user explicitly asks for it.
- Do not overwrite `resources/bundled-deepscientist-core` casually; packaging and local WebUI depend on the platform-specific binary layout.
- Do not commit `resources/bundled-deepscientist-core`; it is a local/prepared artifact and is ignored on purpose.
- Do not fix an DeepScientist Core missing-resource error by hiding the installation integrity dialog. Fix the bundle, resolver, or packaging path.
- Do not log API keys, auth tokens, JWTs, or provider secrets.
- Do not edit or commit `screenlog.*`, `out/`, `output/`, coverage, Playwright results, temporary databases, or local screenshots as source fixes.
- Do not treat disabled agents as available in picker UI. Use the managed agents endpoint only for settings.
- Do not run broad destructive cleanup commands in user data dirs. The app stores real conversations, providers, credentials, cron jobs, and team state there.
- Do not add AI signatures such as `Co-Authored-By` or generated-by footers to commits or PRs.

## Definition Of Done

- Re-run `git rev-parse --show-toplevel` and `git status --short`; confirm all changed paths belong to this repository and the requested scope.
- Inspect the final diff and preserve pre-existing user edits. Verify no unrelated formatting, generated artifacts, secrets, local absolute paths, test data, or runtime logs entered the change.
- Run the smallest complete verification set from the matrix above, including at least one relevant failure/degraded path for behavior changes.
- Confirm Electron/WebUI/mobile implications instead of assuming a shared type or renderer automatically gives parity.
- For conversation workbench changes, verify link/path resolution, deduplication, streaming completion, active-tab behavior, dirty-tab protection, Files default state, responsive layout, and specialized Science/PDF previews as applicable.
- For persistence/config/bridge changes, verify migration or backward compatibility, authorization, retry/idempotency, listener/process cleanup, and actionable errors.
- State which tests passed, which were skipped, and what could not run. Do not commit or push unless the user requested it.

## Useful Inspection Commands

```bash
git rev-parse --show-toplevel
git status --short
rg --files -g 'AGENTS.md' -g '!node_modules' -g '!out' -g '!dist'
rg --files | sed -n '1,200p'
rg -n "ipcBridge\\.|/api/agents|/api/teams|/api/providers|wsEmitter" packages/desktop/src
rg -n "APP_FILES_MARKER|MessageOutputFiles|LocalFileLink|openPreview|replace: true" packages/desktop/src/renderer packages/desktop/src/common
rg -n "science_report|SciencePanelData|medical_evidence|larkProjectAgent" packages/desktop/src tests
rg -n "CREATE TABLE|ALTER TABLE|CURRENT_DB_VERSION" packages/desktop/src/process/services/database
rg -n "model|provider|agent_type|backend" packages/desktop/src/common packages/desktop/src/renderer
curl -fsS http://127.0.0.1:25809/api/auth/status
curl -fsS 'http://127.0.0.1:25809/api/agents?include_disabled=true'
```

When the WebUI was launched through this workspace during setup, it used:

```bash
DEEPSCIENTIST_DATA_DIR="$HOME/.deepscientist-web-dev" DEEPSCIENTIST_OPEN_BROWSER=0 DEEPSCIENTIST_NO_BUILD=1 bun run webui -- --no-open --no-build
```

The launchd label used for that local service was `com.codex.deepscientist.webui`; remove it with `launchctl remove com.codex.deepscientist.webui` if you need to stop that background instance.
