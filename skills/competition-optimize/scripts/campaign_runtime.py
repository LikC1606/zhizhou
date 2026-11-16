#!/usr/bin/env python3
"""Linux process and durability primitives for autonomous_campaign.py.

The worker, rather than the manager, owns a turn. Its lock is inherited by Codex
so a manager/worker crash cannot make a surviving invocation look unstarted.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import uuid
from typing import Any, BinaryIO


POLL_SECONDS = 0.2
HEARTBEAT_SECONDS = 2.0
AGENT_TOKEN = "COMPETITION_AGENT_TURN_TOKEN"
WORKER_TOKEN = "COMPETITION_AGENT_WORKER_TOKEN"


class CampaignError(Exception):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def atomic_json(path: pathlib.Path, value: Any) -> None:
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    atomic_bytes(path, raw)


def atomic_bytes(path: pathlib.Path, raw: bytes) -> None:
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temporary.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_json(path: pathlib.Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def process_info(pid: int) -> dict[str, Any] | None:
    try:
        fields = pathlib.Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        return {"pid": pid, "start_time": fields[19], "group": int(fields[2])}
    except (OSError, IndexError, ValueError):
        return None


def process_alive(identity: dict[str, Any] | None) -> bool:
    if not identity:
        return False
    current = process_info(identity["pid"])
    return current is not None and current["start_time"] == identity.get("start_time")


def exclusive_lock(path: pathlib.Path) -> BinaryIO:
    stream = path.open("a+b")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        stream.close()
        raise
    return stream


def lock_busy(path: pathlib.Path) -> bool:
    try:
        stream = exclusive_lock(path)
    except BlockingIOError:
        return True
    stream.close()
    return False


def resource_paths(state: dict[str, Any]) -> list[pathlib.Path]:
    root = pathlib.Path.home() / ".cache" / "competition-agent" / "locks"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return [root / (hashlib.sha256(f"{kind}:{state[kind]}".encode()).hexdigest() + ".lock")
            for kind in ("workspace", "archive")]


def acquire_resources(campaign: pathlib.Path, state: dict[str, Any]) -> list[BinaryIO] | None:
    """None means this campaign's surviving worker still owns the resources."""
    acquired: list[BinaryIO] = []
    try:
        for path in resource_paths(state):
            try:
                stream = exclusive_lock(path)
            except BlockingIOError:
                try:
                    owner = read_json(path)
                except (OSError, ValueError):
                    owner = {}
                if (owner.get("campaign_id") == state["campaign_id"] and state["inflight"]):
                    return None
                raise CampaignError(f"Workspace/archive is already owned by another runner: {owner.get('campaign', path)}")
            acquired.append(stream)
            # A dead manager may have left a clean-environment child with no lock FD.
            # Its in-flight intent still reserves the resource until reconciliation.
            stream.seek(0)
            try:
                previous = json.loads(stream.read())
            except (ValueError, UnicodeError):
                previous = {}
            if previous.get("campaign_id") not in (None, state["campaign_id"]):
                previous_state = pathlib.Path(previous.get("campaign", "")) / "state.json"
                if previous_state.is_file():
                    other = read_json(previous_state)
                    if other.get("campaign_id") == previous["campaign_id"] and other.get("inflight"):
                        raise CampaignError(
                            f"Workspace/archive has an unreconciled in-flight owner: {previous['campaign']}")
        owner = {"campaign": str(campaign), "campaign_id": state["campaign_id"],
                 "manager": process_info(os.getpid()), "acquired_at": utc_now()}
        for stream in acquired:
            stream.seek(0)
            stream.truncate()
            stream.write((json.dumps(owner) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        result, acquired = acquired, []
        return result
    finally:
        # Do not LOCK_UN: worker and CLI duplicates share the open file description.
        for stream in acquired:
            stream.close()


def owned_processes(token: str, group: int | None = None,
                    worker: bool = False) -> list[dict[str, Any]]:
    expected = f"{WORKER_TOKEN if worker else AGENT_TOKEN}={token}".encode()
    found = []
    for directory in pathlib.Path("/proc").iterdir():
        if not directory.name.isdecimal() or int(directory.name) == os.getpid():
            continue
        try:
            if directory.stat().st_uid != os.getuid():
                continue
            info = process_info(int(directory.name))
            if info and (group is not None and info["group"] == group or
                         expected in (directory / "environ").read_bytes().split(b"\0")):
                found.append(info)
        except (OSError, ProcessLookupError):
            continue
    return found


def terminate_owned(token: str, group: int | None = None,
                    process: subprocess.Popen | None = None) -> tuple[int, list[dict[str, Any]]]:
    """Stop the whole owned tree, including descendants whose leader already exited."""
    initial = owned_processes(token, group)
    current = initial
    deadline = time.monotonic() + 2.0
    while current:
        action = signal.SIGTERM if time.monotonic() < deadline else signal.SIGKILL
        for identity in current:
            if process_alive(identity):
                try:
                    os.kill(identity["pid"], action)
                except ProcessLookupError:
                    pass
        if process is not None:
            process.poll()
        time.sleep(0.05)
        current = owned_processes(token, group)
        if time.monotonic() > deadline + 3:
            break
    return len(initial), current


def turn_directory(campaign: pathlib.Path, number: int) -> pathlib.Path:
    return campaign / "turns" / f"{number:06d}"


def job_directory(campaign: pathlib.Path, number: int, kind: str = "agent") -> pathlib.Path:
    directory = turn_directory(campaign, number)
    if kind not in {"agent", "completion"}:
        raise CampaignError(f"Unsupported job kind: {kind}")
    return directory / "completion" if kind == "completion" else directory


def boot_id() -> str:
    return pathlib.Path("/proc/sys/kernel/random/boot_id").read_text().strip()


def recorded_group(directory: pathlib.Path, token: str) -> int | None:
    marker = directory / "agent.json"
    if not marker.exists():
        return None
    identity = read_json(marker)
    if identity.get("token") != token:
        raise CampaignError("Agent process marker belongs to a different request")
    if identity.get("boot_id") != boot_id():
        return None
    current = process_info(identity["pid"])
    if current and current["start_time"] != identity["start_time"]:
        return None  # Reused PID/group on the same boot is not owned by this turn.
    group = identity["group"]
    return group if type(group) is int and group > 1 and group != os.getpgrp() else None


def exec_agent(directory: pathlib.Path) -> int:
    """Persist identity before the first instruction of the actual CLI can run."""
    request = read_json(directory / "request.json")
    atomic_json(directory / "agent.json", {"token": request["token"],
                **process_info(os.getpid()), "boot_id": boot_id()})
    try:
        os.execvpe(request["command"][0], request["command"], dict(os.environ))
    except OSError as exc:
        atomic_json(directory / "exec.error.json", {"token": request["token"],
                    "errno": exc.errno, "error": str(exc)})
        return 126


def output_hashes(directory: pathlib.Path) -> dict[str, str | None]:
    return {name: file_hash(directory / name) if (directory / name).exists() else None
            for name in ("events.jsonl", "stderr.log", "message.json")}


def run_worker(campaign: pathlib.Path, number: int, resource_fds: list[int],
               kind: str = "agent") -> int:
    directory = job_directory(campaign, number, kind)
    request = read_json(directory / "request.json")
    token = request["token"]
    try:
        turn_lock = exclusive_lock(directory / "execution.lock")
    except BlockingIOError:
        return 75
    # A duplicate recovery worker can never launch a second agent for this request.
    with turn_lock:
        if (directory / "exit.json").exists():
            if read_json(directory / "exit.json").get("token") != token:
                raise CampaignError("Turn exit marker belongs to a different request")
            return 0
        worker_identity = process_info(os.getpid())
        atomic_json(directory / "worker.json", {"token": token, **worker_identity,
                                                 "started_at": utc_now()})
        started = time.monotonic()
        process = None
        returncode = None
        error = ""
        launch_errno = None
        cleanup_count = 0
        remaining: list[dict[str, Any]] = []
        cancelled = []

        def cancel(signum: int, _frame: Any) -> None:
            cancelled.append(f"Worker received signal {signum}")

        signal.signal(signal.SIGTERM, cancel)
        signal.signal(signal.SIGINT, cancel)
        try:
            if (directory / "launch.intent.json").exists():
                error = "Previous worker lost its exit record; reconcile artifacts before another experiment"
            elif cancelled:
                error = cancelled[0]
            elif ((campaign / "stop.request.json").exists() and
                  read_json(campaign / "stop.request.json").get("immediate")):
                error = "User requested immediate stop before launch"
            elif (request.get("timeout_seconds") is not None and
                  time.time() - request["started_unix"] >= request["timeout_seconds"]):
                error = "Per-turn watchdog expired before launch"
            else:
                # This journal is durable BEFORE Popen, closing the PID-save crash window.
                atomic_json(directory / "launch.intent.json", {"token": token, "at": utc_now()})
                environment = dict(os.environ)
                environment.pop(WORKER_TOKEN, None)
                environment[AGENT_TOKEN] = token
                inherited = tuple([turn_lock.fileno(), *resource_fds])
                with (directory / "prompt.txt").open("rb") as stdin, \
                        (directory / "events.jsonl").open("wb") as stdout, \
                        (directory / "stderr.log").open("wb") as stderr:
                    process = subprocess.Popen([sys.executable, str(pathlib.Path(__file__).resolve()),
                                                str(directory)], cwd=request["workspace"],
                                               stdin=stdin, stdout=stdout, stderr=stderr,
                                               env=environment, start_new_session=True,
                                               pass_fds=inherited)
                    heartbeat_at = 0.0
                    while process.poll() is None:
                        now = time.monotonic()
                        if now >= heartbeat_at:
                            atomic_json(directory / "heartbeat.json", {"token": token,
                                        "worker": worker_identity, "agent": process_info(process.pid),
                                        "at": utc_now(), "elapsed_seconds": now - started})
                            heartbeat_at = now + HEARTBEAT_SECONDS
                        stop_path = campaign / "stop.request.json"
                        stop_now = stop_path.exists() and read_json(stop_path).get("immediate", False)
                        timeout = request.get("timeout_seconds")
                        if cancelled or stop_now or timeout is not None and now - started >= timeout:
                            error = (cancelled[0] if cancelled else "User requested immediate stop" if stop_now
                                     else "Per-turn watchdog expired")
                            break
                        time.sleep(POLL_SECONDS)
                    returncode = process.poll()
                    if returncode is None:
                        cleanup_count, remaining = terminate_owned(token, process.pid, process)
                        returncode = process.wait(timeout=5)
                    else:
                        cleanup_count, remaining = terminate_owned(token, process.pid, process)
                        if cleanup_count:
                            error = "Agent exited with local child processes still running; reconcile the interrupted work"
                    stdout.flush()
                    stderr.flush()
                    os.fsync(stdout.fileno())
                    os.fsync(stderr.fileno())
                    exec_error = directory / "exec.error.json"
                    if exec_error.exists():
                        failure = read_json(exec_error)
                        if failure["token"] != token:
                            raise CampaignError("CLI exec error belongs to a different request")
                        launch_errno, error = failure["errno"], failure["error"]
        except OSError as exc:
            launch_errno = exc.errno
            error = f"Worker launch/output error: {exc}"
        except Exception as exc:
            error = f"Worker error: {type(exc).__name__}: {exc}"
        finally:
            # Also handles a crash in the supervisor code after Popen but before agent.json.
            cleaned, survivors = terminate_owned(token, process.pid if process else None, process)
            cleanup_count += cleaned
            remaining = survivors
            if process is not None:
                returncode = process.poll()
            if remaining:
                error = "Owned local processes could not be terminated"
            cancellation = directory / "cancel.request.json"
            if cancellation.exists():
                request_cancel = read_json(cancellation)
                if request_cancel.get("token") != token:
                    raise CampaignError("Cancellation belongs to a different request")
                # Manager-initiated cancellation can race with the leader's exit.
                # Child cleanup is expected here; retain the actual stop/watchdog
                # reason instead of misreporting it as an accidental child leak.
                error = request_cancel["reason"]
                if remaining:
                    error += "; owned local processes could not be terminated"
            message = directory / "message.json"
            if message.exists():
                with message.open("rb") as stream:
                    os.fsync(stream.fileno())
            atomic_json(directory / "exit.json", {
                "token": token, "returncode": returncode, "error": error,
                "launch_errno": launch_errno, "cleanup_count": cleanup_count,
                "survivors": remaining, "elapsed_seconds": time.monotonic() - started,
                "finished_at": utc_now(), "outputs": output_hashes(directory),
            })
    return 0


if __name__ == "__main__":
    raise SystemExit(exec_agent(pathlib.Path(sys.argv[1])))
