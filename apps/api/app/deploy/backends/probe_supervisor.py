"""Fixed guest-side process supervisor used by the cancellable PVE probe transport.

The operation state is deliberately kept on the worker VM, outside Docker, so a
second API worker can observe cancel-before-start tombstones and join a process
whose original API request disappeared.
"""

PROBE_SUPERVISOR_PATH = "/opt/cr-runtime/probe-supervisor.sh"

PROBE_SUPERVISOR_SCRIPT = r'''#!/bin/sh
set -eu

PATH=/usr/bin:/bin
export PATH
STATE_DIR=/var/lib/cr-runtime/probe-operations
DOCKER_BIN=/usr/bin/docker
FLOCK_BIN=/usr/bin/flock
HELPER_IMAGE=python@sha256:a0f57064cbdcd6285fa45f51237ab0b35ea8ebaed06a1f5973e89e19dfb86704
MAX_OUTPUT=12000

action=${1:-}
operation_id=${2:-}
scenario_id=${3:-}
target_name=${4:-}
timeout_s=${5:-}
payload_b64=${6:-}

case "$action" in start|wait|cancel|join) ;; *) echo 'state=uncertain'; exit 75 ;; esac
case "$operation_id" in
  *[!0-9a-f]*|'') echo 'state=uncertain'; exit 75 ;;
esac
[ "${#operation_id}" -eq 32 ] || { echo 'state=uncertain'; exit 75; }
case "$scenario_id" in *[!a-zA-Z0-9_-]*|'') echo 'state=uncertain'; exit 75 ;; esac
case "$target_name" in "cr-demo-${scenario_id}-"*) ;; *) echo 'state=uncertain'; exit 75 ;; esac
case "$timeout_s" in *[!0-9]*|'') echo 'state=uncertain'; exit 75 ;; esac
[ "$timeout_s" -ge 1 ] && [ "$timeout_s" -le 300 ] || { echo 'state=uncertain'; exit 75; }

mkdir -p "$STATE_DIR"
chmod 0700 "$STATE_DIR"
state_file="$STATE_DIR/$operation_id.state"
lock_file="$STATE_DIR/$operation_id.lock"
exec 9>"$lock_file"
"$FLOCK_BIN" -x 9 || { echo 'state=uncertain'; exit 75; }

container_name="cr-poc-$operation_id"
saved_state=
saved_scenario=
saved_target=
saved_code=
saved_stdout=
saved_stderr=
if [ -f "$state_file" ]; then
  IFS='|' read -r saved_state saved_scenario saved_target saved_code saved_stdout saved_stderr < "$state_file" || true
  if [ "$saved_scenario" != "$scenario_id" ] || [ "$saved_target" != "$target_name" ]; then
    echo 'state=uncertain'
    exit 75
  fi
fi

save_state() {
  next_state=$1
  next_code=${2:-}
  next_stdout=${3:-}
  next_stderr=${4:-}
  temp="$state_file.tmp.$$"
  printf '%s|%s|%s|%s|%s|%s\n' "$next_state" "$scenario_id" "$target_name" "$next_code" "$next_stdout" "$next_stderr" > "$temp"
  chmod 0600 "$temp"
  /bin/sync -f "$temp"
  mv -f "$temp" "$state_file"
  /bin/sync -f "$STATE_DIR"
  saved_state=$next_state
  saved_scenario=$scenario_id
  saved_target=$target_name
  saved_code=$next_code
  saved_stdout=$next_stdout
  saved_stderr=$next_stderr
}

emit_state() {
  printf 'state=%s\n' "$1"
  if [ -n "${2:-}" ]; then printf 'exitcode=%s\n' "$2"; fi
  if [ -n "${3:-}" ]; then printf 'stdout_b64=%s\n' "$3"; fi
  if [ -n "${4:-}" ]; then printf 'stderr_b64=%s\n' "$4"; fi
  printf 'resource_absent=%s\n' "$5"
}

inspect_helper() {
  detail=$("$DOCKER_BIN" inspect -f '{{.Id}}|{{.State.Status}}|{{index .Config.Labels "cr.poc.operation"}}|{{index .Config.Labels "cr.poc.scenario"}}|{{index .Config.Labels "cr.poc.target"}}|{{.Config.Image}}|{{.HostConfig.NetworkMode}}|{{.Config.User}}|{{.HostConfig.ReadonlyRootfs}}|{{json .HostConfig.CapDrop}}|{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.PidsLimit}}' "$container_name" 2>&1) || {
    printf '%s\n' "$detail"
    return 1
  }
  IFS='|' read -r container_id container_status owner_operation owner_scenario owner_target image network_mode user readonly cap_drop memory nano_cpus pids_limit <<EOF
$detail
EOF
  case "$container_id" in *[!0-9a-f]*|'') echo 'helper ownership check failed'; return 2 ;; esac
  [ "${#container_id}" -ge 12 ] || { echo 'helper ownership check failed'; return 2; }
  target_id=$("$DOCKER_BIN" inspect -f '{{.Id}}' "$target_name" 2>/dev/null) || {
    echo 'target ownership proof failed'
    return 2
  }
  case "$target_id" in *[!0-9a-f]*|'') echo 'target ownership proof failed'; return 2 ;; esac
  [ "${#target_id}" -ge 12 ] || { echo 'target ownership proof failed'; return 2; }
  [ "$owner_operation" = "$operation_id" ] || { echo 'helper ownership check failed'; return 2; }
  [ "$owner_scenario" = "$scenario_id" ] || { echo 'helper ownership check failed'; return 2; }
  [ "$owner_target" = "$target_name" ] || { echo 'helper ownership check failed'; return 2; }
  [ "$image" = "$HELPER_IMAGE" ] || { echo 'helper ownership check failed'; return 2; }
  case "$network_mode" in
    "container:$target_name"|"container:$target_id") ;;
    *) echo 'helper ownership check failed'; return 2 ;;
  esac
  [ "$user" = '65532:65532' ] || { echo 'helper ownership check failed'; return 2; }
  [ "$readonly" = true ] && [ "$cap_drop" = '["ALL"]' ] || { echo 'helper ownership check failed'; return 2; }
  [ "$memory" = 268435456 ] && [ "$nano_cpus" = 1000000000 ] && [ "$pids_limit" = 128 ] || {
    echo 'helper ownership check failed'
    return 2
  }
  printf '%s|%s\n' "$container_id" "$container_status"
}

is_confirmed_absent() {
  reference=${1:-$container_name}
  inspect_output=$("$DOCKER_BIN" inspect "$reference" 2>&1) && return 1
  lower_inspect_output=$(printf '%s' "$inspect_output" | tr '[:upper:]' '[:lower:]')
  case "$lower_inspect_output" in
    *'no such object'*|*'no such container'*) return 0 ;;
    *) return 2 ;;
  esac
}

remove_and_confirm() {
  detail=$(inspect_helper) || return 1
  container_id=${detail%%|*}
  "$DOCKER_BIN" rm -f "$container_id" >/dev/null 2>&1 || true
  is_confirmed_absent "$container_id"
}

finalize_exited() {
  detail=$(inspect_helper) || return 2
  container_id=${detail%%|*}
  exit_code=$("$DOCKER_BIN" inspect -f '{{.State.ExitCode}}' "$container_id" 2>/dev/null) || return 2
  case "$exit_code" in *[!0-9]*|'') return 2 ;; esac
  stdout_b64=$("$DOCKER_BIN" logs "$container_id" 2>/dev/null | head -c "$MAX_OUTPUT" | base64 -w 0) || return 2
  stderr_b64=
  "$DOCKER_BIN" rm -f "$container_id" >/dev/null 2>&1 || true
  if ! is_confirmed_absent "$container_id"; then return 2; fi
  save_state completed "$exit_code" "$stdout_b64" "$stderr_b64"
  emit_state completed "$exit_code" "$stdout_b64" "$stderr_b64" true
}

case "$action" in
  start)
    if [ -n "$saved_state" ]; then
      case "$saved_state" in
        cancelled) emit_state cancelled '' '' '' true; exit 0 ;;
        running) emit_state running '' '' '' false; exit 0 ;;
        completed|failed) emit_state "$saved_state" "$saved_code" "$saved_stdout" "$saved_stderr" true; exit 0 ;;
        starting)
          live_detail=$(inspect_helper) || {
            lower_live_detail=$(printf '%s' "$live_detail" | tr '[:upper:]' '[:lower:]')
            case "$lower_live_detail" in
              *'no such object'*|*'no such container'*) save_state failed 127 '' ''; emit_state failed 127 '' '' true; exit 0 ;;
              *) save_state uncertain; emit_state uncertain '' '' '' false; exit 75 ;;
            esac
          }
          live_status=${live_detail#*|}
          if [ "$live_status" = running ]; then save_state running; emit_state running '' '' '' false; exit 0; fi
          finalize_exited || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }
          exit 0
          ;;
        uncertain) emit_state uncertain '' '' '' false; exit 75 ;;
        *) echo 'state=uncertain'; exit 75 ;;
      esac
    fi
    [ -n "$payload_b64" ] || { save_state failed 127 '' ''; emit_state failed 127 '' '' true; exit 0; }
    payload=$(printf '%s' "$payload_b64" | base64 -d 2>/dev/null) || { save_state failed 127 '' ''; emit_state failed 127 '' '' true; exit 0; }
    save_state starting
    if "$DOCKER_BIN" run --detach --pull=never --name "$container_name" \
        --label "cr.poc.operation=$operation_id" \
        --label "cr.poc.scenario=$scenario_id" \
        --label "cr.poc.target=$target_name" \
        --network "container:$target_name" --read-only --cap-drop=ALL \
        --security-opt no-new-privileges:true --user 65532:65532 \
        --tmpfs /tmp:rw,noexec,nosuid,size=16m --memory 256m --cpus 1 --pids-limit 128 \
        "$HELPER_IMAGE" python -c "$payload" >/dev/null 2>&1; then
      live_detail=$(inspect_helper) || {
        lower_live_detail=$(printf '%s' "$live_detail" | tr '[:upper:]' '[:lower:]')
        case "$lower_live_detail" in
          *'no such object'*|*'no such container'*) save_state failed 127 '' ''; emit_state failed 127 '' '' true; exit 0 ;;
          *) save_state uncertain; emit_state uncertain '' '' '' false; exit 75 ;;
        esac
      }
      live_status=${live_detail#*|}
      if [ "$live_status" = running ]; then
        save_state running
        emit_state running '' '' '' false
        exit 0
      fi
      finalize_exited || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }
      exit 0
    fi
    absent=0
    is_confirmed_absent "$container_name" && absent=1 || absent=0
    if [ "$absent" -eq 1 ]; then save_state failed 127 '' ''; emit_state failed 127 '' '' true; exit 0; fi
    live_detail=$(inspect_helper) || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }
    live_status=${live_detail#*|}
    if [ "$live_status" = running ]; then save_state running; emit_state running '' '' '' false; exit 0; fi
    finalize_exited || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }
    ;;
  wait|join)
    if [ "$saved_state" = cancelled ]; then emit_state cancelled '' '' '' true; exit 0; fi
    if [ "$saved_state" = completed ] || [ "$saved_state" = failed ]; then
      emit_state "$saved_state" "$saved_code" "$saved_stdout" "$saved_stderr" true
      exit 0
    fi
    live_detail=$(inspect_helper) || {
      lower_live_detail=$(printf '%s' "$live_detail" | tr '[:upper:]' '[:lower:]')
      case "$lower_live_detail" in
        *'no such object'*|*'no such container'*)
          save_state failed 127 '' ''
          emit_state failed 127 '' '' true
          exit 0
          ;;
        *) save_state uncertain; emit_state uncertain '' '' '' false; exit 75 ;;
      esac
    }
    live_status=${live_detail#*|}
    if [ "$live_status" = running ]; then save_state running; emit_state running '' '' '' false; exit 0; fi
    finalize_exited || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }
    ;;
  cancel)
    if [ -z "$saved_state" ]; then
      save_state cancelled
      emit_state cancelled '' '' '' true
      exit 0
    fi
    if [ "$saved_state" = cancelled ]; then emit_state cancelled '' '' '' true; exit 0; fi
    if [ "$saved_state" = completed ] || [ "$saved_state" = failed ]; then
      emit_state "$saved_state" "$saved_code" "$saved_stdout" "$saved_stderr" true
      exit 0
    fi
    live_detail=$(inspect_helper) || {
      lower_live_detail=$(printf '%s' "$live_detail" | tr '[:upper:]' '[:lower:]')
      case "$lower_live_detail" in
        *'no such object'*|*'no such container'*) save_state cancelled; emit_state cancelled '' '' '' true; exit 0 ;;
        *) save_state uncertain; emit_state uncertain '' '' '' false; exit 75 ;;
      esac
    }
    live_status=${live_detail#*|}
    if [ "$live_status" != running ]; then finalize_exited || { save_state uncertain; emit_state uncertain '' '' '' false; exit 75; }; exit 0; fi
    if remove_and_confirm; then
      save_state cancelled
      emit_state cancelled '' '' '' true
      exit 0
    fi
    save_state uncertain
    emit_state uncertain '' '' '' false
    exit 75
    ;;
esac
'''
