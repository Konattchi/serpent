# Serpent Architecture Guide for AI Agents

## Architectural thesis

Serpent's core design is fixture-driven. Fixtures describe hardware anatomy/capability; generic core code turns fixture data into topology, rendering, input, synchronization, and UI behavior; backends perform transport. The system evolved away from model-specific logic specifically so a third or fourth device can be added primarily through fixture metadata.

## Layering

```text
hardware/OpenRazer/sysfs
        ↑
backend transport
        ↑
fixture capability + physical topology
        ↑
rendering/effect semantics
        ↑
sync/personal ownership
        ↑
scene/runtime application
        ↑
GUI/CLI/tray
```

Reactive input enters alongside rendering:

```text
/dev/input → fixture mapping → EffectEvent → effect instance → renderer
```

## Data authority

Prefer these authoritative sources:

- fixture JSON for device anatomy/capability;
- effect registry/plugin metadata for installed software effects;
- scene repository for scene enumeration;
- sync/profile model for current group membership;
- ownership module/service state for writer ownership;
- systemd units for lifecycle;
- Doctor for integrated operational state.

Do not duplicate authoritative lists in UI code.

## Genericity test

Whenever adding a condition, ask:

> If the same capability appeared on a completely different vendor/model tomorrow, would this code still be correct?

If not, the condition probably belongs in fixture metadata, capability metadata, or a backend adapter.

## Logical regions vs physical devices

A physical fixture can expose multiple logical lighting regions. Synchronization can select independently groupable regions. Therefore:

- device count != sync member count;
- per-member brightness can differ within one physical device;
- identity must include fixture instance + region;
- group-aware code must not collapse everything to model name.

## Effect/runtime split

Effects should describe/render visual behavior. Hardware-native effects are represented by fixture/backend IDs; software effects are Python implementations/plugins. Do not fake Python source for firmware behavior except through explicit starter/adaptation templates in the Workshop.

## Ownership

Ownership is a state machine, not a side effect of which process happened to start last. Scene application, GUI controls, restore, sync, and personal rendering must all respect the same ownership contract.

## Compatibility philosophy

Preserve stable Plugin API and fixture contracts unless a breaking change is genuinely necessary. Prefer additive metadata and adapters. When a breaking change is unavoidable, document migration and update Doctor/tests in the same change.

## Architecture smell list

Red flags:

- `if model == ...` in generic rendering/sync code;
- direct sysfs writes from GUI callbacks;
- tray actions implementing their own Scene application logic;
- effects opening `/dev/input` themselves;
- effect plugin install code that writes over its source target without explicit save/install lifecycle;
- a second scene/profile schema;
- a second renderer created only for preview;
- service changes without ownership checks.
