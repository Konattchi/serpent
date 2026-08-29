# Historical Development Sources

The AI manual was synthesized from the Serpent development continuity exports and the certified 1.0.0 release/cleanup state.

The source exports span the project's evolution from Linux/OpenRazer troubleshooting into a fixture-driven RGB engine, then through reactive effects, Workshop/Composer, scenes, sync, fixture authoring, multi-zone device identity, visual polish, release certification, packaging, and cleanup.

## How to use historical material

Historical material is excellent for discovering:
- why a design exists;
- failed approaches;
- old acceptance tests;
- visual contracts;
- migration reasoning.

It is not automatically current API documentation.

If a historical statement conflicts with current source, inspect current code/fixtures/tests and update this manual if the architectural rule itself changed.

## Major historical lessons retained in this manual

- fixtures describe hardware;
- backends implement capabilities;
- no exclusive input grabs;
- explicit reactive capabilities;
- persistent effect instance state;
- deterministic event behavior;
- Workshop candidate isolation;
- installed source not edited in place;
- scene application reuses existing ownership/runtime;
- sync supports logical regions;
- `sync_groupable` remains generic;
- Doctor is part of the release contract;
- probes precede patches when architecture is uncertain;
- source-locked builders/installers reduce corruption;
- file modes must be preserved;
- live acceptance is mandatory for hardware/session behavior;
- release/runtime trees must be cleaned of development history.

The PDFs themselves should not be committed to the main repository unless the maintainer explicitly wants a large historical archive. This manual is intended to preserve the actionable engineering knowledge without requiring an AI agent to ingest thousands of PDF pages for routine work.
