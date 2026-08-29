# Release, Packaging, and Repository Hygiene Guide

## Canonical source

Public development should occur in the clean source repository, not the installed runtime.

## Public packaging assets

The repository includes:
- `bin/serpent`
- `bin/serpent-gui`
- desktop template;
- autostart template;
- four systemd user units;
- `install.sh`;
- `uninstall.sh`;
- README.

## Installer behavior

Install to user-local paths using `$HOME`/XDG conventions. Public files must not embed a developer-specific absolute home.

Do:
- install payload;
- install launchers;
- install desktop file;
- install units;
- daemon-reload.

Do not:
- force service enablement;
- force autostart;
- copy repository-only packaging directories into the installed application payload.

## Isolated install certification

Before release, test the actual installer against a temporary fake HOME/XDG environment, with service operations stubbed if necessary. Verify:
- installed file locations;
- hashes;
- desktop portability;
- no forced autostart;
- packaging metadata exclusion;
- Python compile;
- actual uninstall removes artifacts.

## Repository hygiene

Reject:
- milestone builders;
- probes;
- candidates;
- backups;
- snapshots/reports;
- `__pycache__`;
- `.pyc`;
- absolute local home paths;
- obsolete branding;
- experimental test effects;
- giant release archives.

Historical material belongs in separate archives, not the shipping tree.

## License

A public repository should contain an explicitly chosen license. This is a policy/legal decision for the maintainer, not for an AI to invent.

## Release manifest

For each release, create a fresh manifest of important hashes/modes. Historical 1.0 hashes prove the original certified release but should not block legitimate 1.0.1+ changes.

## Final checklist

```text
source compile
JSON validate
shell syntax
offscreen tests
Doctor
live hardware
service ownership
startup/tray
logout/login
isolated install
isolated uninstall
repository hygiene
version/branding
license
Git commit/tag/release
```
