from __future__ import annotations

import shutil
import subprocess

from serverops.models import CheckResult, Status, Target
from serverops.runner import run_command


def host_checks(target: Target, timeout: int) -> list[CheckResult]:
    checks: list[CheckResult] = []
    commands = {
        "uptime": ["uptime"],
        "disk": ["df", "-h", "/"],
        "memory": ["free", "-h"],
    }
    for name, argv in commands.items():
        try:
            result = run_command(argv, target=target, timeout=timeout)
            checks.append(
                CheckResult(
                    name=name,
                    status=Status.OK if result.returncode == 0 else Status.ERROR,
                    summary=result.stdout or result.stderr,
                    details={"returncode": result.returncode},
                )
            )
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            checks.append(CheckResult(name=name, status=Status.ERROR, summary=str(exc)))
    if target.kind == "local":
        checks.append(
            CheckResult(
                name="docker",
                status=Status.OK if shutil.which("docker") else Status.WARNING,
                summary="Docker CLI found" if shutil.which("docker") else "Docker CLI not found",
            )
        )
    return checks
