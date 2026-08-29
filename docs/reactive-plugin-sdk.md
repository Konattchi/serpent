# Serpent 0.8 Reactive Effect Plugin SDK

This document defines the developer contract for reactive effects in Serpent
0.8.x. It is intentionally small: a reactive effect is still an ordinary
Effect Plugin API 1 plugin with explicit input and render capabilities.

## 1. Plugin metadata

A new reactive plugin should declare both fields explicitly:

```python
EffectPluginSpec(
    id="my-effect",
    name="My Effect",
    description="...",
    effect_class=MyEffect,
    input_capabilities=("keyboard",),
    render_targets=("keyboard", "mouse"),
    parameters=(...),
)
```

Supported input capabilities in 0.8:

- `keyboard`
- `mouse`

Supported render targets in 0.8:

- `keyboard`
- `mouse`

`input_capabilities` determines which fixture-derived event sources Serpent
opens. `render_targets` describes which device classes the effect is designed
to render on. They are deliberately independent.

For example:

```python
input_capabilities=("keyboard",)
render_targets=("keyboard", "mouse")
```

means that only keyboard input is monitored, while the same key event may
produce a full keyboard animation and a simpler companion mouse animation.

Legacy Plugin API 1 effects that omit `input_capabilities` remain supported,
but new reactive plugins should always declare their capabilities explicitly.

## 2. EffectEvent contract

Reactive effects receive immutable `EffectEvent` values through:

```python
def handle_event(self, event: EffectEvent) -> None:
    ...
```

The currently relevant event kinds are:

- `key-press`
- `key-release`
- `key-repeat`
- `mouse-press`

Common fields:

- `kind`: event category
- `timestamp`: effect-render epoch timestamp
- `source`: presentation-neutral source identity
- `code`: Linux/OpenRazer-derived key/button name
- `value`: raw logical value when applicable
- `row`: spatial keyboard row when available
- `column`: spatial keyboard column when available

Keyboard spatial coordinates have already passed through fixture-defined
mapping and coordinate correction. Plugins must not contain device-specific
DeathStalker/Naga offsets or `/dev/input` paths.

Mouse events currently have no matrix row/column. A mouse-target animation
should therefore be device-local rather than pretending it has keyboard
geometry.

## 3. Event handling rules

`handle_event()` runs on Serpent's synchronization/render thread.

Plugins should:

- keep the handler short;
- update only effect-owned Python state;
- never open input devices themselves;
- never write lighting hardware directly;
- never call `EVIOCGRAB`;
- never block waiting for I/O;
- tolerate events that they do not use;
- normally spawn animation state only from `*-press` events.

Multiple events can arrive between frames. Keep independent animation objects
when simultaneous effects should coexist.

Example:

```python
def handle_event(self, event):
    if event.kind != "key-press":
        return
    if event.row is None or event.column is None:
        return
    self._flashes.append(
        Flash(event.row, event.column, event.timestamp)
    )
```

## 4. State lifetime and reloads

Effect object state is transient.

State that should live in the effect object:

- active ripples;
- explosions in flight;
- crack paths;
- particles;
- temporary flashes;
- procedural animation state.

State that should NOT live in the effect object:

- selected effect id;
- user parameter configuration;
- ownership;
- service state;
- hardware paths.

A hard `serpent sync reload-engine` starts a fresh sync-engine process.
Successful in-process reloads also replace the active effect instance and
force-reconcile reactive sources. Do not expect transient animation objects
to survive either reload boundary.

## 5. Keyboard versus companion-device rendering

Serpent deliberately permits different visual implementations on different
target topologies.

A typical spatial reactive effect may use:

```python
if target.rows < 3 or target.columns < 3:
    return self._render_companion_target(...)
return self._render_keyboard(...)
```

The companion animation should share the same visual language rather than
attempting to copy impossible geometry.

Examples:

- Ripple: spatial A-B-A wave on keyboard; local pulse on mouse.
- Explosion: local thermal shockwave on keyboard; thermal ignition burst on mouse.
- Cracking Rock: branching fissures on keyboard; crack-colour pulse on mouse.
- Lightning: jagged bolt on keyboard; sharp flash/afterglow on mouse.

## 6. Rendering rules

`render()` must always return a valid `EffectFrame`.

Use `target.active_cells` for spatial targets so nonexistent matrix cells stay
dark.

Keep device writes, brightness policy, synchronization ownership, and service
control outside the plugin. Plugins render colours only.

If an effect cannot express its full geometry on a target, return a deliberate
fallback rather than failing.

## 7. Deterministic randomness

Procedural effects such as cracks, lightning, sparks, meteors, rain and
fireworks need randomness. Tests must still be reproducible.

Do not build core animation geometry from the process-global random stream.
Instead keep an effect-owned `random.Random` or derive a local generator from
a deterministic event seed.

Conceptually:

```python
seed = hash((event.code, round(event.timestamp * 1000), serial))
rng = random.Random(seed)
```

Tests can then inject or reproduce known seeds.

The exact seed algorithm is effect-owned in Plugin API 1, but a given seed
must generate repeatable geometry.

## 8. Error isolation

A plugin exception must never intentionally escape as a hardware-management
strategy. Serpent already contains handler/render exception isolation and
plugin quarantine behavior.

Plugins should still validate internal assumptions and fail with ordinary
Python exceptions when state is genuinely invalid. Do not catch every
exception and silently continue with corrupt state.

## 9. Minimal reactive plugin checklist

Before installing a reactive plugin:

1. `python3 -m py_compile plugin.py`
2. `EffectPluginSpec.validate()` passes.
3. Explicit `input_capabilities` declared.
4. Explicit `render_targets` declared.
5. `handle_event()` does not access `/dev/input`.
6. No `EVIOCGRAB`.
7. No direct hardware/service writes.
8. Multiple simultaneous events behave intentionally.
9. Expired transient state is removed.
10. Keyboard spatial coordinates are consumed as supplied.
11. Small-target fallback is intentional when render target includes mouse.
12. Offline tests prove animation changes without touching live hardware.

The accompanying `reactive_key_flash.py` is the canonical small example for
this contract.

## M8.6 offline developer tools

Serpent installs an offline helper command:

```text
serpent-effect-dev validate ./my_effect.py
serpent-effect-dev inspect ./my_effect.py
serpent-effect-dev simulate ./my_effect.py --row 3 --column 5
```

These commands import/render the supplied file without copying it into the
live plugin directory and without opening input devices or lighting hardware.

Procedural effects may use:

```python
from serpent_core.effect_random import event_rng

rng = event_rng(event, serial=self._serial, namespace="my-effect")
```

`event_rng()` uses a stable process-independent seed so procedural tests can
be reproduced exactly.
