---
trigger: always_on
description: User preference for the default subagent model and reasoning strength.
---
When delegating work and the user has not chosen another model, use the hydrogen-default subagent. Its local model route is Gemini 4 Hydrogen with medium reasoning.

For follow-up work on the same delegated task, continue with the existing hydrogen-default worker by calling send_message with that worker's conversation ID as Recipient. An idle worker can be resumed this way and retains its conversation, allowing the upstream to reuse its existing prompt prefix. Read the worker's latest result before sending the next task. Do not invoke a new worker for each follow-up, tool step, retry, or progress check; creating a new conversation makes the first request cold again. Keep concurrent work coordinated with the worker's current state.

When no suitable worker exists, or a separate task needs its own context, invoke a new worker with TypeName set to hydrogen-default. Omit Model so the subagent uses its own configured model; do not replace it with inherit, flash, or the parent's model. Keep unrelated tasks in separate workers. Apply this default to nested delegated work. Honor the user's explicit model or reasoning-strength choice for a particular task. This preference does not require delegation when a task can be completed directly.

When the user explicitly requests GPT-6.1 Sol, gpt-6.1-sol, 6.1sol, or 6.1 sol as a subagent, delegate the task to the installed Codex CLI through run_command. This is an actual separate GPT-6.1 Sol worker with file and shell tools. The native invoke_subagent Model parameter only accepts AGY's built-in model tiers; do not pass an OpenAI model ID there, substitute hydrogen-default, or merely claim the requested model has been selected.

Start the worker in the delegated task's actual workspace using the following command. Supply the bounded task, constraints, required output, and relevant context through a single-quoted heredoc on stdin. Read-only is suitable for inspection, research, and review. For an explicitly authorized implementation task, replace read-only with workspace-write. Respect all applicable project instructions and the user's permission boundary.

```sh
/home/lzh/.local/bin/codex exec --model gpt-6.1-sol -c 'model_provider="my_codex"' -c 'model_reasoning_effort="medium"' -c 'approval_policy="never"' -c 'mcp_servers.codex_native_thread.enabled=false' --sandbox read-only --skip-git-repo-check --json --cd /absolute/task/workspace - <<'CODEX_TASK'
The actual delegated task, constraints, context, and requested result go here.
CODEX_TASK
```

Use the requested reasoning strength when the user specifies one; otherwise use medium for this worker. Forward the task's authorization and restrictions to the worker. Do not enable unrestricted access or communicate with unrelated existing Codex tasks. This command uses the already configured OpenAI provider and credentials; no API key belongs in the command or task prompt.

Keep the thread ID from the thread.started JSON event. Read the worker's item events and final agent_message, wait for turn.completed and a successful command exit, and relay the actual result and any failure to the parent task. If run_command returns a background command ID, poll that same command using the native command status tool until it finishes; do not launch another worker for a progress check. A turn.failed, error event, or nonzero command exit is a failure, not a completed delegation.

For follow-up work, resume only the Codex thread created for this delegated task, in the same workspace, using the following command with its exact thread ID and the follow-up task on stdin. Keep --json to capture the continued worker's actual results. Do not use --last or another task's thread ID.

```sh
/home/lzh/.local/bin/codex exec resume --model gpt-6.1-sol -c 'model_provider="my_codex"' -c 'model_reasoning_effort="medium"' -c 'approval_policy="never"' -c 'mcp_servers.codex_native_thread.enabled=false' -c 'sandbox_mode="read-only"' --skip-git-repo-check --json EXACT_THREAD_ID - <<'CODEX_TASK'
The follow-up task for that same worker goes here.
CODEX_TASK
```

These explicit GPT-6.1 Sol requests take precedence over the default Hydrogen delegation above. When no other model is requested, keep using hydrogen-default with medium reasoning.

