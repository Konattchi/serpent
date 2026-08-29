#!/usr/bin/env bash

set -u

SERPENT_DIR="$HOME/.local/share/serpent"
OWNERSHIP="$SERPENT_DIR/serpent_core/ownership.py"
RUNTIME_ROOT="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
RELOAD_MARKER="$RUNTIME_ROOT/serpent-sync-engine-reload"
DISABLE_MARKER="$RUNTIME_ROOT/serpent-sync-disable"

# `serpent sync reload-engine` creates this short-lived runtime marker
# immediately before asking systemd to restart the daemon. During that
# specific stop/start cycle we deliberately keep `sync` ownership and do
# not restore normal device profiles. ExecStartPre can then reclaim the
# already-owned `sync` state and launch the fresh Python process cleanly.
if [ -f "$RELOAD_MARKER" ]; then
    rm -f "$RELOAD_MARKER"
    exit 0
fi

# Only an explicit `serpent sync disable` is allowed to change
# persisted ownership from sync to normal. Service teardown caused by
# logout/reboot/shutdown must preserve sync for the next login.
if [ ! -f "$DISABLE_MARKER" ]; then
    exit 0
fi

rm -f "$DISABLE_MARKER"

owner="$(
    /usr/bin/python3 "$OWNERSHIP" get 2>/dev/null
)"

if [ "$owner" = "sync" ]; then
    /usr/bin/python3 "$OWNERSHIP" \
        release sync >/dev/null 2>&1 || \
    /usr/bin/python3 "$OWNERSHIP" \
        set normal >/dev/null 2>&1 || true
fi

/usr/bin/systemctl --user start \
    serpent-individual.service >/dev/null 2>&1 || true

"$HOME/.local/bin/serpent" \
    keyboard apply-profile >/dev/null 2>&1 || true

exit 0
