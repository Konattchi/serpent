#!/usr/bin/env bash

set -u

LOG_TAG="serpent-restore"
SERPENT_DIR="$HOME/.local/share/serpent"
OWNERSHIP="$SERPENT_DIR/serpent_core/ownership.py"


log_message() {
    /usr/bin/logger -t "$LOG_TAG" -- "$1"
}


current_owner() {
    /usr/bin/python3 "$OWNERSHIP" get 2>/dev/null
}


restore_sync_owner() {
    if ! /usr/bin/systemctl --user cat \
        serpent-sync.service >/dev/null 2>&1
    then
        log_message \
            "Sync owns lighting, but serpent-sync.service is not installed yet; skipping normal restoration."
        return 0
    fi

    if /usr/bin/systemctl --user start serpent-sync.service; then
        log_message "Ensured synchronization owner is running."
        return 0
    fi

    log_message "ERROR: Failed to start synchronization owner."
    return 1
}


restore_normal_owner() {
    local attempt
    local mouse_ok
    local keyboard_ok

    # OpenRazer, USB devices and the wireless mouse may not be ready
    # immediately.
    /usr/bin/sleep 3

    for attempt in 1 2 3 4 5; do
        mouse_ok=false
        keyboard_ok=false

        if /usr/bin/systemctl --user start \
            serpent-individual.service
        then
            mouse_ok=true
        fi

        if "$HOME/.local/bin/serpent" \
            keyboard apply-profile
        then
            keyboard_ok=true
        fi

        if [ "$mouse_ok" = true ] &&
           [ "$keyboard_ok" = true ]; then
            log_message \
                "Restored normal Serpent profiles on attempt $attempt."
            # Refresh normal-mode dynamic plugins after both profile paths succeed.
            /usr/bin/systemctl --user start \
                serpent-individual.service >/dev/null 2>&1 || true
            return 0
        fi

        log_message \
            "Devices not ready on normal restore attempt $attempt."

        /usr/bin/sleep 3
    done

    log_message \
        "ERROR: Failed to restore one or more normal-mode devices."

    return 1
}


owner="$(current_owner)"

case "$owner" in
    normal)
        restore_normal_owner
        exit $?
        ;;

    sync)
        restore_sync_owner
        exit $?
        ;;

    "")
        log_message \
            "ERROR: Lighting ownership state could not be read."
        exit 1
        ;;

    *)
        log_message \
            "Lighting is owned by '$owner'; skipping normal profile restoration."
        exit 0
        ;;
esac
