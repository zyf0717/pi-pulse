#!/usr/bin/env bash
# services.sh — manage pi-pulse systemd services
#
# Usage (must be run with sudo for commands that write to /etc/systemd/system):
#   sudo ./services.sh <command> [service ...]
#
# Commands:
#   install   substitute placeholders, copy units, daemon-reload, enable, start
#   remove    stop, disable, delete installed units, daemon-reload
#   start     start service(s)
#   stop      stop service(s)
#   restart   restart service(s)
#   status    show status (no sudo needed)
#   reload    daemon-reload only
#
# Examples:
#   sudo ./services.sh install              # all services in this directory
#   sudo ./services.sh install pulse sen66  # specific services
#   sudo ./services.sh remove h10
#   sudo ./services.sh restart
#        ./services.sh status
#
# Placeholder substitution (performed at install time):
#   ${SERVICE_USER}  — user who owns the repo (SUDO_USER, or current user)
#   ${WORKING_DIR}   — directory containing the service Python files (rpi4/)
#   ${UVICORN_BIN}   — uvicorn executable found in the active Python environment

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSTEMD_DIR="/etc/systemd/system"

# ── helpers ────────────────────────────────────────────────────────────────────

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

must_root() {
    [[ $EUID -eq 0 ]] || die "this command requires root — run with sudo"
}

# Detect the three variables used in the service file templates.
resolve_context() {
    # SERVICE_USER: prefer the invoking user when run via sudo, else current user
    SERVICE_USER="${SUDO_USER:-$(id -un)}"

    # WORKING_DIR: the rpi4/ directory next to this script (where *.py live)
    WORKING_DIR="$SCRIPT_DIR"

    # UVICORN_BIN: search in order —
    #   1. active conda env  2. venv next to repo root  3. PATH
    local repo_root; repo_root="$(dirname "$SCRIPT_DIR")"
    local conda_uvicorn="${CONDA_PREFIX:-}/bin/uvicorn"
    local venv_uvicorn="$repo_root/venv/bin/uvicorn"
    local dotvenv_uvicorn="$repo_root/.venv/bin/uvicorn"

    if [[ -x "$conda_uvicorn" ]]; then
        UVICORN_BIN="$conda_uvicorn"
    elif [[ -x "$venv_uvicorn" ]]; then
        UVICORN_BIN="$venv_uvicorn"
    elif [[ -x "$dotvenv_uvicorn" ]]; then
        UVICORN_BIN="$dotvenv_uvicorn"
    elif command -v uvicorn &>/dev/null; then
        UVICORN_BIN="$(command -v uvicorn)"
    else
        die "uvicorn not found — activate the project environment before running this script"
    fi

    export SERVICE_USER WORKING_DIR UVICORN_BIN
}

# Resolve service files from names or discover all in SCRIPT_DIR.
resolve_services() {
    local -a names=("$@")
    local -a files=()

    if [[ ${#names[@]} -eq 0 ]]; then
        while IFS= read -r -d '' f; do
            files+=("$f")
        done < <(find "$SCRIPT_DIR" -maxdepth 1 -name "*.service" -print0 | sort -z)
        [[ ${#files[@]} -gt 0 ]] || die "no .service files found in $SCRIPT_DIR"
    else
        for name in "${names[@]}"; do
            local path
            [[ "$name" == *.service ]] && path="$SCRIPT_DIR/$name" \
                                       || path="$SCRIPT_DIR/${name}.service"
            [[ -f "$path" ]] || die "service file not found: $path"
            files+=("$path")
        done
    fi

    printf '%s\n' "${files[@]}"
}

unit_name() { basename "$1"; }

# ── commands ───────────────────────────────────────────────────────────────────

cmd_install() {
    must_root
    resolve_context

    info "Installing with:"
    info "  SERVICE_USER = $SERVICE_USER"
    info "  WORKING_DIR  = $WORKING_DIR"
    info "  UVICORN_BIN  = $UVICORN_BIN"

    local -a files
    mapfile -t files < <(resolve_services "$@")

    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        local dest="$SYSTEMD_DIR/$unit"
        info "Installing $unit → $dest"
        envsubst '${SERVICE_USER} ${WORKING_DIR} ${UVICORN_BIN}' < "$f" > "$dest"
    done

    info "Running daemon-reload"
    systemctl daemon-reload

    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        info "Enabling  $unit"
        systemctl enable "$unit"
        info "Starting  $unit"
        systemctl start  "$unit"
    done

    echo
    info "Done. Status:"
    for f in "${files[@]}"; do
        systemctl status "$(unit_name "$f")" --no-pager -l || true
    done
}

cmd_remove() {
    must_root
    local -a files
    mapfile -t files < <(resolve_services "$@")

    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        info "Stopping   $unit"
        systemctl stop    "$unit" || true
        info "Disabling  $unit"
        systemctl disable "$unit" || true
        local dest="$SYSTEMD_DIR/$unit"
        if [[ -f "$dest" ]]; then
            info "Removing   $dest"
            rm "$dest"
        else
            info "$dest not found — skipping"
        fi
    done

    info "Running daemon-reload"
    systemctl daemon-reload
    info "Done."
}

cmd_start() {
    must_root
    local -a files; mapfile -t files < <(resolve_services "$@")
    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        info "Starting $unit"; systemctl start "$unit"
    done
}

cmd_stop() {
    must_root
    local -a files; mapfile -t files < <(resolve_services "$@")
    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        info "Stopping $unit"; systemctl stop "$unit"
    done
}

cmd_restart() {
    must_root
    local -a files; mapfile -t files < <(resolve_services "$@")
    for f in "${files[@]}"; do
        local unit; unit=$(unit_name "$f")
        info "Restarting $unit"; systemctl restart "$unit"
    done
}

cmd_status() {
    local -a files; mapfile -t files < <(resolve_services "$@")
    for f in "${files[@]}"; do
        systemctl status "$(unit_name "$f")" --no-pager -l || true
    done
}

cmd_reload() {
    must_root
    info "Running daemon-reload"
    systemctl daemon-reload
    info "Done."
}

# ── dispatch ───────────────────────────────────────────────────────────────────

usage() { sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'; exit 1; }

[[ $# -ge 1 ]] || usage
COMMAND="$1"; shift

case "$COMMAND" in
    install) cmd_install "$@" ;;
    remove)  cmd_remove  "$@" ;;
    start)   cmd_start   "$@" ;;
    stop)    cmd_stop    "$@" ;;
    restart) cmd_restart "$@" ;;
    status)  cmd_status  "$@" ;;
    reload)  cmd_reload        ;;
    *)       die "unknown command: $COMMAND"; usage ;;
esac
