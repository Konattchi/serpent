#!/usr/bin/env bash

set -u

SERPENT_DIR="$HOME/.local/share/serpent"
TRIGGER="$SERPENT_DIR/serpent-trigger-restore.sh"
USB_ID_HELPER="$SERPENT_DIR/fixture_usb_ids.py"
OWNERSHIP="$SERPENT_DIR/serpent_core/ownership.py"

pids=()
supported_usb_ids=()
shutting_down=false


log_message() {
    /usr/bin/logger -t serpent-watcher -- "$1"
}


current_owner() {
    /usr/bin/python3 "$OWNERSHIP" get 2>/dev/null
}


normal_mode_active() {
    [ "$(current_owner)" = "normal" ]
}


load_supported_usb_ids() {
    local usb_id

    supported_usb_ids=()

    while IFS= read -r usb_id; do
        usb_id="${usb_id,,}"

        if [ -n "$usb_id" ]; then
            supported_usb_ids+=("$usb_id")
        fi
    done < <(/usr/bin/python3 "$USB_ID_HELPER")

    if [ "${#supported_usb_ids[@]}" -eq 0 ]; then
        log_message \
            "ERROR: No supported USB IDs were loaded from fixtures."
        return 1
    fi

    log_message \
        "Loaded ${#supported_usb_ids[@]} supported USB ID(s) from fixtures."

    return 0
}


line_matches_supported_device() {
    local line="${1,,}"
    local usb_id

    for usb_id in "${supported_usb_ids[@]}"; do
        if [[ "$line" == *"$usb_id"* ]]; then
            return 0
        fi
    done

    return 1
}


cleanup() {
    if [ "${#pids[@]}" -gt 0 ]; then
        kill "${pids[@]}" 2>/dev/null || true
        wait "${pids[@]}" 2>/dev/null || true
    fi
}


shutdown_cleanly() {
    shutting_down=true
    log_message "Serpent watcher stopping cleanly."
    cleanup
    exit 0
}


trap cleanup EXIT
trap shutdown_cleanly INT TERM


monitor_unlock() {
    /usr/bin/dbus-monitor --session \
        "type='signal',interface='org.freedesktop.ScreenSaver',member='ActiveChanged'" \
        2>/dev/null |
    while IFS= read -r line; do
        if [[ "$line" == *"boolean false"* ]]; then
            log_message "Screen unlock detected."
            "$TRIGGER" 1 &
        fi
    done
}


monitor_resume() {
    /usr/bin/dbus-monitor --system \
        "type='signal',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'" \
        2>/dev/null |
    while IFS= read -r line; do
        if [[ "$line" == *"boolean false"* ]]; then
            log_message "Resume from suspend detected."
            "$TRIGGER" 3 &
        fi
    done
}


monitor_devices() {
    /usr/bin/udevadm monitor \
        --udev \
        --subsystem-match=hid \
        2>/dev/null |
    while IFS= read -r line; do
        local_line="${line,,}"
        connection_event=false

        if [[ "$local_line" == *" add "* ]] ||
           [[ "$local_line" == *" bind "* ]] ||
           [[ "$local_line" == *" change "* ]]; then
            connection_event=true
        fi

        if [ "$connection_event" = true ] &&
           line_matches_supported_device "$local_line"; then
            log_message \
                "Fixture-supported device connection event detected."

            "$TRIGGER" 2 &
        fi
    done
}


monitor_engine() {
    while /usr/bin/sleep 30; do
        if ! normal_mode_active; then
            continue
        fi

        if /usr/bin/systemctl --user is-active --quiet serpent-individual.service; then
            continue
        fi

        if ! /usr/bin/systemctl --user is-active \
            --quiet serpent-individual.service
        then
            log_message \
                "Mouse effect engine inactive; restoring profiles."

            "$TRIGGER" 1 &
        fi
    done
}


if ! load_supported_usb_ids; then
    exit 1
fi


monitor_unlock &
pids+=("$!")

monitor_resume &
pids+=("$!")

monitor_devices &
pids+=("$!")

monitor_engine &
pids+=("$!")


log_message "Fixture-driven Serpent watcher started."


# An unexpected monitor exit is a real failure. An intentional signal is
# handled by shutdown_cleanly() and exits successfully.
wait -n "${pids[@]}"
result=$?

if [ "$shutting_down" = true ]; then
    exit 0
fi

log_message \
    "ERROR: An essential watcher monitor exited with status $result."

exit 1
