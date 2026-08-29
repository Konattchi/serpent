# Serpent AI Engineering Manual

**Project:** Serpent  
**Release baseline:** 1.0.0  
**Purpose:** Give an AI coding agent enough architectural, operational, and procedural context to modify Serpent safely without rediscovering the project from scratch.

> **Prime directive:** Serpent is a fixture-driven RGB runtime, not a collection of device-specific scripts. Probe first, preserve ownership boundaries, make the smallest possible change, validate offscreen/static behavior before touching live runtime, and use `serpent doctor` as the final operational truth.

---

## 1. What Serpent Is

Serpent is a Linux RGB-control application and runtime built around a fixture-driven architecture. It combines:

- device fixtures describing physical lighting/input anatomy;
- backend contracts for hardware and software RGB transport;
- rendering and effect systems;
- reactive keyboard/mouse input;
- synchronized multi-device/group rendering;
- independent per-device/personal rendering;
- scenes and runtime ownership transitions;
- an Effects Workshop for browsing, previewing, creating, validating, and installing effects;
- a Fixture Editor for teaching Serpent about devices without hard-coding model knowledge;
- systemd user services for synchronized rendering, individual rendering, restore behavior, and watcher/recovery behavior;
- a PySide6 GUI with tray integration;
- a `doctor.py` diagnostic that is part of the release contract, not an optional debug helper.

The architecture evolved specifically to avoid constructs such as:

```python
if device == "naga":
    ...
elif device == "deathstalker":
    ...
```

When adding a new device, effect, zone, or capability, prefer extending fixture metadata and generic contracts over embedding model-specific branches in the core.

---

## 2. Repository vs Installed Runtime vs Lab

There are three conceptually different trees. Do not confuse them.

```text
~/Projects/serpent/         canonical GitHub/release source
~/Projects/serpent-lab/     private/local experiments and unfinished effects
~/.local/share/serpent/     installed runtime copy used by the current machine
```

### Rules

1. **GitHub source is canonical for public development.**
2. **The installed runtime is not a development-history archive.** It should remain clean.
3. **Experimental effects belong in `serpent-lab`, not the public repository, until promoted deliberately.**
4. Do not turn `~/.local/share/serpent` into the Git repository.
5. Build/test changes against a source or candidate tree, then install/promote intentionally.

At the 1.0.0 cleanup, the development-history mountain was removed from the live install. Do not reintroduce milestone builders, probes, candidates, backup directories, generated `.pyc`, or scratch files into the installed root.

---

## 3. Current High-Level Tree

A 1.0.0 installation/source tree contains the following important areas:

```text
serpent/
├── docs/
├── examples/
├── fixtures/
├── gui/
├── plugins/
│   └── effects/
├── projects/
├── resources/
├── serpent_core/
├── doctor.py
├── effect_dev.py
├── fixture_usb_ids.py
├── fixtures_cli.py
├── individual_engine.py
├── mouse_effects.py
├── serpent.py
├── serpent-restore.sh
├── serpent-sync-start.sh
├── serpent-sync-stop.sh
├── serpent-trigger-restore.sh
├── serpent-watcher.sh
└── sync_engine.py
```

The public repository additionally contains release/install material:

```text
bin/
├── serpent
└── serpent-gui

packaging/
├── applications/serpent.desktop
├── autostart/serpent.desktop
└── systemd/user/
    ├── serpent-individual.service
    ├── serpent-restore.service
    ├── serpent-sync.service
    └── serpent-watcher.service

install.sh
uninstall.sh
README.md
```

Treat this map as a navigation index, not as permission to edit every file casually. Before modifying a subsystem, inspect its imports/callers and establish a source lock.

---

## 4. Architecture in One Diagram

```text
                    ┌───────────────────────┐
                    │      PySide6 GUI      │
                    │ app / Workshop /      │
                    │ Scenes / Sync /       │
                    │ Fixture Editor        │
                    └───────────┬───────────┘
                                │
                                v
┌───────────────┐     ┌───────────────────────┐
│ Fixture JSON  │────>│ fixture/topology model│
└───────────────┘     └───────────┬───────────┘
                                  │
                    ┌─────────────┴─────────────┐
                    v                           v
          ┌──────────────────┐        ┌────────────────────┐
          │ Effects/Plugins  │        │ Sync/Scene planning │
          └────────┬─────────┘        └─────────┬──────────┘
                   │                            │
                   └──────────────┬─────────────┘
                                  v
                         ┌──────────────────┐
                         │ Rendering /      │
                         │ ownership layer  │
                         └────────┬─────────┘
                                  v
                         ┌──────────────────┐
                         │ Backend contract │
                         └────────┬─────────┘
                                  v
                         ┌──────────────────┐
                         │ OpenRazer/sysfs  │
                         │ device endpoints │
                         └──────────────────┘

Reactive path:

Linux input device
    ↓
fixture-declared input source/mapping
    ↓
Serpent input source
    ↓
EffectEvent
    ↓
device-aware routing
    ↓
persistent effect instance
    ↓
renderer
```

The important property is **reuse of one runtime path**. Scenes, tray actions, GUI controls, and automation-style entry points should call existing runtime/application layers rather than creating parallel renderers or hardware writers.

---

## 5. Architectural Invariants

An AI modifying Serpent should treat these as strong constraints.

### 5.1 Fixtures describe devices

Fixtures should describe:

- device identity/reference information;
- zones/regions;
- controllability;
- backend;
- available effects/capabilities;
- brightness behavior;
- input anatomy/mapping;
- sync-groupability;
- safety requirements;
- any relevant telemetry.

A generic core should consume that metadata.

### 5.2 Backends implement transport/capability, not product personality

The backend knows how to perform a class of write. The fixture knows what the device exposes.

### 5.3 Ownership is explicit

Only one runtime path should own lighting for a given operating mode.

Typical owner concepts are synchronized/group rendering versus individual/personal rendering. Do not start a second writer merely because a new feature needs lighting.

### 5.4 Scenes reuse the existing runtime

A Scene should produce an application plan and pass through the established ownership/profile/service paths. It must not create a scene-specific rendering engine.

### 5.5 Reactive input is non-exclusive

Production input monitoring is read-only/non-exclusive. Serpent must not monopolize keyboard/mouse event devices.

### 5.6 Device-specific correction belongs in fixtures

A physical layout offset, zone mapping, input interface, or model quirk should be fixture metadata whenever possible. A historical example was keyboard coordinate correction being moved from special-case Python into fixture input anatomy.

### 5.7 Effects declare capabilities

Reactive effects should declare the events/capabilities they require. Runtime monitoring should be activated because an effect declares it, not merely because some method happens to be overridden.

### 5.8 Development candidates are contained

Untrusted/in-development effect source is validated/previewed through the Workshop worker boundary. Do not weaken that boundary to make authoring more convenient.

### 5.9 Installed effects are not edited in place

Opening an installed effect for authoring must produce an unsaved/editable authoring state or a separate copy/adaptation. The installed original is never silently made the save target.

### 5.10 Hardware-native effects are not decompiled

Firmware/native effects such as hardware Spectrum/Wave do not have a Python implementation to reconstruct. Workshop adapters for them are explicit starter approximations based on known semantics, not fake decompilation.

---

## 6. Ownership and Service Model

The service layer is part of Serpent's runtime correctness.

Public packaging includes:

- `serpent-sync.service`
- `serpent-individual.service`
- `serpent-restore.service`
- `serpent-watcher.service`

### Expected behavioral model

**Sync owner**
- synchronized lighting is active;
- `serpent-sync.service` owns the synchronized render path;
- individual service should not simultaneously fight for the same lighting.

**Individual/personal owner**
- individual/personal renderer owns applicable devices/zones;
- sync path is inactive or relinquishes those members according to the runtime contract.

**Restore**
- restores saved profiles/state using the established ownership rules;
- it is not a second permanent renderer.

**Watcher**
- observes/reconciles runtime lifecycle and recovery;
- in 1.0.0 it is tied to the graphical user session and restarts on failure.

### Critical rule

Before changing services, ownership, restore, startup, or logout behavior:

```bash
systemctl --user status serpent-sync.service
systemctl --user status serpent-individual.service
systemctl --user status serpent-restore.service
systemctl --user status serpent-watcher.service
serpent doctor
```

Then inspect the relevant source and service unit. Do not infer ownership from GUI appearance.

---

## 7. GUI and Session Lifecycle

The GUI is PySide6-based, with the main application in `gui/app.py`.

Important behavioral contracts at 1.0.0:

- normal window close hides Serpent to the native system tray;
- tray-only startup is supported;
- session logout must bypass close-to-tray behavior and allow the application to terminate;
- the tray icon is native rather than a custom replacement;
- startup/autostart is a user preference;
- the release banner and visual identity are resources, not generated at runtime;
- About remains under Help → About;
- runtime status shown in the UI should represent real state rather than decorative placeholders.

KDE/Wayland may append application identity to the visible window title. Do not "fix" compositor-owned title decoration by casually changing application metadata; that can affect grouping, tray behavior, and notifications.

### GUI change workflow

Before changing a GUI feature:

1. locate the exact widget/class/method;
2. inspect container/layout insertion order, not just construction order;
3. identify callbacks into runtime/service layers;
4. determine whether an offscreen Qt test can prove the change;
5. patch only the narrow section;
6. compile;
7. run offscreen/static gate;
8. launch and perform a manual acceptance check.

A historical failure mode was a static/layout probe concluding that two panels were ordered correctly while the actual rendered Qt hierarchy proved otherwise. **Rendered behavior outranks a brittle source-string assertion.**

---

## 8. Effects Workshop

The Effects Workshop grew from the earlier Effect Lab. Its safety boundaries are deliberate and should be preserved.

Core ideas:

- installed-effect catalog;
- metadata/capability display;
- normal-user controls;
- developer/authoring mode;
- source editor;
- validation;
- isolated worker process for candidate code;
- watchdog/timeout behavior;
- offline preview;
- synthetic keyboard/mouse event injection;
- target selection;
- reset;
- live preview;
- save/save-as/install lifecycle;
- safe uninstall for user-installable effects;
- installed-effect-to-template/adaptation workflow.

### Do not fork the preview architecture

Installed trusted effects and development candidates can take different loading paths, but they should converge on shared rendering semantics where appropriate. Do not invent a second independent preview renderer simply to solve one adapter bug.

### Opening installed effects

The safe authoring contract is:

```text
Installed Effects
    ↓
Use Selected as Template / authoring entry
    ↓
load source or generate explicit adapter
    ↓
open as unsaved authoring state
    ↓
Validate
    ↓
Preview/Test
    ↓
Save / Save As
    ↓
optional Install Effect
```

The first actual project file should appear only when the user explicitly saves. Merely opening an installed effect should not litter the project tree.

### Composer-native vs arbitrary Python vs hardware-native

**Composer-native software effect**
- reconstruct structured controls when possible.

**Arbitrary installed Python effect**
- use safe import;
- reconstruct what can be represented;
- fall back to Advanced Python for semantics the visual editor cannot represent;
- never pretend a lossy conversion is exact.

**Hardware-native effect**
- generate an explicitly labeled starter/approximation when useful;
- do not claim the firmware implementation was reconstructed.

---

## 9. Creating an Effect

The 1.0 architecture supports effect authoring in the Workshop. Historically the creator exposed starting points such as:

- Blank / Static
- Animated Matrix
- Reactive Keyboard
- Reactive Mouse
- Reactive Keyboard + Mouse

The generated effect is ordinary Serpent plugin source and is not installed automatically.

### AI workflow for a new effect

1. **Decide the topology semantics.**
   - full spatial/matrix effect?
   - uniform device-local effect?
   - per-zone?
   - keyboard reactive?
   - mouse reactive?
   - both?

2. **Choose or inspect an existing effect with similar semantics.**
   Do not copy an effect merely because the animation looks similar; choose one using the same runtime/rendering contract.

3. **Define identity and metadata.**
   Give the effect a stable, unique ID and human-readable name/description.

4. **Declare capabilities.**
   Reactive events must be explicit.

5. **Keep transient state inside the effect instance.**
   Effects should survive/reinitialize cleanly across reload boundaries.

6. **Use deterministic/random helpers where the SDK contract provides them.**
   Avoid global random state that makes event behavior impossible to reproduce.

7. **Handle simultaneous events.**
   Do not assume only one key/click event is active.

8. **Render according to topology.**
   A large keyboard matrix and a one-position mousepad are not the same canvas.

9. **Validate in containment.**

10. **Preview with synthetic events.**

11. **Test at least one keyboard-like and one low-resolution/uniform target if capability allows.**

12. **Install only after validation.**

13. **Run Doctor after promotion if the effect affects capabilities/runtime discovery.**

### Effect identity examples from the mature reactive catalog

The 1.0 release lineage includes reactive effects such as:

- Cracking Rock
- Explosion
- Flying Hearts
- Implosion
- Meteor Explosion
- Reactive Ripple
- Sparks
- Spectrum Ripples
- Tesla Lightning

Do not confuse **Reactive Ripple** (production effect) with the historical **Reactive Ripple Test** experiment. The test effect was intentionally removed from the public release/GitHub tree and preserved only as local lab material.

### Visual-contract lesson

Some effects have intentional identities that should not drift during refactors. Historically:

- Reactive Ripple: long-travel wave behavior;
- Explosion: short local thermal blast, not a renamed Ripple;
- Fire: continuous spatial flame behavior.

When refactoring render helpers, regression-test the effect's visual contract, not just syntax/API compatibility.

---

## 10. Fixtures and Adding Devices

Adding a new device should mostly be a fixture/backend exercise.

Relevant public/runtime files include:

```text
fixtures/
fixture_usb_ids.py
fixtures_cli.py
gui/fixture_editor_dialog.py      # when present in source tree
serpent_core/... fixture/topology modules
```

### Device-addition workflow

1. **Reconnaissance first.**
   Identify USB/device identity, OpenRazer representation, sysfs endpoints, zones, capabilities, brightness controls, input interfaces, and safety properties.

2. **Do not write to hardware during reconnaissance unless explicitly required.**
   Prefer read-only discovery.

3. **Create/modify fixture metadata.**

4. **Validate JSON syntax.**
   Example:
   ```bash
   python3 -m json.tool fixtures/<fixture>.json >/dev/null
   ```

5. **Validate fixture schema/semantic loader.**

6. **Check topology generation.**

7. **Check rendering capability.**

8. **Check sync-groupability by zone.**

9. **Check reactive input mapping if relevant.**

10. **Check Doctor reporting.**

11. **Only then perform live endpoint acceptance.**

### `sync_groupable`

Per-zone sync eligibility is generic metadata. It should be explicit or inferred from generic semantics such as confirmed + controllable. Do not add a rule equivalent to "if model is Naga, zones X/Y are groupable."

Reserved/non-controllable zones should not be treated as synchronization members.

### Fixture Editor principle

The editor exists so future hardware support does not require source surgery. If a new fixture property is needed, extend the fixture document/editor contract generically and make loaded/reference fixtures round-trip it.

---

## 11. Rendering and Topology

Serpent distinguishes physical topology from effect semantics.

A device can support:

- full spatial rendering;
- uniform spatial collapse;
- one or multiple positions/zones;
- native hardware effects;
- software-rendered RGB.

An effect that produces a spatial field may be collapsed for a low-resolution target. That is not necessarily an error; it is part of the topology/capability policy.

### AI checklist before changing rendering

Ask:

- Is this a geometry problem or a transport problem?
- Does the fixture expose positions/zones correctly?
- Is the target capability `spatial`, `uniform`, or hardware-native?
- Is brightness applied per physical device, per logical region, or per group member?
- Does sync operate on regions rather than only whole devices?
- Will the change preserve independent personal rendering?
- Does the change accidentally encode one model's geometry into a generic helper?

Core modules such as `serpent_core/rendering.py` and `serpent_core/topology.py` should remain generic.

---

## 12. Sync and Multi-Zone Membership

Sync evolved from whole-device assumptions into group-aware region membership.

Conceptually:

```text
Sync Group
    ├── fixture-instance A : region matrix
    ├── fixture-instance B : region matrix
    ├── fixture-instance C : region logo
    └── fixture-instance C : region side-buttons
```

The group has effect semantics; members can have their own brightness.

### Modification rules

- Membership is based on physical fixture instance + region.
- Never infer membership from a display name alone.
- Preserve stable physical identity.
- Preserve per-member brightness.
- Keep unsupported/reserved regions out.
- When adding a new fixture, test at least two independently groupable zones if the hardware exposes them.
- Doctor should report logical members generically rather than with device-specific branches.

---

## 13. Scenes

Scenes reuse existing profile, sync, ownership, and runtime machinery.

Conceptual flow:

```text
Scene
  ↓
application plan
  ↓
Serpent scene runtime adapter
  ↓
existing ownership/profile/service transitions
  ↓
renderer/backend
  ↓
devices
```

The GUI Scene Library, tray scene actions, CLI scene commands, and any future automation should enumerate/apply through the same scene repository/application path.

### Never do this

```text
Tray Scene button
   ↓
custom one-off hardware write code
```

Instead, the tray should call the same authoritative scene repository and `apply_scene(...)`/runtime path used by the Scenes UI.

---

## 14. Reactive Input

Reactive input is an explicit subsystem.

Important contracts:

- read-only/non-exclusive device access;
- fixture-declared interfaces/mapping;
- keyboard and mouse sources fail independently;
- event exceptions are isolated;
- monitoring opens only when required by effect capabilities;
- duplicate-event behavior is controlled;
- reload/start/stop lifecycle is clean;
- device identity is attached to events;
- effects must not contain DeathStalker/Naga-specific input knowledge.

### Input mapping

Physical input and lighting coordinates may differ. Correct this through fixture input anatomy:

```text
physical key/button
    ↓
fixture mapping
    ↓
lighting coordinate / reactive zone
```

Do not hide coordinate corrections inside one built-in effect.

---

## 15. Doctor Is a Product Contract

`doctor.py` is part of Serpent's release definition.

At 1.0.0 it validates categories including:

```text
Installation
Fixtures
Profiles
Sync Membership
Rendering
Services
Devices
Reactive Input
Safety
Summary
```

Doctor is valuable because it crosses subsystem boundaries and catches drift that isolated unit/static checks can miss.

### Rules for modifying Doctor

- Do not make it device-specific when the runtime is generic.
- Use the same authoritative fixture/topology/profile contracts as production.
- Service policy must reflect ownership: a service being inactive can be correct.
- A user unit may be installed but intentionally disabled.
- Executable/readability assumptions must match how scripts are actually invoked.
- A warning is not automatically a failure. Understand the warning's policy.

### Release expectation

A successful release/runtime acceptance should end with Doctor exit code `0`, with any known non-blocking warning understood and documented.

---

## 16. Safe AI Modification Protocol

This is the most important section for an autonomous coding agent.

### Phase A — Understand

Before writing:

1. identify the subsystem;
2. identify live/source tree;
3. inspect relevant files;
4. inspect call sites/imports;
5. inspect service/ownership state if runtime-related;
6. run Doctor if the change could cross subsystem boundaries;
7. write down the invariant you are trying to preserve.

### Phase B — Probe

When the exact architecture is uncertain, create a **read-only probe**.

A good probe:

- reads exact source/runtime state;
- prints paths/hashes/modes;
- locates precise anchors;
- reports service state without changing it;
- never performs hardware writes unless specifically called an acceptance test;
- emits PASS/FAIL in a machine-readable-ish form;
- proves which branch/path is actually used.

If a probe can answer the question, do not guess.

### Phase C — Source lock

Hash all files the installer/builder expects to modify:

```python
sha256(file)
```

Refuse to proceed if the current file is not the exact version the patch was built against.

This prevents applying a perfectly valid patch to the wrong generation of the source.

### Phase D — Candidate

For a risky or broad change, create a candidate outside the live runtime. Compile and inspect it before installation.

### Phase E — Static/offscreen gate

Use the strongest non-mutating proof available:

- AST parse;
- `python3 -m py_compile`;
- JSON load/`json.tool`;
- `bash -n`;
- offscreen Qt construction;
- synthetic fixture/topology;
- synthetic events;
- temporary files/state;
- isolated worker;
- direct function-level assertions.

Explicitly state what the gate **does not** test.

### Phase F — Install/promote

Installer should:

- recheck source locks immediately before writing;
- create a rollback copy when modifying an installed runtime during development;
- preserve file modes;
- write atomically when practical;
- modify only declared files;
- not restart unrelated services;
- print resulting hashes.

### Phase G — Runtime acceptance

Depending on scope:

- relaunch GUI;
- exercise exact changed path;
- verify service owner;
- verify real hardware where required;
- run Doctor.

### Phase H — Cleanup

After promotion:

- remove candidate/probe/cache debris from the live root;
- keep experimental source in lab, not runtime;
- keep GitHub tree release-clean.

---

## 17. Testing Tiers

Do not treat all green tests as equivalent.

### Tier 1: Syntax/static

Useful for:
- import mistakes;
- malformed Python;
- malformed JSON;
- shell syntax;
- missing anchors.

Cannot prove:
- live Qt hierarchy;
- actual worker routing;
- systemd state;
- hardware behavior.

### Tier 2: Synthetic/offscreen

Useful for:
- fixture/topology construction;
- rendering logic;
- reactive injected events;
- Workshop construction;
- scene/sync contracts;
- safe temporary-state behavior.

Cannot prove:
- physical endpoint writes;
- actual `/dev/input` access;
- compositor/session lifecycle;
- live service transitions;
- device discovery.

### Tier 3: Isolated install simulation

Use a temporary HOME/XDG layout and stub service manager where appropriate. Proves install/uninstall layout and portability without contaminating the real system.

### Tier 4: Live acceptance

Use for:
- hardware writes;
- device discovery;
- service ownership;
- login/logout/reboot;
- tray behavior;
- actual keyboard/mouse reactive input.

### Tier 5: Doctor

Run after live acceptance to catch cross-subsystem regressions.

---

## 18. Installer and Packaging Rules

The public repository provides install/uninstall support.

The installer should:

- determine repository root;
- install to user-local/XDG paths;
- install launchers to `~/.local/bin`;
- materialize desktop icon paths appropriately;
- install user systemd units;
- run `systemctl --user daemon-reload`;
- **not force service enablement**;
- **not force autostart**;
- exclude repository-only packaging metadata from the installed application payload.

The uninstall path should remove installed artifacts deliberately and stop/disable relevant units best-effort without deleting unrelated user data outside the installation contract.

Portability rule: public templates must not contain one developer's absolute home path.

---

## 19. Startup, Tray, and Logout

Startup is a preference, not a requirement.

Expected behavior:

- normal launch can show the GUI;
- autostart launches tray-only;
- closing the main window normally hides to tray;
- session logout must actually quit;
- watcher service follows graphical-session lifecycle;
- do not replace the native tray unless there is a proven requirement.

When touching this area, test at least:

```text
manual launch
normal X close
restore from tray
tray-only autostart
logout with GUI visible
logout with notifications/popups previously shown
login again
watcher state
```

---

## 20. Common Failure Modes and Lessons

### 20.1 Guessing from stale architecture

The project changed significantly across versions. Historical milestones are evidence of why a contract exists, not authority over current 1.0 source.

**Rule:** current source + current Doctor + current fixtures win.

### 20.2 Static gate proves wrong thing

A test can assert the wrong source string and still be green.

**Rule:** design gates around behavior/structure, and perform live visual acceptance for GUI layout.

### 20.3 Patch applied at wrong scope/indentation

Large source-surgery scripts can compile while placing lifecycle logic in the wrong class/method.

**Rule:** AST-aware or exact-anchor patches; candidate compile; offscreen construction.

### 20.4 File mode loss

Replacing source can strip executable bits.

**Rule:** capture mode before replacement and restore/verify it afterward.

### 20.5 Runtime ownership conflict

Starting both sync and individual writers can create flicker/races.

**Rule:** inspect ownership and service state before/after change.

### 20.6 Device-specific core branch

A quick fix for one device can poison future hardware expansion.

**Rule:** ask whether the property belongs in fixture metadata first.

### 20.7 Installed effect mutated accidentally

Authoring workflow must not overwrite canonical installed source.

**Rule:** installed → unsaved/template/adapted copy → explicit save.

### 20.8 Candidate debris leaks into release

Milestone builders/backups can dwarf the application and leak old versions into GitHub.

**Rule:** release tree is exported/curated, not a dump of the historical runtime directory.

---

## 21. AI Decision Tree

### "I need to modify the GUI."

Start with:
```text
gui/app.py
gui/<relevant panel/dialog>.py
resources/visual_identity/...
```

Then:
- identify runtime callbacks;
- build an offscreen probe if layout/control behavior is unclear;
- avoid touching ownership/rendering unless the GUI truly requires it.

### "I need to create/change an effect."

Start with:
```text
plugins/effects/
serpent_core/effects/
gui/effect_lab.py
gui/effect_lab_worker.py
effect_dev.py
examples/
```

Then:
- inspect a semantically similar effect;
- preserve Plugin API contract;
- declare reactive capabilities;
- validate/preview before install;
- test multiple target topologies.

### "I need to add a device."

Start with:
```text
fixtures/
fixture_usb_ids.py
fixtures_cli.py
serpent_core fixture/topology/backend modules
gui/fixture_editor_dialog.py
doctor.py
```

Then:
- reconnaissance;
- fixture first;
- generic backend only if new transport capability is needed;
- no model branch in core.

### "I need to change Sync."

Start with:
```text
sync_engine.py
serpent_core/sync.py
serpent_core/ownership.py
serpent_core/topology.py
profiles/scenes contracts
systemd sync/individual units
```

Then:
- inspect current owner;
- verify region membership;
- preserve per-member brightness;
- test service transition and Doctor.

### "I need to change Scenes."

Start with the scene repository/application/runtime path already used by the GUI. Do not create another hardware path.

### "I need to fix startup/tray/logout."

Start with:
```text
gui/app.py
bin/serpent-gui
packaging/autostart/serpent.desktop
packaging/systemd/user/serpent-watcher.service
```

Test Wayland/KDE session behavior live.

### "Something broke after an installer."

1. stop making further writes;
2. collect traceback/log/service output;
3. hash current files;
4. compare against installer source locks/backups;
5. restore known-good file if necessary;
6. reproduce with a read-only probe;
7. fix the builder/gate, not only the symptom.

---

## 22. Release Discipline

A release should be more than a version-string change.

Recommended certification:

```text
Python compile                     PASS
JSON validation                    PASS
shell syntax                       PASS
offscreen/synthetic gates          PASS
packaging isolated install         PASS
isolated uninstall                 PASS
repository hygiene                 PASS
live runtime acceptance            PASS
Doctor exit 0                      PASS
service ownership                  PASS
startup/tray/logout                PASS
certified artifact hashes          PASS
```

For 1.0.0, selected certified artifacts were frozen byte-for-byte. Future releases should establish a new manifest rather than assuming those historical hashes remain correct.

The current 1.0 baseline deliberately has no release codename in user-facing production branding.

---

## 23. Historical Sources vs Current Truth

The development PDFs contain thousands of pages across pre-1.0 milestones. They are extremely useful for:

- rationale;
- architecture evolution;
- regressions and recovery lessons;
- acceptance criteria;
- why a safety boundary exists.

They also contain:

- obsolete file hashes;
- superseded milestone names;
- removed experimental effects;
- pre-1.0 branding;
- old service names/ownership models;
- candidate paths that no longer exist.

### Priority order for an AI

When sources disagree:

1. **Current checked-out source**
2. **Current fixture/schema data**
3. **Current packaging/service files**
4. **Current `serpent doctor` output**
5. **Current release tests**
6. **This AI manual**
7. **Historical PDFs/milestone artifacts**

The manual summarizes the stable lessons; it is not permission to ignore the code.

---

## 24. First 10 Minutes for a New AI Agent

Run/inspect roughly this sequence:

```bash
pwd
find . -maxdepth 2 -type f | sort
cat README.md
cat serpent_core/version.py
sed -n '1,240p' doctor.py
find fixtures -maxdepth 1 -type f -print | sort
find serpent_core -maxdepth 2 -type f -print | sort
find plugins/effects -maxdepth 1 -type f -print | sort
find gui -maxdepth 1 -type f -print | sort
find packaging -type f -print | sort
```

If working on the installed system:

```bash
serpent doctor
systemctl --user status serpent-sync.service --no-pager
systemctl --user status serpent-individual.service --no-pager
systemctl --user status serpent-restore.service --no-pager
systemctl --user status serpent-watcher.service --no-pager
```

Then answer before coding:

```text
What subsystem owns this behavior?
What is the authoritative data source?
What invariant must remain true?
Can I prove the bug with a read-only probe?
What is the smallest set of files that must change?
What static/offscreen test proves the patch?
What live acceptance remains impossible to simulate?
What rollback path exists?
```

If you cannot answer those, you are not ready to patch.

---

## 25. Golden Rules

1. **Probe, do not guess.**
2. **Fixture first, special case last.**
3. **One ownership model, one hardware-write path per owner.**
4. **Reuse Scene/Sync/runtime machinery rather than duplicating it.**
5. **Reactive input stays read-only and non-exclusive.**
6. **Installed effects are never silently overwritten by authoring.**
7. **Candidate code is contained and validated before promotion.**
8. **Preserve executable modes and verify hashes.**
9. **A static PASS does not replace live acceptance where hardware/session behavior matters.**
10. **Doctor is the final cross-system sanity check.**
11. **Keep the GitHub tree and installed runtime clean.**
12. **When uncertain, make a read-only probe before making a builder.**

---

## 26. Manufacturer Neutrality and Future Hardware Support

**Manufacturer-neutrality is an architectural invariant.**

Razer/OpenRazer is Serpent's current Linux hardware implementation; it is not Serpent's architectural identity. The fixture, topology, rendering, effect, Scene, Sync, ownership, reactive-input, and GUI layers should remain manufacturer-independent wherever the underlying capability can be expressed generically.

When adding support for another manufacturer, the normal path is:

```text
new Linux RGB hardware
    ↓
device reconnaissance
    ↓
fixture definition
    +
backend/transport integration
    ↓
existing Serpent topology/render/effect/Scene/Sync machinery
```

A new manufacturer should **not** normally require edits such as:

```python
if manufacturer == "razer":
    ...
elif manufacturer == "other-vendor":
    ...
```

inside generic effects, rendering, Scenes, Sync, ownership, or GUI code.

Instead:

- put physical anatomy and supported capabilities in fixtures;
- put transport/protocol behavior in backends;
- add a new generic capability contract only when the hardware exposes a genuinely new concept that Serpent cannot already represent;
- update Fixture Editor, Doctor, tests, and documentation generically when such a capability is added;
- regression-test existing Razer/OpenRazer devices to ensure the abstraction remains backward-compatible.

A useful design test is:

> If this same capability appeared tomorrow on hardware from a different manufacturer, would this implementation still be correct?

If the answer is no, the change probably belongs lower in the fixture/backend boundary or requires a new generic capability abstraction.

Serpent 1.0 does **not** claim support for non-Razer hardware. This rule exists so contributors with other Linux RGB hardware have a clear architectural path to add support without redesigning the higher-level application.

---

## 27. Companion Documents

For deeper subsystem instructions, read:

- `docs/ai/architecture.md`
- `docs/ai/effects.md`
- `docs/ai/fixtures-devices.md`
- `docs/ai/runtime-services.md`
- `docs/ai/gui-scenes-sync.md`
- `docs/ai/testing-debugging.md`
- `docs/ai/release-packaging.md`

This file is the mandatory entry point. The companion documents are designed so an AI can load only the subsystem context needed for a task.

---

## 28. Licensing Rule

Serpent is distributed under the **GNU General Public License v3.0 (GPL-3.0)**.

For AI agents and contributors:

- preserve the repository `LICENSE` file and GPL-3.0 designation;
- do not relicense Serpent or remove licensing notices as part of an unrelated change;
- verify the license/provenance of third-party code, assets, or substantial copied material before adding it;
- dependencies retain their own licenses and are not relicensed merely because Serpent uses them;
- treat licensing changes as explicit project-policy decisions, never routine refactoring.

The canonical legal terms are the repository `LICENSE` file. This manual is engineering guidance, not a substitute for the license text.
