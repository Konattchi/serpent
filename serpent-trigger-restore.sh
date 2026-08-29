#!/usr/bin/env bash

set -u

delay="${1:-2}"

exec 9>"$XDG_RUNTIME_DIR/serpent-restore-trigger.lock"

/usr/bin/flock -n 9 || exit 0

/usr/bin/sleep "$delay"

/usr/bin/systemctl --user restart serpent-restore.service
result=$?

if [ "$result" -eq 0 ]; then
    /usr/bin/logger -t serpent-watcher \
        "Triggered successful ownership-aware Serpent restoration."
else
    /usr/bin/logger -t serpent-watcher \
        "ERROR: Serpent restoration failed with status $result."
fi

exit "$result"
