# Fixtures, Devices, and Backends Guide

## Why fixtures exist

Fixtures are the boundary that prevents Serpent from becoming a pile of product branches. They represent physical and logical facts about a device.

A fixture can carry:
- stable identity/reference data;
- zones/regions;
- backend selection;
- effects/capabilities;
- brightness;
- input mapping;
- sync-groupability;
- telemetry;
- safety requirements.

## Adding a device

### 1. Reconnaissance

Collect evidence without mutating the device where possible:
- USB IDs;
- OpenRazer model/identity;
- sysfs endpoints;
- brightness/effect files;
- zones;
- input interfaces;
- serial identity behavior;
- battery/charging telemetry;
- safety requirements.

### 2. Fixture draft

Create a fixture with only verified facts. Mark uncertain/reference-derived values according to the existing schema rather than inventing them.

### 3. JSON/schema validation

At minimum:

```bash
python3 -m json.tool fixtures/<id>.json >/dev/null
```

Then use Serpent's fixture loader/CLI validation.

### 4. Topology

Verify the fixture creates the expected physical positions/zones and capability policy.

### 5. Backend

Use an existing backend if it already implements the transport. Create/extend a backend only when the device requires genuinely new transport semantics.

### 6. Input

Declare input anatomy/mappings in the fixture. Coordinate corrections belong here.

### 7. Sync

Mark eligible zones through generic `sync_groupable` semantics.

### 8. Doctor

Doctor should discover/report the device without a model-specific diagnostic branch.

### 9. Live acceptance

Only after all prior stages:
- detect;
- verify endpoint writability;
- apply representative lighting;
- verify input;
- verify restore/reconcile.

## Fixture Editor

When fixture capabilities evolve, extend the FixtureDocument/editor model so new metadata:
- loads;
- displays;
- edits;
- saves;
- round-trips;
- can be inferred generically from trusted reference semantics where appropriate.

Do not teach the editor individual model names.

## Stable identity

A friendly/model name is not enough for physical-instance identity. Multi-device and scene/sync behavior rely on stable instance identity. Be careful when changing USB/serial matching or ghost-device migration.

## Backend distinction

Examples of backend classes in the 1.0 lineage include hardware-effect sysfs control and software-RGB sysfs control. A fixture selects what applies. UI/effects should not care which exact sysfs file is written.
