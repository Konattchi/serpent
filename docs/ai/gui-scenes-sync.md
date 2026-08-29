# GUI, Scenes, Sync, and User-Flow Guide

## Main GUI principle

The GUI is a view/controller over authoritative runtime data. It should not become another source of truth.

Important surfaces include:
- Status
- Effects Workshop
- Scenes
- Sync
- dynamic device tabs
- Fixture Editor
- Settings
- Help/About
- tray

## Dynamic device tabs

Device UI is fixture/topology-driven. Avoid hard-coding Keyboard/Mouse assumptions when a future fixture can describe a new device class.

## Scenes

All UI and tray scene application should use the same scene repository/application path. Do not duplicate scene enumeration or application.

A Scene eventually delegates to the ownership/profile/service runtime, not directly to hardware.

## Sync UI

The Sync UI must reflect generic member identity: physical instance + region. Multi-zone devices can contribute multiple members.

Preserve:
- per-member brightness;
- group effect;
- stable identity;
- membership validity after topology change;
- offline/ghost reconciliation policy.

## Status

Status indicators should reflect real runtime state. Avoid "green because configured" when the actual service/owner/device is not active.

## Workshop layout

When changing Qt layout:
- inspect actual container insertion;
- use offscreen widget construction if possible;
- visually verify live layout.

A source-level "widget A constructed before B" does not prove rendered order.

## Notifications and modal safety

Prefer nonmodal feedback for routine operations when architecture expects it. Avoid introducing modal dialogs into startup/session-shutdown paths where they can hold Plasma logout.
