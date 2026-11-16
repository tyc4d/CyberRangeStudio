"""Harmless local-process tests for the guest supervisor protocol.

The fake Docker CLI below starts only `sleep` processes. These tests exercise the
launch fence and absence confirmation; they are not Proxmox or Docker acceptance.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app.deploy.backends.probe_supervisor import PROBE_SUPERVISOR_SCRIPT

SID = "supervisor-test"
OPID = "a" * 32
TARGET = f"cr-demo-{SID}-web"


FAKE_DOCKER = r'''#!/bin/sh
set -eu
state=${FAKE_DOCKER_STATE:?}
mkdir -p "$state"
action=${1:-}
case "$action" in
  run)
    printf '%s\n' "$*" > "$state/run-args"
    name=
    while [ "$#" -gt 0 ]; do
      if [ "$1" = --name ]; then name=$2; shift 2; else shift; fi
    done
    [ -n "$name" ] || exit 2
    printf x >> "$state/run-count"
    if [ "${FAKE_DOCKER_DELAY:-0}" != 0 ]; then sleep "$FAKE_DOCKER_DELAY"; fi
    if [ "${FAKE_DOCKER_EXIT_QUICKLY:-0}" = 1 ]; then sleep 0.1 9>&- & else sleep 60 9>&- & fi
    pid=$!
    id=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    printf '%s\n' "$pid" > "$state/$name.pid"
    printf '%s\n' "$pid" > "$state/$id.pid"
    printf '%s\n' "$name" > "$state/$id.name"
    printf '%s\n' "$id"
    ;;
  inspect)
    shift
    format=
    if [ "${1:-}" = -f ]; then format=$2; shift 2; fi
    reference=${1:-}
    name=$reference
    case "$reference" in bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
      name=$(cat "$state/$reference.name" 2>/dev/null || true) ;;
    esac
    file="$state/$name.pid"
    if [ ! -f "$file" ]; then echo "Error: No such object: $name" >&2; exit 1; fi
    pid=$(cat "$file")
    if kill -0 "$pid" 2>/dev/null; then status=running; code=0; else status=exited; code=0; fi
    case "$format" in
      '{{.State.Status}}') printf '%s\n' "$status" ;;
      '{{.State.ExitCode}}') printf '%s\n' "$code" ;;
      *'cr.poc.operation'*)
        printf '%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s|%s\n' \
          bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb "$status" \
          "$FAKE_DOCKER_OPID" "$FAKE_DOCKER_SCENARIO" "$FAKE_DOCKER_TARGET" \
          'python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704' \
          "${FAKE_DOCKER_NETWORK_MODE:-container:$FAKE_DOCKER_TARGET}" '65532:65532' true '["ALL"]' 268435456 1000000000 128 ;;
      *) printf '{}\n' ;;
    esac
    ;;
  logs)
    printf 'VULHUB_HEADER=54289\n'
    ;;
  rm)
    shift
    [ "${1:-}" = -f ] && shift
    name=${1:-}
    case "$name" in bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb)
      name=$(cat "$state/$name.name" 2>/dev/null || true) ;;
    esac
    file="$state/$name.pid"
    if [ -f "$file" ]; then
      pid=$(cat "$file")
      kill "$pid" 2>/dev/null || true
      rm -f "$file"
      rm -f "$state/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pid"
      rm -f "$state/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.name"
    fi
    ;;
  *) echo "unexpected fake docker call: $action" >&2; exit 2 ;;
esac
'''


@pytest.fixture
def supervisor(tmp_path: Path):
    if not shutil.which("flock"):
        pytest.skip("host flock is unavailable for the harmless supervisor process test")
    state = tmp_path / "state"
    docker_state = tmp_path / "fake-docker-state"
    docker = tmp_path / "docker"
    docker.write_text(FAKE_DOCKER)
    docker.chmod(0o700)
    script = PROBE_SUPERVISOR_SCRIPT.replace(
        "STATE_DIR=/var/lib/cr-runtime/probe-operations", f"STATE_DIR={state}")
    script = script.replace("DOCKER_BIN=/usr/bin/docker", f"DOCKER_BIN={docker}")
    supervisor_path = tmp_path / "supervisor.sh"
    supervisor_path.write_text(script)
    payload = "cHJpbnQoJ29rJyk="  # harmless `print('ok')`, never executed by this fake CLI
    env = {**os.environ, "FAKE_DOCKER_STATE": str(docker_state), "FAKE_DOCKER_OPID": OPID,
           "FAKE_DOCKER_SCENARIO": SID, "FAKE_DOCKER_TARGET": TARGET}

    def command(action: str, operation_id: str = OPID):
        command = ["/bin/sh", str(supervisor_path), action, operation_id, SID, TARGET, "5", payload]
        return command

    def call(action: str, operation_id: str = OPID, extra_env: dict[str, str] | None = None):
        return subprocess.run(command(action, operation_id), capture_output=True, text=True, timeout=5,
                              env={**env, **(extra_env or {})})

    return call, command, docker_state, env


def test_cancel_before_start_tombstone_rejects_late_launch(supervisor):
    call, _, state, _ = supervisor
    cancelled = call("cancel")
    late_start = call("start")

    assert cancelled.returncode == late_start.returncode == 0
    assert "state=cancelled" in cancelled.stdout and "resource_absent=true" in cancelled.stdout
    assert "state=cancelled" in late_start.stdout and "resource_absent=true" in late_start.stdout
    assert not (state / "run-count").exists()
    assert not list(state.glob("*.pid"))


def test_start_then_cancel_kills_exact_harmless_process_and_joins(supervisor):
    call, _, state, _ = supervisor
    started = call("start")
    cancelled = call("cancel")
    joined = call("join")

    assert started.returncode == 0 and "state=running" in started.stdout
    assert cancelled.returncode == 0 and "state=cancelled" in cancelled.stdout
    assert "resource_absent=true" in cancelled.stdout
    assert joined.returncode == 0 and "state=cancelled" in joined.stdout
    assert not list(state.glob("*.pid"))
    arguments = (state / "run-args").read_text()
    for required in ("--pull=never", f"container:{TARGET}", "--read-only", "--cap-drop=ALL",
                     "--security-opt no-new-privileges:true", "--user 65532:65532",
                     "--memory 256m", "--cpus 1", "--pids-limit 128", "--tmpfs /tmp:rw,noexec,nosuid,size=16m"):
        assert required in arguments, f"missing helper restriction: {required}"


def test_concurrent_start_first_cancel_waits_for_launch_then_removes_process(supervisor):
    call, command, state, env = supervisor
    runner = subprocess.Popen(command("start"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True, env={**env, "FAKE_DOCKER_DELAY": "0.3"})
    time.sleep(0.05)
    cancelled = call("cancel")
    start_stdout, start_stderr = runner.communicate(timeout=5)
    assert runner.returncode == 0, (start_stdout, start_stderr)
    assert "state=running" in start_stdout
    assert cancelled.returncode == 0 and "state=cancelled" in cancelled.stdout
    assert "resource_absent=true" in cancelled.stdout
    assert not list(state.glob("*.pid"))


def test_identity_mismatch_keeps_helper_and_returns_uncertain(supervisor):
    call, _, state, _ = supervisor
    assert "state=running" in call("start").stdout
    mismatch = call("cancel", extra_env={"FAKE_DOCKER_OPID": "different-operation"})

    assert mismatch.returncode == 75
    assert "state=uncertain" in mismatch.stdout
    assert "resource_absent=false" in mismatch.stdout
    assert list(state.glob("*.pid")), "the supervisor removed a container it could not prove it owned"
    assert "state=cancelled" in call("cancel").stdout


def test_wrong_target_network_keeps_helper_and_returns_uncertain(supervisor):
    call, _, state, _ = supervisor
    assert "state=running" in call("start").stdout
    mismatch = call("cancel", extra_env={"FAKE_DOCKER_NETWORK_MODE": "container:another-service"})

    assert mismatch.returncode == 75
    assert "state=uncertain" in mismatch.stdout
    assert "resource_absent=false" in mismatch.stdout
    assert list(state.glob("*.pid")), "the supervisor removed a helper attached to an unexpected target"
    assert "state=cancelled" in call("cancel").stdout
