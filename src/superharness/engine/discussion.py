"""Python port of engine/discussion.rb — multi-round discussion engine."""
from __future__ import annotations

import fcntl
import glob
import json
import os
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator

import yaml

from superharness.engine.yaml_helpers import safe_load


def _atomic_write(path: str, content: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    fd, tmp_path = tempfile.mkstemp(prefix=base, suffix=".tmp", dir=dir_)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp_path, path)
        tmp_path = None
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@contextmanager
def _file_lock(path: str, timeout: float = 5.0) -> Iterator[None]:
    lock_path = f"{path}.flock"
    with open(lock_path, "a+") as lock_file:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    sys.exit(f"E_LOCK_TIMEOUT: could not acquire lock on {path} within {timeout}s")
                time.sleep(0.1)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _generate_id() -> str:
    import random

    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"discuss-{ts}-{os.getpid()}-{random.randint(0, 999999999)}"


def _state_file(discussion_dir: str) -> str:
    return os.path.join(discussion_dir, "state.yaml")


def _round_file(discussion_dir: str, round_: int, agent: str) -> str:
    return os.path.join(discussion_dir, f"round-{round_}-{agent}.yaml")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------


def cmd_start(
    discussions_dir: str,
    topic: str,
    participants: list[str],
    max_rounds: int,
    task_id: str | None,
    project: str,
    created_by: str,
) -> int:
    id_ = _generate_id()
    discussion_dir = os.path.join(discussions_dir, id_)
    os.makedirs(discussion_dir, exist_ok=True)

    state = {
        "id": id_,
        "topic": topic,
        "participants": participants,
        "max_rounds": max_rounds,
        "current_round": 1,
        "status": "active",
        "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "created_by": created_by,
        "project": project,
        "task_id": None if not task_id else task_id,
    }

    sf = _state_file(discussion_dir)
    _atomic_write(sf, yaml.dump(state))

    print(
        json.dumps(
            {
                "id": id_,
                "discussion_dir": discussion_dir,
                "status": "active",
                "current_round": 1,
                "participants": participants,
            },
            separators=(", ", ": "),
        )
    )
    return 0


def cmd_submit_round(
    discussion_dir: str,
    round_: int,
    agent: str,
    verdict: str,
    position: str,
    points_file: str | None,
) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    with _file_lock(sf):
        state = safe_load(sf, dict)
        if state.get("status") != "active":
            sys.exit(f"Discussion is not active (status={state.get('status')})")
        if agent not in (state.get("participants") or []):
            sys.exit(f"Agent '{agent}' is not a participant")
        if round_ != state.get("current_round"):
            sys.exit(f"Round {round_} != current round {state.get('current_round')}")

        rf = _round_file(discussion_dir, round_, agent)
        if os.path.exists(rf):
            sys.exit(f"Round {round_} already submitted by {agent}")

        points: list = []
        if points_file and os.path.exists(points_file):
            raw = safe_load(points_file, list)
            if isinstance(raw, list):
                points = raw

        doc = {
            "discussion_id": state.get("id"),
            "round": round_,
            "agent": agent,
            "verdict": verdict,
            "position": position,
            "points": points,
            "submitted_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        _atomic_write(rf, yaml.dump(doc))

    print(json.dumps({"submitted": True, "round": round_, "agent": agent, "verdict": verdict}, separators=(", ", ": ")))
    return 0


def cmd_check_round(discussion_dir: str, round_: int) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    state = safe_load(sf, dict)
    participants = state.get("participants") or []
    done = []
    pending = []
    for agent in participants:
        rf = _round_file(discussion_dir, round_, agent)
        if os.path.exists(rf):
            done.append(agent)
        else:
            pending.append(agent)

    print(
        json.dumps(
            {
                "complete": len(pending) == 0,
                "round": round_,
                "agents_done": done,
                "agents_pending": pending,
            },
            separators=(", ", ": "),
        )
    )
    return 0


def cmd_check_consensus(discussion_dir: str) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    state = safe_load(sf, dict)
    round_ = state.get("current_round", 1)
    participants = state.get("participants") or []

    verdicts: dict[str, str] = {}
    for agent in participants:
        rf = _round_file(discussion_dir, round_, agent)
        if os.path.exists(rf):
            doc = safe_load(rf, dict)
            verdicts[agent] = str(doc.get("verdict", "")).lower()

    all_submitted = len(verdicts) == len(participants)
    consensus = all_submitted and all(v == "agree" for v in verdicts.values())

    print(
        json.dumps(
            {
                "consensus": consensus,
                "round": round_,
                "verdicts": verdicts,
                "all_submitted": all_submitted,
            },
            separators=(", ", ": "),
        )
    )
    return 0


def cmd_advance(discussion_dir: str) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    result = None
    with _file_lock(sf):
        state = safe_load(sf, dict)
        if state.get("status") != "active":
            sys.exit(f"Discussion is not active (status={state.get('status')})")

        round_ = state.get("current_round", 1)
        participants = state.get("participants") or []
        max_rounds = state.get("max_rounds", 3)

        all_done = all(os.path.exists(_round_file(discussion_dir, round_, a)) for a in participants)
        if not all_done:
            sys.exit(f"Round {round_} is not complete yet")

        verdicts: dict[str, str] = {}
        for agent in participants:
            doc = safe_load(_round_file(discussion_dir, round_, agent), dict)
            verdicts[agent] = str(doc.get("verdict", "")).lower()
        consensus = all(v == "agree" for v in verdicts.values())

        if consensus:
            state["status"] = "consensus"
            state["closed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            state["consensus_round"] = round_
            _atomic_write(sf, yaml.dump(state))
            result = {"action": "closed", "reason": "consensus", "round": round_}
        elif round_ >= max_rounds:
            state["status"] = "no_consensus"
            state["closed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
            _atomic_write(sf, yaml.dump(state))
            result = {"action": "closed", "reason": "max_rounds_reached", "round": round_}
        else:
            state["current_round"] = round_ + 1
            _atomic_write(sf, yaml.dump(state))
            result = {"action": "advanced", "next_round": round_ + 1}

    if result is not None:
        print(json.dumps(result, separators=(", ", ": ")))
    return 0


def cmd_status(discussion_dir: str) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    state = safe_load(sf, dict)
    rounds_info = []
    for r in range(1, (state.get("current_round") or 1) + 1):
        round_data: dict = {"round": r, "submissions": []}
        for agent in state.get("participants") or []:
            rf = _round_file(discussion_dir, r, agent)
            if os.path.exists(rf):
                doc = safe_load(rf, dict)
                round_data["submissions"].append(
                    {
                        "agent": agent,
                        "verdict": doc.get("verdict"),
                        "submitted_at": doc.get("submitted_at"),
                    }
                )
        rounds_info.append(round_data)

    output = dict(state)
    output["rounds"] = rounds_info
    print(json.dumps(output, separators=(", ", ": ")))
    return 0


def cmd_list(discussions_dir: str) -> int:
    if not os.path.isdir(discussions_dir):
        print("[]")
        return 0

    discussions = []
    for sf in sorted(glob.glob(os.path.join(discussions_dir, "*/state.yaml"))):
        state = safe_load(sf, dict)
        discussions.append(
            {
                "id": state.get("id"),
                "topic": state.get("topic"),
                "status": state.get("status"),
                "current_round": state.get("current_round"),
                "max_rounds": state.get("max_rounds"),
                "participants": state.get("participants"),
                "dir": os.path.dirname(sf),
            }
        )

    print(json.dumps(discussions, separators=(", ", ": ")))
    return 0


def cmd_close(discussion_dir: str, outcome: str) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    with _file_lock(sf):
        state = safe_load(sf, dict)
        state["status"] = outcome
        state["closed_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        _atomic_write(sf, yaml.dump(state))

    print(json.dumps({"closed": True, "outcome": outcome}, separators=(", ", ": ")))
    return 0


def cmd_round_context(discussion_dir: str, round_: int, agent: str) -> int:
    sf = _state_file(discussion_dir)
    if not os.path.exists(sf):
        sys.exit(f"Discussion not found: {discussion_dir}")

    state = safe_load(sf, dict)
    participants = state.get("participants") or []
    other_agents = [a for a in participants if a != agent]

    context: dict = {
        "discussion_id": state.get("id"),
        "topic": state.get("topic"),
        "round": round_,
        "max_rounds": state.get("max_rounds"),
        "agent": agent,
        "other_agents": other_agents,
        "prior_rounds": [],
    }

    for r in range(1, round_):
        round_data: dict = {"round": r, "positions": []}
        for a in participants:
            rf = _round_file(discussion_dir, r, a)
            if os.path.exists(rf):
                doc = safe_load(rf, dict)
                round_data["positions"].append(doc)
        context["prior_rounds"].append(round_data)

    print(json.dumps(context, separators=(", ", ": ")))
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    import argparse

    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(
            "Usage: discussion <start|submit_round|check_round|check_consensus"
            "|advance|status|list|close|round_context> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = argv[0]
    rest = argv[1:]

    valid = {
        "start", "submit_round", "check_round", "check_consensus",
        "advance", "status", "list", "close", "round_context",
    }
    if cmd not in valid:
        print(
            "Usage: discussion <start|submit_round|check_round|check_consensus"
            "|advance|status|list|close|round_context> [options]",
            file=sys.stderr,
        )
        sys.exit(1)

    if cmd == "start":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussions-dir", dest="discussions_dir")
        parser.add_argument("--topic")
        parser.add_argument("--participant", dest="participants", action="append", default=[])
        parser.add_argument("--max-rounds", dest="max_rounds", type=int, default=3)
        parser.add_argument("--task")
        parser.add_argument("--project")
        parser.add_argument("--created-by", dest="created_by", default="owner")
        opts = parser.parse_args(rest)
        if not opts.discussions_dir:
            sys.exit("--discussions-dir is required")
        if not opts.topic:
            sys.exit("--topic is required")
        if len(opts.participants) < 2:
            sys.exit("Need at least 2 --participant flags")
        if not opts.project:
            sys.exit("--project is required")
        sys.exit(
            cmd_start(
                opts.discussions_dir, opts.topic, opts.participants,
                opts.max_rounds, opts.task, opts.project, opts.created_by,
            )
        )

    elif cmd == "submit_round":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        parser.add_argument("--agent")
        parser.add_argument("--verdict")
        parser.add_argument("--position")
        parser.add_argument("--points-file", dest="points_file")
        opts = parser.parse_args(rest)
        for attr in ("discussion_dir", "round_", "agent", "verdict", "position"):
            if getattr(opts, attr, None) is None:
                flag = attr.replace("_", "-")
                sys.exit(f"--{flag} is required")
        sys.exit(
            cmd_submit_round(
                opts.discussion_dir, opts.round_, opts.agent,
                opts.verdict, opts.position, opts.points_file,
            )
        )

    elif cmd == "check_round":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        if opts.round_ is None:
            sys.exit("--round is required")
        sys.exit(cmd_check_round(opts.discussion_dir, opts.round_))

    elif cmd == "check_consensus":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_check_consensus(opts.discussion_dir))

    elif cmd == "advance":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_advance(opts.discussion_dir))

    elif cmd == "status":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_status(opts.discussion_dir))

    elif cmd == "list":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussions-dir", dest="discussions_dir")
        opts = parser.parse_args(rest)
        if not opts.discussions_dir:
            sys.exit("--discussions-dir is required")
        sys.exit(cmd_list(opts.discussions_dir))

    elif cmd == "close":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--outcome", default="cancelled")
        opts = parser.parse_args(rest)
        if not opts.discussion_dir:
            sys.exit("--discussion-dir is required")
        sys.exit(cmd_close(opts.discussion_dir, opts.outcome))

    elif cmd == "round_context":
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--discussion-dir", dest="discussion_dir")
        parser.add_argument("--round", dest="round_", type=int)
        parser.add_argument("--agent")
        opts = parser.parse_args(rest)
        for attr in ("discussion_dir", "round_", "agent"):
            if getattr(opts, attr, None) is None:
                flag = attr.replace("_", "-")
                sys.exit(f"--{flag} is required")
        sys.exit(cmd_round_context(opts.discussion_dir, opts.round_, opts.agent))


if __name__ == "__main__":
    main()
