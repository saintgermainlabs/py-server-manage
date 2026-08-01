from __future__ import annotations

import shlex
import subprocess
import time

from .models import CommandResult, Target

READ_ONLY_PREFIXES = {
    ("borg", "info"),
    ("borg", "list"),
    ("borgmatic", "check"),
    ("borgmatic", "list"),
    ("df",),
    ("docker", "compose", "config"),
    ("docker", "inspect"),
    ("docker", "logs"),
    ("docker", "network", "ls"),
    ("docker", "ps"),
    ("docker", "system", "df"),
    ("docker", "system", "info"),
    ("docker", "version"),
    ("docker", "volume", "inspect"),
    ("docker", "volume", "ls"),
    ("du",),
    ("findmnt",),
    ("free",),
    ("hostnamectl",),
    ("journalctl",),
    ("lsblk",),
    ("ss",),
    ("systemctl", "is-active"),
    ("systemctl", "list-timers"),
    ("systemctl", "list-units"),
    ("systemctl", "status"),
    ("uname",),
    ("uptime",),
    ("which",),
}


def is_read_only(argv: list[str]) -> bool:
    return any(tuple(argv[: len(prefix)]) == prefix for prefix in READ_ONLY_PREFIXES)


def run_command(
    argv: list[str],
    *,
    target: Target,
    timeout: int,
    allow_mutation: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    if not allow_mutation and not is_read_only(argv):
        raise PermissionError(f"Command is not in the read-only allowlist: {shlex.join(argv)}")

    effective = argv
    if target.kind == "ssh":
        if not target.host:
            raise ValueError("SSH target requires a host")
        destination = f"{target.user}@{target.host}" if target.user else target.host
        effective = [
            "ssh",
            "-p",
            str(target.port),
            "--",
            destination,
            shlex.join(argv),
        ]
    elif target.kind != "local":
        raise ValueError(f"Unsupported target kind: {target.kind}")

    started = time.monotonic()
    completed = subprocess.run(
        effective,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )
    return CommandResult(
        argv=effective,
        returncode=completed.returncode,
        stdout=completed.stdout.rstrip(),
        stderr=completed.stderr.rstrip(),
        duration_seconds=round(time.monotonic() - started, 3),
    )
