# Effects and Effects Workshop Guide

## Effect categories

Serpent effectively has three authoring categories:

1. **Software/plugin effects** — Python source exists.
2. **Composer/Workshop-native effects** — Python plus structured metadata can be reconstructed visually.
3. **Hardware-native fixture effects** — firmware/backend operations such as native Spectrum/Wave; no Python implementation exists to recover.

Treat those categories differently.

## Workshop safety boundary

Development candidate source is not trusted merely because it parses. The Workshop's isolated worker, watchdog/timeout behavior, synthetic events, and offline preview are a containment boundary. Preserve that architecture.

## New effect workflow

```text
New Effect
→ choose template/category
→ create unsaved source
→ edit
→ validate
→ offline preview
→ synthetic reactive events
→ optional live preview
→ Save/Save As
→ optional Install
```

Installation is a promotion step, not part of creation.

## Reactive design contract

A reactive effect should explicitly say what it consumes. Typical concepts include keyboard-key and mouse-button capability. Runtime monitors should be activated from declared capabilities.

Do not:
- probe method overrides to infer capability;
- open input devices inside an effect;
- assume event order is single-threaded/singular;
- hard-code device paths;
- hard-code a keyboard coordinate offset.

## State and determinism

Transient animation/event state belongs to effect instances and should survive the intended lifecycle without leaking across reloads. Use deterministic event random helpers where the SDK exposes them; global uncontrolled RNG complicates testing.

## Simultaneous events

Effects such as ripples, sparks, impacts, etc. must support multiple concurrent events. Never store only one global "last event" if the visual contract requires independent particles/waves.

## Topology adaptation

Effects should render into an abstract target/topology. Let topology policy collapse a spatial result to a uniform device where appropriate.

Examples:
- keyboard: full spatial field;
- multi-zone mouse: zone-aware collapse or per-region render;
- mousepad: one-position uniform collapse.

## Installed-effect template workflow

Safe behavior:

```text
installed canonical effect
→ open/use as template
→ unsaved authoring document
→ explicit Save/Save As creates first writable project target
```

Never mutate canonical installed source when the user merely wants a starting point.

If arbitrary Python cannot be reconstructed visually, open it as Advanced Python rather than lying about a complete conversion.

Hardware-native effects should be adapted as labeled starter approximations based on exposed semantics/parameters.

## Regression expectations

For any effect change, test:
- import/metadata;
- normal render;
- target topology handling;
- capability declarations;
- synthetic events;
- simultaneous events if reactive;
- reset/reload;
- preview worker;
- installed registry discovery if promoted.

## Production vs lab

`reactive-ripple` is production. Historical `reactive_ripple_test.py` / `reactive-ripple-test2.py` were experiment material and must remain outside the public release tree unless deliberately redesigned and promoted under a new contract.
