#!/usr/bin/env python3

from __future__ import annotations

import copy

import faulthandler
import json
from concurrent.futures import Future, ThreadPoolExecutor
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer, Signal, QSettings
from PySide6.QtGui import QAction, QColor, QIcon, QKeySequence, QPixmap
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QInputDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QPlainTextEdit,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSystemTrayIcon,
    QTabWidget,
    QTabBar,
    QVBoxLayout,
    QWidget,
)


HOME = Path.home()
SERPENT_DIR = HOME / ".local" / "share" / "serpent"
FIXTURE_DIR = SERPENT_DIR / "fixtures"
PROFILE_PATH = HOME / ".config" / "serpent" / "profile.json"
SERPENT_COMMAND = HOME / ".local" / "bin" / "serpent"

VISUAL_IDENTITY_DIR = SERPENT_DIR / "resources" / "visual_identity"
SERPENT_APP_ICON_PATH = (
    VISUAL_IDENTITY_DIR / "icons" / "app" / "serpent_256.png"
)
SERPENT_ABOUT_ART_PATH = (
    VISUAL_IDENTITY_DIR / "branding" / "serpent_splash_about.png"
)
SERPENT_WORDMARK_PATH = (
    VISUAL_IDENTITY_DIR / "branding" / "wordmark.png"
)
# M10.0.0.39-M - release banner header
# M10.0.0.39-M-Fix2 - wide release banner presentation
SERPENT_BANNER_PATH = (
    VISUAL_IDENTITY_DIR / "branding" / "serpent_banner.png"
)
SERPENT_ACCENT_QSS_PATH = (
    VISUAL_IDENTITY_DIR / "theme" / "serpent_dark_accent.qss"
)


def load_serpent_visual_stylesheet() -> str:
    try:
        return SERPENT_ACCENT_QSS_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""



GUI_COMMAND = HOME / ".local" / "bin" / "serpent-gui"
AUTOSTART_PATH = HOME / ".config" / "autostart" / "serpent.desktop"
AUTOSTART_MARKER = "X-Serpent-Managed=true"


def serpent_gui_launch_command() -> list[str]:
    if GUI_COMMAND.is_file():
        return [str(GUI_COMMAND), "--tray"]

    return ["/usr/bin/python3", str(SERPENT_DIR / "gui" / "app.py"), "--tray"]


def _desktop_exec_argument(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"' if any(ch.isspace() for ch in value) else escaped


def serpent_autostart_desktop_text() -> str:
    command = " ".join(
        _desktop_exec_argument(value)
        for value in serpent_gui_launch_command()
    )
    return (
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Serpent\n"
        "Comment=Start Serpent in the system tray\n"
        f"Exec={command}\n"
        "Terminal=false\n"
        "StartupNotify=false\n"
        "X-GNOME-Autostart-enabled=true\n"
        f"{AUTOSTART_MARKER}\n"
    )


def serpent_autostart_enabled() -> bool:
    try:
        text = AUTOSTART_PATH.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False

    expected_exec = next(
        line for line in serpent_autostart_desktop_text().splitlines()
        if line.startswith("Exec=")
    )
    return (
        AUTOSTART_MARKER in text.splitlines()
        and expected_exec in text.splitlines()
    )


def set_serpent_autostart(enabled: bool) -> None:
    if enabled:
        AUTOSTART_PATH.parent.mkdir(parents=True, exist_ok=True)
        text = serpent_autostart_desktop_text()
        fd, raw = tempfile.mkstemp(
            prefix=".serpent.desktop.",
            dir=str(AUTOSTART_PATH.parent),
            text=True,
        )
        os.close(fd)
        temporary = Path(raw)
        try:
            temporary.write_text(text, encoding="utf-8")
            temporary.chmod(0o644)
            os.replace(temporary, AUTOSTART_PATH)
        finally:
            if temporary.exists():
                temporary.unlink()
        return

    if not AUTOSTART_PATH.exists():
        return

    try:
        existing = AUTOSTART_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuiError(f"Could not read Serpent autostart entry: {exc}") from exc

    if AUTOSTART_MARKER not in existing.splitlines():
        raise GuiError(
            "The existing serpent.desktop autostart entry is not managed by "
            "Serpent, so it was left untouched."
        )

    AUTOSTART_PATH.unlink()



sys.path.insert(0, str(SERPENT_DIR))

from serpent_core.region_ownership import (
    store_personal_region_settings,
    sync_region_assignments,
)
from serpent_core.version import (  # noqa: E402
    GUI_INSTANCE_SERVER_NAME as INSTANCE_SERVER_NAME,
    VERSION,
)

from serpent_core.backends.base import BackendError  # noqa: E402
from serpent_core.backends.registry import create_backend  # noqa: E402
from serpent_core.discovery import detect_fixture, detect_all_fixture_instances  # noqa: E402
from serpent_core.telemetry import DeviceTelemetrySnapshot, collect_device_telemetry  # noqa: E402
from serpent_core.fixtures import (  # noqa: E402
    FixtureError,
    find_fixture_by_id,
)

from gui.status import summary as load_status_summary  # noqa: E402
from serpent_core.effects import (  # noqa: E402
    get_effect_plugin_spec,
)
from serpent_core.presentation import (  # noqa: E402
    effect_presentations,
    rendering_presentations,
    sync_member_presentations,
)
from serpent_core.scene_application import (  # noqa: E402
    SceneApplicationError,
    apply_scene,
)
from serpent_core.scene_repository import (  # noqa: E402
    DEFAULT_SCENE_DIR,
    SceneAlreadyExistsError,
    SceneRepository,
    SceneRepositoryError,
)
from serpent_core.scene_runtime import SerpentSceneRuntime  # noqa: E402
from serpent_core.scenes import scene_from_dict, scene_to_dict  # noqa: E402
from serpent_core.device import build_device_model
from serpent_core.sync import require_topology
from gui.notifications import NotificationCenter, notify_error, notify_info, notify_warning


class GuiError(RuntimeError):
    """An error suitable for display in the graphical interface."""


def load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise GuiError(f"Could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise GuiError(
            f"Invalid JSON in {path.name}, "
            f"line {exc.lineno}: {exc.msg}"
        ) from exc


def load_fixtures() -> list[dict[str, Any]]:
    fixtures: list[dict[str, Any]] = []

    for path in sorted(FIXTURE_DIR.glob("*.json")):
        fixture = load_json(path)
        fixture["_path"] = str(path)
        fixtures.append(fixture)

    if not fixtures:
        raise GuiError("No Serpent fixtures are installed.")

    return fixtures


def load_profile() -> dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {}

    return load_json(PROFILE_PATH)


def run_serpent(arguments: list[str]) -> str:
    result = subprocess.run(
        [str(SERPENT_COMMAND), *arguments],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    output = result.stdout.strip()

    if result.returncode != 0:
        raise GuiError(output or "Serpent command failed.")

    return output


def gui_scene_repository() -> SceneRepository:
    configured = os.environ.get("SERPENT_SCENE_DIR")

    if configured:
        return SceneRepository(
            Path(configured).expanduser()
        )

    return SceneRepository(DEFAULT_SCENE_DIR)


def restore_all_profiles() -> str:
    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "restart",
            "serpent-restore.service",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    if result.returncode != 0:
        raise GuiError(
            result.stdout.strip()
            or "Could not restore Serpent profiles."
        )

    return "Restored saved Serpent profiles."


def read_mouse_status_value(label: str) -> str:
    result = subprocess.run(
        [str(SERPENT_COMMAND), "mouse", "status"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )

    if result.returncode != 0:
        return "Unknown"

    prefix = f"{label}:"

    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line.split(":", 1)[1].strip()

    return "Unknown"


def humanize(value: str) -> str:
    return value.replace("-", " ").title()


def scene_id_from_name(name: str) -> str:
    """Create a repository-safe scene id from a user-facing name."""
    value = name.strip().lower()
    value = re.sub(r"[^a-z0-9._-]+", "-", value)
    value = re.sub(r"[-_.]{2,}", "-", value).strip("-_.")
    return value or "scene"


def unique_scene_id(name: str, repository: SceneRepository) -> str:
    base = scene_id_from_name(name)
    candidate = base
    suffix = 2
    existing = set(repository.list_ids())

    while candidate in existing:
        candidate = f"{base}-{suffix}"
        suffix += 1

    return candidate


def scene_effect_payload(
    settings: dict[str, object],
    *,
    synchronized: bool = False,
) -> dict[str, object]:
    effect = settings.get("effect")
    if not isinstance(effect, str) or not effect:
        raise GuiError("Effect settings contain no effect id.")

    try:
        spec = get_effect_plugin_spec(effect)
    except Exception:
        spec = None

    parameters: dict[str, object] = {}
    if spec is not None:
        for parameter in spec.parameters:
            if parameter.id in settings:
                parameters[parameter.id] = copy.deepcopy(settings[parameter.id])
    else:
        for key in ("colour1", "colour2", "speed", "direction"):
            if key in settings:
                parameters[key] = copy.deepcopy(settings[key])

    return {"id": effect, "parameters": parameters}


def capture_current_scene(name: str, repository: SceneRepository):
    profile = load_profile()
    output = run_serpent(["sync", "status"])
    runtime = SyncPanel.parse_sync_status(output)
    synchronized = (
        runtime.get("Owner") == "sync"
        and runtime.get("Service") == "active"
        and runtime.get("State") == "synchronized"
    )
    scene_id = unique_scene_id(name, repository)

    if synchronized:
        sync = profile.get("sync", {})
        if not isinstance(sync, dict):
            raise GuiError("Saved synchronization profile is not an object.")

        groups = sync.get("groups")
        if isinstance(groups, list) and groups:
            from serpent_core.sync_groups import validate_groups
            try:
                validate_groups(groups)
            except Exception as exc:
                raise GuiError(f"Saved synchronization groups are invalid: {exc}") from exc

            raw: dict[str, object] = {
                "schema_version": 1,
                "id": scene_id,
                "name": name.strip(),
                "mode": "synchronized",
                "groups": copy.deepcopy(groups),
            }
        else:
            effect_settings = dict(sync)
            runtime_effect = runtime.get("Effect")
            if runtime_effect and not effect_settings.get("effect"):
                effect_settings["effect"] = runtime_effect

            members = sync.get("members", [])
            brightness = sync.get("member_brightness", {})
            if not isinstance(members, list) or not members:
                raise GuiError("Synchronized profile has no saved members to capture.")
            if not isinstance(brightness, dict):
                raise GuiError("Synchronized member brightness settings are invalid.")

            member_payload: dict[str, object] = {}
            for member in members:
                if not isinstance(member, str) or member not in brightness:
                    raise GuiError(
                        f"Synchronized member {member!r} has no saved brightness."
                    )
                member_payload[member] = {"brightness": brightness[member]}

            raw = {
                "schema_version": 1,
                "id": scene_id,
                "name": name.strip(),
                "mode": "synchronized",
                "effect": scene_effect_payload(
                    effect_settings,
                    synchronized=True,
                ),
                "members": member_payload,
            }
    else:
        devices: dict[str, object] = {}

        keyboard = profile.get("keyboard")
        if isinstance(keyboard, dict) and keyboard.get("effect"):
            devices["razer-deathstalker-v2"] = {
                "effect": scene_effect_payload(keyboard),
                "brightness": keyboard.get("brightness"),
            }

        mouse = profile.get("mouse")
        if isinstance(mouse, dict):
            zones = mouse.get("zones")
            if isinstance(zones, dict) and zones:
                mouse_zones: dict[str, object] = {}
                for zone_id, settings in zones.items():
                    if not isinstance(zone_id, str) or not isinstance(settings, dict):
                        raise GuiError("Saved mouse zone settings are invalid.")
                    if not settings.get("effect"):
                        continue
                    mouse_zones[zone_id] = {
                        "effect": scene_effect_payload(settings),
                        "brightness": settings.get("brightness"),
                    }
                if mouse_zones:
                    devices["razer-naga-v2-pro-wireless"] = {
                        "linked": bool(mouse.get("linked", True)),
                        "zones": mouse_zones,
                    }

        fixture_devices = profile.get("fixture_devices", {})
        if isinstance(fixture_devices, dict):
            for instance_id, saved in fixture_devices.items():
                if not isinstance(instance_id, str) or not isinstance(saved, dict):
                    continue
                fixture_id = saved.get("fixture_id")
                if fixture_id in {
                    "razer-deathstalker-v2",
                    "razer-naga-v2-pro-wireless",
                }:
                    continue

                item: dict[str, object] = {}
                settings = saved.get("settings")
                if isinstance(settings, dict) and settings.get("effect"):
                    item["effect"] = scene_effect_payload(settings)
                    item["brightness"] = settings.get("brightness")

                saved_zones = saved.get("zones")
                if isinstance(saved_zones, dict):
                    zone_payload: dict[str, object] = {}
                    for zone_id, zone_settings in saved_zones.items():
                        if not isinstance(zone_id, str) or not isinstance(zone_settings, dict):
                            continue
                        if not zone_settings.get("effect"):
                            continue
                        zone_payload[zone_id] = {
                            "effect": scene_effect_payload(zone_settings),
                            "brightness": zone_settings.get("brightness"),
                        }
                    if zone_payload:
                        item["zones"] = zone_payload

                if item:
                    devices[instance_id] = item

        if not devices:
            raise GuiError("No saved individual lighting devices are available to capture.")

        raw = {
            "schema_version": 1,
            "id": scene_id,
            "name": name.strip(),
            "mode": "individual",
            "devices": devices,
        }

    return scene_from_dict(raw)


def get_mouse_backend():
    fixture = find_fixture_by_id(
        "razer-naga-v2-pro-wireless"
    )
    detected = detect_fixture(fixture)

    if detected is None:
        raise GuiError(
            "The Razer Naga V2 Pro is not connected."
        )

    return create_backend(
        fixture,
        detected.sysfs_path,
    )


class ColourButton(QPushButton):
    """Clickable colour swatch with guarded dialog preview."""

    previewChanged = Signal()
    colourCommitted = Signal()
    colourCancelled = Signal()

    def __init__(
        self,
        colour: list[int] | tuple[int, int, int],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)

        self._colour = QColor(*colour)
        self.clicked.connect(self.choose_colour)

        self.setMinimumHeight(34)
        self.update_appearance()

    def colour_tuple(self) -> tuple[int, int, int]:
        return (
            self._colour.red(),
            self._colour.green(),
            self._colour.blue(),
        )

    def set_colour(
        self,
        colour: list[int] | tuple[int, int, int],
    ) -> None:
        self._colour = QColor(*colour)
        self.update_appearance()

    def preview_colour(self, colour: QColor) -> None:
        if not colour.isValid():
            return

        self._colour = QColor(colour)
        self.update_appearance()
        self.previewChanged.emit()

    def choose_colour(self) -> None:
        original = QColor(self._colour)

        dialog = QColorDialog(self._colour, self)
        dialog.setWindowTitle("Choose lighting colour")
        dialog.setOption(
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
            False,
        )
        dialog.currentColorChanged.connect(
            self.preview_colour
        )

        result = dialog.exec()

        if result == QColorDialog.DialogCode.Accepted:
            selected = dialog.currentColor()

            if selected.isValid():
                self._colour = QColor(selected)
                self.update_appearance()

            self.colourCommitted.emit()
        else:
            self._colour = original
            self.update_appearance()
            self.colourCancelled.emit()

    def update_appearance(self) -> None:
        red, green, blue = self.colour_tuple()

        luminance = (
            0.299 * red
            + 0.587 * green
            + 0.114 * blue
        )

        text_colour = (
            "black"
            if luminance > 150
            else "white"
        )

        hex_value = self._colour.name().upper()
        self.setText(
            f"{hex_value}  ·  RGB {red}, {green}, {blue}"
        )

        self.setStyleSheet(
            "QPushButton {"
            f"background-color: rgb({red}, {green}, {blue});"
            f"color: {text_colour};"
            "border: 1px solid palette(mid);"
            "border-radius: 5px;"
            "padding: 6px;"
            "}"
        )


def _renderer_owned_plugin_target_compatible(
    device_class: str,
    render_targets,
    *,
    renderer_owned: bool,
) -> bool:
    # Exact plugin device-class declarations remain authoritative everywhere.
    # Renderer-owned matrix fixtures may additionally consume effects written
    # against Serpent's established keyboard/mouse matrix target contract.
    targets = tuple(str(target) for target in (render_targets or ()))
    if device_class in targets:
        return True
    if not renderer_owned:
        return False
    return any(target in {"keyboard", "mouse"} for target in targets)


def _device_effect_catalog(
    device_class: str,
    fixture_effects: dict[str, Any],
*,
    renderer_owned: bool = False,
) -> dict[str, Any]:
    effects = dict(fixture_effects)

    for presentation in effect_presentations():
        try:
            spec = get_effect_plugin_spec(presentation.id)
        except (KeyError, TypeError, ValueError):
            continue

        if not _renderer_owned_plugin_target_compatible(
            device_class,
            spec.render_targets,
            renderer_owned=renderer_owned,
        ):
            continue

        definition: dict[str, Any] = {
            "label": presentation.name,
        }

        colour_ids = [
            parameter.id
            for parameter in spec.parameters
            if parameter.kind == "colour"
            and parameter.id in {"colour1", "colour2"}
        ]
        if "colour2" in colour_ids:
            definition["colours"] = 2
        elif "colour1" in colour_ids:
            definition["colours"] = 1

        speed_parameter = next(
            (
                parameter
                for parameter in spec.parameters
                if parameter.id == "speed"
                and parameter.kind == "integer"
            ),
            None,
        )
        if speed_parameter is not None:
            definition["speed"] = True
            if (
                speed_parameter.minimum is not None
                and speed_parameter.maximum is not None
            ):
                definition["speed_min"] = int(speed_parameter.minimum)
                definition["speed_max"] = int(speed_parameter.maximum)

        direction_parameter = next(
            (
                parameter
                for parameter in spec.parameters
                if parameter.id == "direction"
            ),
            None,
        )
        if (
            direction_parameter is not None
            and direction_parameter.choices
        ):
            definition["directions"] = list(direction_parameter.choices)

        effects[presentation.id] = definition

    return effects

def _normalise_profile_value(value):
    if isinstance(value, tuple):
        return [_normalise_profile_value(item) for item in value]
    if isinstance(value, list):
        return [_normalise_profile_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _normalise_profile_value(item) for key, item in value.items()}
    return value


def _personal_profile_settings(
    effect: str,
    settings: dict[str, Any],
    fixture_effects: dict[str, Any],
) -> dict[str, Any]:
    if effect in fixture_effects:
        result = dict(settings)
        result["effect"] = effect
        return result

    return _plugin_profile_settings(effect, settings)

def _plugin_profile_settings(effect_id: str, overrides: dict[str, Any]) -> dict[str, Any]:
    spec = get_effect_plugin_spec(effect_id)
    result = {
        parameter.id: _normalise_profile_value(parameter.default)
        for parameter in spec.parameters
    }
    result.update(_normalise_profile_value(dict(overrides)))
    result["effect"] = effect_id
    return result


def _is_dynamic_device_effect(effect_id: str, device_class: str, fixture_effects: dict[str, Any]) -> bool:
    if effect_id in fixture_effects:
        return False
    try:
        spec = get_effect_plugin_spec(effect_id)
    except (KeyError, TypeError, ValueError):
        return False
    return device_class in spec.render_targets


def _save_profile_atomic(profile: dict[str, Any]) -> None:
    PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = PROFILE_PATH.with_name(PROFILE_PATH.name + ".serpent.tmp")
    temporary.write_text(
        json.dumps(profile, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, PROFILE_PATH)


_INDIVIDUAL_RESTART_SERIAL = 0
_INDIVIDUAL_RESTART_DELAY_MS = 220


def _perform_individual_renderer_restart(serial: int) -> None:
    global _INDIVIDUAL_RESTART_SERIAL

    if serial != _INDIVIDUAL_RESTART_SERIAL:
        return

    from serpent_core.ownership import current_owner

    if current_owner() != "normal":
        return

    health = subprocess.run(
        [
            "systemctl",
            "--user",
            "is-active",
            "--quiet",
            "serpent-individual.service",
        ],
        check=False,
    )
    if health.returncode == 0:
        return

    subprocess.run(
        [
            "systemctl",
            "--user",
            "reset-failed",
            "serpent-individual.service",
        ],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    result = subprocess.run(
        [
            "systemctl",
            "--user",
            "start",
            "serpent-individual.service",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    if result.returncode != 0:
        notify_error(
            None,
            "Individual renderer activation failed",
            result.stdout.strip()
            or "Could not start the Serpent individual software renderer.",
        )




def _restart_individual_renderer() -> None:
    """Coalesce rapid Personal applies; the newest saved profile wins."""
    global _INDIVIDUAL_RESTART_SERIAL

    _INDIVIDUAL_RESTART_SERIAL += 1
    serial = _INDIVIDUAL_RESTART_SERIAL

    QTimer.singleShot(
        _INDIVIDUAL_RESTART_DELAY_MS,
        lambda serial=serial: _perform_individual_renderer_restart(serial),
    )


_SYNC_RELOAD_SERIAL = 0
_SYNC_RELOAD_DELAY_MS = 220


def _request_sync_renderer_reload() -> None:
    """Coalesce rapid personal-region changes while Sync owns lighting."""
    global _SYNC_RELOAD_SERIAL

    _SYNC_RELOAD_SERIAL += 1
    serial = _SYNC_RELOAD_SERIAL

    def reload_latest() -> None:
        if serial != _SYNC_RELOAD_SERIAL:
            return
        try:
            run_serpent(["sync", "reload-engine"])
        except (GuiError, OSError, ValueError) as exc:
            notify_error(
                None,
                "Synchronization reload failed",
                str(exc),
            )

    QTimer.singleShot(
        _SYNC_RELOAD_DELAY_MS,
        reload_latest,
    )


class EffectEditor(QGroupBox):
    def __init__(
        self,
        title: str,
        effects: dict[str, Any],
        settings: dict[str, Any],
        apply_callback: Callable[
            [str, dict[str, Any]],
            None,
        ],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(title, parent)
        # M10.0.0.39-K - device page semantic presentation
        self.setObjectName("serpentEffectEditor")
        self.setProperty("controlState", "individual")

        self.effects = effects
        self.settings = dict(settings)
        self.apply_callback = apply_callback

        self.live_preview_enabled = True
        self.apply_in_progress = False
        self.pending_apply = False

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(350)
        self.preview_timer.timeout.connect(self.apply)

        self.colour_preview_timer = QTimer(self)
        self.colour_preview_timer.setSingleShot(True)
        self.colour_preview_timer.setInterval(900)
        self.colour_preview_timer.timeout.connect(self.apply)

        self.effect_combo = QComboBox()

        self.brightness_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.brightness_value = QLabel()

        self.colour1_button = ColourButton(
            self.settings.get(
                "colour1",
                [0, 0, 255],
            )
        )
        self.colour2_button = ColourButton(
            self.settings.get(
                "colour2",
                [0, 255, 255],
            )
        )

        self.speed_spin = QSpinBox()

        self.colour1_label = QLabel("Primary colour")
        self.colour2_label = QLabel("Secondary colour")
        self.speed_label = QLabel("Speed")

        self.apply_button = QPushButton(
            f"Apply {title}"
        )

        self.build_ui()
        self.load_settings(self.settings)
        self.update_effect_controls()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy
            .AllNonFixedFieldsGrow
        )

        for effect_name in self.effects:
            self.effect_combo.addItem(
                humanize(effect_name),
                effect_name,
            )

        self.effect_combo.currentIndexChanged.connect(
            self.update_effect_controls
        )

        form.addRow("Effect", self.effect_combo)

        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.valueChanged.connect(
            self.update_brightness_label
        )

        brightness_row = QWidget()
        brightness_layout = QHBoxLayout(brightness_row)
        brightness_layout.setContentsMargins(0, 0, 0, 0)
        brightness_layout.addWidget(
            self.brightness_slider
        )
        brightness_layout.addWidget(
            self.brightness_value
        )

        form.addRow("Brightness", brightness_row)

        form.addRow(
            self.colour1_label,
            self.colour1_button,
        )
        form.addRow(
            self.colour2_label,
            self.colour2_button,
        )

        self.speed_spin.setRange(1, 10)

        form.addRow(
            self.speed_label,
            self.speed_spin,
        )

        layout.addLayout(form)
        layout.addWidget(
            self.apply_button,
            alignment=Qt.AlignmentFlag.AlignRight,
        )

        self.apply_button.clicked.connect(
            self.apply
        )

        self.effect_combo.currentIndexChanged.connect(
            self.restore_selected_effect_state
        )
        self.effect_combo.currentIndexChanged.connect(
            self.schedule_preview
        )
        self.brightness_slider.valueChanged.connect(
            self.schedule_preview
        )
        self.colour1_button.previewChanged.connect(
            self.schedule_colour_preview
        )
        self.colour2_button.previewChanged.connect(
            self.schedule_colour_preview
        )

        self.colour1_button.colourCommitted.connect(
            self.apply_colour_now
        )
        self.colour2_button.colourCommitted.connect(
            self.apply_colour_now
        )

        self.colour1_button.colourCancelled.connect(
            self.apply_colour_now
        )
        self.colour2_button.colourCancelled.connect(
            self.apply_colour_now
        )
        self.speed_spin.valueChanged.connect(
            self.schedule_preview
        )

    def restore_selected_effect_state(self) -> None:
        # Restore remembered controls before the debounced preview runs.
        if not isinstance(getattr(self, "settings", None), dict):
            return

        effect = str(self.effect_combo.currentData())
        previous_effect = str(self.settings.get("effect", ""))

        if not effect or effect == previous_effect:
            return

        selected_effect, restored = self.current_settings()

        if selected_effect != effect:
            return

        previous_preview_state = self.live_preview_enabled
        self.live_preview_enabled = False

        try:
            definition = self.current_effect_definition()

            self.brightness_slider.blockSignals(True)
            self.speed_spin.blockSignals(True)

            try:
                if "brightness" in restored:
                    brightness = int(restored["brightness"])
                    self.brightness_slider.setValue(brightness)
                    self.update_brightness_label(brightness)

                if (
                    int(definition.get("colours", 0)) >= 1
                    and "colour1" in restored
                ):
                    self.colour1_button.set_colour(restored["colour1"])

                if (
                    int(definition.get("colours", 0)) >= 2
                    and "colour2" in restored
                ):
                    self.colour2_button.set_colour(restored["colour2"])

                if (
                    definition.get("speed")
                    or definition.get("speeds")
                ) and "speed" in restored:
                    self.speed_spin.setValue(int(restored["speed"]))

            finally:
                self.brightness_slider.blockSignals(False)
                self.speed_spin.blockSignals(False)

            committed = dict(restored)
            committed["effect"] = effect
            self.settings = committed
            self.update_effect_controls()

        finally:
            self.live_preview_enabled = previous_preview_state


    def schedule_preview(self) -> None:
        if not self.live_preview_enabled:
            return

        self.preview_timer.start()

    def schedule_colour_preview(self) -> None:
        if not self.live_preview_enabled:
            return

        self.preview_timer.stop()
        self.colour_preview_timer.start()

    def apply_colour_now(self) -> None:
        if not self.live_preview_enabled:
            return

        self.preview_timer.stop()
        self.colour_preview_timer.stop()
        self.apply()

    def load_settings(
        self,
        settings: dict[str, Any],
    ) -> None:
        previous_preview_state = self.live_preview_enabled
        self.live_preview_enabled = False

        try:
            self.settings = dict(settings)

            effect = self.settings.get(
                "effect",
                "static",
            )

            index = self.effect_combo.findData(effect)

            if index >= 0:
                self.effect_combo.setCurrentIndex(index)

            brightness = int(
                self.settings.get("brightness", 20)
            )

            self.brightness_slider.setValue(brightness)
            self.update_brightness_label(brightness)

            self.colour1_button.set_colour(
                self.settings.get(
                    "colour1",
                    [0, 0, 255],
                )
            )

            self.colour2_button.set_colour(
                self.settings.get(
                    "colour2",
                    [0, 255, 255],
                )
            )

            self.speed_spin.setValue(
                int(self.settings.get("speed", 2))
            )

            self.update_effect_controls()

        finally:
            self.live_preview_enabled = previous_preview_state

    def update_brightness_label(
        self,
        value: int,
    ) -> None:
        self.brightness_value.setText(
            f"{value}%"
        )

    def current_effect_definition(
        self,
    ) -> dict[str, Any]:
        effect = self.effect_combo.currentData()
        definition = self.effects.get(effect, {})

        if isinstance(definition, dict):
            return definition

        return {}

    def update_effect_controls(self) -> None:
        definition = (
            self.current_effect_definition()
        )

        colour_count = int(
            definition.get("colours", 0)
        )

        has_colour1 = colour_count >= 1
        has_colour2 = colour_count >= 2

        has_speed = bool(
            definition.get("speed")
            or definition.get("speeds")
        )

        self.colour1_label.setVisible(
            has_colour1
        )
        self.colour1_button.setVisible(
            has_colour1
        )

        self.colour2_label.setVisible(
            has_colour2
        )
        self.colour2_button.setVisible(
            has_colour2
        )

        self.speed_label.setVisible(has_speed)
        self.speed_spin.setVisible(has_speed)

        speed_values = definition.get("speeds")

        if speed_values:
            values = [
                int(value)
                for value in speed_values
            ]

            self.speed_spin.setRange(
                min(values),
                max(values),
            )
        else:
            self.speed_spin.setRange(
                int(definition.get("speed_min", 1)),
                int(definition.get("speed_max", 10)),
            )

    def current_settings(
        self,
    ) -> tuple[str, dict[str, Any]]:
        effect = str(
            self.effect_combo.currentData()
        )

        definition = (
            self.current_effect_definition()
        )

        settings: dict[str, Any] = {
            "brightness":
                self.brightness_slider.value(),
        }

        colour_count = int(
            definition.get("colours", 0)
        )

        if colour_count >= 1:
            settings["colour1"] = list(
                self.colour1_button.colour_tuple()
            )

        if colour_count >= 2:
            settings["colour2"] = list(
                self.colour2_button.colour_tuple()
            )

        if (
            definition.get("speed")
            or definition.get("speeds")
        ):
            settings["speed"] = (
                self.speed_spin.value()
            )

        history = {}
        if isinstance(getattr(self, "settings", None), dict):
            persisted_history = self.settings.get("_effect_history", {})
            if isinstance(persisted_history, dict):
                history.update(persisted_history)

        previous_effect = str(
            self.settings.get("effect", "")
            if isinstance(getattr(self, "settings", None), dict)
            else ""
        )

        if previous_effect:
            previous_snapshot = dict(self.settings)
            previous_snapshot.pop("_effect_history", None)
            history[previous_effect] = previous_snapshot

        if effect != previous_effect:
            remembered = history.get(effect)
            if isinstance(remembered, dict):
                for key in (
                    "brightness",
                    "colour1",
                    "colour2",
                    "speed",
                    "direction",
                ):
                    if key in settings and key in remembered:
                        value = remembered[key]
                        settings[key] = (
                            list(value)
                            if isinstance(value, list)
                            else value
                        )

        remembered_now = dict(settings)
        history[effect] = remembered_now
        settings["_effect_history"] = history

        return effect, settings

    def apply(self) -> None:
        self.preview_timer.stop()
        self.colour_preview_timer.stop()

        if self.apply_in_progress:
            self.pending_apply = True
            return

        self.apply_in_progress = True

        try:
            effect, settings = self.current_settings()
            self.apply_callback(effect, settings)
        finally:
            self.apply_in_progress = False

        if self.pending_apply:
            self.pending_apply = False
            self.preview_timer.start(500)


    def replace_effects(self, effects: dict[str, Any]) -> None:
        selected = self.effect_combo.currentData()
        self.effects = effects
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for effect_name in self.effects:
            self.effect_combo.addItem(humanize(effect_name), effect_name)
        if selected is not None:
            index = self.effect_combo.findData(selected)
            if index >= 0:
                self.effect_combo.setCurrentIndex(index)
        self.effect_combo.blockSignals(False)
        self.update_effect_controls()



def _panel_uses_software_rgb(panel) -> bool:
    for attr in ("fixture_object", "device", "device_model"):
        candidate = getattr(panel, attr, None)
        backend_type = getattr(candidate, "backend_type", None)
        if isinstance(backend_type, str) and backend_type:
            return backend_type == "software-rgb-sysfs"

    fixture = getattr(panel, "fixture", None)
    if isinstance(fixture, dict):
        backend = fixture.get("backend", {})
        if isinstance(backend, dict):
            return str(backend.get("type", "")) == "software-rgb-sysfs"

    return False

class MousePanel(QWidget):
    def __init__(
        self,
        fixture: dict[str, Any],
        profile: dict[str, Any],
        status_refresh_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serpentMousePanel")

        self.fixture = fixture
        self.fixture_effects = dict(fixture.get("effects", {}))
        self.effects = _device_effect_catalog("mouse", self.fixture_effects)
        self.status_refresh_callback = status_refresh_callback

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("serpentDeviceActionStatus")
        self.status_label.setWordWrap(True)
        self.ownership_label = QLabel("Individual lighting active.")
        self.ownership_label.setObjectName("serpentOwnershipState")
        self.ownership_label.setProperty("ownershipState", "individual")
        self.ownership_label.setWordWrap(True)
        self.sync_owned = False
        self.device_connected = True

        mouse_profile = profile.get("mouse", {})
        zones = mouse_profile.get("zones", {})

        logo_settings = zones.get(
            "logo",
            self.default_settings(),
        )

        side_settings = zones.get(
            "side-buttons",
            self.default_settings(),
        )

        self.link_checkbox = QCheckBox(
            "Link Logo and Side Buttons"
        )

        self.link_checkbox.setChecked(
            bool(mouse_profile.get("linked", True))
        )

        self.live_preview_checkbox = QCheckBox(
            "Live preview"
        )
        self.live_preview_checkbox.setChecked(True)

        self.logo_editor = EffectEditor(
            "Logo",
            self.effects,
            logo_settings,
            self.apply_logo,
        )

        self.side_editor = EffectEditor(
            "Side Buttons",
            self.effects,
            side_settings,
            self.apply_side_buttons,
        )

        self.build_ui()
        self.update_link_state()

    def default_settings(self) -> dict[str, Any]:
        return {
            "effect": "static",
            "brightness": 20,
            "colour1": [0, 0, 255],
            "colour2": [0, 255, 255],
            "speed": 2,
        }

    def build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        title = QLabel(
            "Razer Naga V2 Pro (Wireless)"
        )
        title.setObjectName("serpentDevicePageTitle")

        title_font = title.font()
        title_font.setPointSize(
            title_font.pointSize() + 3
        )
        title_font.setBold(True)
        title.setFont(title_font)

        details = QLabel(
            f"Fixture: {self.fixture['id']}\n"
            f"Backend: "
            f"{self.fixture['backend']['type']}\n"
            f"USB ID: "
            f"{self.fixture['usb']['vendor_id']}:"
            f"{self.fixture['usb']['product_id']}"
        )
        details.setObjectName("serpentDevicePageDetails")
        details.setProperty("serpentRole", "secondaryText")

        battery = read_mouse_status_value(
            "Battery"
        )
        charging = read_mouse_status_value(
            "Charging"
        )

        battery_label = QLabel(
            f"Battery: {battery}    "
            f"Charging: {charging}"
        )

        separator = QFrame()
        separator.setFrameShape(
            QFrame.Shape.HLine
        )
        separator.setFrameShadow(
            QFrame.Shadow.Sunken
        )

        linked_hint = QLabel(
            "When linked, applying the Logo settings "
            "updates both lighting zones."
        )
        linked_hint.setWordWrap(True)

        self.restore_button = QPushButton(
            "Restore saved mouse profile"
        )
        self.restore_button.clicked.connect(
            self.restore_profile
        )

        self.link_checkbox.toggled.connect(
            self.change_link_state
        )
        self.live_preview_checkbox.toggled.connect(
            self.set_live_preview
        )

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.restore_button)

        outer.addWidget(title)
        outer.addWidget(details)
        outer.addWidget(battery_label)
        outer.addWidget(separator)
        outer.addWidget(self.ownership_label)
        outer.addWidget(self.link_checkbox)
        outer.addWidget(self.live_preview_checkbox)
        outer.addWidget(linked_hint)
        outer.addWidget(self.logo_editor)
        outer.addWidget(self.side_editor)
        outer.addLayout(button_row)
        outer.addWidget(self.status_label)
        outer.addStretch()

    def set_sync_context(
        self,
        synchronized: bool,
        profile: dict[str, Any],
    ) -> None:
        self.sync_owned = bool(synchronized)
        instance_id = str(getattr(self, "instance_id", ""))
        self.sync_region_groups = (
            sync_region_assignments(profile, instance_id)
            if self.sync_owned and instance_id
            else {}
        )
        self.update_interaction_state()

    def _zone_sync_group(self, zone_id: str) -> str | None:
        groups = getattr(self, "sync_region_groups", {})
        value = groups.get(zone_id) if isinstance(groups, dict) else None
        return str(value) if value else None

    def _zone_editable(self, zone_id: str) -> bool:
        if not self.device_connected:
            return False
        if not self.sync_owned:
            return True
        return self._zone_sync_group(zone_id) is None

    def set_sync_ownership(self, synchronized: bool) -> None:
        """Update whether synchronized lighting owns the mouse."""
        if self.sync_owned == synchronized:
            return

        self.sync_owned = synchronized
        self.update_interaction_state()

    def set_device_connected(self, connected: bool) -> None:
        """Keep the saved profile visible when hardware disappears."""
        if self.device_connected == connected:
            return

        self.device_connected = connected
        self.update_interaction_state()

    def update_interaction_state(self) -> None:
        if not self.device_connected:
            logo_editable = side_editable = False
        elif not self.sync_owned:
            logo_editable = side_editable = True
        else:
            logo_editable = self._zone_editable("logo")
            side_editable = self._zone_editable("side-buttons")

        if not logo_editable:
            self.logo_editor.preview_timer.stop()
            self.logo_editor.colour_preview_timer.stop()
        if not side_editable:
            self.side_editor.preview_timer.stop()
            self.side_editor.colour_preview_timer.stop()

        self.link_checkbox.setEnabled(self.device_connected and not self.sync_owned)
        self.live_preview_checkbox.setEnabled(self.device_connected and not self.sync_owned)
        self.restore_button.setEnabled(self.device_connected and not self.sync_owned)
        self.logo_editor.setEnabled(logo_editable)
        self.side_editor.setEnabled(side_editable)

        ownership_state = (
            "disconnected"
            if not self.device_connected
            else "sync"
            if self.sync_owned
            else "individual"
        )
        self.ownership_label.setProperty("ownershipState", ownership_state)
        self.ownership_label.style().unpolish(self.ownership_label)
        self.ownership_label.style().polish(self.ownership_label)
        self.ownership_label.update()

        for editor, editable in (
            (self.logo_editor, logo_editable),
            (self.side_editor, side_editable),
        ):
            editor.setProperty(
                "controlState",
                "disconnected"
                if not self.device_connected
                else "sync"
                if self.sync_owned and not editable
                else "individual",
            )
            editor.style().unpolish(editor)
            editor.style().polish(editor)
            editor.update()

        if not self.device_connected:
            self.ownership_label.setText(
                "Mouse disconnected. The saved individual profile is still available."
            )
            return
        if not self.sync_owned:
            self.ownership_label.setText("Individual lighting active.")
            self.update_link_state()
            return

        locked = []
        for zone_id, label in (("logo", "Logo"), ("side-buttons", "Side Buttons")):
            group = self._zone_sync_group(zone_id)
            if group:
                locked.append(f"{label}: {group}")

        if locked:
            self.ownership_label.setText(
                "Sync owns grouped regions only. Ungrouped regions remain editable. "
                "Locked — " + "; ".join(locked)
            )
        else:
            self.ownership_label.setText(
                "Sync owns the physical writer; both ungrouped mouse regions remain editable."
            )

    def set_live_preview(
        self,
        enabled: bool,
    ) -> None:
        self.logo_editor.live_preview_enabled = enabled
        self.side_editor.live_preview_enabled = enabled

        if not enabled:
            self.logo_editor.preview_timer.stop()
            self.logo_editor.colour_preview_timer.stop()
            self.side_editor.preview_timer.stop()
            self.side_editor.colour_preview_timer.stop()

        self.status_label.setText(
            "Live preview enabled."
            if enabled
            else "Live preview disabled."
        )

    def show_error(self, exc: Exception) -> None:
        self.status_label.setText(
            f"Error: {exc}"
        )

        notify_error(
            self,
            "Serpent error",
            str(exc),
        )

    def update_link_state(self) -> None:
        linked = self.link_checkbox.isChecked()

        self.side_editor.setEnabled(
            not linked
        )

        self.logo_editor.apply_button.setText(
            "Apply Both Zones"
            if linked
            else "Apply Logo"
        )

    def change_link_state(
        self,
        linked: bool,
    ) -> None:
        if self.sync_owned or not self.device_connected:
            return

        try:
            backend = get_mouse_backend()
            backend.set_linked(linked)

            if linked:
                profile = load_profile()
                logo = (
                    profile["mouse"]["zones"]["logo"]
                )

                self.side_editor.load_settings(
                    logo
                )

                self.status_label.setText(
                    "Mouse zones linked. "
                    "Logo settings now control both zones."
                )
            else:
                self.status_label.setText(
                    "Mouse zones unlinked. "
                    "Logo and Side Buttons can now "
                    "be configured independently."
                )

            self.update_link_state()
            self.refresh_dashboard()

        except (
            GuiError,
            BackendError,
            FixtureError,
            OSError,
            ValueError,
            KeyError,
        ) as exc:
            self.link_checkbox.blockSignals(True)
            self.link_checkbox.setChecked(
                not linked
            )
            self.link_checkbox.blockSignals(False)
            self.update_link_state()
            self.show_error(exc)

    def apply_logo(
        self,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        if not self.device_connected:
            return
        if self.sync_owned and not self._zone_editable("logo"):
            self.status_label.setText(
                f"Logo is controlled by Sync group {self._zone_sync_group('logo')}."
            )
            return

        self.logo_editor.apply_button.setEnabled(False)
        QApplication.processEvents()
        try:
            profile = load_profile()
            mouse_profile = profile.setdefault("mouse", {})
            zones = mouse_profile.setdefault("zones", {})
            linked = self.link_checkbox.isChecked() and not self.sync_owned
            candidate = _personal_profile_settings(effect, settings, self.fixture_effects)
            zones["logo"] = candidate
            if linked:
                zones["side-buttons"] = dict(candidate)
            mouse_profile["linked"] = linked

            instance_id = str(getattr(self, "instance_id", ""))
            fixture_id = str(getattr(self, "fixture_id", "razer-naga-v2-pro-wireless"))
            if instance_id:
                store_personal_region_settings(
                    profile, instance_id=instance_id, fixture_id=fixture_id,
                    region_id="logo", settings=candidate,
                )
                if linked:
                    store_personal_region_settings(
                        profile, instance_id=instance_id, fixture_id=fixture_id,
                        region_id="side-buttons", settings=candidate,
                    )
            _save_profile_atomic(profile)

            if self.sync_owned:
                _request_sync_renderer_reload()
                self.logo_editor.load_settings(candidate)
                self.status_label.setText(
                    f"Saved {humanize(effect)} for the ungrouped Logo; Sync reloaded it."
                )
                self.refresh_dashboard()
                return

            other = zones.get("side-buttons", {})
            software_needed = (
                _is_dynamic_device_effect(
                    str(zones["logo"].get("effect", "static")), "mouse", self.fixture_effects
                )
                or (
                    not linked
                    and _is_dynamic_device_effect(
                        str(other.get("effect", "static")), "mouse", self.fixture_effects
                    )
                )
            )
            if _panel_uses_software_rgb(self) or (software_needed):
                _restart_individual_renderer()
                self.logo_editor.load_settings(candidate)
                if linked:
                    self.side_editor.load_settings(candidate)
                return
            else:
                backend = get_mouse_backend()
                if linked:
                    backend.apply(effect, settings)
                    self.logo_editor.load_settings(candidate)
                    self.side_editor.load_settings(candidate)
                else:
                    backend.apply_zone("logo", effect, settings)
                    self.logo_editor.load_settings(candidate)

            self.status_label.setText(
                f"Applied {humanize(effect)} "
                + ("to both mouse zones." if linked else "to the Logo.")
            )
            self.refresh_dashboard()
        except (GuiError, BackendError, FixtureError, OSError, ValueError, KeyError) as exc:
            self.show_error(exc)
        finally:
            self.logo_editor.apply_button.setEnabled(self._zone_editable("logo"))

    def apply_side_buttons(
        self,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        if not self.device_connected:
            return
        if self.sync_owned and not self._zone_editable("side-buttons"):
            self.status_label.setText(
                f"Side Buttons are controlled by Sync group {self._zone_sync_group('side-buttons')}."
            )
            return

        self.side_editor.apply_button.setEnabled(False)
        QApplication.processEvents()
        try:
            profile = load_profile()
            mouse_profile = profile.setdefault("mouse", {})
            zones = mouse_profile.setdefault("zones", {})
            candidate = _personal_profile_settings(effect, settings, self.fixture_effects)
            zones["side-buttons"] = candidate

            instance_id = str(getattr(self, "instance_id", ""))
            fixture_id = str(getattr(self, "fixture_id", "razer-naga-v2-pro-wireless"))
            if instance_id:
                store_personal_region_settings(
                    profile, instance_id=instance_id, fixture_id=fixture_id,
                    region_id="side-buttons", settings=candidate,
                )
            _save_profile_atomic(profile)

            if self.sync_owned:
                _request_sync_renderer_reload()
                self.side_editor.load_settings(candidate)
                self.status_label.setText(
                    f"Saved {humanize(effect)} for ungrouped Side Buttons; Sync reloaded it."
                )
                self.refresh_dashboard()
                return

            logo = zones.get("logo", {})
            software_needed = (
                _is_dynamic_device_effect(
                    str(logo.get("effect", "static")), "mouse", self.fixture_effects
                )
                or _is_dynamic_device_effect(effect, "mouse", self.fixture_effects)
            )
            if _panel_uses_software_rgb(self) or (software_needed):
                _restart_individual_renderer()
                self.side_editor.load_settings(candidate)
                return
            else:
                backend = get_mouse_backend()
                backend.apply_zone("side-buttons", effect, settings)
                self.side_editor.load_settings(candidate)

            self.status_label.setText(
                f"Applied {humanize(effect)} to the Side Buttons."
            )
            self.refresh_dashboard()
        except (GuiError, BackendError, FixtureError, OSError, ValueError, KeyError) as exc:
            self.show_error(exc)
        finally:
            self.side_editor.apply_button.setEnabled(
                self._zone_editable("side-buttons")
            )


    def refresh_effect_catalog(self) -> None:
        self.effects = _device_effect_catalog(
            "mouse", self.fixture_effects
        )
        self.logo_editor.replace_effects(self.effects)
        self.side_editor.replace_effects(self.effects)

    def refresh_dashboard(self) -> None:
        if self.status_refresh_callback is not None:
            QTimer.singleShot(0, self.status_refresh_callback)

    def restore_profile(self) -> None:
        if self.sync_owned or not self.device_connected:
            return

        result = subprocess.run(
            [
                "systemctl",
                "--user",
                "restart",
                "serpent-individual.service",
            ],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )

        if result.returncode != 0:
            self.show_error(
                GuiError(
                    result.stdout.strip()
                    or "Could not restore mouse profile."
                )
            )
            return

        self.status_label.setText(
            "Restored the saved mouse profile."
        )
        self.refresh_dashboard()


class KeyboardPanel(QWidget):
    def __init__(
        self,
        fixture: dict[str, Any],
        profile: dict[str, Any],
        status_refresh_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serpentKeyboardPanel")

        self.fixture = fixture
        self.fixture_effects = dict(fixture.get("effects", {}))
        self.effects = _device_effect_catalog("keyboard", self.fixture_effects)
        if "wave" in self.fixture_effects and "wave" in self.effects:
            self.effects["wave"] = dict(
                self.fixture_effects["wave"]
            )
        self.status_refresh_callback = status_refresh_callback
        self.settings = dict(
            profile.get("keyboard", {})
        )

        self.effect_combo = QComboBox()
        self.brightness_slider = QSlider(
            Qt.Orientation.Horizontal
        )
        self.brightness_value = QLabel()

        self.colour1_button = ColourButton(
            self.settings.get(
                "colour1",
                [0, 0, 255],
            )
        )
        self.colour2_button = ColourButton(
            self.settings.get(
                "colour2",
                [0, 255, 255],
            )
        )

        self.speed_spin = QSpinBox()
        self.direction_combo = QComboBox()

        self.colour1_label = QLabel(
            "Primary colour"
        )
        self.colour2_label = QLabel(
            "Secondary colour"
        )
        self.speed_label = QLabel("Speed")
        self.direction_label = QLabel(
            "Direction"
        )

        self.apply_button = QPushButton("Apply")
        self.restore_button = QPushButton(
            "Restore saved profile"
        )
        self.live_preview_checkbox = QCheckBox(
            "Live preview"
        )
        self.live_preview_checkbox.setChecked(True)

        self.live_preview_enabled = True
        self.loading_settings = False
        self.apply_in_progress = False
        self.pending_apply = False

        self.preview_timer = QTimer(self)
        self.preview_timer.setSingleShot(True)
        self.preview_timer.setInterval(350)
        self.preview_timer.timeout.connect(
            self.apply_settings
        )

        self.colour_preview_timer = QTimer(self)
        self.colour_preview_timer.setSingleShot(True)
        self.colour_preview_timer.setInterval(900)
        self.colour_preview_timer.timeout.connect(
            self.apply_settings
        )

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("serpentDeviceActionStatus")
        self.ownership_label = QLabel("Individual lighting active.")
        self.ownership_label.setObjectName("serpentOwnershipState")
        self.ownership_label.setProperty("ownershipState", "individual")
        self.ownership_label.setWordWrap(True)
        self.sync_owned = False
        self.device_connected = True

        self.build_ui()
        self.load_current_settings()
        self.update_effect_controls()

    def build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        title = QLabel(
            "Razer DeathStalker V2"
        )
        title.setObjectName("serpentDevicePageTitle")

        title_font = title.font()
        title_font.setPointSize(
            title_font.pointSize() + 3
        )
        title_font.setBold(True)
        title.setFont(title_font)

        details = QLabel(
            f"Fixture: {self.fixture['id']}\n"
            f"Backend: "
            f"{self.fixture['backend']['type']}\n"
            f"USB ID: "
            f"{self.fixture['usb']['vendor_id']}:"
            f"{self.fixture['usb']['product_id']}"
        )
        details.setObjectName("serpentDevicePageDetails")
        details.setProperty("serpentRole", "secondaryText")

        separator = QFrame()
        separator.setFrameShape(
            QFrame.Shape.HLine
        )
        separator.setFrameShadow(
            QFrame.Shadow.Sunken
        )

        outer.addWidget(title)
        outer.addWidget(details)
        outer.addWidget(separator)
        outer.addWidget(self.ownership_label)
        outer.addWidget(self.live_preview_checkbox)

        form = QFormLayout()

        for effect_name in self.effects:
            self.effect_combo.addItem(
                humanize(effect_name),
                effect_name,
            )

        self.effect_combo.currentIndexChanged.connect(
            self.update_effect_controls
        )

        form.addRow("Effect", self.effect_combo)

        self.brightness_slider.setRange(0, 100)
        self.brightness_slider.valueChanged.connect(
            self.update_brightness_label
        )

        brightness_row = QWidget()
        brightness_layout = QHBoxLayout(
            brightness_row
        )
        brightness_layout.setContentsMargins(
            0,
            0,
            0,
            0,
        )

        brightness_layout.addWidget(
            self.brightness_slider
        )
        brightness_layout.addWidget(
            self.brightness_value
        )

        form.addRow("Brightness", brightness_row)

        form.addRow(
            self.colour1_label,
            self.colour1_button,
        )
        form.addRow(
            self.colour2_label,
            self.colour2_button,
        )

        self.speed_spin.setRange(1, 10)

        form.addRow(
            self.speed_label,
            self.speed_spin,
        )

        self.direction_combo.addItem(
            "Direction 1",
            1,
        )
        self.direction_combo.addItem(
            "Direction 2",
            2,
        )

        form.addRow(
            self.direction_label,
            self.direction_combo,
        )

        outer.addLayout(form)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(
            self.restore_button
        )
        button_row.addWidget(
            self.apply_button
        )

        outer.addLayout(button_row)
        outer.addWidget(self.status_label)
        outer.addStretch()

        self.apply_button.clicked.connect(
            self.apply_settings
        )
        self.restore_button.clicked.connect(
            self.restore_profile
        )
        self.live_preview_checkbox.toggled.connect(
            self.set_live_preview
        )

        self.effect_combo.currentIndexChanged.connect(
            self.schedule_preview
        )
        self.brightness_slider.valueChanged.connect(
            self.schedule_preview
        )
        self.colour1_button.previewChanged.connect(
            self.schedule_colour_preview
        )
        self.colour2_button.previewChanged.connect(
            self.schedule_colour_preview
        )

        self.colour1_button.colourCommitted.connect(
            self.apply_colour_now
        )
        self.colour2_button.colourCommitted.connect(
            self.apply_colour_now
        )

        self.colour1_button.colourCancelled.connect(
            self.apply_colour_now
        )
        self.colour2_button.colourCancelled.connect(
            self.apply_colour_now
        )
        self.speed_spin.valueChanged.connect(
            self.schedule_preview
        )
        self.direction_combo.currentIndexChanged.connect(
            self.schedule_preview
        )

    def set_sync_ownership(self, synchronized: bool) -> None:
        """Update whether synchronized lighting owns the keyboard."""
        if self.sync_owned == synchronized:
            return

        self.sync_owned = synchronized
        self.update_interaction_state()

    def set_device_connected(self, connected: bool) -> None:
        """Keep the saved keyboard profile visible across disconnects."""
        if self.device_connected == connected:
            return

        self.device_connected = connected
        self.update_interaction_state()

    def update_interaction_state(self) -> None:
        editable = self.device_connected and not self.sync_owned

        if not editable:
            self.preview_timer.stop()
            self.colour_preview_timer.stop()

        for widget in (
            self.live_preview_checkbox,
            self.effect_combo,
            self.brightness_slider,
            self.colour1_button,
            self.colour2_button,
            self.speed_spin,
            self.direction_combo,
            self.apply_button,
            self.restore_button,
        ):
            widget.setEnabled(editable)

        ownership_state = (
            "individual"
            if editable
            else "disconnected"
            if not self.device_connected
            else "sync"
        )
        self.ownership_label.setProperty("ownershipState", ownership_state)
        self.ownership_label.style().unpolish(self.ownership_label)
        self.ownership_label.style().polish(self.ownership_label)
        self.ownership_label.update()

        if editable:
            self.ownership_label.setText("Individual lighting active.")
        elif not self.device_connected:
            self.ownership_label.setText(
                "Keyboard disconnected. The saved individual profile is "
                "still available and will be used when the device returns."
            )
        else:
            self.ownership_label.setText(
                "Synchronized lighting is active. This saved keyboard "
                "profile is visible but is not currently controlling "
                "the device."
            )

    def set_live_preview(self, enabled: bool) -> None:
        self.live_preview_enabled = enabled

        if not enabled:
            self.preview_timer.stop()
            self.colour_preview_timer.stop()

        self.status_label.setText(
            "Keyboard live preview enabled."
            if enabled
            else "Keyboard live preview disabled."
        )

    def schedule_preview(self) -> None:
        if (
            not self.live_preview_enabled
            or self.loading_settings
        ):
            return

        self.preview_timer.start()

    def schedule_colour_preview(self) -> None:
        if (
            not self.live_preview_enabled
            or self.loading_settings
        ):
            return

        self.preview_timer.stop()
        self.colour_preview_timer.start()

    def apply_colour_now(self) -> None:
        if (
            not self.live_preview_enabled
            or self.loading_settings
        ):
            return

        self.preview_timer.stop()
        self.colour_preview_timer.stop()
        self.apply_settings()

    def load_current_settings(self) -> None:
        self.loading_settings = True

        try:
            current_effect = self.settings.get(
                "effect",
                "static",
            )

            index = self.effect_combo.findData(
                current_effect
            )

            if index >= 0:
                self.effect_combo.setCurrentIndex(
                    index
                )

            brightness = int(
                self.settings.get("brightness", 40)
            )

            self.brightness_slider.setValue(
                brightness
            )
            self.update_brightness_label(
                brightness
            )

            self.colour1_button.set_colour(
                self.settings.get(
                    "colour1",
                    [0, 0, 255],
                )
            )

            self.colour2_button.set_colour(
                self.settings.get(
                    "colour2",
                    [0, 255, 255],
                )
            )

            self.speed_spin.setValue(
                int(self.settings.get("speed", 2))
            )

            direction = int(
                self.settings.get("direction", 1)
            )

            direction_index = (
                self.direction_combo.findData(
                    direction
                )
            )

            if direction_index >= 0:
                self.direction_combo.setCurrentIndex(
                    direction_index
                )

        finally:
            self.loading_settings = False

    def update_brightness_label(
        self,
        value: int,
    ) -> None:
        self.brightness_value.setText(
            f"{value}%"
        )

    def current_effect_definition(
        self,
    ) -> dict[str, Any]:
        effect = self.effect_combo.currentData()
        definition = self.effects.get(effect, {})

        if isinstance(definition, dict):
            return definition

        return {}

    def update_effect_controls(self) -> None:
        definition = (
            self.current_effect_definition()
        )

        colour_count = int(
            definition.get("colours", 0)
        )

        self.colour1_label.setVisible(
            colour_count >= 1
        )
        self.colour1_button.setVisible(
            colour_count >= 1
        )

        self.colour2_label.setVisible(
            colour_count >= 2
        )
        self.colour2_button.setVisible(
            colour_count >= 2
        )

        speed_values = definition.get(
            "speeds"
        )

        has_speed = bool(
            definition.get("speed")
            or speed_values
        )

        directions = definition.get(
            "directions"
        )

        self.speed_label.setVisible(has_speed)
        self.speed_spin.setVisible(has_speed)

        self.direction_label.setVisible(
            bool(directions)
        )
        self.direction_combo.setVisible(
            bool(directions)
        )

        if speed_values:
            values = [
                int(value)
                for value in speed_values
            ]

            self.speed_spin.setRange(
                min(values),
                max(values),
            )

    def build_command(self) -> list[str]:
        effect = str(
            self.effect_combo.currentData()
        )

        definition = (
            self.current_effect_definition()
        )

        command = [
            "keyboard",
            "set",
            effect,
            "--brightness",
            str(self.brightness_slider.value()),
        ]

        colour_count = int(
            definition.get("colours", 0)
        )

        if colour_count >= 1:
            command.extend(
                [
                    "--colour1",
                    *(
                        str(value)
                        for value
                        in self.colour1_button
                        .colour_tuple()
                    ),
                ]
            )

        if colour_count >= 2:
            command.extend(
                [
                    "--colour2",
                    *(
                        str(value)
                        for value
                        in self.colour2_button
                        .colour_tuple()
                    ),
                ]
            )

        if (
            definition.get("speed")
            or definition.get("speeds")
        ):
            command.extend(
                [
                    "--speed",
                    str(self.speed_spin.value()),
                ]
            )

        if definition.get("directions"):
            command.extend(
                [
                    "--direction",
                    str(
                        self.direction_combo
                        .currentData()
                    ),
                ]
            )

        return command

    def apply_settings(self) -> None:
        if self.sync_owned or not self.device_connected:
            return

        self.preview_timer.stop()
        self.colour_preview_timer.stop()

        if self.apply_in_progress:
            self.pending_apply = True
            return

        self.apply_in_progress = True
        self.apply_button.setEnabled(False)
        self.status_label.setText(
            "Previewing…"
            if self.live_preview_enabled
            else "Applying…"
        )
        QApplication.processEvents()

        try:
            effect = str(self.effect_combo.currentData())
            if _is_dynamic_device_effect(
                effect, "keyboard", self.fixture_effects
            ):
                overrides = {"brightness": self.brightness_slider.value()}
                definition = self.current_effect_definition()
                if int(definition.get("colours", 0)) >= 1:
                    overrides["colour1"] = list(self.colour1_button.colour_tuple())
                if int(definition.get("colours", 0)) >= 2:
                    overrides["colour2"] = list(self.colour2_button.colour_tuple())
                if definition.get("speed") or definition.get("speeds"):
                    overrides["speed"] = self.speed_spin.value()
                if definition.get("directions"):
                    overrides["direction"] = int(self.direction_combo.currentData())

                profile = load_profile()
                profile["keyboard"] = _plugin_profile_settings(effect, overrides)
                _save_profile_atomic(profile)
                _restart_individual_renderer()
                self.settings = dict(profile["keyboard"])
                self.status_label.setText(
                    f"Applied software plugin {humanize(effect)}."
                )
            else:
                output = run_serpent(self.build_command())
                self.status_label.setText(output or "Applied successfully.")
            self.refresh_dashboard()

        except GuiError as exc:
            notify_error(
                self,
                "Serpent error",
                str(exc),
            )
            self.status_label.setText(
                f"Error: {exc}"
            )

        finally:
            self.apply_button.setEnabled(True)
            self.apply_in_progress = False

        if self.pending_apply:
            self.pending_apply = False
            self.preview_timer.start(500)


    def refresh_effect_catalog(self) -> None:
        selected = self.effect_combo.currentData()
        self.effects = _device_effect_catalog(
            "keyboard", self.fixture_effects
        )
        if "wave" in self.fixture_effects and "wave" in self.effects:
            self.effects["wave"] = dict(
                self.fixture_effects["wave"]
            )
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for effect_name in self.effects:
            self.effect_combo.addItem(humanize(effect_name), effect_name)
        if selected is not None:
            index = self.effect_combo.findData(selected)
            if index >= 0:
                self.effect_combo.setCurrentIndex(index)
        self.effect_combo.blockSignals(False)
        self.update_effect_controls()

    def refresh_dashboard(self) -> None:
        if self.status_refresh_callback is not None:
            QTimer.singleShot(0, self.status_refresh_callback)

    def restore_profile(self) -> None:
        if self.sync_owned or not self.device_connected:
            return

        try:
            output = run_serpent(
                ["keyboard", "apply-profile"]
            )

            self.status_label.setText(output)
            self.refresh_dashboard()

        except GuiError as exc:
            notify_error(
                self,
                "Serpent error",
                str(exc),
            )


class PluginParameterEditor(QWidget):
    # Schema-driven Qt editor for one EffectPluginSpec.
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = None
        self._presentation = None
        self._controls: dict[str, QWidget] = {}
        self._cache: dict[str, Any] = {}
        self._form = QFormLayout(self)
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

    @property
    def controls(self) -> dict[str, QWidget]:
        return dict(self._controls)

    def _capture(self) -> None:
        if self._controls:
            self._cache.update(self.values())

    def _clear(self) -> None:
        while self._form.rowCount():
            self._form.removeRow(0)
        self._controls.clear()

    def _choice_label(self, parameter, value: Any) -> str:
        if parameter.id == 'direction' and self._presentation is not None:
            for choice in self._presentation.directions:
                if choice.value == value:
                    return choice.label
        return str(value)

    def _make_control(self, parameter) -> QWidget:
        value = self._cache.get(parameter.id, parameter.default)
        if parameter.kind == 'colour':
            control = ColourButton(value, self)
            control.previewChanged.connect(self.changed)
            control.colourCommitted.connect(self.changed)
            return control
        if parameter.kind == 'integer':
            control = QSpinBox(self)
            control.setRange(
                int(parameter.minimum) if parameter.minimum is not None else -2147483648,
                int(parameter.maximum) if parameter.maximum is not None else 2147483647,
            )
            control.setValue(int(value))
            control.valueChanged.connect(self.changed)
            return control
        if parameter.kind == 'number':
            control = QDoubleSpinBox(self)
            control.setRange(
                float(parameter.minimum) if parameter.minimum is not None else -1e9,
                float(parameter.maximum) if parameter.maximum is not None else 1e9,
            )
            control.setDecimals(3)
            control.setValue(float(value))
            control.valueChanged.connect(self.changed)
            return control
        if parameter.kind == 'choice':
            control = QComboBox(self)
            for choice in parameter.choices:
                control.addItem(self._choice_label(parameter, choice), choice)
            index = control.findData(value)
            if index >= 0:
                control.setCurrentIndex(index)
            control.currentIndexChanged.connect(self.changed)
            return control
        if parameter.kind == 'boolean':
            control = QCheckBox(self)
            control.setChecked(bool(value))
            control.toggled.connect(self.changed)
            return control
        raise GuiError(f'Unsupported plugin parameter kind: {parameter.kind!r}')

    def set_effect(self, effect_id: str, presentation=None) -> None:
        self.set_spec(get_effect_plugin_spec(effect_id), presentation)

    def set_spec(self, spec, presentation=None) -> None:
        self._capture()
        self._clear()
        self._spec = spec
        self._presentation = presentation
        if not spec.parameters:
            empty = QLabel('This effect has no effect-specific controls.')
            empty.setWordWrap(True)
            self._form.addRow(empty)
            return
        for parameter in spec.parameters:
            control = self._make_control(parameter)
            self._controls[parameter.id] = control
            self._form.addRow(parameter.label, control)

    def values(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        if self._spec is None:
            return result
        for parameter in self._spec.parameters:
            control = self._controls.get(parameter.id)
            if control is None:
                continue
            if parameter.kind == 'colour':
                result[parameter.id] = list(control.colour_tuple())
            elif parameter.kind in {'integer', 'number'}:
                result[parameter.id] = control.value()
            elif parameter.kind == 'choice':
                result[parameter.id] = control.currentData()
            elif parameter.kind == 'boolean':
                result[parameter.id] = control.isChecked()
        return result

    def load_values(self, values: dict[str, Any]) -> None:
        if self._spec is None:
            return
        self._cache.update({k: v for k, v in values.items() if isinstance(k, str)})
        for parameter in self._spec.parameters:
            if parameter.id not in values:
                continue
            control = self._controls.get(parameter.id)
            if control is None:
                continue
            value = values[parameter.id]
            control.blockSignals(True)
            try:
                if parameter.kind == 'colour':
                    control.set_colour(value)
                elif parameter.kind == 'integer':
                    control.setValue(int(value))
                elif parameter.kind == 'number':
                    control.setValue(float(value))
                elif parameter.kind == 'choice':
                    index = control.findData(value)
                    if index >= 0:
                        control.setCurrentIndex(index)
                elif parameter.kind == 'boolean':
                    control.setChecked(bool(value))
            finally:
                control.blockSignals(False)

    def cli_arguments(self) -> list[str]:
        if self._spec is None:
            return []
        values = self.values()
        arguments: list[str] = []
        for parameter in self._spec.parameters:
            if parameter.id not in values:
                continue
            option = '--' + parameter.id.replace('_', '-')
            value = values[parameter.id]
            if parameter.kind == 'colour':
                arguments.extend([option, *(str(v) for v in value)])
            elif parameter.kind in {'integer', 'number', 'choice'}:
                arguments.extend([option, str(value)])
            elif parameter.kind == 'boolean':
                arguments.append(option if value else '--no-' + parameter.id.replace('_', '-'))
        return arguments


class SyncPanel(QWidget):
    # M10.0.0.39-L - workshop scenes sync visual roles
    REFRESH_INTERVAL_MS = 1_000

    def __init__(self, status_refresh_callback: Callable[[], None] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("serpentSyncPanel")
        self.status_refresh_callback = status_refresh_callback
        self.presentations = {item.id: item for item in effect_presentations()}
        self.loading = False
        self.editor_dirty = False
        self.runtime_synchronized = False
        self._profile_signature = ''
        self.group_combo = QComboBox()
        self.group_combo.setEditable(True)
        self.add_group_button = QPushButton('Add group')
        self.delete_group_button = QPushButton('Delete group')
        self.effect_combo = QComboBox()
        self.effect_parameters = PluginParameterEditor(self)
        self.effect_description_label = QLabel(); self.effect_description_label.setWordWrap(True)
        self.effect_description_label.setProperty("serpentRole", "secondaryText")
        self.effect_input_label = QLabel(); self.effect_input_label.setWordWrap(True)
        self.effect_input_label.setProperty("serpentRole", "secondaryText")
        self.effect_targets_label = QLabel(); self.effect_targets_label.setWordWrap(True)
        self.effect_targets_label.setProperty("serpentRole", "secondaryText")
        self.members_group = QGroupBox('Physical Members')
        self.members_layout = QFormLayout(self.members_group)
        self.member_group_combos: dict[str,QComboBox] = {}
        self.member_brightness_sliders: dict[str,QSlider] = {}
        self.member_brightness_values: dict[str,QLabel] = {}
        self.rendering_label = QLabel(); self.rendering_label.setWordWrap(True)
        self.status_label = QLabel('Ready'); self.status_label.setWordWrap(True)
        self.enable_button = QPushButton('Enable synchronization')
        self.enable_button.setObjectName("serpentSyncPrimaryAction")
        self.enable_button.setProperty("serpentRole", "primaryAction")
        self.disable_button = QPushButton('Disable synchronization')
        self.disable_button.setObjectName("serpentSyncDisableAction")
        self.disable_button.setProperty("serpentRole", "secondaryAction")
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.setProperty("serpentRole", "secondaryAction")
        self.add_group_button.setProperty("serpentRole", "secondaryAction")
        self.delete_group_button.setProperty("serpentRole", "dangerAction")
        self.members_group.setObjectName("serpentSyncMembersCard")
        self.status_label.setObjectName("serpentSyncStatus")
        self.status_label.setProperty("serpentRole", "statusStrip")
        self.build_ui()
        self.refresh_from_engine()

    @staticmethod
    def profile_signature(sync_profile: dict[str,Any]) -> str:
        return json.dumps(sync_profile,sort_keys=True,separators=(',',':'))

    @staticmethod
    def parse_sync_status(output: str) -> dict[str,str]:
        values={}
        for line in output.splitlines():
            if ':' not in line: continue
            key,value=line.split(':',1); key=key.strip(); value=value.strip()
            if key and not key.startswith('-'): values[key]=value
        return values

    def _sync_profile(self) -> dict[str,Any]:
        profile=load_profile(); sync=profile.get('sync',{})
        return dict(sync) if isinstance(sync,dict) else {}

    def _groups(self) -> list[dict[str,Any]]:
        groups=self._sync_profile().get('groups',[])
        return [dict(group) for group in groups if isinstance(group,dict)] if isinstance(groups,list) else []

    def _atomic_save_sync(self,sync: dict[str,Any]) -> None:
        profile=load_profile(); profile['sync']=sync
        PROFILE_PATH.parent.mkdir(parents=True,exist_ok=True)
        temp_path=PROFILE_PATH.with_name(PROFILE_PATH.name+'.m28.tmp')
        temp_path.write_text(json.dumps(profile,indent=4)+'\n',encoding='utf-8')
        temp_path.replace(PROFILE_PATH)

    def current_group_id(self) -> str:
        return str(self.group_combo.currentData() or '')

    def current_group(self) -> dict[str,Any] | None:
        wanted=self.current_group_id()
        for group in self._groups():
            if str(group.get('id',''))==wanted: return group
        return None

    def build_ui(self) -> None:
        outer=QVBoxLayout(self); outer.setContentsMargins(18,18,18,18); outer.setSpacing(14)
        title=QLabel('Synchronization Groups'); font=title.font(); font.setPointSize(font.pointSize()+3); font.setBold(True); title.setFont(font)
        subtitle=QLabel('Assign each physical device zone to one independent synchronization group or leave it ungrouped.'); subtitle.setWordWrap(True); subtitle.setObjectName("serpentSecondaryLabel"); subtitle.setProperty("serpentRole","secondaryText")
        group_row=QHBoxLayout(); group_row.addWidget(QLabel('Group')); group_row.addWidget(self.group_combo,1); group_row.addWidget(self.add_group_button); group_row.addWidget(self.delete_group_button)
        form=QFormLayout(); form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for p in self.presentations.values(): self.effect_combo.addItem(p.name,p.id)
        form.addRow('Effect',self.effect_combo); form.addRow(self.effect_parameters)
        info = QGroupBox('Effect Information')
        info.setObjectName("serpentSyncEffectInfoCard")
        info.setProperty("serpentRole", "infoCard")
        il = QFormLayout(info)
        il.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        il.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        il.setContentsMargins(14, 14, 14, 14)
        il.setHorizontalSpacing(14)
        il.setVerticalSpacing(8)
        il.addRow('Description', self.effect_description_label)
        il.addRow('Reactive Input', self.effect_input_label)
        il.addRow('Render Targets', self.effect_targets_label)
        rendering = QGroupBox('Rendering')
        rendering.setObjectName("serpentSyncRenderingCard")
        rendering.setProperty("serpentRole", "infoCard")
        rl = QVBoxLayout(rendering)
        rl.addWidget(self.rendering_label)
        buttons=QHBoxLayout(); buttons.addWidget(self.refresh_button); buttons.addStretch(); buttons.addWidget(self.disable_button); buttons.addWidget(self.enable_button)
        outer.addWidget(title); outer.addWidget(subtitle); outer.addLayout(group_row); outer.addLayout(form); outer.addWidget(info); outer.addWidget(self.members_group); outer.addWidget(rendering); outer.addLayout(buttons); outer.addWidget(self.status_label); outer.addStretch()
        self.group_combo.currentIndexChanged.connect(self.load_current_group)
        if self.group_combo.lineEdit() is not None: self.group_combo.lineEdit().editingFinished.connect(self.rename_current_group)
        self.add_group_button.clicked.connect(self.add_group); self.delete_group_button.clicked.connect(self.delete_group)
        self.effect_combo.currentIndexChanged.connect(self.update_effect_controls); self.effect_combo.currentIndexChanged.connect(self.mark_editor_dirty)
        self.effect_parameters.changed.connect(self.mark_editor_dirty); self.refresh_button.clicked.connect(self.refresh_from_engine)
        self.enable_button.clicked.connect(self.enable_sync); self.disable_button.clicked.connect(self.disable_sync)

    def rebuild_group_combo(self,selected: str | None=None) -> None:
        groups=self._groups(); self.group_combo.blockSignals(True); self.group_combo.clear()
        for group in groups:
            gid=str(group.get('id','')); self.group_combo.addItem(str(group.get('name',gid)),gid)
        self.group_combo.blockSignals(False)
        if groups:
            index=self.group_combo.findData(selected) if selected else 0; self.group_combo.setCurrentIndex(index if index>=0 else 0)

    def _connected_member_catalog(self) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []

        for detected in detect_all_fixture_instances():
            device = build_device_model(
                detected.fixture,
                sysfs_path=detected.sysfs_path,
            )

            zones = device.controllable_zones() or device.visible_zones()

            if zones:
                for zone in zones:
                    key = f"{detected.instance_id}:{zone.id}"
                    rows.append((key, f"{device.name} · {zone.name}"))
                continue

            topology = require_topology(device)
            for region in topology.regions:
                key = f"{detected.instance_id}:{region.id}"
                label = (
                    getattr(region, "name", None)
                    or region.id.replace("-", " ").title()
                )
                rows.append((key, f"{device.name} · {label}"))

        rows.sort(key=lambda item: item[0])
        return rows

    def rebuild_member_rows(self) -> None:
        while self.members_layout.rowCount(): self.members_layout.removeRow(0)
        self.member_group_combos.clear(); self.member_brightness_sliders.clear(); self.member_brightness_values.clear()
        groups=self._groups(); names={str(g.get('id')):str(g.get('name',g.get('id'))) for g in groups}; owner={}; configured=set()
        for group in groups:
            gid=str(group.get('id','')); members=group.get('members',[])
            if not isinstance(members,list): continue
            for member in members:
                if not isinstance(member,dict): continue
                key=f"{member.get('instance_id')}:{member.get('zone_id')}"; owner[key]=(gid,float(member.get('brightness',100))); configured.add(key)
        connected=self._connected_member_catalog(); connected_keys={key for key,_ in connected}; rows=list(connected)
        for key in sorted(configured-connected_keys): rows.append((key,f'Offline · {key}'))
        for key,label in rows:
            assignment=QComboBox(); assignment.addItem('Ungrouped','')
            for gid,name in names.items(): assignment.addItem(name,gid)
            gid,brightness=owner.get(key,('',100.0)); index=assignment.findData(gid); assignment.setCurrentIndex(index if index>=0 else 0)
            slider=QSlider(Qt.Orientation.Horizontal); slider.setRange(0,100); slider.setValue(int(brightness)); value_label=QLabel(f'{int(brightness)}%')
            row=QWidget(); layout=QHBoxLayout(row); layout.setContentsMargins(0,0,0,0); layout.addWidget(assignment,1); layout.addWidget(slider,2); layout.addWidget(value_label)
            assignment.currentIndexChanged.connect(self.mark_editor_dirty)
            slider.valueChanged.connect(lambda value,target=value_label: target.setText(f'{value}%')); slider.valueChanged.connect(self.mark_editor_dirty)
            self.member_group_combos[key]=assignment; self.member_brightness_sliders[key]=slider; self.member_brightness_values[key]=value_label; self.members_layout.addRow(label,row)

    def add_group(self) -> None:
        groups=self._groups(); used={str(g.get('id','')) for g in groups}; number=1; gid='group'
        while gid in used: number+=1; gid=f'group-{number}'
        groups.append({'id':gid,'name':f'Group {number}','effect':'spectrum','speed':4,'colour1':[0,0,255],'colour2':[0,255,255],'direction':1,'members':[]})
        sync=self._sync_profile(); sync['groups']=groups; sync['group_schema_version']=1; self._atomic_save_sync(sync)
        self.rebuild_group_combo(gid); self.rebuild_member_rows(); self.load_current_group()

    def delete_group(self) -> None:
        gid=self.current_group_id()
        if not gid: return
        sync=self._sync_profile(); sync['groups']=[g for g in self._groups() if str(g.get('id',''))!=gid]; sync['group_schema_version']=1; self._atomic_save_sync(sync)
        self.rebuild_group_combo(); self.rebuild_member_rows(); self.load_current_group()

    def rename_current_group(self) -> None:
        gid=self.current_group_id(); name=self.group_combo.currentText().strip()
        if not gid or not name: return
        groups=self._groups()
        for group in groups:
            if str(group.get('id',''))==gid: group['name']=name
        sync=self._sync_profile(); sync['groups']=groups; self._atomic_save_sync(sync); self.rebuild_group_combo(gid)

    def current_presentation(self):
        return self.presentations.get(str(self.effect_combo.currentData()))

    @staticmethod
    def _capability_text(values,*,legacy_auto: bool=False) -> str:
        if values is None and legacy_auto: return 'Automatic (legacy capability detection)'
        if not values: return 'None'
        return ', '.join(str(v).replace('-',' ').title() for v in values)

    def update_effect_controls(self) -> None:
        presentation=self.current_presentation()
        if presentation is None: self.effect_description_label.clear(); self.effect_input_label.clear(); self.effect_targets_label.clear(); return
        spec=get_effect_plugin_spec(presentation.id); self.effect_parameters.set_spec(spec,presentation); self.effect_description_label.setText(spec.description)
        self.effect_input_label.setText(self._capability_text(spec.input_capabilities,legacy_auto=True)); self.effect_targets_label.setText(self._capability_text(spec.render_targets))

    def load_current_group(self,*args) -> None:
        if self.loading: return
        group=self.current_group()
        if group is None: self.update_primary_action_state(); return
        self.loading=True
        try:
            effect=str(group.get('effect','spectrum')); index=self.effect_combo.findData(effect)
            if index>=0: self.effect_combo.setCurrentIndex(index)
            self.update_effect_controls(); self.effect_parameters.load_values(group); self.editor_dirty=False
        finally: self.loading=False
        self.update_primary_action_state(); self.update_rendering_preview()

    def mark_editor_dirty(self,*args) -> None:
        if not self.loading: self.editor_dirty=True; self.update_primary_action_state()

    def _commit_editor_to_groups(self) -> None:
        groups=self._groups(); gid=self.current_group_id(); presentation=self.current_presentation()
        if not groups: raise GuiError('Create a synchronization group first.')
        if presentation is None: raise GuiError('No synchronized effect is selected.')
        by_id={}
        for group in groups:
            group_id=str(group.get('id','')); by_id[group_id]=group
            if group_id==gid: group['effect']=presentation.id; group.update(self.effect_parameters.values())
            group['members']=[]
        for key,combo in self.member_group_combos.items():
            assigned=str(combo.currentData() or '')
            if not assigned: continue
            if assigned not in by_id: raise GuiError(f'Unknown synchronization group {assigned!r}.')
            instance_id,zone_id=key.rsplit(':',1); by_id[assigned]['members'].append({'instance_id':instance_id,'zone_id':zone_id,'brightness':self.member_brightness_sliders[key].value()})
        sync=self._sync_profile(); sync['groups']=groups; sync['group_schema_version']=1; self._atomic_save_sync(sync); self._profile_signature=self.profile_signature(sync); self.editor_dirty=False

    def update_primary_action_state(self) -> None:
        if self.runtime_synchronized:
            if self.editor_dirty: self.enable_button.setText('Apply changes'); self.enable_button.setEnabled(True)
            else: self.enable_button.setText('Synchronized'); self.enable_button.setEnabled(False)
            self.disable_button.setEnabled(True); return
        self.enable_button.setText('Enable synchronization'); self.enable_button.setEnabled(bool(self._groups())); self.disable_button.setEnabled(False)

    def update_rendering_preview(self) -> None:
        groups=self._groups()
        if not groups: self.rendering_label.setText('No synchronization groups configured.'); return
        connected={key for key,_ in self._connected_member_catalog()}; lines=[]
        for group in groups:
            active=missing=0; members=group.get('members',[])
            if isinstance(members,list):
                for member in members:
                    if not isinstance(member,dict): continue
                    key=f"{member.get('instance_id')}:{member.get('zone_id')}"
                    if key in connected: active+=1
                    else: missing+=1
            lines.append(f"{group.get('name',group.get('id'))}: {group.get('effect','spectrum')} · {active} active · {missing} offline")
        self.rendering_label.setText('\n'.join(lines))

    def apply_runtime_state(self,values: dict[str,str]) -> None:
        owner=values.get('Owner','unknown'); service=values.get('Service','unknown'); state=values.get('State','unknown')
        self.runtime_synchronized=(owner=='sync' and service=='active' and state=='synchronized'); self.update_primary_action_state(); self.status_label.setText(f'Owner: {owner} · Service: {service} · State: {state}')

    def reconcile_runtime_snapshot(self,output: str,profile: dict[str,Any]) -> None:
        values=self.parse_sync_status(output); sync=profile.get('sync',{}); sync=sync if isinstance(sync,dict) else {}; signature=self.profile_signature(sync)
        if signature!=self._profile_signature and not self.editor_dirty:
            selected=self.current_group_id(); self._profile_signature=signature; self.rebuild_group_combo(selected); self.rebuild_member_rows(); self.load_current_group()
        self.apply_runtime_state(values)

    def refresh_runtime_state(self) -> None:
        try: self.reconcile_runtime_snapshot(run_serpent(['sync','status']),load_profile())
        except GuiError as exc: self.status_label.setText(f'Runtime status unavailable: {exc}')

    def refresh_from_engine(self) -> None:
        selected=self.current_group_id(); self.presentations={item.id:item for item in effect_presentations()}; self.effect_combo.blockSignals(True); self.effect_combo.clear()
        for presentation in self.presentations.values(): self.effect_combo.addItem(presentation.name,presentation.id)
        self.effect_combo.blockSignals(False); self.loading=True
        try:
            values=self.parse_sync_status(run_serpent(['sync','status'])); sync=self._sync_profile(); self._profile_signature=self.profile_signature(sync); self.rebuild_group_combo(selected); self.rebuild_member_rows()
        except (GuiError,TypeError,ValueError) as exc: values={}; self.status_label.setText(f'Synchronization refresh failed: {exc}')
        finally: self.loading=False
        self.load_current_group(); self.apply_runtime_state(values); self.editor_dirty=False; self.update_primary_action_state(); self.update_rendering_preview()

    def enable_sync(self) -> None:
        applying=self.runtime_synchronized; self.enable_button.setEnabled(False); QApplication.processEvents()
        try:
            self._commit_editor_to_groups(); group=self.current_group()
            if group is None: raise GuiError('No synchronization group is selected.')
            output=run_serpent(['sync','enable',str(group.get('effect','spectrum'))]); self.status_label.setText(output or ('Synchronization groups updated.' if applying else 'Synchronization groups enabled.')); self.refresh_from_engine(); self.refresh_dashboard()
        except GuiError as exc: self.status_label.setText(f'Could not apply synchronization groups: {exc}')
        finally: self.update_primary_action_state()

    def disable_sync(self) -> None:
        self.disable_button.setEnabled(False); QApplication.processEvents()
        try: output=run_serpent(['sync','disable']); self.status_label.setText(output or 'Synchronized lighting disabled.'); self.refresh_from_engine(); self.refresh_dashboard()
        except GuiError as exc: self.status_label.setText(f'Could not disable synchronization: {exc}')
        finally: self.update_primary_action_state()

    def refresh_dashboard(self) -> None:
        if self.status_refresh_callback is not None: QTimer.singleShot(0,self.status_refresh_callback)



class SceneLibraryPanel(QWidget):
    """Browse and apply saved Serpent scenes."""

    REFRESH_INTERVAL_MS = 1_000

    def __init__(
        self,
        runtime_refresh_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serpentScenesPanel")

        self.runtime_refresh_callback = runtime_refresh_callback
        self.workshop_open_callback = None
        self._repository_signature: tuple[tuple[str, int, int], ...] = ()

        self.scene_list = QListWidget()
        self.scene_list.setObjectName("serpentSceneList")
        self.details = QPlainTextEdit()
        self.details.setObjectName("serpentSceneDetails")
        self.details.setReadOnly(True)

        self.save_button = QPushButton("Save Current as Scene…")
        self.save_button.setProperty("serpentRole", "secondaryAction")
        self.rename_button = QPushButton("Rename scene…")
        self.rename_button.setProperty("serpentRole", "secondaryAction")
        self.apply_button = QPushButton("Apply scene")
        self.apply_button.setObjectName("serpentScenePrimaryAction")
        self.apply_button.setProperty("serpentRole", "primaryAction")
        self.workshop_button = QPushButton("Open in Workshop")
        self.workshop_button.setProperty("serpentRole", "secondaryAction")
        self.delete_button = QPushButton("Delete scene")
        self.delete_button.setProperty("serpentRole", "dangerAction")
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setProperty("serpentRole", "secondaryAction")

        self.status_label = QLabel(
            "No scenes saved yet."
        )
        self.status_label.setWordWrap(True)
        self.status_label.setObjectName("serpentSceneStatus")
        self.status_label.setProperty("serpentRole", "statusStrip")

        self.build_ui()

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(
            self.REFRESH_INTERVAL_MS
        )
        self.refresh_timer.timeout.connect(
            self.refresh_if_changed
        )

        self.refresh_scenes()
        self.refresh_timer.start()

    def build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        title = QLabel("Scenes")
        title_font = title.font()
        title_font.setPointSize(
            title_font.pointSize() + 3
        )
        title_font.setBold(True)
        title.setFont(title_font)

        description = QLabel(
            "Saved lighting setups. Select a scene to inspect it, "
            "then apply it through Serpent's shared scene runtime."
        )
        description.setWordWrap(True)
        description.setObjectName("serpentSecondaryLabel")
        description.setProperty("serpentRole", "secondaryText")

        layout.addWidget(title)
        layout.addWidget(description)

        content = QHBoxLayout()
        content.setSpacing(12)
        content.addWidget(self.scene_list, 2)
        content.addWidget(self.details, 3)
        layout.addLayout(content, 1)

        buttons = QHBoxLayout()
        buttons.addWidget(self.refresh_button)
        buttons.addWidget(self.save_button)
        buttons.addStretch()
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.delete_button)
        buttons.addWidget(self.workshop_button)
        buttons.addWidget(self.apply_button)

        layout.addLayout(buttons)
        layout.addWidget(self.status_label)

        self.scene_list.currentItemChanged.connect(
            self.selection_changed
        )
        self.scene_list.itemDoubleClicked.connect(
            lambda _item: self.apply_selected_scene()
        )
        self.refresh_button.clicked.connect(
            self.refresh_scenes
        )
        self.save_button.clicked.connect(
            self.save_current_scene
        )
        self.rename_button.clicked.connect(
            self.rename_selected_scene
        )
        self.apply_button.clicked.connect(
            self.apply_selected_scene
        )
        self.workshop_button.clicked.connect(
            self.open_selected_scene_in_workshop
        )
        self.delete_button.clicked.connect(
            self.delete_selected_scene
        )

    def repository(self) -> SceneRepository:
        return gui_scene_repository()

    def repository_signature(
        self,
    ) -> tuple[tuple[str, int, int], ...]:
        directory = self.repository().directory

        if not directory.is_dir():
            return ()

        result: list[tuple[str, int, int]] = []

        for path in sorted(
            directory.glob("*.json"),
            key=lambda candidate: candidate.name,
        ):
            try:
                stat = path.stat()
            except OSError:
                continue

            result.append(
                (
                    path.name,
                    stat.st_mtime_ns,
                    stat.st_size,
                )
            )

        return tuple(result)

    def selected_scene_id(self) -> str | None:
        item = self.scene_list.currentItem()

        if item is None:
            return None

        value = item.data(Qt.ItemDataRole.UserRole)

        return str(value) if value else None

    def refresh_if_changed(self) -> None:
        signature = self.repository_signature()

        if signature != self._repository_signature:
            self.refresh_scenes()

    def refresh_scenes(self) -> None:
        selected = self.selected_scene_id()
        repository = self.repository()

        try:
            scenes = repository.list_scenes()
            invalid = repository.invalid_files()
            signature = self.repository_signature()
        except SceneRepositoryError as exc:
            self.status_label.setText(
                f"Could not read scene library: {exc}"
            )
            return

        self.scene_list.blockSignals(True)
        self.scene_list.clear()

        selected_row = -1

        for row, scene in enumerate(scenes):
            item = QListWidgetItem(
                f"{scene.name}\n{scene.mode} · {scene.id}"
            )
            item.setData(
                Qt.ItemDataRole.UserRole,
                scene.id,
            )
            self.scene_list.addItem(item)

            if scene.id == selected:
                selected_row = row

        self.scene_list.blockSignals(False)
        self._repository_signature = signature

        if scenes:
            if selected_row < 0:
                selected_row = 0
            self.scene_list.setCurrentRow(selected_row)
            self.apply_button.setEnabled(True)
            self.rename_button.setEnabled(True)
            self.workshop_button.setEnabled(True)
            self.delete_button.setEnabled(True)

            message = (
                f"{len(scenes)} saved scene"
                + ("" if len(scenes) == 1 else "s")
                + "."
            )
        else:
            self.details.setPlainText(
                "No scenes saved yet.\n\n"
                "Use “Save Current as Scene” to capture the lighting "
                "configuration Serpent is currently using."
            )
            self.apply_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.workshop_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            message = "No scenes saved yet."

        if invalid:
            message += (
                f" {len(invalid)} invalid scene file"
                + ("" if len(invalid) == 1 else "s")
                + " ignored."
            )

        self.status_label.setText(message)

    def selection_changed(
        self,
        _current: QListWidgetItem | None,
        _previous: QListWidgetItem | None,
    ) -> None:
        scene_id = self.selected_scene_id()

        if scene_id is None:
            self.apply_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.workshop_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        try:
            scene = self.repository().load(scene_id)
        except SceneRepositoryError as exc:
            self.details.setPlainText(str(exc))
            self.apply_button.setEnabled(False)
            self.rename_button.setEnabled(False)
            self.workshop_button.setEnabled(False)
            self.delete_button.setEnabled(False)
            return

        self.details.setPlainText(
            json.dumps(
                scene_to_dict(scene),
                indent=2,
                ensure_ascii=False,
            )
        )
        self.apply_button.setEnabled(True)
        self.rename_button.setEnabled(True)
        self.workshop_button.setEnabled(True)
        self.delete_button.setEnabled(True)

    def open_selected_scene_in_workshop(self) -> None:
        scene_id = self.selected_scene_id()
        if scene_id is None:
            return

        if self.workshop_open_callback is None:
            self.status_label.setText(
                "Effects Workshop is not available."
            )
            return

        try:
            scene = self.repository().load(scene_id)
            opened = self.workshop_open_callback(scene)
        except (SceneRepositoryError, ValueError) as exc:
            notify_error(
                self,
                "Could not open scene in Workshop",
                str(exc),
            )
            self.status_label.setText(
                f"Could not open scene in Workshop: {exc}"
            )
            return

        if opened is False:
            self.status_label.setText(
                f"{scene.name} could not be represented in the Workshop."
            )
            return

        self.status_label.setText(
            f"Opened {scene.name} in Effects Workshop."
        )

    @staticmethod
    @staticmethod
    def _replace_scene_effect(
        scene,
        effect_id: str,
        parameters: dict[str, object],
        target: str,
    ):
        raw = scene_to_dict(scene)
        synchronized = scene.mode == "synchronized"
        payload = scene_effect_payload(
            {"effect": effect_id, **parameters},
            synchronized=synchronized,
        )

        if synchronized:
            raw["effect"] = payload
            return scene_from_dict(raw)

        devices = raw.get("devices")
        if not isinstance(devices, dict):
            raise GuiError("Individual scene has no editable device mapping.")

        profile = load_profile()
        generic_profiles = profile.get("fixture_devices", {})
        if not isinstance(generic_profiles, dict):
            generic_profiles = {}

        matched_ids: list[str] = []
        if target in devices:
            matched_ids.append(target)

        legacy_target = {
            "keyboard": "razer-deathstalker-v2",
            "mouse": "razer-naga-v2-pro-wireless",
        }.get(target)
        if legacy_target in devices and legacy_target not in matched_ids:
            matched_ids.append(legacy_target)

        for device_id in devices:
            if device_id in matched_ids:
                continue
            saved = generic_profiles.get(device_id)
            if not isinstance(saved, dict):
                continue
            fixture_id = saved.get("fixture_id")
            if not isinstance(fixture_id, str) or not fixture_id:
                continue
            try:
                fixture = find_fixture_by_id(fixture_id)
            except FixtureError:
                continue
            if fixture.device_class == target:
                matched_ids.append(device_id)

        changed = False
        for device_id in matched_ids:
            device = devices.get(device_id)
            if not isinstance(device, dict):
                continue

            if "effect" in device:
                device["effect"] = payload
                changed = True

            zones = device.get("zones")
            if isinstance(zones, dict):
                for zone in zones.values():
                    if isinstance(zone, dict) and "effect" in zone:
                        zone["effect"] = payload
                        changed = True

        if changed:
            return scene_from_dict(raw)

        raise GuiError(
            f"Scene has no editable effect slot for Workshop target {target!r}."
        )

    def save_workshop_scene(
        self,
        effect_id: str,
        parameters: dict[str, object],
        target: str,
    ):
        name, accepted = QInputDialog.getText(
            self,
            "Save Workshop as Scene",
            "Scene name:",
        )
        if not accepted:
            return None

        name = name.strip()
        if not name:
            notify_warning(
                self,
                "Scene name required",
                "Enter a name for the scene.",
            )
            return None

        try:
            repository = self.repository()
            base = capture_current_scene(name, repository)
            scene = self._replace_scene_effect(
                base,
                effect_id,
                parameters,
                target,
            )
            repository.save(scene, overwrite=False)
        except (
            GuiError,
            SceneAlreadyExistsError,
            SceneRepositoryError,
            OSError,
            ValueError,
        ) as exc:
            notify_error(
                self,
                "Could not save Workshop scene",
                str(exc),
            )
            self.status_label.setText(
                f"Could not save Workshop scene: {exc}"
            )
            return None

        self.refresh_scenes()
        for row in range(self.scene_list.count()):
            item = self.scene_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == scene.id:
                self.scene_list.setCurrentRow(row)
                break

        self.status_label.setText(
            f"Saved {scene.name} ({scene.id}) from Effects Workshop."
        )
        return scene

    def update_selected_scene_from_workshop(
        self,
        effect_id: str,
        parameters: dict[str, object],
        target: str,
    ):
        scene_id = self.selected_scene_id()
        if scene_id is None:
            notify_info(
                self,
                "Select a scene",
                "Select a scene in the Scenes tab before updating it "
                "from the Workshop.",
            )
            return None

        try:
            repository = self.repository()
            original = repository.load(scene_id)
        except SceneRepositoryError as exc:
            notify_error(
                self,
                "Scene error",
                str(exc),
            )
            return None

        answer = QMessageBox.question(
            self,
            "Update selected scene",
            (
                f"Update {original.name!r} ({original.id}) with the "
                f"current Workshop effect for {target}?\n\n"
                "Scene topology, brightness, members, and unrelated device "
                "settings are preserved."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None

        try:
            updated = self._replace_scene_effect(
                original,
                effect_id,
                parameters,
                target,
            )
            repository.save(updated, overwrite=True)
        except (
            GuiError,
            SceneRepositoryError,
            OSError,
            ValueError,
        ) as exc:
            notify_error(
                self,
                "Could not update scene",
                str(exc),
            )
            self.status_label.setText(
                f"Could not update scene: {exc}"
            )
            return None

        self.refresh_scenes()
        for row in range(self.scene_list.count()):
            item = self.scene_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == updated.id:
                self.scene_list.setCurrentRow(row)
                break

        self.status_label.setText(
            f"Updated {updated.name} from Effects Workshop."
        )
        return updated

    def save_current_scene(self) -> None:
        name, accepted = QInputDialog.getText(
            self,
            "Save Current as Scene",
            "Scene name:",
        )

        if not accepted:
            return

        name = name.strip()
        if not name:
            notify_warning(
                self,
                "Scene name required",
                "Enter a name for the scene.",
            )
            return

        self.save_button.setEnabled(False)
        self.status_label.setText("Capturing current lighting…")
        QApplication.processEvents()

        try:
            repository = self.repository()
            scene = capture_current_scene(name, repository)
            repository.save(scene, overwrite=False)
        except (
            GuiError,
            SceneAlreadyExistsError,
            SceneRepositoryError,
            OSError,
            ValueError,
        ) as exc:
            notify_error(
                self,
                "Could not save scene",
                str(exc),
            )
            self.status_label.setText(
                f"Could not save scene: {exc}"
            )
            return
        finally:
            self.save_button.setEnabled(True)

        self.refresh_scenes()

        for row in range(self.scene_list.count()):
            item = self.scene_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == scene.id:
                self.scene_list.setCurrentRow(row)
                break

        self.status_label.setText(
            f"Saved {scene.name} as {scene.id} ({scene.mode})."
        )

    def rename_selected_scene(self) -> None:
        scene_id = self.selected_scene_id()

        if scene_id is None:
            return

        repository = self.repository()

        try:
            scene = repository.load(scene_id)
        except SceneRepositoryError as exc:
            notify_error(
                self,
                "Scene error",
                str(exc),
            )
            return

        name, accepted = QInputDialog.getText(
            self,
            "Rename Scene",
            "Scene name:",
            text=scene.name,
        )

        if not accepted:
            return

        name = name.strip()

        if not name:
            notify_warning(
                self,
                "Scene name required",
                "Enter a name for the scene.",
            )
            return

        if name == scene.name:
            self.status_label.setText(
                f"Scene is already named {scene.name}."
            )
            return

        raw = scene_to_dict(scene)
        raw["name"] = name

        # Keep the human name and on-disk scene id aligned. If the new
        # slug collides with another scene, reuse the same safe suffix
        # policy as Save Current as Scene.
        requested_id = scene_id_from_name(name)

        if requested_id == scene.id:
            new_id = scene.id
        else:
            new_id = unique_scene_id(name, repository)

        raw["id"] = new_id

        try:
            renamed = scene_from_dict(raw)

            if new_id == scene.id:
                repository.save(
                    renamed,
                    overwrite=True,
                )
            else:
                # Write the replacement first so a failed rename never
                # destroys the original scene. If removing the old file
                # fails, remove the replacement again.
                repository.save(
                    renamed,
                    overwrite=False,
                )

                try:
                    repository.delete(scene.id)
                except Exception:
                    try:
                        repository.delete(renamed.id)
                    except Exception:
                        pass
                    raise

        except (
            SceneAlreadyExistsError,
            SceneRepositoryError,
            OSError,
            ValueError,
        ) as exc:
            notify_error(
                self,
                "Could not rename scene",
                str(exc),
            )
            self.status_label.setText(
                f"Could not rename scene: {exc}"
            )
            return

        self.refresh_scenes()

        for row in range(self.scene_list.count()):
            item = self.scene_list.item(row)

            if (
                item.data(Qt.ItemDataRole.UserRole)
                == renamed.id
            ):
                self.scene_list.setCurrentRow(row)
                break

        self.status_label.setText(
            f"Renamed {scene.name} to {renamed.name} "
            f"({renamed.id})."
        )

    def apply_selected_scene(self) -> None:
        scene_id = self.selected_scene_id()

        if scene_id is None:
            return

        self.apply_button.setEnabled(False)
        self.status_label.setText(
            f"Applying {scene_id}…"
        )
        QApplication.processEvents()

        try:
            scene = self.repository().load(scene_id)
            plan = apply_scene(
                scene,
                SerpentSceneRuntime(),
            )
        except (
            SceneRepositoryError,
            SceneApplicationError,
            OSError,
            ValueError,
        ) as exc:
            notify_error(
                self,
                "Scene application failed",
                str(exc),
            )
            self.status_label.setText(
                f"Could not apply scene: {exc}"
            )
        else:
            self.status_label.setText(
                f"Applied {plan.scene_name} "
                f"({plan.mode})."
            )

            if self.runtime_refresh_callback is not None:
                QTimer.singleShot(
                    0,
                    self.runtime_refresh_callback,
                )
        finally:
            self.apply_button.setEnabled(
                self.selected_scene_id() is not None
            )

    def delete_selected_scene(self) -> None:
        scene_id = self.selected_scene_id()

        if scene_id is None:
            return

        try:
            scene = self.repository().load(scene_id)
        except SceneRepositoryError as exc:
            notify_error(
                self,
                "Scene error",
                str(exc),
            )
            return

        answer = QMessageBox.question(
            self,
            "Delete scene",
            (
                f"Delete {scene.name!r} ({scene.id})?\n\n"
                "This removes the saved scene file. "
                "It does not change the lighting currently running."
            ),
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        try:
            self.repository().delete(scene_id)
        except SceneRepositoryError as exc:
            notify_error(
                self,
                "Scene deletion failed",
                str(exc),
            )
            return

        self.status_label.setText(
            f"Deleted {scene.name}."
        )
        self.refresh_scenes()


class StatusDashboard(QWidget):
    REFRESH_INTERVAL_MS = 30_000

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # M10.0.0.39-J - semantic Status Dashboard presentation
        self.setObjectName("serpentStatusDashboard")
        self.device_cards: dict[str, dict[str, Any]] = {}
        self.services_labels: dict[str, QLabel] = {}
        self.last_refresh = QLabel("Not refreshed yet")
        self.refresh_button = QPushButton("Refresh status")
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(self.REFRESH_INTERVAL_MS)
        self.refresh_timer.timeout.connect(self.refresh_status)
        self.build_ui()
        self.refresh_status()

    @staticmethod
    def indicator(text: str, healthy: bool) -> str:
        colour = "#2ecc71" if healthy else "#e74c3c"
        return f"<span style='color:{colour}; font-weight:600;'>●</span> {text}"

    @staticmethod
    def human_service_name(service_name: str) -> str:
        names = {
            "openrazer-daemon.service": "OpenRazer",
            "serpent-individual.service": "Individual software renderer",
            "serpent-sync.service": "Synchronization engine",
            "serpent-watcher.service": "Serpent watcher",
            "serpent-restore.service": "Profile restore service",
        }
        return names.get(service_name, service_name.removesuffix(".service"))

    @staticmethod
    def device_type_label(device_class: str) -> str:
        friendly = {
            "mouse": "Mouse",
            "keyboard": "Keyboard",
            "mousepad": "Mousepad",
            "keypad": "Keypad",
            "speaker": "Speaker",
            "dock": "Dock",
            "charging-pad": "Charging Pad",
            "accessory": "Accessory",
            "headset": "Headset",
        }
        return friendly.get(
            device_class,
            device_class.replace("-", " ").title() or "Device",
        )

    def build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        title = QLabel("System Status")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)

        subtitle = QLabel(
            "Live connected-device and service health. Status refresh is read-only."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("serpentSecondaryLabel")
        subtitle.setProperty("serpentRole", "secondaryText")

        self.devices_group = QGroupBox("Connected Devices")
        self.devices_group.setObjectName("serpentSectionCard")
        self.devices_layout = QVBoxLayout(self.devices_group)
        self.no_devices_label = QLabel("No supported devices connected.")
        self.devices_layout.addWidget(self.no_devices_label)

        services_group = QGroupBox("Services")
        services_group.setObjectName("serpentServicesCard")
        services_group.setProperty("serpentRole", "statusSection")
        services_layout = QVBoxLayout(services_group)
        for service_name in (
            "openrazer-daemon.service",
            "serpent-individual.service",
            "serpent-sync.service",
            "serpent-watcher.service",
            "serpent-restore.service",
        ):
            label = QLabel("Checking…")
            label.setObjectName("serpentServiceState")
            label.setProperty("serviceHealth", "checking")
            label.setTextFormat(Qt.TextFormat.RichText)
            self.services_labels[service_name] = label
            services_layout.addWidget(label)

        self.last_refresh.setObjectName("serpentSecondaryLabel")
        self.last_refresh.setProperty("serpentRole", "secondaryText")

        refresh_row = QHBoxLayout()
        refresh_row.addWidget(self.last_refresh)
        refresh_row.addStretch()
        refresh_row.addWidget(self.refresh_button)
        self.refresh_button.clicked.connect(self.refresh_status)

        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addWidget(self.devices_group)
        outer.addWidget(services_group)
        outer.addLayout(refresh_row)
        outer.addStretch()

    def _create_device_card(self, snapshot: DeviceTelemetrySnapshot) -> dict[str, Any]:
        group = QGroupBox()
        group.setObjectName("serpentDeviceCard")
        layout = QVBoxLayout(group)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        state = QLabel()
        state.setObjectName("serpentStatusState")
        state.setProperty("deviceHealth", "connected")
        state.setTextFormat(Qt.TextFormat.RichText)
        battery = QProgressBar()
        battery.setObjectName("serpentBatteryState")
        battery.setProperty("batteryState", "unknown")
        battery.setRange(0, 100)
        battery.setTextVisible(True)
        details = QLabel()
        details.setWordWrap(True)
        details.setObjectName("serpentSecondaryLabel")
        details.setProperty("serpentRole", "secondaryText")
        layout.addWidget(state)
        layout.addWidget(battery)
        layout.addWidget(details)
        self.devices_layout.addWidget(group)
        card = {"group": group, "state": state, "battery": battery, "details": details}
        self.device_cards[snapshot.instance_id] = card
        return card

    def _update_device_card(self, snapshot: DeviceTelemetrySnapshot) -> None:
        card = self.device_cards.get(snapshot.instance_id)
        if card is None:
            card = self._create_device_card(snapshot)

        card["group"].setTitle(
            f"{self.device_type_label(snapshot.device_class)} — {snapshot.display_name}"
        )
        card["state"].setText(self.indicator("Connected", True))

        battery = card["battery"]
        battery.setVisible(snapshot.battery_supported)
        if snapshot.battery_supported:
            if snapshot.battery is None:
                battery.setProperty("batteryState", "unknown")
                battery.setValue(0)
                battery.setFormat("Unavailable")
            else:
                battery_state = (
                    "charging"
                    if snapshot.charging is True
                    else "low"
                    if snapshot.battery <= 20
                    else "normal"
                )
                battery.setProperty("batteryState", battery_state)
                battery.setValue(snapshot.battery)
                battery.setFormat(f"{snapshot.battery}%")
            battery.style().unpolish(battery)
            battery.style().polish(battery)
            battery.update()

        rows = [
            f"Name: {snapshot.display_name}",
            f"Class: {self.device_type_label(snapshot.device_class)}",
            f"Fixture: {snapshot.fixture_id}",
        ]
        if snapshot.charging_supported:
            power = (
                "Charging" if snapshot.charging is True
                else "Not charging" if snapshot.charging is False
                else "Charging state unavailable"
            )
            rows.append(f"Power: {power}")
        card["details"].setText("\n".join(rows))

    def reconcile_device_cards(self, snapshots: list[DeviceTelemetrySnapshot]) -> None:
        wanted = {snapshot.instance_id for snapshot in snapshots}
        for instance_id in list(self.device_cards):
            if instance_id in wanted:
                continue
            card = self.device_cards.pop(instance_id)
            card["group"].deleteLater()
        for snapshot in snapshots:
            self._update_device_card(snapshot)
        self.no_devices_label.setVisible(not snapshots)

    def apply_status_summary(
        self,
        status,
        telemetry: list[DeviceTelemetrySnapshot] | None = None,
    ) -> None:
        if telemetry is not None:
            self.reconcile_device_cards(telemetry)

        for service in status["services"]:
            label = self.services_labels.get(service.name)
            if label is None:
                continue
            if (
                service.name == "serpent-restore.service"
                and service.healthy
                and not service.active
            ):
                state_text = "Idle"
            else:
                state_text = "Healthy" if service.healthy else humanize(service.state)
            service_health = (
                "idle"
                if state_text == "Idle"
                else "healthy"
                if service.healthy
                else "error"
            )
            label.setProperty("serviceHealth", service_health)
            label.setText(
                self.indicator(
                    f"{self.human_service_name(service.name)} — {state_text}",
                    service.healthy,
                )
            )
            label.style().unpolish(label)
            label.style().polish(label)
            label.update()

        self.last_refresh.setText(
            "Last refreshed: " + datetime.now().strftime("%H:%M:%S")
        )

    def refresh_status(self) -> None:
        self.refresh_button.setEnabled(False)
        QApplication.processEvents()
        try:
            self.apply_status_summary(
                load_status_summary(),
                collect_device_telemetry(),
            )
        except Exception as exc:
            self.last_refresh.setText(f"Status refresh failed: {exc}")
        finally:
            self.refresh_button.setEnabled(True)

class GenericFixturePanel(QWidget):
    # Fixture-driven individual lighting controls for generic device classes.

    PROFILE_KEY = "fixture_devices"

    def __init__(
        self,
        fixture: dict[str, Any],
        fixture_object,
        sysfs_path: Path,
        instance_id: str,
        profile: dict[str, Any],
        status_refresh_callback: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serpentGenericFixturePanel")

        self.fixture = fixture
        self.fixture_object = fixture_object
        self.sysfs_path = Path(sysfs_path)
        self.instance_id = instance_id
        self.fixture_effects = dict(fixture.get("effects", {}))
        self.device_class = str(fixture.get("device_class", "device"))
        self.effects = _device_effect_catalog(
            self.device_class,
            self.fixture_effects,
            renderer_owned=(
                str(self.fixture.get("backend", {}).get("type", ""))
                == "software-rgb-sysfs"
                and isinstance(
                    self.fixture.get("capabilities", {}).get("matrix"),
                    dict,
                )
            ),
        )
        self.status_refresh_callback = status_refresh_callback
        self.sync_owned = False
        self.device_connected = True
        self.editors: dict[str, EffectEditor] = {}

        saved = profile.get(self.PROFILE_KEY, {}).get(self.instance_id, {})
        if not isinstance(saved, dict):
            saved = {}
        self.saved_settings = saved

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("serpentDeviceActionStatus")
        self.status_label.setWordWrap(True)

        self.telemetry_label = QLabel("")
        self.telemetry_label.setObjectName("serpentDeviceTelemetry")
        self.telemetry_label.setProperty("serpentRole", "secondaryText")
        self.telemetry_label.setWordWrap(True)
        self.telemetry_label.setVisible(False)

        self.ownership_label = QLabel("Individual lighting active.")
        self.ownership_label.setObjectName("serpentOwnershipState")
        self.ownership_label.setProperty("ownershipState", "individual")
        self.ownership_label.setWordWrap(True)

        self.live_preview_checkbox = QCheckBox("Live preview")
        self.live_preview_checkbox.setChecked(True)
        self.restore_button = QPushButton("Restore saved profile")

        self.build_ui()
        self.update_interaction_state()

    def default_settings(self) -> dict[str, Any]:
        return {
            "effect": "static",
            "brightness": 20,
            "colour1": [0, 0, 255],
            "colour2": [0, 255, 255],
            "speed": 2,
        }

    def _zone_definitions(self) -> list[tuple[str, str, bool]]:
        zones = self.fixture.get("zones", {})
        result: list[tuple[str, str, bool]] = []

        if isinstance(zones, dict):
            for zone_id, definition in zones.items():
                if not isinstance(definition, dict):
                    continue
                if not bool(definition.get("visible", True)):
                    continue
                if not bool(
                    definition.get(
                        "controllable",
                        definition.get("confirmed", True),
                    )
                ):
                    continue
                result.append(
                    (
                        str(zone_id),
                        str(definition.get("name", zone_id)),
                        True,
                    )
                )

        if not result:
            result.append(("__device__", "Lighting", False))

        return result

    def _saved_zone_settings(self, zone_id: str) -> dict[str, Any]:
        if zone_id == "__device__":
            value = self.saved_settings.get("settings", {})
        else:
            zones = self.saved_settings.get("zones", {})
            value = zones.get(zone_id, {}) if isinstance(zones, dict) else {}

        if not isinstance(value, dict):
            return self.default_settings()

        result = self.default_settings()
        result.update(value)
        return result

    def build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(14)

        title = QLabel(
            (
                str(self.fixture.get("manufacturer", ""))
                + " "
                + str(self.fixture.get("model", ""))
            ).strip()
            or str(self.fixture.get("id", "Connected Device"))
        )
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 3)
        title_font.setBold(True)
        title.setFont(title_font)
        title.setObjectName("serpentDevicePageTitle")

        details = QLabel(
            f"Class: {self.device_class}\n"
            f"Backend: {self.fixture.get('backend', {}).get('type', 'unknown')}\n"
            f"USB ID: "
            f"{self.fixture.get('usb', {}).get('vendor_id', '????')}:"
            f"{self.fixture.get('usb', {}).get('product_id', '????')}"
        )
        details.setObjectName("serpentDevicePageDetails")
        details.setProperty("serpentRole", "secondaryText")

        outer.addWidget(title)
        outer.addWidget(details)
        outer.addWidget(self.telemetry_label)
        outer.addWidget(self.ownership_label)
        outer.addWidget(self.live_preview_checkbox)

        for zone_id, label, explicit_zone in self._zone_definitions():
            editor = EffectEditor(
                label,
                self.effects,
                self._saved_zone_settings(zone_id),
                lambda effect, settings, zid=zone_id, explicit=explicit_zone:
                    self.apply_fixture_effect(
                        zid,
                        explicit,
                        effect,
                        settings,
                    ),
            )
            editor.live_preview_enabled = self.live_preview_checkbox.isChecked()
            self.editors[zone_id] = editor
            outer.addWidget(editor)

        button_row = QHBoxLayout()
        button_row.addStretch()
        button_row.addWidget(self.restore_button)
        outer.addLayout(button_row)
        outer.addWidget(self.status_label)
        self.live_preview_checkbox.toggled.connect(
            self.set_live_preview
        )
        self.restore_button.clicked.connect(
            self.restore_profile
        )

        outer.addStretch()

    def _sync_currently_owns_lighting(self) -> bool:
        try:
            output = run_serpent(["sync", "status"])
            runtime = SyncPanel.parse_sync_status(output)
        except Exception:
            return self.sync_owned

        return (
            runtime.get("Owner") == "sync"
            and runtime.get("State") == "synchronized"
        )

    def set_telemetry_snapshot(
        self,
        snapshot: DeviceTelemetrySnapshot,
    ) -> None:
        rows = []
        if snapshot.battery_supported:
            rows.append(
                "Battery: "
                + (f"{snapshot.battery}%" if snapshot.battery is not None else "Unavailable")
            )
        if snapshot.charging_supported:
            rows.append(
                "Charging: "
                + (
                    "Yes" if snapshot.charging is True
                    else "No" if snapshot.charging is False
                    else "Unavailable"
                )
            )
        self.telemetry_label.setText("    ".join(rows))
        self.telemetry_label.setVisible(bool(rows))

    def set_sync_context(
        self,
        synchronized: bool,
        profile: dict[str, Any],
    ) -> None:
        self.sync_owned = bool(synchronized)
        self.sync_region_groups = (
            sync_region_assignments(profile, self.instance_id)
            if self.sync_owned
            else {}
        )
        self.update_interaction_state()

    def _zone_sync_group(self, zone_id: str) -> str | None:
        groups = getattr(self, "sync_region_groups", {})
        if zone_id == "__device__":
            if isinstance(groups, dict) and groups:
                return ", ".join(sorted(set(str(v) for v in groups.values())))
            return None
        value = groups.get(zone_id) if isinstance(groups, dict) else None
        return str(value) if value else None

    def _zone_editable(self, zone_id: str) -> bool:
        if not self.device_connected:
            return False
        if not self.sync_owned:
            return True
        if zone_id == "__device__":
            return not bool(getattr(self, "sync_region_groups", {}))
        return self._zone_sync_group(zone_id) is None

    def set_sync_ownership(self, synchronized: bool) -> None:
        self.sync_owned = bool(synchronized)
        self.update_interaction_state()
        self.live_preview_checkbox.setEnabled(self.device_connected and not self.sync_owned)
        self.restore_button.setEnabled(self.device_connected and not self.sync_owned)

    def set_device_connected(self, connected: bool) -> None:
        self.device_connected = bool(connected)
        self.update_interaction_state()
        self.live_preview_checkbox.setEnabled(self.device_connected and not self.sync_owned)
        self.restore_button.setEnabled(self.device_connected and not self.sync_owned)

    def update_interaction_state(self) -> None:
        panel_editable = self.device_connected and not self.sync_owned
        self.live_preview_checkbox.setEnabled(panel_editable)
        self.restore_button.setEnabled(panel_editable)

        ownership_state = (
            "disconnected"
            if not self.device_connected
            else "sync"
            if self.sync_owned
            else "individual"
        )
        self.ownership_label.setProperty("ownershipState", ownership_state)
        self.ownership_label.style().unpolish(self.ownership_label)
        self.ownership_label.style().polish(self.ownership_label)
        self.ownership_label.update()

        locked = []
        for zone_id, editor in self.editors.items():
            editable = self._zone_editable(zone_id)
            editor.setProperty(
                "controlState",
                "disconnected"
                if not self.device_connected
                else "sync"
                if self.sync_owned and not editable
                else "individual",
            )
            if not editable:
                editor.preview_timer.stop()
                editor.colour_preview_timer.stop()
            editor.setEnabled(editable)
            editor.style().unpolish(editor)
            editor.style().polish(editor)
            editor.update()
            if not editable and self.sync_owned and self.device_connected:
                group = self._zone_sync_group(zone_id)
                if group:
                    locked.append(f"{zone_id}: {group}")

        if not self.device_connected:
            self.ownership_label.setText(
                "Device disconnected. Saved individual settings are retained."
            )
        elif not self.sync_owned:
            self.ownership_label.setText("Individual lighting active.")
        elif locked:
            self.ownership_label.setText(
                "Sync owns grouped regions only; ungrouped personal regions "
                "remain editable. Locked — " + "; ".join(locked)
            )
        else:
            self.ownership_label.setText(
                "Sync owns the physical writer, but available personal regions "
                "remain editable because they are ungrouped."
            )

    def set_live_preview(self, enabled: bool) -> None:
        for editor in self.editors.values():
            editor.live_preview_enabled = bool(enabled)
            if not enabled:
                editor.preview_timer.stop()
                editor.colour_preview_timer.stop()

        self.status_label.setText(
            "Live preview enabled."
            if enabled
            else "Live preview disabled."
        )

    def restore_profile(self) -> None:
        if self.sync_owned or not self.device_connected:
            return

        try:
            profile = load_profile()
            devices = profile.get(self.PROFILE_KEY, {})
            saved = (
                devices.get(self.instance_id, {})
                if isinstance(devices, dict)
                else {}
            )
            if not isinstance(saved, dict):
                saved = {}

            self.saved_settings = dict(saved)

            for zone_id, _label, _explicit in self._zone_definitions():
                editor = self.editors.get(zone_id)
                if editor is not None:
                    editor.load_settings(
                        self._saved_zone_settings(zone_id)
                    )

            synchronized = self._sync_currently_owns_lighting()
            if synchronized:
                _request_sync_renderer_reload()
                self.status_label.setText(
                    "Restored the saved personal profile; "
                    "the Sync compositor will reload it."
                )
            else:
                backend_type = str(
                    self.fixture.get("backend", {}).get("type", "")
                )
                saved_effects = [
                    str(
                        self._saved_zone_settings(zone_id).get(
                            "effect",
                            "static",
                        )
                    )
                    for zone_id, _label, _explicit
                    in self._zone_definitions()
                ]
                software_needed = (
                    backend_type == "software-rgb-sysfs"
                    or any(
                        _is_dynamic_device_effect(
                            effect,
                            self.device_class,
                            self.fixture_effects,
                        )
                        for effect in saved_effects
                    )
                )

                if software_needed:
                    _restart_individual_renderer()
                else:
                    backend = create_backend(
                        self.fixture_object,
                        self.sysfs_path,
                    )
                    for zone_id, _label, explicit in self._zone_definitions():
                        settings = self._saved_zone_settings(zone_id)
                        effect = str(settings.get("effect", "static"))
                        if explicit:
                            backend.apply_zone(
                                zone_id,
                                effect,
                                settings,
                            )
                        else:
                            backend.apply(
                                effect,
                                settings,
                            )

                self.status_label.setText(
                    "Restored the saved personal profile."
                )

            if self.status_refresh_callback is not None:
                QTimer.singleShot(
                    0,
                    self.status_refresh_callback,
                )

        except (
            GuiError,
            BackendError,
            FixtureError,
            OSError,
            ValueError,
            KeyError,
        ) as exc:
            self.status_label.setText(f"Error: {exc}")
            notify_error(
                self,
                "Serpent error",
                str(exc),
            )

    def _save_settings(
        self,
        zone_id: str,
        settings: dict[str, Any],
    ) -> None:
        profile = load_profile()
        devices = profile.setdefault(self.PROFILE_KEY, {})
        device_profile = devices.setdefault(self.instance_id, {})
        device_profile["fixture_id"] = str(self.fixture.get("id", ""))

        if zone_id == "__device__":
            device_profile["settings"] = dict(settings)
        else:
            zones = device_profile.setdefault("zones", {})
            zones[zone_id] = dict(settings)

        _save_profile_atomic(profile)
        self.saved_settings = dict(device_profile)

    def apply_fixture_effect(
        self,
        zone_id: str,
        explicit_zone: bool,
        effect: str,
        settings: dict[str, Any],
    ) -> None:
        if not self.device_connected:
            return

        synchronized = self._sync_currently_owns_lighting()
        if synchronized:
            self.sync_owned = True

        if synchronized and not self._zone_editable(zone_id):
            self.update_interaction_state()
            self.status_label.setText(
                "This region is controlled by Sync group "
                f"{self._zone_sync_group(zone_id)}; personal Apply was ignored."
            )
            return

        editor = self.editors[zone_id]
        editor.apply_button.setEnabled(False)
        QApplication.processEvents()
        try:
            candidate = _personal_profile_settings(effect, settings, self.fixture_effects)
            self._save_settings(zone_id, candidate)

            if synchronized:
                _request_sync_renderer_reload()
                editor.load_settings(candidate)
                self.status_label.setText(
                    f"Saved {humanize(effect)} for the ungrouped personal "
                    "region; the Sync compositor reloaded it."
                )
                if self.status_refresh_callback is not None:
                    QTimer.singleShot(0, self.status_refresh_callback)
                return

            backend_type = str(
                self.fixture.get("backend", {}).get("type", "")
            )
            software_owned = (
                backend_type == "software-rgb-sysfs"
                or _is_dynamic_device_effect(
                    effect,
                    self.device_class,
                    self.fixture_effects,
                )
            )

            if software_owned:
                _restart_individual_renderer()
                editor.load_settings(candidate)
                self.status_label.setText(
                    f"Applied {humanize(effect)} through the per-instance "
                    "software renderer."
                )
                if self.status_refresh_callback is not None:
                    QTimer.singleShot(0, self.status_refresh_callback)
                return

            backend = create_backend(self.fixture_object, self.sysfs_path)
            if explicit_zone:
                backend.apply_zone(zone_id, effect, settings)
            else:
                backend.apply(effect, settings)

            editor.load_settings(candidate)
            self.status_label.setText(f"Applied {humanize(effect)}.")
            if self.status_refresh_callback is not None:
                QTimer.singleShot(0, self.status_refresh_callback)

        except (GuiError, BackendError, FixtureError, OSError, ValueError, KeyError) as exc:
            self.status_label.setText(f"Error: {exc}")
            notify_error(self, "Serpent error", str(exc))
        finally:
            editor.apply_button.setEnabled(self._zone_editable(zone_id))

    def refresh_effect_catalog(self) -> None:
        self.effects = _device_effect_catalog(
            self.device_class,
            self.fixture_effects,
            renderer_owned=(
                str(self.fixture.get("backend", {}).get("type", ""))
                == "software-rgb-sysfs"
                and isinstance(
                    self.fixture.get("capabilities", {}).get("matrix"),
                    dict,
                )
            ),
        )
        for editor in self.editors.values():
            editor.replace_effects(self.effects)


class SerpentWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.settings = QSettings(
            "Serpent Project",
            "Serpent",
        )
        self.really_quit = False
        self.tray_icon: QSystemTrayIcon | None = None
        self.tray_message_shown = False

        self.setWindowTitle(
            f"Serpent {VERSION}"
        )
        self.resize(760, 760)
        self.setMinimumSize(620, 560)

        central = QWidget()
        central.setObjectName("serpentRoot")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 14, 18, 12)
        layout.setSpacing(10)

        heading = QLabel(
            f"Serpent {VERSION}"
        )
        heading.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        heading.setObjectName("serpentHeading")
        heading.setProperty("serpentRole", "primaryTitle")

        heading_font = heading.font()
        heading_font.setPointSize(
            heading_font.pointSize() + 5
        )
        heading_font.setBold(True)
        heading.setFont(heading_font)
        if SERPENT_BANNER_PATH.is_file():
            brand_pixmap = QPixmap(str(SERPENT_BANNER_PATH))
            if not brand_pixmap.isNull():
                heading.setText("")
                heading.setPixmap(
                    brand_pixmap.scaled(
                        1000,
                        230,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                heading.setToolTip(
                    f"Serpent {VERSION}"
                )

        subtitle = QLabel(
            "Fixture-driven RGB control for Linux"
        )
        subtitle.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )
        subtitle.setObjectName("serpentSubtitle")
        subtitle.setProperty("serpentRole", "secondaryText")
        # The release banner already contains the Serpent tagline.
        subtitle.setVisible(False)

        self.notification_center = NotificationCenter(self)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("serpentMainTabs")
        self.tabs.setDocumentMode(True)
        self.status_dashboard = StatusDashboard()
        self.device_panels: list[QWidget] = []
        self.device_pages: dict[str, tuple[QWidget, QWidget]] = {}
        self._fixture_dicts_by_id: dict[str, dict[str, Any]] = {}
        self._last_sync_ownership: bool | None = None

        status_scroll = QScrollArea()
        status_scroll.setWidgetResizable(True)
        status_scroll.setFrameShape(QFrame.Shape.NoFrame)
        status_scroll.setWidget(self.status_dashboard)
        self.tabs.addTab(status_scroll, "Status")

        # Construct Scenes before the Workshop because the two panels share
        # explicit callbacks, but add tabs in the user-facing 0.9.1 order.
        self.scene_panel = SceneLibraryPanel(
            self.refresh_after_scene_application
        )
        scene_scroll = QScrollArea()
        scene_scroll.setWidgetResizable(True)
        scene_scroll.setFrameShape(QFrame.Shape.NoFrame)
        scene_scroll.setWidget(self.scene_panel)

        # M9.12.1: the existing Effect Lab graduates into the first-class
        # Effects Workshop. Installed Effects is the default user mode while
        # Developer mode preserves the isolated authoring worker.
        from gui.effect_lab import EffectsWorkshopPanel
        self.effect_lab = EffectsWorkshopPanel(PluginParameterEditor)
        self.effect_lab.setObjectName("serpentEffectsWorkshop")
        self.effect_lab.setProperty("serpentRole", "workshopSurface")
        self.effect_lab.scene_save_callback = (
            self.scene_panel.save_workshop_scene
        )
        self.effect_lab.scene_update_callback = (
            self.scene_panel.update_selected_scene_from_workshop
        )
        self.scene_panel.workshop_open_callback = (
            self.open_scene_in_workshop
        )

        effect_lab_scroll = QScrollArea()
        effect_lab_scroll.setWidgetResizable(True)
        effect_lab_scroll.setFrameShape(QFrame.Shape.NoFrame)
        effect_lab_scroll.setWidget(self.effect_lab)
        self.tabs.addTab(effect_lab_scroll, "Effects Workshop")
        self.tabs.addTab(scene_scroll, "Scenes")

        self.sync_panel = SyncPanel(
            self.status_dashboard.refresh_status
        )
        sync_scroll = QScrollArea()
        sync_scroll.setWidgetResizable(True)
        sync_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sync_scroll.setWidget(self.sync_panel)
        self.tabs.addTab(sync_scroll, "Sync")

        profile = load_profile()
        fixtures = load_fixtures()
        self._fixture_dicts_by_id = {
            str(fixture.get("id", "")): fixture
            for fixture in fixtures
            if fixture.get("id")
        }
        self.reconcile_connected_device_pages(profile=profile)

        self.effect_lab.effect_catalog_refresh_callback = (
            self.refresh_effect_catalogs
        )

        # H3 shared reconciliation: expensive runtime/device reads happen in
        # worker threads and their results are fanned out to all consumers.
        self._poll_executor = ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="serpent-gui-poll",
        )
        self._runtime_future: Future | None = None
        self._status_future: Future | None = None

        self.runtime_poll_timer = QTimer(self)
        self.runtime_poll_timer.setInterval(1_000)
        self.runtime_poll_timer.timeout.connect(
            self.schedule_runtime_snapshot
        )

        self.device_state_timer = QTimer(self)
        self.device_state_timer.setInterval(5_000)
        self.device_state_timer.timeout.connect(
            self.schedule_status_snapshot
        )

        self.result_poll_timer = QTimer(self)
        self.result_poll_timer.setInterval(50)
        self.result_poll_timer.timeout.connect(
            self.collect_background_snapshots
        )

        self.set_background_polling(True)
        self.schedule_runtime_snapshot()
        self.schedule_status_snapshot()

        footer = QWidget()
        footer.setObjectName("serpentRuntimeStrip")
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(12, 7, 12, 7)
        footer_layout.setSpacing(12)

        self.footer_service = QLabel("Service: checking")
        self.footer_service.setObjectName("serpentRuntimeGood")
        self.footer_profile = QLabel("Profile: loaded")
        self.footer_profile.setObjectName("serpentRuntimeNeutral")
        self.footer_mode = QLabel("Runtime: checking")
        self.footer_mode.setObjectName("serpentRuntimeGood")

        footer_layout.addWidget(self.footer_service)
        footer_layout.addStretch()
        footer_layout.addWidget(self.footer_profile)
        footer_layout.addStretch()
        footer_layout.addWidget(self.footer_mode)

        layout.addWidget(heading)
        layout.addWidget(subtitle)
        layout.addWidget(self.tabs, 1)
        layout.addWidget(footer)

        layout.addWidget(self.notification_center)
        self.setCentralWidget(central)

        self.build_actions()
        self.build_menus()
        self.build_tray()
        self.restore_window_state()

    @staticmethod
    def _load_runtime_snapshot():
        return (
            run_serpent(["sync", "status"]),
            load_profile(),
        )

    @staticmethod
    def _load_status_snapshot():
        return (
            load_status_summary(),
            collect_device_telemetry(),
        )

    def schedule_runtime_snapshot(self) -> None:
        if not self.isVisible():
            return

        if (
            self._runtime_future is not None
            and not self._runtime_future.done()
        ):
            return

        self._runtime_future = self._poll_executor.submit(
            self._load_runtime_snapshot
        )

    def schedule_status_snapshot(self) -> None:
        if not self.isVisible():
            return

        if (
            self._status_future is not None
            and not self._status_future.done()
        ):
            return

        self._status_future = self._poll_executor.submit(
            self._load_status_snapshot
        )

    def collect_background_snapshots(self) -> None:
        runtime_future = self._runtime_future
        if (
            runtime_future is not None
            and runtime_future.done()
        ):
            self._runtime_future = None
            try:
                output, profile = runtime_future.result()
            except Exception:
                # Preserve the last known runtime ownership/editor state.
                pass
            else:
                self.apply_runtime_snapshot(output, profile)

        status_future = self._status_future
        if (
            status_future is not None
            and status_future.done()
        ):
            self._status_future = None
            try:
                status = status_future.result()
            except Exception:
                # Preserve the last known device/status state.
                pass
            else:
                status, telemetry = status
                self.status_dashboard.apply_status_summary(status, telemetry)
                self.apply_device_availability_status(status)

                telemetry_by_instance = {
                    item.instance_id: item
                    for item in telemetry
                }
                for panel in self.device_panels:
                    setter = getattr(panel, "set_telemetry_snapshot", None)
                    instance_id = getattr(panel, "instance_id", None)
                    if callable(setter) and instance_id in telemetry_by_instance:
                        setter(telemetry_by_instance[instance_id])

    def apply_runtime_snapshot(
        self,
        output: str,
        profile: dict[str, Any],
    ) -> None:
        values = SyncPanel.parse_sync_status(output)
        self.sync_panel.reconcile_runtime_snapshot(output, profile)

        synchronized = (
            values.get("Owner") == "sync"
            and values.get("Service") == "active"
            and values.get("State") == "synchronized"
        )

        service_state = values.get("Service", "unknown")
        self.footer_service.setText(f"Service: {service_state}")
        self.footer_service.setProperty(
            "runtimeHealthy",
            service_state == "active",
        )
        self.footer_profile.setText(
            "Profile: loaded" if isinstance(profile, dict) else "Profile: unavailable"
        )
        self.footer_mode.setText(
            "Runtime: synchronized" if synchronized else "Runtime: individual"
        )
        self.footer_mode.setProperty("runtimeHealthy", True)
        for widget in (
            self.footer_service,
            self.footer_profile,
            self.footer_mode,
        ):
            widget.style().unpolish(widget)
            widget.style().polish(widget)

        for panel in self.device_panels:
            context_setter = getattr(panel, "set_sync_context", None)
            if callable(context_setter):
                context_setter(synchronized, profile)
                continue
            setter = getattr(panel, "set_sync_ownership", None)
            if callable(setter):
                setter(synchronized)

        self._last_sync_ownership = synchronized

    @staticmethod
    def _device_tab_label(fixture: dict[str, Any], instance_id: str) -> str:
        return str(
            fixture.get("model")
            or fixture.get("display_name")
            or fixture.get("name")
            or fixture.get("id")
            or "Device"
        )

    @staticmethod
    def _device_type_label(fixture: dict[str, Any]) -> str:
        device_class = str(fixture.get("device_class") or "device")
        friendly = {
            "mouse": "Mouse",
            "keyboard": "Keyboard",
            "mousepad": "Mousepad",
            "keypad": "Keypad",
            "speaker": "Speaker",
            "dock": "Dock",
            "charging-pad": "Charging Pad",
            "accessory": "Accessory",
        }
        return friendly.get(
            device_class,
            device_class.replace("-", " ").title(),
        )

    def _make_device_tab_widget(
        self,
        fixture: dict[str, Any],
        instance_id: str,
    ) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(10, 2, 10, 2)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # The custom device label occupies QTabBar's LeftSide slot. Symmetric
        # margins keep the two-line label visually centered in the native tab.
        layout.setContentsMargins(16, 0, 16, 0)

        kind = QLabel(self._device_type_label(fixture))
        kind_font = kind.font()
        kind_font.setBold(True)
        kind_font.setPointSize(kind_font.pointSize() + 1)
        kind.setFont(kind_font)
        kind.setAlignment(Qt.AlignmentFlag.AlignCenter)
        kind.setObjectName("serpentDeviceTabKind")

        model = QLabel(self._device_tab_label(fixture, instance_id))
        model_font = model.font()
        model_font.setPointSize(max(7, model_font.pointSize() - 1))
        model.setFont(model_font)
        model.setAlignment(Qt.AlignmentFlag.AlignCenter)
        model.setObjectName("serpentDeviceTabModel")
        model.setProperty("serpentRole", "secondaryText")

        widget.setObjectName("serpentDeviceTab")
        widget.setToolTip(
            f"{self._device_type_label(fixture)} — "
            f"{self._device_tab_label(fixture, instance_id)}\n"
            f"Instance: {instance_id}"
        )
        layout.addWidget(kind)
        layout.addWidget(model)
        return widget

    def _build_connected_device_panel(
        self,
        fixture: dict[str, Any],
        detected,
        instance_id: str,
        profile: dict[str, Any],
    ) -> QWidget:
        device_class = str(fixture.get("device_class", ""))
        specialized_factories = {
            "razer-naga-v2-pro-wireless": MousePanel,
            "razer-deathstalker-v2": KeyboardPanel,
        }
        factory = specialized_factories.get(
            str(fixture.get("id", ""))
        )

        if factory is not None:
            panel = factory(
                fixture,
                profile,
                self.status_dashboard.refresh_status,
            )
        else:
            panel = GenericFixturePanel(
                fixture,
                detected.fixture,
                detected.sysfs_path,
                instance_id,
                profile,
                self.status_dashboard.refresh_status,
            )

        setattr(panel, "instance_id", instance_id)
        setattr(panel, "fixture_id", str(fixture.get("id", "")))
        return panel

    def reconcile_connected_device_pages(
        self,
        *,
        profile: dict[str, Any] | None = None,
    ) -> None:
        if profile is None:
            profile = load_profile()

        connected = {}
        for item in detect_all_fixture_instances():
            fixture = self._fixture_dicts_by_id.get(str(item.fixture.id))
            if fixture is not None:
                connected[item.instance_id] = (item, fixture)

        for instance_id in list(self.device_pages):
            if instance_id in connected:
                continue
            panel, scroll = self.device_pages.pop(instance_id)
            index = self.tabs.indexOf(scroll)
            if index >= 0:
                self.tabs.removeTab(index)
            if panel in self.device_panels:
                self.device_panels.remove(panel)
            scroll.deleteLater()

        device_order = {"keyboard": 0, "mouse": 1}
        additions = sorted(
            (
                (instance_id, item, fixture)
                for instance_id, (item, fixture) in connected.items()
                if instance_id not in self.device_pages
            ),
            key=lambda row: (
                device_order.get(str(row[2].get("device_class")), 99),
                str(row[2].get("display_name") or row[2].get("id", "")),
                row[0],
            ),
        )

        for instance_id, item, fixture in additions:
            panel = self._build_connected_device_panel(
                fixture, item, instance_id, profile
            )
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(panel)
            # The custom two-line tab widget owns all visible text.
            # Use Qt's native tab text area for device labels. Unlike a
            # LeftSide tab-button widget, native tab text is centered across
            # the full tab geometry by QTabBar's style engine.
            device_kind = self._device_type_label(fixture)
            device_model = self._device_tab_label(fixture, instance_id)
            tab_index = self.tabs.addTab(
                scroll,
                f"{device_kind}\n{device_model}",
            )
            self.tabs.setTabToolTip(
                tab_index,
                f"{device_kind} — {device_model}\nInstance: {instance_id}",
            )
            self.device_panels.append(panel)
            self.device_pages[instance_id] = (panel, scroll)

    def apply_device_availability_status(self, status) -> None:
        # Physical-instance discovery is authoritative for page presence.
        # This reconciliation does not change profiles or lighting ownership.
        self.reconcile_connected_device_pages()


    def refresh_effect_catalogs(self) -> None:
        for panel in self.device_panels:
            refresh = getattr(panel, "refresh_effect_catalog", None)
            if callable(refresh):
                refresh()
        self.sync_panel.refresh_from_engine()
        self.schedule_status_snapshot()

    def refresh_after_scene_application(self) -> None:
        # Scene application is explicit user work. Refresh the Sync editor
        # immediately, then let device/status reconciliation arrive from the
        # shared background snapshot without blocking the Qt event loop.
        self.sync_panel.refresh_from_engine()
        self.schedule_runtime_snapshot()
        self.schedule_status_snapshot()

    def refresh_device_availability(self) -> None:
        """Compatibility hook: schedule one non-blocking shared status read."""
        self.schedule_status_snapshot()

    def refresh_lighting_ownership(self) -> None:
        """Compatibility hook: schedule one non-blocking runtime read."""
        self.schedule_runtime_snapshot()

    def set_background_polling(self, active: bool) -> None:
        timers = (
            self.runtime_poll_timer,
            self.device_state_timer,
            self.result_poll_timer,
            self.scene_panel.refresh_timer,
        )

        if active:
            for timer in timers:
                if not timer.isActive():
                    timer.start()
        else:
            for timer in timers:
                timer.stop()


    def application_icon(self) -> QIcon:
        if SERPENT_APP_ICON_PATH.is_file():
            icon = QIcon(str(SERPENT_APP_ICON_PATH))
            if not icon.isNull():
                return icon

        icon = QIcon.fromTheme(
            "preferences-desktop-peripherals"
        )

        if icon.isNull():
            icon = self.style().standardIcon(
                self.style().StandardPixmap.SP_ComputerIcon
            )

        return icon

    @staticmethod
    def themed_icon(*names: str) -> QIcon:
        for name in names:
            icon = QIcon.fromTheme(name)
            if not icon.isNull():
                return icon
        return QIcon()

    def build_actions(self) -> None:
        self.refresh_action = QAction(
            self.themed_icon("view-refresh", "reload"),
            "Refresh Status",
            self,
        )
        self.refresh_action.setShortcut(
            QKeySequence("Ctrl+R")
        )
        self.refresh_action.triggered.connect(
            self.status_dashboard.refresh_status
        )

        self.restore_action = QAction(
            self.themed_icon("document-revert", "edit-undo"),
            "Restore Profiles",
            self,
        )
        self.restore_action.setShortcut(
            QKeySequence("Ctrl+Shift+R")
        )
        self.restore_action.triggered.connect(
            self.restore_profiles
        )

        self.fixture_editor_action = QAction(
            self.themed_icon(
                "preferences-desktop-peripherals",
                "input-keyboard",
            ),
            "Fixture Editor…",
            self,
        )
        self.fixture_editor_action.triggered.connect(
            self.open_fixture_editor
        )

        self.settings_action = QAction(
            self.themed_icon(
                "settings-configure",
                "preferences-system",
            ),
            "Settings…",
            self,
        )
        self.settings_action.triggered.connect(
            self.open_settings
        )

        self.export_action = QAction(
            self.themed_icon("document-save-as", "document-export"),
            "Export Profile…",
            self,
        )
        self.export_action.setShortcut(
            QKeySequence("Ctrl+E")
        )
        self.export_action.triggered.connect(
            self.export_profile
        )

        self.import_action = QAction(
            self.themed_icon("document-open", "document-import"),
            "Import Profile…",
            self,
        )
        self.import_action.setShortcut(
            QKeySequence("Ctrl+I")
        )
        self.import_action.triggered.connect(
            self.import_profile
        )

        self.about_action = QAction(
            self.themed_icon("help-about", "dialog-information"),
            "About Serpent",
            self,
        )
        self.about_action.triggered.connect(
            self.show_about
        )

        self.quit_action = QAction(
            self.themed_icon("application-exit", "system-log-out"),
            "Quit",
            self,
        )
        self.quit_action.setShortcut(
            QKeySequence("Ctrl+Q")
        )
        self.quit_action.triggered.connect(
            self.quit_application
        )

        self.status_tab_action = QAction(
            "Status Tab",
            self,
        )
        self.status_tab_action.setShortcut(
            QKeySequence("Ctrl+1")
        )
        self.status_tab_action.triggered.connect(
            lambda: self.select_tab("Status")
        )

        self.effects_workshop_tab_action = QAction(
            "Effects Workshop Tab",
            self,
        )
        self.effects_workshop_tab_action.setShortcut(
            QKeySequence("Ctrl+2")
        )
        self.effects_workshop_tab_action.triggered.connect(
            lambda: self.select_tab("Effects Workshop")
        )

        self.scenes_tab_action = QAction(
            "Scenes Tab",
            self,
        )
        self.scenes_tab_action.setShortcut(
            QKeySequence("Ctrl+3")
        )
        self.scenes_tab_action.triggered.connect(
            lambda: self.select_tab("Scenes")
        )

        self.sync_tab_action = QAction(
            "Sync Tab",
            self,
        )
        self.sync_tab_action.setShortcut(
            QKeySequence("Ctrl+4")
        )
        self.sync_tab_action.triggered.connect(
            lambda: self.select_tab("Sync")
        )

        for action in (
            self.refresh_action,
            self.restore_action,
            self.fixture_editor_action,
            self.export_action,
            self.import_action,
            self.about_action,
            self.quit_action,
            self.status_tab_action,
            self.effects_workshop_tab_action,
            self.scenes_tab_action,
            self.sync_tab_action,
        ):
            self.addAction(action)

    def build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction(self.import_action)
        file_menu.addAction(self.export_action)
        file_menu.addSeparator()
        file_menu.addAction(self.quit_action)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self.refresh_action)
        tools_menu.addAction(self.restore_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.fixture_editor_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self.settings_action)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self.status_tab_action)
        view_menu.addAction(self.effects_workshop_tab_action)
        view_menu.addAction(self.scenes_tab_action)
        view_menu.addAction(self.sync_tab_action)

        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction(self.about_action)

    def build_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return

        self.tray_icon = QSystemTrayIcon(
            self.application_icon(),
            self,
        )
        self.tray_icon.setToolTip(
            f"Serpent {VERSION}"
        )

        tray_menu = QMenu(self)
        tray_menu.setObjectName("serpentTrayMenu")

        open_action = QAction(
            self.application_icon(),
            "Open Serpent",
            tray_menu,
        )
        open_action.setObjectName("serpentTrayOpenAction")
        open_action.triggered.connect(
            self.show_from_tray
        )
        tray_menu.addAction(open_action)

        tray_menu.addSeparator()
        self.tray_scenes_menu = tray_menu.addMenu("Scenes")
        self.tray_scenes_menu.setIcon(
            self.themed_icon("view-list-icons", "folder")
        )
        self.tray_scenes_menu.aboutToShow.connect(
            self.refresh_tray_scenes
        )
        self.refresh_tray_scenes()

        tray_menu.addSeparator()
        tray_menu.addAction(self.refresh_action)
        tray_menu.addAction(self.restore_action)
        tray_menu.addSeparator()
        tray_menu.addAction(self.quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(
            self.tray_activated
        )
        self.tray_icon.show()

    def tray_activated(
        self,
        reason: QSystemTrayIcon.ActivationReason,
    ) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.show_from_tray()

    def open_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Serpent Settings")
        dialog.setObjectName("serpentSettingsDialog")
        dialog.setModal(True)
        dialog.setMinimumWidth(540)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(14)

        title = QLabel("Startup")
        title.setObjectName("serpentDialogTitle")
        title_font = title.font()
        title_font.setBold(True)
        title_font.setPointSize(title_font.pointSize() + 3)
        title.setFont(title_font)
        layout.addWidget(title)

        startup_check = QCheckBox("Start Serpent when I log in")
        startup_check.setChecked(serpent_autostart_enabled())
        layout.addWidget(startup_check)

        startup_detail = QLabel(
            "Launch Serpent in the system tray when your desktop session starts. "
            "The lighting engine remains independent of the GUI."
        )
        startup_detail.setWordWrap(True)
        startup_detail.setObjectName("serpentSecondaryLabel")
        layout.addWidget(startup_detail)

        startup_note = QLabel(
            "When enabled, Serpent starts tray-only the next time you log in."
        )
        startup_note.setWordWrap(True)
        startup_note.setObjectName("serpentSettingsInfo")
        layout.addWidget(startup_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.setObjectName("serpentSettingsButtons")
        ok_button = buttons.button(
            QDialogButtonBox.StandardButton.Ok
        )
        cancel_button = buttons.button(
            QDialogButtonBox.StandardButton.Cancel
        )
        if ok_button is not None:
            ok_button.setProperty("serpentRole", "primary")
        if cancel_button is not None:
            cancel_button.setProperty("serpentRole", "secondary")
        startup_commit_succeeded = False

        def commit_startup_choice() -> None:
            nonlocal startup_commit_succeeded
            requested = startup_check.isChecked()
            before = serpent_autostart_enabled()
            try:
                if requested != before:
                    set_serpent_autostart(requested)
            except (OSError, GuiError) as exc:
                notify_error(
                    self,
                    "Could not update startup setting",
                    str(exc),
                )
                return

            if serpent_autostart_enabled() != requested:
                notify_error(
                    self,
                    "Could not update startup setting",
                    "Serpent could not verify the saved autostart state.",
                )
                return

            startup_commit_succeeded = True
            dialog.accept()

        if ok_button is not None:
            ok_button.clicked.connect(commit_startup_choice)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        if not startup_commit_succeeded:
            return

        requested = serpent_autostart_enabled()
        notify_info(
            self,
            "Startup setting updated",
            (
                "Serpent will start in the system tray the next time you log in."
                if requested
                else "Serpent will no longer start automatically when you log in."
            ),
        )

    def refresh_tray_scenes(self) -> None:
        menu = getattr(self, "tray_scenes_menu", None)
        if menu is None:
            return

        menu.clear()

        try:
            scenes = gui_scene_repository().list_scenes()
        except SceneRepositoryError as exc:
            action = menu.addAction("Scene library unavailable")
            action.setEnabled(False)
            action.setToolTip(str(exc))
            return

        if not scenes:
            action = menu.addAction("No saved scenes")
            action.setEnabled(False)
            return

        for scene in scenes:
            action = menu.addAction(scene.name)
            action.setToolTip(f"{scene.mode} · {scene.id}")
            action.triggered.connect(
                lambda _checked=False, scene_id=scene.id:
                    self.apply_tray_scene(scene_id)
            )

    def apply_tray_scene(self, scene_id: str) -> None:
        try:
            scene = gui_scene_repository().load(scene_id)
            plan = apply_scene(
                scene,
                SerpentSceneRuntime(),
            )
        except (
            SceneRepositoryError,
            SceneApplicationError,
            OSError,
            ValueError,
        ) as exc:
            if self.tray_icon is not None:
                self.tray_icon.showMessage(
                    "Scene application failed",
                    str(exc),
                    QSystemTrayIcon.MessageIcon.Critical,
                )
            notify_error(
                self,
                "Scene application failed",
                str(exc),
            )
            return

        self.refresh_after_scene_application()

        if self.tray_icon is not None:
            self.tray_icon.showMessage(
                "Scene applied",
                f"{plan.scene_name} ({plan.mode})",
                QSystemTrayIcon.MessageIcon.Information,
            )

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.set_background_polling(True)
        self.schedule_runtime_snapshot()
        self.schedule_status_snapshot()

    def open_scene_in_workshop(self, scene):
        opened = self.effect_lab.load_scene(scene)
        if opened:
            self.select_tab("Effects Workshop")
        return opened

    def select_tab(self, name: str) -> None:
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == name:
                self.tabs.setCurrentIndex(index)
                return

    def restore_profiles(self) -> None:
        try:
            message = restore_all_profiles()
            self.status_dashboard.refresh_status()

            if self.tray_icon is not None:
                self.tray_icon.showMessage(
                    "Serpent",
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    2500,
                )

        except GuiError as exc:
            notify_error(
                self,
                "Serpent error",
                str(exc),
            )

    def open_fixture_editor(self) -> None:
        from gui.fixture_editor_dialog import FixtureEditorDialog

        dialog = FixtureEditorDialog(
            self,
            fixture_dir=FIXTURE_DIR,
        )
        dialog.setModal(True)

        # Match About-dialog behavior: nested QDialog event loops must not
        # run background reconciliation timers concurrently.
        active_timers = [
            timer
            for timer in self.findChildren(QTimer)
            if timer.isActive()
        ]
        for timer in active_timers:
            timer.stop()

        try:
            dialog.exec()
        finally:
            for timer in active_timers:
                timer.start()

    def export_profile(self) -> None:
        if not PROFILE_PATH.exists():
            notify_warning(
                self,
                "No profile",
                "There is no Serpent profile to export.",
            )
            return

        destination, _selected_filter = (
            QFileDialog.getSaveFileName(
                self,
                "Export Serpent profile",
                str(
                    HOME
                    / "serpent-profile.json"
                ),
                "JSON files (*.json)",
            )
        )

        if not destination:
            return

        try:
            shutil.copy2(
                PROFILE_PATH,
                Path(destination),
            )
        except OSError as exc:
            notify_error(
                self,
                "Export failed",
                str(exc),
            )
            return

        notify_info(
            self,
            "Profile exported",
            f"Saved profile to:\n{destination}",
        )

    def import_profile(self) -> None:
        source, _selected_filter = (
            QFileDialog.getOpenFileName(
                self,
                "Import Serpent profile",
                str(HOME),
                "JSON files (*.json)",
            )
        )

        if not source:
            return

        source_path = Path(source)

        try:
            imported = json.loads(
                source_path.read_text(
                    encoding="utf-8"
                )
            )

            if not isinstance(imported, dict):
                raise ValueError(
                    "The selected file does not contain "
                    "a JSON object."
                )

            if (
                "mouse" not in imported
                and "keyboard" not in imported
            ):
                raise ValueError(
                    "The selected file does not contain "
                    "a mouse or keyboard profile."
                )

            PROFILE_PATH.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

            if PROFILE_PATH.exists():
                backup = PROFILE_PATH.with_suffix(
                    ".json.before-import"
                )
                shutil.copy2(
                    PROFILE_PATH,
                    backup,
                )

            PROFILE_PATH.write_text(
                json.dumps(
                    imported,
                    indent=4,
                )
                + "\n",
                encoding="utf-8",
            )

            restore_all_profiles()
            self.status_dashboard.refresh_status()

        except (
            OSError,
            ValueError,
            json.JSONDecodeError,
            GuiError,
        ) as exc:
            notify_error(
                self,
                "Import failed",
                str(exc),
            )
            return

        notify_info(
            self,
            "Profile imported",
            "The profile was imported and restored. "
            "Reopen Serpent to refresh all editor controls.",
        )

    def show_about(self) -> None:
        fixture_count = len(
            list(FIXTURE_DIR.glob("*.json"))
        )

        dialog = QDialog(self)
        dialog.setWindowTitle("About Serpent")
        dialog.setObjectName("serpentAboutDialog")
        dialog.setModal(True)
        dialog.setMinimumWidth(420)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(22, 22, 22, 18)
        layout.setSpacing(14)

        if SERPENT_ABOUT_ART_PATH.is_file():
            brand = QLabel()
            brand_pixmap = QPixmap(str(SERPENT_ABOUT_ART_PATH))
            if not brand_pixmap.isNull():
                brand.setPixmap(
                    brand_pixmap.scaled(
                        370,
                        132,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
                layout.addWidget(brand)

        information = QLabel(
            (
                f"<h2>Serpent {VERSION}</h2>"
                "<p>Fixture-driven RGB control for Linux.</p>"
                f"<p><b>Installed fixtures:</b> {fixture_count}<br>"
                f"<b>Python:</b> {sys.version.split()[0]}<br>"
                "<b>Qt:</b> PySide6</p>"
                "<p>Features include persistent profiles, "
                "hardware and software effects, multi-zone "
                "mouse lighting, live preview, recovery "
                "services, and diagnostics.</p>"
                "<p>Powered by OpenRazer.</p>"
            )
        )
        information.setWordWrap(True)
        information.setObjectName("serpentAboutInformation")
        information.setTextFormat(
            Qt.TextFormat.RichText
        )
        layout.addWidget(information)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(dialog.accept)
        layout.addWidget(buttons)

        # QDialog.exec() runs a nested Qt event loop. Keep background
        # reconciliation out of that nested loop and keep an explicit
        # Python reference to the dialog until exec() returns.
        active_timers = [
            timer
            for timer in self.findChildren(QTimer)
            if timer.isActive()
        ]

        for timer in active_timers:
            timer.stop()

        try:
            dialog.exec()
        finally:
            for timer in active_timers:
                timer.start()

    def restore_window_state(self) -> None:
        geometry = self.settings.value("window/geometry")

        if geometry is not None:
            self.restoreGeometry(geometry)

        selected_tab = self.settings.value(
            "window/tab",
            "Status",
        )
        self.select_tab(str(selected_tab))

    def save_window_state(self) -> None:
        self.settings.setValue(
            "window/geometry",
            self.saveGeometry(),
        )
        self.settings.setValue(
            "window/tab",
            self.tabs.tabText(
                self.tabs.currentIndex()
            ),
        )

    def quit_application(self) -> None:
        self.really_quit = True
        self.save_window_state()

        if hasattr(self, "effect_lab"):
            self.effect_lab.stop_live_preview(silent=True)

        if self.tray_icon is not None:
            self.tray_icon.hide()

        if hasattr(self, "_poll_executor"):
            self._poll_executor.shutdown(
                wait=False,
                cancel_futures=True,
            )

        QApplication.instance().quit()

    def closeEvent(self, event) -> None:
        self.save_window_state()

        application = QApplication.instance()
        session_shutdown = bool(
            application is not None
            and application.isSavingSession()
        )

        # Desktop-session shutdown must override the normal close-to-tray
        # behavior. Otherwise Plasma waits for Serpent while closeEvent()
        # hides the window and deliberately keeps the process alive.
        if session_shutdown:
            self.really_quit = True

            if hasattr(self, "effect_lab"):
                self.effect_lab.stop_live_preview(silent=True)

            if self.tray_icon is not None:
                self.tray_icon.hide()

            if hasattr(self, "_poll_executor"):
                self._poll_executor.shutdown(
                    wait=False,
                    cancel_futures=True,
                )

            event.accept()

            if application is not None:
                QTimer.singleShot(0, application.quit)

            return

        if (
            self.tray_icon is not None
            and not self.really_quit
        ):
            event.ignore()
            self.set_background_polling(False)
            self.hide()

            if not self.tray_message_shown:
                self.tray_icon.showMessage(
                    "Serpent is still running",
                    "Use the tray icon to reopen or quit the GUI. "
                    "Lighting services continue independently.",
                    QSystemTrayIcon.MessageIcon.Information,
                    3500,
                )
                self.tray_message_shown = True

            return

        event.accept()


def notify_existing_instance(
    *,
    show_window: bool,
) -> bool:
    """Contact the running Serpent GUI, if one exists."""

    socket = QLocalSocket()
    socket.connectToServer(INSTANCE_SERVER_NAME)

    if not socket.waitForConnected(300):
        return False

    if show_window:
        socket.write(b"show\n")
        socket.flush()
        socket.waitForBytesWritten(300)

    socket.disconnectFromServer()
    socket.waitForDisconnected(100)
    return True


def attach_instance_server(
    application: QApplication,
    window: SerpentWindow,
) -> QLocalServer:
    """Create the local IPC server owned by the first instance."""

    # Remove a stale endpoint left behind by an unclean shutdown.
    QLocalServer.removeServer(INSTANCE_SERVER_NAME)

    server = QLocalServer(application)

    if not server.listen(INSTANCE_SERVER_NAME):
        raise GuiError(
            "Could not create the Serpent single-instance server: "
            f"{server.errorString()}"
        )

    def handle_client(client: QLocalSocket) -> None:
        request = bytes(client.readAll()).decode(
            "utf-8",
            errors="replace",
        ).strip()

        if request == "show":
            window.show_from_tray()

        client.disconnectFromServer()
        client.deleteLater()

    def accept_connections() -> None:
        while server.hasPendingConnections():
            client = server.nextPendingConnection()

            if client is None:
                continue

            client.readyRead.connect(
                lambda client=client: handle_client(client)
            )

            # The message may already have arrived before the signal
            # connection was installed.
            if client.bytesAvailable():
                handle_client(client)

    server.newConnection.connect(accept_connections)
    return server


def main() -> int:
    if not faulthandler.is_enabled():
        faulthandler.enable(all_threads=True)

    application = QApplication(sys.argv)
    application.setApplicationName("Serpent")
    application.setApplicationDisplayName("Serpent")
    application.setApplicationVersion(VERSION)
    application.setDesktopFileName("serpent")
    application.setOrganizationName("Serpent Project")

    serpent_stylesheet = load_serpent_visual_stylesheet()
    if serpent_stylesheet:
        application.setStyleSheet(serpent_stylesheet)

    tray_only = "--tray" in sys.argv

    # A second normal launch raises the existing window. A second
    # tray-only launch exits silently, leaving the existing tray owner.
    if notify_existing_instance(
        show_window=not tray_only,
    ):
        return 0

    try:
        window = SerpentWindow()
        instance_server = attach_instance_server(
            application,
            window,
        )
    except (
        GuiError,
        BackendError,
        FixtureError,
        OSError,
        ValueError,
        KeyError,
        json.JSONDecodeError,
    ) as exc:
        notify_error(
            None,
            "Serpent could not start",
            str(exc),
        )
        return 1

    # Keep an explicit Python reference for the entire event loop.
    window.instance_server = instance_server

    application.setWindowIcon(
        window.application_icon()
    )

    if tray_only and window.tray_icon is not None:
        application.setQuitOnLastWindowClosed(False)
    else:
        window.show()

    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
