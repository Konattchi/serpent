#!/usr/bin/env bash

set -u

SERPENT_DIR="$HOME/.local/share/serpent"
OWNERSHIP="$SERPENT_DIR/serpent_core/ownership.py"

if ! /usr/bin/python3 "$OWNERSHIP" \
    claim sync --expected normal >/dev/null
then
    exit 1
fi

if ! /usr/bin/systemctl --user stop \
    serpent-individual.service
then
    /usr/bin/python3 "$OWNERSHIP" \
        release sync >/dev/null 2>&1 || true
    exit 1
fi

exit 0
