"""
shux talk — session-name-addressed inter-agent conversation threads.

Interactive agent-to-agent messaging built on the discussions engine.
Sessions register a stable name once, then exchange messages by peer name —
no discussion-id juggling. Threads are ordinary discussions kept open by
always submitting verdict=partial (auto-consensus never fires), so a live
conversation is never closed under the participants.

    shux talk register <my-name> <agent-kind> [--project DIR]
    shux talk <peer> -m "message"      send (first contact auto-creates thread)
    shux talk <peer>                   show the thread
    shux talk inbox                    threads where the peer spoke last

Registry layout (under the talk dir):
    sessions/<name>.json    name → {agent kind, host, project, registered at}
    threads/<a>~<b>.id      sorted-pair pointer → discussion id
    threads/<a>~<b>.history rotated thread ids (append-only)

Talk dir resolution: $SUPERHARNESS_TALK_DIR, else <project>/.superharness/talk.
Cross-host setups point SUPERHARNESS_TALK_DIR (and the state registry, via
SUPERHARNESS_STATE_DIR or a shared project checkout) at a mount every host
sees. Keep traffic light when the registry lives on network storage.

Self identity: $SUPERHARNESS_TALK_SELF names the identity file directly;
otherwise ~/.config/superharness/talk-self-<instance>, where <instance> is
$SUPERHARNESS_TALK_INSTANCE (or $HERDR_PANE_ID, or "shared"). Co-located
agents sharing an OS user MUST NOT share one identity file — whoever
registers last would win — so give each an instance id.

See docs/inter-agent-talk-protocol.md for the channel-split protocol
(talk = interactive conversation; append-only mailbox files = durable
handoffs/receipts/decisions).
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import socket
import sys
from datetime import datetime, timezone

from superharness.engine.errors import SuperharnessError, UsageError, handle_cli_error

MAX_ROUNDS = 99
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _talk_dir(project_dir: str) -> str:
    override = os.environ.get("SUPERHARNESS_TALK_DIR", "").strip()
    return override or os.path.join(project_dir, ".superharness", "talk")


def _self_file() -> str:
    override = os.environ.get("SUPERHARNESS_TALK_SELF", "").strip()
    if override:
        return override
    instance = (
        os.environ.get("SUPERHARNESS_TALK_INSTANCE", "").strip()
        or os.environ.get("HERDR_PANE_ID", "").strip()
        or "shared"
    )
    instance = re.sub(r"[^A-Za-z0-9._-]", "_", instance)
    return os.path.join(
        os.path.expanduser("~"), ".config", "superharness", f"talk-self-{instance}"
    )


def _check_name(name: str, what: str = "session name") -> str:
    if not _NAME_RE.match(name):
        raise UsageError(
            f"Invalid {what} '{name}' — use letters, digits, '.', '_', '-'", exit_code=2
        )
    return name


def _load_self() -> tuple[str, str]:
    path = _self_file()
    if not os.path.isfile(path):
        raise UsageError(
            "not registered — run: shux talk register <my-name> <agent-kind>",
            exit_code=1,
        )
    with open(path, encoding="utf-8") as f:
        parts = f.read().split()
    if len(parts) < 2:
        raise UsageError(f"corrupt identity file {path} — re-register", exit_code=1)
    return parts[0], parts[1]


def _rounds(project_dir: str, disc_id: str):
    """Conversation rounds, oldest first; system rows (agent '_*') excluded."""
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        rows = discussions_dao.get_rounds(conn, disc_id)
    finally:
        conn.close()
    return sorted(
        (r for r in rows if r.content is not None and not r.agent.startswith("_")),
        key=lambda r: (r.created_at, r.id),
    )


def _status(project_dir: str, disc_id: str) -> str:
    from superharness.engine.db import get_connection, init_db
    from superharness.engine import discussions_dao

    conn = get_connection(project_dir)
    try:
        init_db(conn)
        disc = discussions_dao.get(conn, disc_id)
    finally:
        conn.close()
    return disc.status if disc else "missing"


def _pair_file(talk_dir: str, a: str, b: str) -> str:
    pair = "~".join(sorted((a, b)))
    return os.path.join(talk_dir, "threads", f"{pair}.id")


def _create_thread(project_dir: str, talk_dir: str, self_name: str, peer: str) -> str:
    """Start a fresh discussion for the pair and atomically update the pointer.

    A superseded pointer (closed/cancelled thread) is appended to the pair's
    .history file so rotated conversations stay discoverable.
    """
    from superharness.engine.discussion import cmd_start

    pair_file = _pair_file(talk_dir, self_name, peer)
    os.makedirs(os.path.dirname(pair_file), exist_ok=True)

    if os.path.isfile(pair_file):
        with open(pair_file, encoding="utf-8") as f:
            previous = f.read().strip()
        if previous:
            with open(
                pair_file[: -len(".id")] + ".history", "a", encoding="utf-8"
            ) as f:
                f.write(
                    f"[{_now_utc()}] {previous} status={_status(project_dir, previous)}\n"
                )

    participants = sorted({self_name, peer})
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cmd_start(
            discussions_dir=os.path.join(project_dir, ".superharness", "discussions"),
            topic=(
                f"talk: {self_name} <-> {peer} (open conversation; "
                f"verdict=partial keeps it open; started {_now_utc()})"
            ),
            participants=participants,
            max_rounds=MAX_ROUNDS,
            task_id=None,
            project=project_dir,
            created_by=self_name,
        )
    disc_id = json.loads(buf.getvalue())["id"]

    tmp = f"{pair_file}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(disc_id + "\n")
    os.replace(tmp, pair_file)
    return disc_id


def _resolve_thread(
    project_dir: str, talk_dir: str, self_name: str, peer: str, for_send: bool
) -> str:
    pair_file = _pair_file(talk_dir, self_name, peer)
    if not os.path.isfile(pair_file):
        return _create_thread(project_dir, talk_dir, self_name, peer)
    with open(pair_file, encoding="utf-8") as f:
        disc_id = f.read().strip()
    if for_send and _status(project_dir, disc_id) != "active":
        return _create_thread(project_dir, talk_dir, self_name, peer)
    return disc_id


def cmd_register(project_dir: str, name: str, kind: str) -> int:
    _check_name(name)
    _check_name(kind, "agent kind")
    talk_dir = _talk_dir(project_dir)
    os.makedirs(os.path.join(talk_dir, "sessions"), exist_ok=True)

    self_file = _self_file()
    os.makedirs(os.path.dirname(self_file), exist_ok=True)
    with open(self_file, "w", encoding="utf-8") as f:
        f.write(f"{name} {kind}\n")

    record = {
        "name": name,
        "agent": kind,
        "host": socket.gethostname(),
        "project": project_dir,
        "at": _now_utc(),
    }
    session_file = os.path.join(talk_dir, "sessions", f"{name}.json")
    tmp = f"{session_file}.tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(record, f)
        f.write("\n")
    os.replace(tmp, session_file)
    print(f"registered {name} ({kind} @ {record['host']})")
    return 0


def cmd_send(project_dir: str, peer: str, message: str) -> int:
    from superharness.engine.discussion import cmd_submit_round

    self_name, _kind = _load_self()
    talk_dir = _talk_dir(project_dir)
    _require_peer(talk_dir, peer)

    disc_id = _resolve_thread(project_dir, talk_dir, self_name, peer, for_send=True)
    next_round = (
        sum(1 for r in _rounds(project_dir, disc_id) if r.agent == self_name) + 1
    )
    disc_dir = os.path.join(project_dir, ".superharness", "discussions", disc_id)
    with contextlib.redirect_stdout(io.StringIO()):
        cmd_submit_round(
            discussion_dir=disc_dir,
            round_=next_round,
            agent=self_name,
            verdict="partial",
            position=message,
        )
    print(f"sent (thread {disc_id}, round {next_round})")
    return 0


def cmd_show(project_dir: str, peer: str) -> int:
    self_name, _kind = _load_self()
    talk_dir = _talk_dir(project_dir)
    _require_peer(talk_dir, peer)

    disc_id = _resolve_thread(project_dir, talk_dir, self_name, peer, for_send=False)
    print(f"thread {disc_id} with {peer}:")
    for r in _rounds(project_dir, disc_id):
        print(f"[{r.created_at}] r{r.round_number} {r.agent}: {r.content}")
    return 0


def cmd_inbox(project_dir: str) -> int:
    self_name, _kind = _load_self()
    threads_dir = os.path.join(_talk_dir(project_dir), "threads")
    if not os.path.isdir(threads_dir):
        return 0
    for entry in sorted(os.listdir(threads_dir)):
        if not entry.endswith(".id"):
            continue
        pair = entry[: -len(".id")]
        if self_name not in pair.split("~"):
            continue
        with open(os.path.join(threads_dir, entry), encoding="utf-8") as f:
            disc_id = f.read().strip()
        rounds = _rounds(project_dir, disc_id)
        if rounds and rounds[-1].agent != self_name:
            last = rounds[-1]
            print(f"{pair}: [{last.created_at}] {last.agent}: {last.content}")
    return 0


def _require_peer(talk_dir: str, peer: str) -> None:
    _check_name(peer, "peer session name")
    if not os.path.isfile(os.path.join(talk_dir, "sessions", f"{peer}.json")):
        raise UsageError(
            f"unknown session '{peer}' — peers register with: "
            f"shux talk register <name> <agent-kind>",
            exit_code=1,
        )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="shux talk",
        description="Session-name-addressed inter-agent conversation threads.",
    )
    parser.add_argument(
        "--project", "-p", default=None, help="project root (default: cwd)"
    )
    parser.add_argument(
        "target",
        help="'register', 'inbox', or a peer session name",
    )
    parser.add_argument(
        "rest",
        nargs="*",
        help="register: <my-name> <agent-kind>; peer: [-m MESSAGE]",
    )
    parser.add_argument(
        "-m", "--message", default=None, help="message to send to the peer"
    )
    opts = parser.parse_args(argv)

    project_dir = os.path.abspath(opts.project or os.getcwd())

    if opts.target == "register":
        if len(opts.rest) != 2:
            raise UsageError(
                "usage: shux talk register <my-name> <agent-kind>", exit_code=2
            )
        rc = cmd_register(project_dir, opts.rest[0], opts.rest[1])
    elif opts.target == "inbox":
        if opts.rest or opts.message is not None:
            raise UsageError("usage: shux talk inbox", exit_code=2)
        rc = cmd_inbox(project_dir)
    else:
        if opts.rest:
            raise UsageError("usage: shux talk <peer> [-m MESSAGE]", exit_code=2)
        if opts.message is not None:
            rc = cmd_send(project_dir, opts.target, opts.message)
        else:
            rc = cmd_show(project_dir, opts.target)
    sys.exit(rc)


if __name__ == "__main__":
    try:
        main()
    except SuperharnessError as e:
        handle_cli_error(e)
