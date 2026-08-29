# Testing, Probing, and Debugging Guide

## The Serpent engineering method

Serpent's development history repeatedly validated one principle:

> Evidence before mutation.

Use this protocol.

## Read-only probe

A probe is appropriate when:
- source structure is unclear;
- runtime ownership is unclear;
- you need exact hashes/modes;
- a GUI path is taking an unexpected branch;
- a worker receives the wrong identity;
- a fixture property may be inferred in multiple places.

The probe should print enough evidence to choose one patch. It should not "helpfully fix" anything.

## Builder

A builder creates a candidate and supporting gate/installer. It should be source-locked.

## Gate

A gate proves a specific contract. Name what it tests and what it intentionally does not test.

Good gate statement:

```text
STATIC/OFFSCREEN:
- no live profile mutation
- no service restart
- no sysfs writes
- no input-device acquisition
```

## Installer

Installer:
- verifies source lock;
- verifies candidate hash;
- preserves file modes;
- creates backup during active development;
- modifies only declared paths;
- prints post-install hash.

## Failure response

If an install causes a crash:
1. stop;
2. collect traceback/log;
3. inspect exact modified file;
4. restore known-good backup if needed;
5. reproduce with probe;
6. fix builder/gate;
7. retest candidate;
8. install again.

Do not stack speculative fixes on a broken unknown state.

## Whole-system testing

Static/offscreen tests should not pretend to test:
- real hardware writes;
- real `/dev/input`;
- actual systemd transitions;
- physical hotplug;
- compositor/logout;
- packaging outside the test tree.

Those need real acceptance.

## Doctor

Doctor runs last. A gate can be green while Doctor exposes a stale diagnostic contract or service-policy mismatch. Update Doctor when architecture changes, not months later.
