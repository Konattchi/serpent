# Runtime, Ownership, and Services Guide

## Services

Public user units:

```text
serpent-sync.service
serpent-individual.service
serpent-restore.service
serpent-watcher.service
```

They complement the OpenRazer daemon.

## Ownership invariant

At runtime, the owner determines which renderer should be active. Sync and individual/personal rendering must not race.

Before service-related work:

```bash
serpent doctor
systemctl --user status serpent-sync.service --no-pager
systemctl --user status serpent-individual.service --no-pager
systemctl --user status serpent-restore.service --no-pager
systemctl --user status serpent-watcher.service --no-pager
```

## Watcher lifecycle

The 1.0 watcher follows the graphical session, includes session lifecycle integration, and restarts on failure. Do not casually change it back to a generic boot/default target without re-testing logout/login behavior.

## Restore

Restore is a transaction/reconciliation operation, not a permanent competing renderer. Restore ordering matters: apply ownership/profile transitions in the same order production expects.

## GUI lifecycle

Normal close:
```text
X → hide to native tray → process remains
```

Session shutdown:
```text
Plasma session save/logout → hide/stop tray background work → accept close → QApplication.quit
```

Do not handle logout like a normal user close.

## Autostart

Autostart is a preference. Public installer must not force it. Installed autostart launches `serpent-gui --tray`.

## Debugging a service issue

Capture:
- current ownership;
- unit enabled/active state;
- last exit;
- logs;
- source/service unit hashes if patching;
- whether the issue occurs at normal launch, login, logout, resume, or device reconnect.

Then make a read-only lifecycle probe before editing.
