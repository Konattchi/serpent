from __future__ import annotations

import ast
import copy
import json
import math
import os
import subprocess
import tempfile
from pathlib import Path

from PySide6.QtCore import QProcess, QSettings, QTimer, Signal, Qt
from PySide6.QtGui import QAction, QColor, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QAbstractItemView,
    QComboBox,
    QColorDialog,
    QDoubleSpinBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

ROOT = Path.home() / ".local" / "share" / "serpent"
WORKER = ROOT / "gui" / "effect_lab_worker.py"


class EffectLabPreview(QWidget):
    cellActivated = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._frame = None
        self._target = {
            "display_rows": 1,
            "display_columns": 1,
            "display_cells": [[0, 0]],
        }
        self.setMinimumHeight(210)
        self.setToolTip("Click a cell to inject a synthetic key press.")

    def set_target(self, target):
        if not isinstance(target, dict):
            return
        self._target = dict(target)
        self.update()

    def set_frame(self, frame):
        self._frame = frame
        self.update()

    def clear_frame(self):
        self._frame = None
        self.update()

    def _geometry(self):
        rows = int(self._target.get("display_rows", 1) or 1)
        columns = int(self._target.get("display_columns", 1) or 1)
        margin, gap = 8.0, 2.0
        width = max(1.0, self.width() - margin * 2)
        height = max(1.0, self.height() - margin * 2)
        cell_width = max(2.0, (width - gap * (columns - 1)) / columns)
        cell_height = max(2.0, (height - gap * (rows - 1)) / rows)
        return rows, columns, margin, gap, cell_width, cell_height

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(18, 18, 18))
        rows, columns, margin, gap, cell_width, cell_height = self._geometry()

        for row in range(rows):
            for column in range(columns):
                colour = (30, 30, 30)
                if self._frame is not None:
                    try:
                        display_columns = int(
                            self._target.get("display_columns", columns)
                        )
                        display_cells = self._target.get("display_cells", [])
                        index = row * display_columns + column
                        source_row, source_column = display_cells[index]
                        if source_row >= 0 and source_column >= 0:
                            colour = self._frame.colour_at(
                                int(source_row),
                                int(source_column),
                            )
                    except Exception:
                        pass

                painter.fillRect(
                    int(margin + column * (cell_width + gap)),
                    int(margin + row * (cell_height + gap)),
                    max(1, int(cell_width)),
                    max(1, int(cell_height)),
                    QColor(*colour),
                )

    def mousePressEvent(self, event):
        rows, columns, margin, gap, cell_width, cell_height = self._geometry()
        x = float(event.position().x()) - margin
        y = float(event.position().y()) - margin
        if x < 0 or y < 0:
            return

        column = int(x // (cell_width + gap))
        row = int(y // (cell_height + gap))
        if not (0 <= row < rows and 0 <= column < columns):
            return

        try:
            display_columns = int(
                self._target.get("display_columns", columns)
            )
            display_cells = self._target.get("display_cells", [])
            index = row * display_columns + column
            source_row, source_column = display_cells[index]
        except Exception:
            return

        if source_row < 0 or source_column < 0:
            return

        self.cellActivated.emit(
            int(source_row),
            int(source_column),
        )


class ComposerMatrix(QWidget):
    cellSelected = Signal(int, int)
    regionSelectionChanged = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = 6
        self.columns = 22
        self.active_cells = {
            (row, column)
            for row in range(self.rows)
            for column in range(self.columns)
        }
        self.selected = None
        self.region_editing = False
        self.region_selection_mode = "add"
        self.region_selection = set()
        self._region_dragging = False
        self._region_drag_seen = set()
        self.colours = {}
        self.setMouseTracking(True)
        self.setMinimumHeight(205)
        self.setToolTip(
            "Visual Composer matrix — click a cell to target the selected Cell layer."
        )

    def set_geometry(
        self,
        rows,
        columns,
        active_cells=None,
    ):
        rows = max(1, int(rows))
        columns = max(1, int(columns))
        self.rows = rows
        self.columns = columns

        if active_cells is None:
            active = {
                (row, column)
                for row in range(rows)
                for column in range(columns)
            }
        else:
            active = {
                (int(row), int(column))
                for row, column in active_cells
                if (
                    0 <= int(row) < rows
                    and 0 <= int(column) < columns
                )
            }

        self.active_cells = active
        if (
            self.selected is not None
            and self.selected not in self.active_cells
        ):
            self.selected = None
        self.region_selection.intersection_update(self.active_cells)
        self.update()

    def set_composition(self, layers, regions=None):
        colours = {}
        background = (18, 18, 18)
        regions = regions or {}

        def cells_for(layer):
            region = layer.get("region")
            if not region:
                return set(self.active_cells)
            return {
                tuple(cell)
                for cell in regions.get(region, ())
                if tuple(cell) in self.active_cells
            }

        def blend(old, new, alpha):
            alpha = max(0.0, min(1.0, float(alpha)))
            return tuple(
                round(old[i] * (1.0 - alpha) + new[i] * alpha)
                for i in range(3)
            )

        for layer in layers:
            kind = layer.get("kind")
            colour = tuple(layer.get("colour", (80, 120, 255)))
            opacity = float(layer.get("opacity", 1.0))
            masked = cells_for(layer)

            if kind == "Fill":
                fill_colour = blend(background, colour, opacity)
                for cell in masked:
                    colours[cell] = fill_colour
            elif kind == "Cell":
                cell = (int(layer.get("row", 0)), int(layer.get("column", 0)))
                if cell in masked:
                    old = colours.get(cell, background)
                    colours[cell] = blend(old, colour, opacity)
            elif kind == "Gradient":
                colour2 = tuple(layer.get("colour2", (255, 80, 160)))
                vertical = layer.get("direction") == "Vertical"
                for row, column in masked:
                    t = (
                        row / max(1, self.rows - 1)
                        if vertical
                        else column / max(1, self.columns - 1)
                    )
                    mixed = tuple(
                        round(colour[i] * (1.0 - t) + colour2[i] * t)
                        for i in range(3)
                    )
                    old = colours.get((row, column), background)
                    colours[(row, column)] = blend(old, mixed, opacity)
            elif kind == "Pulse":
                for cell in masked:
                    old = colours.get(cell, background)
                    colours[cell] = blend(old, colour, opacity)

        self.colours = colours
        self.update()

    def _geometry(self):
        margin, gap = 7.0, 2.0
        width = max(1.0, self.width() - margin * 2)
        height = max(1.0, self.height() - margin * 2)
        cell_width = max(2.0, (width - gap * (self.columns - 1)) / self.columns)
        cell_height = max(2.0, (height - gap * (self.rows - 1)) / self.rows)
        return margin, gap, cell_width, cell_height

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(12, 12, 12))
        margin, gap, cell_width, cell_height = self._geometry()
        for row in range(self.rows):
            for column in range(self.columns):
                active = (row, column) in self.active_cells
                colour = (
                    self.colours.get((row, column), (30, 30, 30))
                    if active
                    else (11, 11, 11)
                )
                x = int(margin + column * (cell_width + gap))
                y = int(margin + row * (cell_height + gap))
                w = max(1, int(cell_width))
                h = max(1, int(cell_height))
                painter.fillRect(x, y, w, h, QColor(*colour))
                if (row, column) in self.region_selection:
                    painter.setPen(QColor(255, 210, 70))
                    painter.drawRect(x, y, w - 1, h - 1)
                elif self.selected == (row, column):
                    painter.setPen(QColor(255, 255, 255))
                    painter.drawRect(x, y, w - 1, h - 1)

    def set_region_editing(self, enabled):
        self.region_editing = bool(enabled)
        self._region_dragging = False
        self._region_drag_seen.clear()
        self.update()

    def set_region_selection_mode(self, mode):
        self.region_selection_mode = (
            mode if mode in {"add", "subtract", "toggle"} else "add"
        )

    def set_region_selection(self, cells):
        self.region_selection = {
            (int(row), int(column))
            for row, column in cells
            if (int(row), int(column)) in self.active_cells
        }
        self.update()

    def _cell_at_position(self, position):
        margin, gap, cell_width, cell_height = self._geometry()
        x = float(position.x()) - margin
        y = float(position.y()) - margin
        if x < 0 or y < 0:
            return None
        column = int(x // (cell_width + gap))
        row = int(y // (cell_height + gap))
        cell = (row, column)
        if not (0 <= row < self.rows and 0 <= column < self.columns):
            return None
        return cell if cell in self.active_cells else None

    def _paint_region_cell(self, cell):
        if cell is None or cell in self._region_drag_seen:
            return
        self._region_drag_seen.add(cell)
        if self.region_selection_mode == "subtract":
            self.region_selection.discard(cell)
        elif self.region_selection_mode == "toggle":
            if cell in self.region_selection:
                self.region_selection.remove(cell)
            else:
                self.region_selection.add(cell)
        else:
            self.region_selection.add(cell)
        self.update()
        self.regionSelectionChanged.emit(tuple(sorted(self.region_selection)))

    def mousePressEvent(self, event):
        cell = self._cell_at_position(event.position())
        if cell is None:
            return
        if self.region_editing:
            if event.button() != Qt.MouseButton.LeftButton:
                return
            self._region_dragging = True
            self._region_drag_seen.clear()
            self._paint_region_cell(cell)
            return
        self.selected = cell
        self.update()
        self.cellSelected.emit(*cell)

    def mouseMoveEvent(self, event):
        if self.region_editing and self._region_dragging:
            self._paint_region_cell(self._cell_at_position(event.position()))

    def mouseReleaseEvent(self, event):
        if self.region_editing and event.button() == Qt.MouseButton.LeftButton:
            self._region_dragging = False
            self._region_drag_seen.clear()


class _Frame:
    def __init__(self, raw):
        self.rows = int(raw["rows"])
        self.columns = int(raw["columns"])
        self.pixels = raw["pixels"]

    def colour_at(self, row, column):
        return tuple(self.pixels[row][column])


class _Param:
    def __init__(self, raw):
        self.id = raw["id"]
        self.label = raw["label"]
        self.kind = raw["kind"]
        self.default = raw["default"]
        self.minimum = raw.get("minimum")
        self.maximum = raw.get("maximum")
        self.choices = tuple(raw.get("choices") or ())


class _Spec:
    def __init__(self, raw):
        self.id = raw["id"]
        self.name = raw["name"]
        self.description = raw.get("description", "")
        self.input_capabilities = tuple(raw.get("input_capabilities") or ())
        self.render_targets = tuple(raw.get("render_targets") or ())
        self.parameters = tuple(_Param(item) for item in raw.get("parameters") or ())


class EffectLabPanel(QWidget):
    FRAME_INTERVAL_MS = 33
    WORKER_TIMEOUT_MS = 1500

    def __init__(self, parameter_editor_class, parent=None):
        super().__init__(parent)

        self.loaded_path = None
        self._composer_output_path = None
        self.specs = []
        self.spec = None
        self.elapsed = 0.0
        self.preview_enabled = False

        self.settings = QSettings("Serpent Project", "Serpent")

        self._request_id = 0
        self._pending = None
        self._stdout_buffer = ""
        self._worker_generation = 0

        self.path_edit = QPlainTextEdit()
        self.path_edit.setMaximumHeight(52)
        self.path_edit.setPlaceholderText("No source loaded — use New Effect… or Browse…")

        self.browse_button = QPushButton("Browse…")
        self.load_button = QPushButton("Load Source")
        self.validate_button = QPushButton("Validate & Preview")
        self.save_button = QPushButton("Save")
        self.reload_button = QPushButton("Save + Reload Installed")
        self.reload_button.setToolTip(
            "Installed user plugins only: validate, atomically save, "
            "then invoke M8.9 hot reload."
        )

        self.new_effect_button = QPushButton("New Effect…")
        self.new_effect_button.setToolTip(
            "Step 1: generate a normal Serpent plugin from an SDK template."
        )
        self.validate_button.setToolTip(
            "Step 3: validate candidate source in the isolated worker and "
            "unlock preview/install when successful."
        )
        self.save_button.setToolTip(
            "Save the current source file without installing it."
        )

        self.promote_button = QPushButton("Install to Serpent")
        self.promote_button.setToolTip(
            "Step 4: install the currently validated Developer effect into "
            "Serpent's normal Installed Effects catalog."
        )

        self.live_preview_start_button = QPushButton("Start Live Preview")
        self.live_preview_stop_button = QPushButton("Stop Live Preview")
        self.live_preview_stop_button.setEnabled(False)
        self.live_preview_label = QLabel("Physical preview: inactive")
        self.live_preview_label.setWordWrap(True)
        self._live_preview_active = False

        self.source_edit = QPlainTextEdit()
        self.source_edit.setPlaceholderText("Step 2 — Python effect source appears here. Create or load an effect to begin.")

        self.effect_combo = QComboBox()
        self.effect_combo.setEnabled(False)
        self.effect_parameters = parameter_editor_class(self)

        self.target_combo = QComboBox()
        self._load_fixture_preview_targets()

        self.reset_button = QPushButton("Reset Preview")
        self.mouse_event_button = QPushButton("Inject Mouse Press")
        self.status_label = QLabel(
            "Effect Lab ready. Candidate code executes in an isolated "
            "persistent worker; the GUI never waits for it."
        )
        self.status_label.setWordWrap(True)
        self.preview = EffectLabPreview(self)

        self._build_ui()

        self.worker = QProcess(self)
        self.worker.setProgram(os.fspath(Path(os.sys.executable)))
        self.worker.setArguments([os.fspath(WORKER)])
        self.worker.readyReadStandardOutput.connect(self._worker_stdout)
        self.worker.readyReadStandardError.connect(self._worker_stderr)
        self.worker.finished.connect(self._worker_finished)

        self.watchdog = QTimer(self)
        self.watchdog.setSingleShot(True)
        self.watchdog.timeout.connect(self._worker_timeout)

        self.timer = QTimer(self)
        self.timer.setInterval(self.FRAME_INTERVAL_MS)
        self.timer.timeout.connect(self.advance_frame)
        self.timer.start()

        self.composer_timeline_timer = QTimer(self)
        self.composer_timeline_timer.setInterval(50)
        self.composer_timeline_timer.timeout.connect(self._composer_timeline_tick)

        self.browse_button.clicked.connect(self.browse)
        self.load_button.clicked.connect(self.load_file)
        self.validate_button.clicked.connect(self.validate_source)
        self.save_button.clicked.connect(self.save_source)
        self.reload_button.clicked.connect(self.save_and_reload)
        self.new_effect_button.clicked.connect(self.create_new_effect)
        self.promote_button.clicked.connect(self.promote_effect)
        self.live_preview_start_button.clicked.connect(self.start_live_preview)
        self.live_preview_stop_button.clicked.connect(self.stop_live_preview)
        self.effect_combo.currentIndexChanged.connect(self.select_effect)
        self.effect_parameters.changed.connect(self.render_now)
        self.target_combo.currentIndexChanged.connect(self._target_changed)
        self.preview.set_target(self._preview_target())
        self.reset_button.clicked.connect(self.reset_effect)
        self.mouse_event_button.clicked.connect(self.inject_mouse)
        self.preview.cellActivated.connect(self.inject_key)

    def _load_fixture_preview_targets(self):
        from serpent_core.device import build_device_model
        from serpent_core.fixtures import find_fixture_by_id
        from serpent_core.sync import require_topology

        fixture_dir = ROOT / "fixtures"
        loaded = 0

        for path in sorted(fixture_dir.glob("*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                fixture_id = str(raw["id"])
                fixture = find_fixture_by_id(fixture_id)
                device = build_device_model(fixture)
                topology = require_topology(device)

                active_cells = [
                    [cell.row, cell.column]
                    for region in topology.controllable_regions()
                    for cell in region.cells
                ]

                if not active_cells:
                    continue

                active_rows = sorted(
                    {row for row, _column in active_cells}
                )
                active_columns = sorted(
                    {column for _row, column in active_cells}
                )

                row_index = {
                    source_row: display_row
                    for display_row, source_row in enumerate(active_rows)
                }
                column_index = {
                    source_column: display_column
                    for display_column, source_column
                    in enumerate(active_columns)
                }

                display_rows = len(active_rows)
                display_columns = len(active_columns)

                display_lookup = {
                    (
                        row_index[source_row],
                        column_index[source_column],
                    ): [source_row, source_column]
                    for source_row, source_column in active_cells
                }

                display_cells = [
                    display_lookup.get(
                        (display_row, display_column),
                        [-1, -1],
                    )
                    for display_row in range(display_rows)
                    for display_column in range(display_columns)
                ]

                device_class = str(
                    raw.get("device_class", "device")
                )
                display_name = str(
                    raw.get("display_name")
                    or raw.get("name")
                    or getattr(fixture, "display_name", fixture_id)
                )

                payload = {
                    "fixture_id": fixture_id,
                    "device_class": device_class,
                    "rows": topology.rows,
                    "columns": topology.columns,
                    "active_cells": active_cells,
                    "display_rows": display_rows,
                    "display_columns": display_columns,
                    "display_cells": display_cells,
                }

                self.target_combo.addItem(
                    f"{display_name} — "
                    f"{display_rows}×{display_columns} "
                    f"({len(active_cells)} LEDs)",
                    payload,
                )
                loaded += 1
            except Exception:
                continue

        if not loaded:
            self.target_combo.addItem(
                "Generic Matrix — 1×1",
                {
                    "fixture_id": None,
                    "device_class": "device",
                    "rows": 1,
                    "columns": 1,
                    "active_cells": [[0, 0]],
                    "display_rows": 1,
                    "display_columns": 1,
                    "display_cells": [[0, 0]],
                },
            )

    def _preview_target(self):
        target = self.target_combo.currentData()
        if not isinstance(target, dict):
            raise RuntimeError("Effect Lab preview fixture is invalid.")
        return dict(target)

    def _target_changed(self):
        try:
            self.preview.set_target(self._preview_target())
        except Exception:
            pass
        self.reset_effect()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(18, 18, 18, 18)
        outer.setSpacing(10)

        title = QLabel("Effect Lab — Safe Editor")
        font = title.font()
        font.setPointSize(font.pointSize() + 3)
        font.setBold(True)
        title.setFont(font)

        subtitle = QLabel(
            "Edit Python and preview synthetic output through an asynchronous "
            "isolated worker. Hangs pause preview without blocking the GUI."
        )
        subtitle.setWordWrap(True)

        file_row = QHBoxLayout()
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(self.browse_button)
        file_row.addWidget(self.load_button)

        form = QFormLayout()
        form.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        form.addRow("Plugin file", file_row)
        form.addRow("Effect", self.effect_combo)
        form.addRow(self.effect_parameters)
        form.addRow("Preview target", self.target_combo)

        actions = QHBoxLayout()
        actions.addWidget(self.new_effect_button)
        actions.addWidget(self.validate_button)
        actions.addWidget(self.save_button)
        actions.addWidget(self.reload_button)
        actions.addWidget(self.promote_button)
        actions.addStretch()

        live_actions = QHBoxLayout()
        live_actions.addWidget(self.live_preview_start_button)
        live_actions.addWidget(self.live_preview_stop_button)
        live_actions.addStretch()

        buttons = QHBoxLayout()
        buttons.addWidget(self.mouse_event_button)
        buttons.addStretch()
        buttons.addWidget(self.reset_button)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.source_edit)
        splitter.addWidget(self.preview)
        splitter.setSizes([300, 300])

        outer.addWidget(title)
        outer.addWidget(subtitle)
        outer.addLayout(form)
        outer.addLayout(actions)
        outer.addLayout(live_actions)
        outer.addWidget(self.live_preview_label)
        outer.addWidget(splitter, 1)
        outer.addLayout(buttons)
        outer.addWidget(self.status_label)

    def _ensure_worker(self):
        if self.worker.state() == QProcess.ProcessState.NotRunning:
            self._stdout_buffer = ""
            self._worker_generation += 1
            self.worker.start()

    def _send(self, action, payload=None):
        if self._pending is not None:
            return False

        self._ensure_worker()
        if not self.worker.waitForStarted(250):
            self.status_label.setText("Effect Lab worker could not start.")
            return False

        self._request_id += 1
        request = dict(payload or {})
        request["action"] = action
        request["request_id"] = self._request_id

        self._pending = {
            "id": self._request_id,
            "action": action,
            "generation": self._worker_generation,
        }

        encoded = (json.dumps(request, separators=(",", ":")) + "\n").encode()
        self.worker.write(encoded)
        self.watchdog.start(self.WORKER_TIMEOUT_MS)
        return True

    def _worker_stdout(self):
        self._stdout_buffer += bytes(
            self.worker.readAllStandardOutput()
        ).decode("utf-8", "replace")

        while "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            if not line.strip():
                continue

            try:
                payload = json.loads(line)
            except Exception as exc:
                self._fail_pending(
                    f"Worker protocol error: {type(exc).__name__}: {exc}"
                )
                continue

            pending = self._pending
            if pending is None:
                continue
            if payload.get("request_id") != pending["id"]:
                continue

            action = pending["action"]
            self._pending = None
            self.watchdog.stop()
            self._handle_reply(action, payload)

    def _worker_stderr(self):
        data = bytes(self.worker.readAllStandardError()).decode(
            "utf-8", "replace"
        ).strip()
        if data:
            self.status_label.setText(
                "Effect Lab worker diagnostic:\n" + data[-1200:]
            )

    def _worker_finished(self, exit_code, exit_status):
        if self._pending is not None:
            self._pending = None
            self.watchdog.stop()
            self.preview_enabled = False
            self.status_label.setText(
                "Preview worker exited unexpectedly. "
                "Fix the candidate and press Validate to restart it."
            )

    def _worker_timeout(self):
        action = self._pending["action"] if self._pending else "request"
        self._pending = None
        self.preview_enabled = False

        # QProcess.kill() is asynchronous. Wait briefly for the disposable
        # worker to actually stop so the next explicit Validate cannot race
        # a dying process and lose its request.
        if self.worker.state() != QProcess.ProcessState.NotRunning:
            self.worker.kill()
            self.worker.waitForFinished(300)

        self.status_label.setText(
            f"{action.title()} stopped: candidate exceeded "
            f"{self.WORKER_TIMEOUT_MS / 1000:.1f}s. "
            "Automatic preview is paused. Fix the code and press Validate."
        )

    def _fail_pending(self, message):
        self._pending = None
        self.watchdog.stop()
        self.preview_enabled = False
        self.status_label.setText(message)

    def _authoring_surface_changed(self, *args):
        if self._is_installed_mode():
            return
        self._apply_workshop_visibility()
        self.workshop_mode_label.setText(
            "Developer / Unified Workshop — compose visually, inspect or edit the "
            "same Python source, use the Python / Effect Guide, validate in the "
            "isolated worker, then save or install."
        )
        self._composer_refresh()

    def _composer_normalize_device_class(self, value):
        return str(value or "").strip().casefold()

    def _composer_initialize_target_models(self):
        current = self._composer_normalize_device_class(
            self._composer_target_payload().get("device_class")
            or self.composer_device_class_combo.currentText()
            or "keyboard"
        )
        self._composer_current_device_class = current
        self._composer_target_layers[current] = self._composer_layers
        self._composer_target_geometries[current] = (
            self._composer_target_payload()
        )
        self._composer_target_regions[current] = self._composer_regions
        self._composer_target_region_selections[current] = set(
            self._composer_region_selection
        )
        self._composer_target_groups[current] = self._composer_groups
        self._composer_ensure_layer_ids()
        self._composer_refresh_region_controls()
        self._composer_refresh_group_controls()
        self._composer_refresh_sync_target_list()

    def _composer_is_synchronized(self):
        return (
            self.composer_intent_combo.currentData()
            == "synchronized"
        )

    def _composer_refresh_sync_target_list(self):
        current = self._composer_current_device_class
        self.composer_sync_targets.blockSignals(True)
        self.composer_sync_targets.clear()
        for device_class in self._composer_target_layers:
            item = QListWidgetItem(device_class)
            item.setData(
                Qt.ItemDataRole.UserRole,
                device_class,
            )
            self.composer_sync_targets.addItem(item)
            if device_class == current:
                self.composer_sync_targets.setCurrentItem(item)
        self.composer_sync_targets.blockSignals(False)

    def _composer_intent_changed(self, *args):
        synchronized = self._composer_is_synchronized()

        self.composer_sync_targets.setVisible(synchronized)
        self.composer_add_target.setVisible(synchronized)
        self.composer_remove_target.setVisible(synchronized)

        self.composer_device_class_combo.setVisible(
            not synchronized
        )

        if synchronized:
            if not self._composer_target_layers:
                self._composer_initialize_target_models()
            self._composer_refresh_sync_target_list()
        else:
            device_class = self._composer_normalize_device_class(
                self.composer_device_class_combo.currentText()
            )
            if device_class:
                self._composer_switch_target_model(
                    device_class,
                    create=True,
                )

        self._composer_refresh_source_preview()

    def _composer_device_class_changed(self, text):
        if self._composer_updating or self._composer_is_synchronized():
            return
        device_class = self._composer_normalize_device_class(text)
        if not device_class:
            return
        self._composer_switch_target_model(
            device_class,
            create=True,
        )

    def _composer_add_sync_target(self):
        device_class = self._composer_normalize_device_class(
            self.composer_device_class_combo.currentText()
        )
        if not device_class:
            device_class = "mouse"

        # If current editable value already exists, choose the first useful
        # standard class not yet participating.
        if device_class in self._composer_target_layers:
            for candidate in ("keyboard", "mouse", "mousepad"):
                if candidate not in self._composer_target_layers:
                    device_class = candidate
                    break
            else:
                suffix = 2
                base = "device"
                while f"{base}-{suffix}" in self._composer_target_layers:
                    suffix += 1
                device_class = f"{base}-{suffix}"

        self._composer_switch_target_model(
            device_class,
            create=True,
        )
        self._composer_refresh_sync_target_list()

    def _composer_remove_sync_target(self):
        if len(self._composer_target_layers) <= 1:
            self.status_label.setText(
                "A synchronized effect must keep at least one target."
            )
            return

        row = self.composer_sync_targets.currentRow()
        item = self.composer_sync_targets.item(row)
        if item is None:
            return

        device_class = item.data(Qt.ItemDataRole.UserRole)

        # If the active target is being removed, clear the active identity
        # before switching. Otherwise _composer_switch_target_model() would
        # save the just-deleted model back into the target dictionary.
        if device_class == self._composer_current_device_class:
            self._composer_current_device_class = None

        self._composer_target_layers.pop(device_class, None)
        self._composer_target_geometries.pop(device_class, None)
        self._composer_target_regions.pop(device_class, None)
        self._composer_target_region_selections.pop(
            device_class,
            None,
        )
        self._composer_target_groups.pop(device_class, None)

        next_class = next(iter(self._composer_target_layers))
        self._composer_switch_target_model(
            next_class,
            create=False,
        )
        self._composer_refresh_sync_target_list()

    def _composer_sync_target_selected(self, row):
        if self._composer_updating or not self._composer_is_synchronized():
            return
        item = self.composer_sync_targets.item(row)
        if item is None:
            return
        self._composer_switch_target_model(
            item.data(Qt.ItemDataRole.UserRole),
            create=False,
        )

    def _composer_switch_target_model(self, device_class, *, create):
        device_class = self._composer_normalize_device_class(
            device_class
        )
        if not device_class:
            return

        if self._composer_current_device_class:
            self._composer_target_layers[
                self._composer_current_device_class
            ] = self._composer_layers
            self._composer_target_geometries[
                self._composer_current_device_class
            ] = self._composer_target_payload()
            self._composer_target_regions[
                self._composer_current_device_class
            ] = self._composer_regions
            self._composer_target_region_selections[
                self._composer_current_device_class
            ] = set(self._composer_region_selection)
            self._composer_target_groups[self._composer_current_device_class] = self._composer_groups

        if device_class not in self._composer_target_layers:
            if not create:
                return
            self._composer_target_layers[device_class] = [
                self._composer_default_layer("Fill")
            ]
            self._composer_target_geometries[
                device_class
            ] = self._composer_default_geometry_for_class(
                device_class
            )
            self._composer_target_regions[device_class] = {}
            self._composer_target_region_selections[device_class] = set()
            self._composer_target_groups[device_class] = []

        self._composer_current_device_class = device_class
        self._composer_layers = self._composer_target_layers[
            device_class
        ]
        self._composer_regions = self._composer_target_regions.setdefault(
            device_class,
            {},
        )
        self._composer_region_selection = set(
            self._composer_target_region_selections.setdefault(
                device_class,
                set(),
            )
        )
        self._composer_groups = self._composer_target_groups.setdefault(device_class, [])
        self._composer_ensure_layer_ids()

        self._composer_updating = True
        try:
            self.composer_device_class_combo.setCurrentText(
                device_class
            )
            self._composer_adopt_target_geometry_payload(
                self._composer_target_geometries.get(
                    device_class,
                    {},
                )
            )
        finally:
            self._composer_updating = False

        self._composer_rebuild_layer_list()
        self._composer_apply_geometry()
        self._composer_refresh_region_controls()
        self._composer_refresh_group_controls()
        self._composer_refresh_sync_target_list()

    def _composer_default_geometry_for_class(self, device_class):
        for index in range(self.composer_target_combo.count()):
            payload = self.composer_target_combo.itemData(index)
            if (
                isinstance(payload, dict)
                and not payload.get("custom")
                and self._composer_normalize_device_class(
                    payload.get("device_class")
                )
                == device_class
            ):
                return dict(payload)

        return {
            "custom": True,
            "device_class": device_class,
            "rows": 6 if device_class == "keyboard" else 1,
            "columns": 22 if device_class == "keyboard" else 1,
        }

    def _composer_adopt_target_geometry_payload(self, payload):
        target_index = -1
        for index in range(self.composer_target_combo.count()):
            candidate = self.composer_target_combo.itemData(index)
            if not isinstance(candidate, dict):
                continue
            if payload.get("custom") and candidate.get("custom"):
                target_index = index
                break
            if (
                not payload.get("custom")
                and not candidate.get("custom")
                and candidate == payload
            ):
                target_index = index
                break

        if target_index < 0:
            target_index = self.composer_target_combo.findText(
                "Custom Matrix…"
            )

        self.composer_target_combo.setCurrentIndex(target_index)

        if payload.get("custom"):
            self.composer_rows.setValue(
                max(1, int(payload.get("rows", 1)))
            )
            self.composer_columns.setValue(
                max(1, int(payload.get("columns", 1)))
            )


    def _composer_group_for_layer_id(self, layer_id):
        for group in self._composer_groups:
            if layer_id in group.get("members", ()):
                return group
        return None

    def _composer_rebuild_visual_stack(self):
        if not hasattr(self, "composer_layer_stack"):
            return

        selected_layer_ids = {
            self._composer_layers[index.row()].get("_authoring_id")
            for index in self.composer_layers.selectedIndexes()
            if 0 <= index.row() < len(self._composer_layers)
        }
        selected_group_id = None
        group_item = self.composer_groups.currentItem()
        if group_item is not None:
            selected_group_id = group_item.data(
                Qt.ItemDataRole.UserRole
            )

        expanded = set()
        for top_index in range(
            self.composer_layer_stack.topLevelItemCount()
        ):
            item = self.composer_layer_stack.topLevelItem(top_index)
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if (
                isinstance(data, dict)
                and data.get("kind") == "group"
                and item.isExpanded()
            ):
                expanded.add(data.get("id"))

        self._composer_stack_syncing = True
        self.composer_layer_stack.blockSignals(True)
        try:
            self.composer_layer_stack.clear()
            index = 0
            occurrence = {}
            while index < len(self._composer_layers):
                layer = self._composer_layers[index]
                layer_id = layer.get("_authoring_id")
                group = self._composer_group_for_layer_id(layer_id)

                if group is None:
                    item = QTreeWidgetItem(
                        [layer.get("kind", "Layer")]
                    )
                    item.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {"kind": "layer", "id": layer_id},
                    )
                    self.composer_layer_stack.addTopLevelItem(item)
                    if layer_id in selected_layer_ids:
                        item.setSelected(True)
                    index += 1
                    continue

                group_id = group.get("id")
                run = []
                cursor = index
                while cursor < len(self._composer_layers):
                    candidate = self._composer_layers[cursor]
                    if (
                        candidate.get("_authoring_id")
                        not in group.get("members", ())
                    ):
                        break
                    run.append(candidate)
                    cursor += 1

                occurrence[group_id] = occurrence.get(group_id, 0) + 1
                continued = (
                    ""
                    if occurrence[group_id] == 1
                    else " (continued)"
                )
                disabled = (
                    ""
                    if group.get("enabled", True)
                    else " (disabled)"
                )
                node = QTreeWidgetItem(
                    [
                        f"{group.get('name', group_id)}"
                        f"{continued}{disabled}"
                    ]
                )
                node.setData(
                    0,
                    Qt.ItemDataRole.UserRole,
                    {"kind": "group", "id": group_id},
                )
                self.composer_layer_stack.addTopLevelItem(node)
                node.setExpanded(
                    group_id in expanded
                    or group_id == selected_group_id
                    or not expanded
                )
                if group_id == selected_group_id:
                    node.setSelected(True)

                for child_layer in run:
                    child_id = child_layer.get("_authoring_id")
                    child = QTreeWidgetItem(
                        [child_layer.get("kind", "Layer")]
                    )
                    child.setData(
                        0,
                        Qt.ItemDataRole.UserRole,
                        {"kind": "layer", "id": child_id},
                    )
                    node.addChild(child)
                    if child_id in selected_layer_ids:
                        child.setSelected(True)
                index = cursor
        finally:
            self.composer_layer_stack.blockSignals(False)
            self._composer_stack_syncing = False

    def _composer_tree_items(self):
        items = []

        def visit(item):
            items.append(item)
            for child_index in range(item.childCount()):
                visit(item.child(child_index))

        for top_index in range(
            self.composer_layer_stack.topLevelItemCount()
        ):
            visit(self.composer_layer_stack.topLevelItem(top_index))
        return items

    def _composer_stack_layer_rows(self):
        id_to_row = {
            layer.get("_authoring_id"): row
            for row, layer in enumerate(self._composer_layers)
        }
        rows = []
        for item in self.composer_layer_stack.selectedItems():
            data = item.data(0, Qt.ItemDataRole.UserRole)
            if (
                not isinstance(data, dict)
                or data.get("kind") != "layer"
            ):
                continue
            row = id_to_row.get(data.get("id"))
            if row is not None:
                rows.append(row)
        return sorted(set(rows))

    def _composer_selected_layer_rows(self):
        if hasattr(self, "composer_layer_stack"):
            rows = self._composer_stack_layer_rows()
            if rows:
                return rows
        rows = sorted(
            {
                index.row()
                for index in self.composer_layers.selectedIndexes()
                if 0 <= index.row() < len(self._composer_layers)
            }
        )
        if (
            not rows
            and 0 <= self.composer_layers.currentRow()
            < len(self._composer_layers)
        ):
            rows = [self.composer_layers.currentRow()]
        return rows

    def _composer_stack_selection_changed(self):
        if self._composer_stack_syncing:
            return

        rows = self._composer_stack_layer_rows()
        self._composer_stack_syncing = True
        try:
            self.composer_layers.blockSignals(True)
            self.composer_layers.clearSelection()
            if rows:
                self.composer_layers.setCurrentRow(rows[0])
                for row in rows:
                    item = self.composer_layers.item(row)
                    if item is not None:
                        item.setSelected(True)
            self.composer_layers.blockSignals(False)

            group_ids = []
            for item in self.composer_layer_stack.selectedItems():
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if (
                    isinstance(data, dict)
                    and data.get("kind") == "group"
                ):
                    group_ids.append(data.get("id"))
            if group_ids:
                for group_row in range(self.composer_groups.count()):
                    item = self.composer_groups.item(group_row)
                    if (
                        item is not None
                        and item.data(Qt.ItemDataRole.UserRole)
                        == group_ids[0]
                    ):
                        self.composer_groups.setCurrentRow(group_row)
                        break
        finally:
            self._composer_stack_syncing = False

        if rows:
            self._composer_select_layer(rows[0])
        self._composer_refresh_bulk_editor()

    def _composer_stack_current_changed(self, current, previous):
        if self._composer_stack_syncing or current is None:
            return
        data = current.data(0, Qt.ItemDataRole.UserRole)
        if (
            not isinstance(data, dict)
            or data.get("kind") != "group"
        ):
            return
        target = data.get("id")
        for group_row in range(self.composer_groups.count()):
            item = self.composer_groups.item(group_row)
            if (
                item is not None
                and item.data(Qt.ItemDataRole.UserRole) == target
            ):
                self.composer_groups.setCurrentRow(group_row)
                break

    @staticmethod
    def _composer_common_value(layers, key, default=None):
        if not layers:
            return False, default
        values = [layer.get(key, default) for layer in layers]
        first = values[0]
        return all(value == first for value in values), first

    def _composer_bulk_mark_dirty(self, key):
        if self._composer_bulk_updating:
            return
        self._composer_bulk_dirty.add(str(key))

    def _composer_refresh_bulk_region_combo(self):
        current = self.composer_bulk_region.currentData()
        self.composer_bulk_region.blockSignals(True)
        try:
            self.composer_bulk_region.clear()
            self.composer_bulk_region.addItem("Mixed", "__mixed__")
            self.composer_bulk_region.addItem("Entire Target", None)
            for name in sorted(self._composer_regions):
                self.composer_bulk_region.addItem(name, name)
            index = self.composer_bulk_region.findData(current)
            self.composer_bulk_region.setCurrentIndex(
                index if index >= 0 else 0
            )
        finally:
            self.composer_bulk_region.blockSignals(False)

    def _composer_update_multiselect_controls(self, count):
        multi = count > 1
        # Existing inspector writes through current-row semantics.
        # During multi-selection, shared fields move to the bulk editor and
        # type-specific fields are disabled rather than guessing.
        for widget in (
            self.composer_opacity,
            self.composer_layer_region,
            self.composer_layer_delay,
            self.composer_layer_speed_multiplier,
            self.composer_colour_mode,
            self.composer_motion_mode,
            self.composer_colour_button,
            self.composer_colour2_button,
            self.composer_row,
            self.composer_column,
            self.composer_direction,
            self.composer_duration,
            self.composer_layer_timeline_duration,
            self.composer_layer_playback,
            self.composer_layer_phase,
            self.composer_layer_fade_in,
            self.composer_layer_fade_out,
            self.composer_motion_direction,
            self.composer_motion_start_kind,
            self.composer_motion_end_kind,
            self.composer_motion_start_row,
            self.composer_motion_start_column,
            self.composer_motion_end_row,
            self.composer_motion_end_column,
            self.composer_motion_start_cell_row,
            self.composer_motion_start_cell_column,
            self.composer_motion_end_cell_row,
            self.composer_motion_end_cell_column,
        ):
            widget.setEnabled(not multi)

    def _composer_refresh_bulk_editor(self):
        if not hasattr(self, "composer_bulk_summary"):
            return

        rows = self._composer_selected_layer_rows()
        layers = [
            self._composer_layers[row]
            for row in rows
            if 0 <= row < len(self._composer_layers)
        ]
        count = len(layers)

        self._composer_bulk_updating = True
        try:
            self._composer_bulk_dirty.clear()
            self._composer_refresh_bulk_region_combo()
            self.composer_bulk_summary.setText(
                (
                    f"{count} selected layers"
                    if count > 1
                    else "Select two or more layers for bulk editing"
                )
            )
            enabled = count > 1
            for widget in (
                self.composer_bulk_opacity,
                self.composer_bulk_region,
                self.composer_bulk_delay,
                self.composer_bulk_speed,
                self.composer_bulk_colour_mode,
                self.composer_bulk_motion_mode,
                self.composer_bulk_apply,
            ):
                widget.setEnabled(enabled)

            self._composer_update_multiselect_controls(count)

            if not enabled:
                self.composer_bulk_opacity.clear()
                self.composer_bulk_delay.clear()
                self.composer_bulk_speed.clear()
                self.composer_bulk_region.setCurrentIndex(0)
                self.composer_bulk_colour_mode.setCurrentIndex(0)
                self.composer_bulk_motion_mode.setCurrentIndex(0)
                return

            common, value = self._composer_common_value(
                layers,
                "opacity",
                1.0,
            )
            self.composer_bulk_opacity.setText(
                f"{float(value):.4g}" if common else ""
            )

            common, value = self._composer_common_value(
                layers,
                "timeline_delay",
                0.0,
            )
            self.composer_bulk_delay.setText(
                f"{float(value):.4g}" if common else ""
            )

            common, value = self._composer_common_value(
                layers,
                "speed_multiplier",
                1.0,
            )
            self.composer_bulk_speed.setText(
                f"{float(value):.4g}" if common else ""
            )

            common, value = self._composer_common_value(
                layers,
                "region",
                None,
            )
            index = (
                self.composer_bulk_region.findData(value)
                if common
                else 0
            )
            self.composer_bulk_region.setCurrentIndex(
                index if index >= 0 else 0
            )

            common, value = self._composer_common_value(
                layers,
                "colour_mode",
                "static",
            )
            index = (
                self.composer_bulk_colour_mode.findData(value)
                if common
                else 0
            )
            self.composer_bulk_colour_mode.setCurrentIndex(
                index if index >= 0 else 0
            )

            common, value = self._composer_common_value(
                layers,
                "motion_mode",
                "none",
            )
            index = (
                self.composer_bulk_motion_mode.findData(value)
                if common
                else 0
            )
            self.composer_bulk_motion_mode.setCurrentIndex(
                index if index >= 0 else 0
            )
        finally:
            self._composer_bulk_updating = False

    def _composer_bulk_apply_changes(self):
        rows = self._composer_selected_layer_rows()
        if len(rows) < 2 or not self._composer_bulk_dirty:
            return

        changes = {}
        try:
            if "opacity" in self._composer_bulk_dirty:
                value = float(self.composer_bulk_opacity.text())
                if not 0.0 <= value <= 1.0:
                    raise ValueError(
                        "Opacity must be between 0 and 1."
                    )
                changes["opacity"] = value

            if "timeline_delay" in self._composer_bulk_dirty:
                changes["timeline_delay"] = float(
                    self.composer_bulk_delay.text()
                )

            if "speed_multiplier" in self._composer_bulk_dirty:
                value = float(self.composer_bulk_speed.text())
                if value <= 0.0:
                    raise ValueError(
                        "Speed multiplier must be greater than zero."
                    )
                changes["speed_multiplier"] = value

            if "region" in self._composer_bulk_dirty:
                value = self.composer_bulk_region.currentData()
                if value != "__mixed__":
                    changes["region"] = value

            if "colour_mode" in self._composer_bulk_dirty:
                value = self.composer_bulk_colour_mode.currentData()
                if value != "__mixed__":
                    changes["colour_mode"] = value

            if "motion_mode" in self._composer_bulk_dirty:
                value = self.composer_bulk_motion_mode.currentData()
                if value != "__mixed__":
                    changes["motion_mode"] = value
        except Exception as exc:
            self.status_label.setText(
                "Bulk edit refused safely: "
                f"{type(exc).__name__}: {exc}"
            )
            return

        if not changes:
            return

        selected_ids = {
            self._composer_layers[row].get("_authoring_id")
            for row in rows
            if 0 <= row < len(self._composer_layers)
        }

        self._composer_history_checkpoint()
        for row in rows:
            if 0 <= row < len(self._composer_layers):
                for key, value in changes.items():
                    self._composer_layers[row][key] = copy.deepcopy(
                        value
                    )

        self._composer_sync_active_model_into_targets()
        self._composer_rebuild_layer_list()
        self._composer_refresh_group_controls()
        self._composer_refresh()
        self._composer_invalidate_validation()

        self._composer_rebuild_visual_stack()
        self._composer_stack_syncing = True
        self.composer_layer_stack.blockSignals(True)
        try:
            self.composer_layer_stack.clearSelection()
            for item in self._composer_tree_items():
                data = item.data(0, Qt.ItemDataRole.UserRole)
                if (
                    isinstance(data, dict)
                    and data.get("kind") == "layer"
                    and data.get("id") in selected_ids
                ):
                    item.setSelected(True)
        finally:
            self.composer_layer_stack.blockSignals(False)
            self._composer_stack_syncing = False

        self._composer_stack_selection_changed()
        self.status_label.setText(
            f"Bulk edit applied to {len(rows)} layers."
        )

    def _composer_rebuild_layer_list(self):
        self.composer_layers.blockSignals(True)
        self.composer_layers.clear()
        for layer in self._composer_layers:
            self.composer_layers.addItem(
                QListWidgetItem(layer["kind"])
            )
        self.composer_layers.blockSignals(False)

        if self.composer_layers.count():
            self.composer_layers.setCurrentRow(0)
        else:
            self.composer_kind.setText("No layer selected")

        self._composer_rebuild_visual_stack()
        self._composer_refresh_bulk_editor()

    def _composer_target_payload(self):
        payload = self.composer_target_combo.currentData()
        if isinstance(payload, dict):
            result = dict(payload)
            if result.get("custom"):
                result["rows"] = self.composer_rows.value()
                result["columns"] = self.composer_columns.value()
                result["device_class"] = (
                    self._composer_current_device_class
                    or self._composer_normalize_device_class(
                        self.composer_device_class_combo.currentText()
                    )
                    or None
                )
            return result
        return {}

    def _composer_is_custom_target(self):
        return bool(
            self._composer_target_payload().get("custom")
        )

    def _composer_active_geometry(self):
        payload = self._composer_target_payload()

        if payload.get("custom"):
            rows = self.composer_rows.value()
            columns = self.composer_columns.value()
            active = [
                (row, column)
                for row in range(rows)
                for column in range(columns)
            ]
            return rows, columns, active

        rows = max(1, int(payload.get("rows", 1)))
        columns = max(1, int(payload.get("columns", 1)))
        raw_active = payload.get("active_cells")
        if not raw_active:
            raw_active = [
                [row, column]
                for row in range(rows)
                for column in range(columns)
            ]

        active = [
            (int(row), int(column))
            for row, column in raw_active
            if (
                0 <= int(row) < rows
                and 0 <= int(column) < columns
            )
        ]
        return rows, columns, active

    def _composer_target_changed(self, *args):
        custom = self._composer_is_custom_target()
        self.composer_rows.setEnabled(custom)
        self.composer_columns.setEnabled(custom)

        if not custom:
            payload = self._composer_target_payload()
            self._composer_updating = True
            try:
                self.composer_rows.setValue(
                    max(1, int(payload.get("rows", 1)))
                )
                self.composer_columns.setValue(
                    max(1, int(payload.get("columns", 1)))
                )
            finally:
                self._composer_updating = False

        if self._composer_current_device_class:
            self._composer_target_geometries[
                self._composer_current_device_class
            ] = self._composer_target_payload()

        self._composer_apply_geometry()

    def _composer_custom_geometry_changed(self, *args):
        if self._composer_updating:
            return
        if self._composer_is_custom_target():
            if self._composer_current_device_class:
                self._composer_target_geometries[
                    self._composer_current_device_class
                ] = self._composer_target_payload()
            self._composer_apply_geometry()

    def _composer_apply_geometry(self):
        rows, columns, active = self._composer_active_geometry()

        self.composer_matrix.set_geometry(
            rows,
            columns,
            active,
        )

        self.composer_row.setMaximum(max(0, rows - 1))
        self.composer_column.setMaximum(
            max(0, columns - 1)
        )
        self.composer_trigger_row.setMaximum(max(0, rows - 1))
        self.composer_trigger_column.setMaximum(max(0, columns - 1))
        for widget in (
            self.composer_motion_start_cell_row,
            self.composer_motion_end_cell_row,
            self.composer_trigger_motion_start_cell_row,
            self.composer_trigger_motion_end_cell_row,
        ):
            widget.setMaximum(max(0, rows - 1))
        for widget in (
            self.composer_motion_start_cell_column,
            self.composer_motion_end_cell_column,
            self.composer_trigger_motion_start_cell_column,
            self.composer_trigger_motion_end_cell_column,
        ):
            widget.setMaximum(max(0, columns - 1))

        active_set = set(active)
        fallback = (
            min(active_set)
            if active_set
            else (0, 0)
        )

        self._composer_region_selection.intersection_update(
            active_set
        )
        self.composer_matrix.set_region_selection(
            self._composer_region_selection
        )
        for name, cells in list(self._composer_regions.items()):
            self._composer_regions[name] = tuple(
                cell for cell in cells if cell in active_set
            )
        if self._composer_current_device_class:
            self._composer_target_regions[
                self._composer_current_device_class
            ] = self._composer_regions
            self._composer_target_region_selections[
                self._composer_current_device_class
            ] = set(self._composer_region_selection)

        for layer in self._composer_layers:
            if layer["kind"] != "Cell":
                continue

            cell = (
                int(layer.get("row", 0)),
                int(layer.get("column", 0)),
            )
            if cell not in active_set:
                layer["row"], layer["column"] = fallback

        current = self.composer_layers.currentRow()
        if 0 <= current < len(self._composer_layers):
            self._composer_select_layer(current)

        self._composer_refresh_region_controls()
        self._composer_refresh()

    @staticmethod
    def _composer_timeline_state(
        *,
        elapsed,
        delay,
        duration,
        playback,
        phase_offset,
        fade_in,
        fade_out,
        speed_multiplier,
    ):
        duration = max(0.05, float(duration))
        delay = max(0.0, float(delay))
        speed_multiplier = max(0.05, float(speed_multiplier))
        local = float(elapsed) * speed_multiplier - delay
        if local < 0.0:
            return False, local, 0.0, 0.0
        if playback == "loop":
            phase = (local / duration) % 1.0
        elif playback == "ping-pong":
            cycle = (local / duration) % 2.0
            phase = cycle if cycle <= 1.0 else 2.0 - cycle
        else:
            if local > duration:
                return False, local, 1.0, 0.0
            phase = min(1.0, local / duration)
        phase = (phase + float(phase_offset)) % 1.0
        envelope = 1.0
        fade_in = max(0.0, float(fade_in))
        fade_out = max(0.0, float(fade_out))
        if fade_in > 0.0:
            envelope = min(envelope, local / fade_in)
        if playback == "once" and fade_out > 0.0:
            envelope = min(envelope, max(0.0, (duration - local) / fade_out))
        return True, local, phase, max(0.0, min(1.0, envelope))

    def _composer_timeline_play_clicked(self):
        self._composer_preview_playing = True
        if not self.composer_timeline_timer.isActive():
            self.composer_timeline_timer.start()

    def _composer_timeline_pause_clicked(self):
        self._composer_preview_playing = False
        self.composer_timeline_timer.stop()

    def _composer_timeline_reset_clicked(self):
        self._composer_preview_playing = False
        self.composer_timeline_timer.stop()
        self._composer_preview_time = 0.0
        self._composer_updating = True
        try:
            self.composer_time.setValue(0.0)
        finally:
            self._composer_updating = False
        self._composer_update_timeline_widgets()
        self._composer_refresh()

    def _composer_timeline_tick(self):
        if not self._composer_preview_playing:
            return
        self._composer_preview_time += 0.05
        if self._composer_preview_time > self.composer_time.maximum():
            self._composer_preview_time = 0.0
        self._composer_updating = True
        try:
            self.composer_time.setValue(self._composer_preview_time)
        finally:
            self._composer_updating = False
        self._composer_update_timeline_widgets()
        self._composer_refresh()

    def _composer_timeline_scrub_changed(self, value):
        if self._composer_updating:
            return
        self._composer_preview_playing = False
        self.composer_timeline_timer.stop()
        self._composer_preview_time = float(value)
        self._composer_update_timeline_widgets()
        self._composer_refresh()

    def _composer_update_timeline_widgets(self):
        maximum = max(0.01, self.composer_time.maximum())
        progress = round(1000.0 * min(1.0, self._composer_preview_time / maximum))
        self.composer_timeline_progress.setValue(int(progress))
        self.composer_timeline_progress.setFormat(f"{self._composer_preview_time:.2f} s")
        row = self.composer_layers.currentRow()
        if 0 <= row < len(self._composer_layers):
            layer = self._composer_layers[row]
            active, local, phase, envelope = self._composer_timeline_state(
                elapsed=self._composer_preview_time,
                delay=layer.get("timeline_delay", 0.0),
                duration=layer.get("timeline_duration", 2.0),
                playback=layer.get("playback", "once"),
                phase_offset=layer.get("phase_offset", 0.0),
                fade_in=layer.get("fade_in", 0.0),
                fade_out=layer.get("fade_out", 0.0),
                speed_multiplier=layer.get("speed_multiplier", 1.0),
            )
            self.composer_layer_timeline_bar.setValue(int(round(1000.0 * phase)) if active else 0)
            self.composer_layer_timeline_bar.setFormat(
                f"phase {phase:.2f} · envelope {envelope:.2f}" if active else "inactive"
            )
        trigger_row = self.composer_trigger_list.currentRow()
        if 0 <= trigger_row < len(self._composer_triggers):
            trigger = self._composer_triggers[trigger_row]
            active, local, phase, envelope = self._composer_timeline_state(
                elapsed=self._composer_preview_time,
                delay=trigger.get("delay", 0.0),
                duration=trigger.get("duration", 0.6),
                playback=trigger.get("playback", "once"),
                phase_offset=trigger.get("phase_offset", 0.0),
                fade_in=trigger.get("fade_in", 0.0),
                fade_out=trigger.get("fade_out", 0.0),
                speed_multiplier=trigger.get("speed_multiplier", 1.0),
            )
            self.composer_trigger_timeline_bar.setValue(int(round(1000.0 * phase)) if active else 0)
            self.composer_trigger_timeline_bar.setFormat(
                f"phase {phase:.2f} · envelope {envelope:.2f}" if active else "inactive"
            )

    def _composer_region_edit_toggled(self, enabled):
        self.composer_matrix.set_region_editing(enabled)
        if enabled:
            self.composer_matrix.set_region_selection(
                self._composer_region_selection
            )

    def _composer_region_mode_changed(self, *args):
        self.composer_matrix.set_region_selection_mode(
            self.composer_region_mode.currentData() or "add"
        )

    def _composer_region_selection_changed(self, cells):
        self._composer_region_selection = set(cells)
        if self._composer_current_device_class:
            self._composer_target_region_selections[
                self._composer_current_device_class
            ] = set(self._composer_region_selection)

    def _composer_region_select_all_cells(self):
        self._composer_region_selection = set(
            self.composer_matrix.active_cells
        )
        self.composer_matrix.set_region_selection(
            self._composer_region_selection
        )

    def _composer_region_clear_selection(self):
        self._composer_region_selection.clear()
        self.composer_matrix.set_region_selection(())

    def _composer_region_invert_selection(self):
        self._composer_region_selection = (
            set(self.composer_matrix.active_cells)
            - set(self._composer_region_selection)
        )
        self.composer_matrix.set_region_selection(
            self._composer_region_selection
        )

    def _composer_region_create(self):
        self._composer_history_checkpoint()
        name = self.composer_region_name.text().strip()
        if not name:
            self.status_label.setText("Region name is required.")
            return
        if name in self._composer_regions:
            self.status_label.setText(
                f"Region already exists: {name}"
            )
            return
        if not self._composer_region_selection:
            self.status_label.setText(
                "Select at least one active cell first."
            )
            return
        self._composer_regions[name] = tuple(
            sorted(self._composer_region_selection)
        )
        self._composer_refresh_region_controls(select_name=name)
        self._composer_refresh()

    def _composer_region_rename_selected(self):
        item = self.composer_region_list.currentItem()
        if item is None:
            return
        old_name = item.text()
        new_name = self.composer_region_name.text().strip()
        if not new_name:
            return
        if new_name != old_name and new_name in self._composer_regions:
            self.status_label.setText(
                f"Region already exists: {new_name}"
            )
            return
        cells = self._composer_regions.pop(old_name, ())
        self._composer_regions[new_name] = cells
        for layer in self._composer_layers:
            if layer.get("region") == old_name:
                layer["region"] = new_name
            if layer.get("motion_start_region") == old_name:
                layer["motion_start_region"] = new_name
            if layer.get("motion_end_region") == old_name:
                layer["motion_end_region"] = new_name
        for trigger in self._composer_triggers:
            if trigger.get("region") == old_name:
                trigger["region"] = new_name
            if trigger.get("motion_start_region") == old_name:
                trigger["motion_start_region"] = new_name
            if trigger.get("motion_end_region") == old_name:
                trigger["motion_end_region"] = new_name
        self._composer_refresh_region_controls(select_name=new_name)
        self._composer_refresh()

    def _composer_region_delete_selected(self):
        item = self.composer_region_list.currentItem()
        if item is not None:
            self._composer_history_checkpoint()
        if item is None:
            return
        name = item.text()
        self._composer_regions.pop(name, None)
        for layer in self._composer_layers:
            if layer.get("region") == name:
                layer["region"] = None
            if layer.get("motion_start_region") == name:
                layer["motion_start_region"] = None
            if layer.get("motion_end_region") == name:
                layer["motion_end_region"] = None
        for trigger in self._composer_triggers:
            if trigger.get("region") == name:
                trigger["region"] = None
            if trigger.get("motion_start_region") == name:
                trigger["motion_start_region"] = None
            if trigger.get("motion_end_region") == name:
                trigger["motion_end_region"] = None
        self._composer_refresh_region_controls()
        self._composer_refresh()

    def _composer_region_list_selected(self, row):
        if not (0 <= row < self.composer_region_list.count()):
            return
        name = self.composer_region_list.item(row).text()
        self.composer_region_name.setText(name)
        self._composer_region_selection = set(
            self._composer_regions.get(name, ())
        )
        self.composer_matrix.set_region_selection(
            self._composer_region_selection
        )

    def _composer_refresh_region_controls(self, *, select_name=None):
        selected = select_name
        if selected is None and self.composer_region_list.currentItem():
            selected = self.composer_region_list.currentItem().text()

        self.composer_region_list.blockSignals(True)
        self.composer_region_list.clear()
        for name in sorted(self._composer_regions):
            self.composer_region_list.addItem(name)
        self.composer_region_list.blockSignals(False)

        if selected:
            matches = self.composer_region_list.findItems(
                selected,
                Qt.MatchFlag.MatchExactly,
            )
            if matches:
                self.composer_region_list.setCurrentItem(matches[0])

        for combo in (
            self.composer_layer_region,
            self.composer_trigger_region,
            self.composer_motion_start_region,
            self.composer_motion_end_region,
            self.composer_trigger_motion_start_region,
            self.composer_trigger_motion_end_region,
        ):
            current = combo.currentData()
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("Entire Target", None)
            for name in sorted(self._composer_regions):
                combo.addItem(name, name)
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else 0)
            combo.blockSignals(False)

        self.composer_matrix.set_region_selection(
            self._composer_region_selection
        )
        self._composer_region_mode_changed()
        self._composer_refresh_group_region_combo()
        if hasattr(self, "composer_bulk_region"):
            self._composer_refresh_bulk_region_combo()


    def _composer_default_layer(self, kind):
        return {
            "kind": kind,
            "colour": (80, 120, 255),
            "colour2": (255, 80, 160),
            "opacity": 1.0,
            "row": 2,
            "column": 10,
            "direction": "Horizontal",
            "duration": 1.5,
            "timeline_delay": 0.0,
            "timeline_duration": 2.0,
            "playback": "once",
            "phase_offset": 0.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "speed_multiplier": 1.0,
            "motion_mode": "none",
            "motion_direction": "left-to-right",
            "motion_start_kind": "normalized",
            "motion_start_row": 0.5,
            "motion_start_column": 0.0,
            "motion_start_cell_row": 0,
            "motion_start_cell_column": 0,
            "motion_start_region": None,
            "motion_end_kind": "normalized",
            "motion_end_row": 0.5,
            "motion_end_column": 1.0,
            "motion_end_cell_row": 0,
            "motion_end_cell_column": 0,
            "motion_end_region": None,
            "motion_head_width": 0.08,
            "motion_trail": 0.20,
            "colour_mode": "static",
            "palette_stops": [
                (0.0, (80, 120, 255)),
                (1.0, (255, 80, 160)),
            ],
            "spatial_palette": False,
            "region": None,
        }

    @staticmethod
    def _composer_preset_slug(value):
        value = "".join(
            char.lower() if char.isalnum() else "-"
            for char in str(value)
        )
        while "--" in value:
            value = value.replace("--", "-")
        return value.strip("-") or "preset"

    @staticmethod
    def _composer_preset_json_safe(value):
        if isinstance(value, dict):
            return {
                str(key): EffectsWorkshopPanel._composer_preset_json_safe(item)
                for key, item in value.items()
            }
        if isinstance(value, (list, tuple, set)):
            return [
                EffectsWorkshopPanel._composer_preset_json_safe(item)
                for item in value
            ]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        raise TypeError(
            f"Preset metadata contains unsupported type: {type(value).__name__}"
        )

    @staticmethod
    def _composer_preset_validate_envelope(data):
        if not isinstance(data, dict):
            raise ValueError("Preset must be a JSON object.")
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported preset schema_version.")
        if data.get("kind") not in {"layer", "group", "trigger", "composition"}:
            raise ValueError("Unknown preset kind.")
        if not isinstance(data.get("name"), str) or not data["name"].strip():
            raise ValueError("Preset name is required.")
        if not isinstance(data.get("payload"), dict):
            raise ValueError("Preset payload must be an object.")
        targets = data.get("target_classes", [])
        if not isinstance(targets, list) or not all(isinstance(item, str) for item in targets):
            raise ValueError("target_classes must contain strings.")
        return data

    def _composer_preset_payload(self, kind):
        self._composer_ensure_layer_ids()
        if kind == "layer":
            row = self.composer_layers.currentRow()
            if not (0 <= row < len(self._composer_layers)):
                raise ValueError("Select a layer first.")
            layer = dict(self._composer_layers[row])
            layer.pop("_authoring_id", None)
            layer.pop("_group_id", None)
            return {"layers": [layer]}
        if kind == "group":
            item = self.composer_groups.currentItem()
            if item is None:
                raise ValueError("Select a group first.")
            group = self._composer_group_by_id(item.data(Qt.ItemDataRole.UserRole))
            if group is None:
                raise ValueError("Selected group is unavailable.")
            ids = list(group.get("members", ()))
            layers = []
            member_positions = []
            for layer in self._composer_layers:
                if layer.get("_authoring_id") in ids:
                    copy = dict(layer)
                    copy.pop("_authoring_id", None)
                    copy.pop("_group_id", None)
                    member_positions.append(len(layers))
                    layers.append(copy)
            group_copy = dict(group)
            group_copy["members"] = member_positions
            return {"group": group_copy, "layers": layers}
        if kind == "trigger":
            row = self.composer_trigger_list.currentRow()
            if not (0 <= row < len(self._composer_triggers)):
                raise ValueError("Select a trigger first.")
            return {"triggers": [dict(self._composer_triggers[row])]}
        if kind == "composition":
            if self._composer_current_device_class:
                self._composer_target_layers[self._composer_current_device_class] = self._composer_layers
                self._composer_target_groups[self._composer_current_device_class] = self._composer_groups
                self._composer_target_regions[self._composer_current_device_class] = self._composer_regions
                self._composer_target_geometries[self._composer_current_device_class] = self._composer_target_payload()
            return {
                "target_layers": {
                    key: [dict(layer) for layer in layers]
                    for key, layers in self._composer_target_layers.items()
                },
                "target_groups": {
                    key: [dict(group) for group in groups]
                    for key, groups in self._composer_target_groups.items()
                },
                "target_regions": {
                    key: {
                        name: list(cells)
                        for name, cells in regions.items()
                    }
                    for key, regions in self._composer_target_regions.items()
                },
                "target_geometries": {
                    key: dict(value)
                    for key, value in self._composer_target_geometries.items()
                },
                "triggers": [dict(trigger) for trigger in self._composer_triggers],
                "intent": self.composer_intent_combo.currentData(),
            }
        raise ValueError("Unsupported preset kind.")

    def _composer_preset_save(self, kind):
        try:
            name = self.composer_preset_name.text().strip() or f"{kind.title()} Preset"
            target_classes = (
                sorted(self._composer_target_layers)
                if kind == "composition"
                else [self._composer_current_device_class or "keyboard"]
            )
            envelope = {
                "schema_version": 1,
                "kind": kind,
                "name": name,
                "description": self.composer_preset_description.text().strip(),
                "target_classes": target_classes,
                "payload": self._composer_preset_json_safe(
                    self._composer_preset_payload(kind)
                ),
            }
            self._composer_preset_directory.mkdir(parents=True, exist_ok=True)
            base = self._composer_preset_slug(name)
            path = self._composer_preset_directory / f"{base}.json"
            suffix = 2
            while path.exists():
                path = self._composer_preset_directory / f"{base}-{suffix}.json"
                suffix += 1
            path.write_text(
                json.dumps(envelope, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            self.status_label.setText(f"Preset saved: {path.name}")
            self._composer_preset_refresh_library()
        except Exception as exc:
            self.status_label.setText(
                f"Preset save failed safely: {type(exc).__name__}: {exc}"
            )

    def _composer_preset_read(self, path):
        return self._composer_preset_validate_envelope(
            json.loads(path.read_text(encoding="utf-8"))
        )

    def _composer_preset_refresh_library(self, *args):
        search = self.composer_preset_search.text().strip().casefold()
        kind_filter = self.composer_preset_kind.currentData()
        target_filter = self.composer_preset_target.text().strip().casefold()
        self.composer_preset_list.clear()
        if not self._composer_preset_directory.is_dir():
            return
        for path in sorted(self._composer_preset_directory.glob("*.json")):
            try:
                data = self._composer_preset_read(path)
            except Exception:
                continue
            text = (
                data.get("name", "") + " " + data.get("description", "")
            ).casefold()
            if search and search not in text:
                continue
            if kind_filter and data.get("kind") != kind_filter:
                continue
            targets = [
                str(item).casefold()
                for item in data.get("target_classes", ())
            ]
            if target_filter and not any(target_filter in item for item in targets):
                continue
            item = QListWidgetItem(
                f"{data['name']}  [{data['kind']}]"
            )
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.composer_preset_list.addItem(item)

    def _composer_validate_imported_layer(self, raw):
        layer = dict(raw)
        rows, columns, active = self._composer_active_geometry()
        active_set = set(active)
        if layer.get("kind") == "Cell":
            cell = (
                int(layer.get("row", 0)),
                int(layer.get("column", 0)),
            )
            if cell not in active_set:
                if not active_set:
                    raise ValueError("Destination target has no active cells.")
                layer["row"], layer["column"] = min(active_set)
        for key in (
            "region",
            "motion_start_region",
            "motion_end_region",
            "group_region",
        ):
            name = layer.get(key)
            if name and name not in self._composer_regions:
                raise ValueError(
                    f"Preset references missing named region: {name}"
                )
        return layer

    def _composer_preset_apply_selected(self):
        item = self.composer_preset_list.currentItem()
        if item is not None:
            self._composer_history_checkpoint()
        if item is None:
            return
        try:
            data = self._composer_preset_read(
                Path(item.data(Qt.ItemDataRole.UserRole))
            )
            kind = data["kind"]
            payload = data["payload"]
            if kind == "layer":
                for raw in payload.get("layers", ()):
                    layer = self._composer_validate_imported_layer(raw)
                    layer["_authoring_id"] = f"L{self._composer_layer_counter}"
                    self._composer_layer_counter += 1
                    self._composer_layers.append(layer)
            elif kind == "group":
                imported = []
                for raw in payload.get("layers", ()):
                    layer = self._composer_validate_imported_layer(raw)
                    layer["_authoring_id"] = f"L{self._composer_layer_counter}"
                    self._composer_layer_counter += 1
                    imported.append(layer)
                group = dict(payload.get("group", {}))
                group_id = f"G{self._composer_group_counter}"
                self._composer_group_counter += 1
                group["id"] = group_id
                indexes = [int(value) for value in group.get("members", ())]
                group["members"] = [
                    imported[index]["_authoring_id"]
                    for index in indexes
                    if 0 <= index < len(imported)
                ]
                for layer in imported:
                    if layer["_authoring_id"] in group["members"]:
                        layer["_group_id"] = group_id
                self._composer_layers.extend(imported)
                self._composer_groups.append(group)
            elif kind == "trigger":
                for raw in payload.get("triggers", ()):
                    trigger = dict(raw)
                    region = trigger.get("region")
                    if region and region not in self._composer_regions:
                        raise ValueError(
                            f"Preset references missing named region: {region}"
                        )
                    self._composer_triggers.append(trigger)
            elif kind == "composition":
                layers = payload.get("target_layers")
                if not isinstance(layers, dict) or not layers:
                    raise ValueError("Composition preset contains no target layers.")
                self._composer_target_layers = {
                    str(key): [dict(layer) for layer in value]
                    for key, value in layers.items()
                }
                self._composer_target_groups = {
                    str(key): [dict(group) for group in value]
                    for key, value in payload.get("target_groups", {}).items()
                }
                self._composer_target_regions = {
                    str(key): {
                        str(name): tuple(tuple(cell) for cell in cells)
                        for name, cells in value.items()
                    }
                    for key, value in payload.get("target_regions", {}).items()
                }
                self._composer_target_geometries = {
                    str(key): dict(value)
                    for key, value in payload.get("target_geometries", {}).items()
                }
                self._composer_target_region_selections = {
                    key: set() for key in self._composer_target_layers
                }
                self._composer_triggers = [
                    dict(trigger)
                    for trigger in payload.get("triggers", ())
                ]
                target = next(iter(self._composer_target_layers))
                self._composer_current_device_class = None
                self._composer_switch_target_model(target, create=False)
            self._composer_ensure_layer_ids()
            if self._composer_current_device_class:
                self._composer_target_layers[self._composer_current_device_class] = self._composer_layers
                self._composer_target_groups[self._composer_current_device_class] = self._composer_groups
            self._composer_rebuild_layer_list()
            self._composer_refresh_group_controls()
            self._composer_rebuild_trigger_list()
            self._composer_refresh()
            self.status_label.setText(f"Preset applied: {data['name']}")
        except Exception as exc:
            self.status_label.setText(
                f"Preset apply refused safely: {type(exc).__name__}: {exc}"
            )

    def _composer_preset_delete_selected(self):
        item = self.composer_preset_list.currentItem()
        if item is None:
            return
        try:
            path = Path(item.data(Qt.ItemDataRole.UserRole))
            path.unlink()
            self._composer_preset_refresh_library()
            self.status_label.setText(f"Preset deleted: {path.name}")
        except Exception as exc:
            self.status_label.setText(
                f"Preset delete failed safely: {type(exc).__name__}: {exc}"
            )

    def _composer_ensure_layer_ids(self):
        for layer in self._composer_layers:
            if "_authoring_id" not in layer:
                layer["_authoring_id"] = f"L{self._composer_layer_counter}"
                self._composer_layer_counter += 1

    def _composer_group_by_id(self, group_id):
        return next((group for group in self._composer_groups if group.get("id") == group_id), None)

    def _composer_refresh_group_region_combo(self):
        current = self.composer_group_region.currentData()
        self.composer_group_region.blockSignals(True)
        self.composer_group_region.clear()
        self.composer_group_region.addItem("Entire Target", None)
        for name in sorted(self._composer_regions):
            self.composer_group_region.addItem(name, name)
        index = self.composer_group_region.findData(current)
        if index >= 0:
            self.composer_group_region.setCurrentIndex(index)
        self.composer_group_region.blockSignals(False)

    def _composer_refresh_group_controls(self, select_id=None):
        self._composer_ensure_layer_ids()
        self.composer_groups.blockSignals(True)
        self.composer_groups.clear()
        selected = -1
        for index, group in enumerate(self._composer_groups):
            suffix = "" if group.get("enabled", True) else " (disabled)"
            item = QListWidgetItem(group.get("name", group["id"]) + suffix)
            item.setData(Qt.ItemDataRole.UserRole, group["id"])
            self.composer_groups.addItem(item)
            if group["id"] == select_id:
                selected = index
        self.composer_groups.blockSignals(False)
        self._composer_refresh_group_region_combo()
        if selected >= 0:
            self.composer_groups.setCurrentRow(selected)
        self._composer_rebuild_visual_stack()

    def _composer_group_selected(self, row):
        item = self.composer_groups.item(row)
        if item is None:
            return
        group = self._composer_group_by_id(item.data(Qt.ItemDataRole.UserRole))
        if group is None:
            return
        self._composer_updating = True
        try:
            self.composer_group_name.setText(group.get("name", group["id"]))
            index = self.composer_group_enabled.findData(bool(group.get("enabled", True)))
            self.composer_group_enabled.setCurrentIndex(index if index >= 0 else 0)
            self.composer_group_opacity.setValue(float(group.get("opacity", 1.0)))
            self.composer_group_timeline_offset.setValue(float(group.get("timeline_offset", 0.0)))
            self.composer_group_speed.setValue(float(group.get("speed_multiplier", 1.0)))
            self._composer_refresh_group_region_combo()
            index = self.composer_group_region.findData(group.get("region"))
            self.composer_group_region.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self._composer_updating = False


    def _composer_sync_active_model_into_targets(self):
        if not self._composer_current_device_class:
            return
        device_class = self._composer_current_device_class
        self._composer_target_layers[device_class] = self._composer_layers
        self._composer_target_groups[device_class] = self._composer_groups
        self._composer_target_regions[device_class] = self._composer_regions
        self._composer_target_region_selections[device_class] = set(
            self._composer_region_selection
        )
        self._composer_target_geometries[device_class] = self._composer_target_payload()

    def _composer_state_snapshot(self):
        self._composer_sync_active_model_into_targets()
        return {
            "intent": self.composer_intent_combo.currentData(),
            "active_device_class": self._composer_current_device_class,
            "target_layers": copy.deepcopy(self._composer_target_layers),
            "target_groups": copy.deepcopy(self._composer_target_groups),
            "target_regions": copy.deepcopy(self._composer_target_regions),
            "target_region_selections": copy.deepcopy(
                self._composer_target_region_selections
            ),
            "target_geometries": copy.deepcopy(self._composer_target_geometries),
            "triggers": copy.deepcopy(self._composer_triggers),
            "layer_counter": int(self._composer_layer_counter),
            "group_counter": int(self._composer_group_counter),
        }

    @staticmethod
    def _composer_state_key(snapshot):
        def normalise(value):
            if isinstance(value, dict):
                return {
                    str(key): normalise(item)
                    for key, item in sorted(
                        value.items(),
                        key=lambda pair: str(pair[0]),
                    )
                }
            if isinstance(value, set):
                return sorted(normalise(item) for item in value)
            if isinstance(value, tuple):
                return [normalise(item) for item in value]
            if isinstance(value, list):
                return [normalise(item) for item in value]
            return value
        return json.dumps(
            normalise(snapshot),
            sort_keys=True,
            separators=(",", ":"),
        )

    def _composer_history_checkpoint(self):
        if self._composer_history_restoring:
            return
        snapshot = self._composer_state_snapshot()
        key = self._composer_state_key(snapshot)
        if (
            not self._composer_history_undo
            or self._composer_state_key(self._composer_history_undo[-1]) != key
        ):
            self._composer_history_undo.append(snapshot)
            if len(self._composer_history_undo) > self._composer_history_limit:
                del self._composer_history_undo[
                    : len(self._composer_history_undo)
                    - self._composer_history_limit
                ]
        self._composer_history_redo.clear()
        self._composer_update_history_buttons()

    def _composer_invalidate_validation(self):
        self._validated_developer_source = None
        self._update_developer_workflow_state()

    def _composer_update_history_buttons(self):
        if hasattr(self, "composer_undo"):
            self.composer_undo.setEnabled(bool(self._composer_history_undo))
        if hasattr(self, "composer_redo"):
            self.composer_redo.setEnabled(bool(self._composer_history_redo))
        if hasattr(self, "composer_paste"):
            self.composer_paste.setEnabled(self._composer_clipboard is not None)

    def _composer_restore_state(self, snapshot):
        self._composer_history_restoring = True
        try:
            self._composer_target_layers = copy.deepcopy(
                snapshot["target_layers"]
            )
            self._composer_target_groups = copy.deepcopy(
                snapshot["target_groups"]
            )
            self._composer_target_regions = copy.deepcopy(
                snapshot["target_regions"]
            )
            self._composer_target_region_selections = copy.deepcopy(
                snapshot["target_region_selections"]
            )
            self._composer_target_geometries = copy.deepcopy(
                snapshot["target_geometries"]
            )
            self._composer_triggers = copy.deepcopy(snapshot["triggers"])
            self._composer_layer_counter = int(snapshot["layer_counter"])
            self._composer_group_counter = int(snapshot["group_counter"])

            intent = snapshot.get("intent")
            index = self.composer_intent_combo.findData(intent)
            if index >= 0:
                self._composer_updating = True
                try:
                    self.composer_intent_combo.setCurrentIndex(index)
                finally:
                    self._composer_updating = False

            target = snapshot.get("active_device_class")
            if target not in self._composer_target_layers:
                target = next(iter(self._composer_target_layers), None)

            self._composer_current_device_class = None
            if target is not None:
                self._composer_switch_target_model(target, create=False)
            else:
                self._composer_layers = []
                self._composer_groups = []
                self._composer_regions = {}
                self._composer_region_selection = set()
                self._composer_rebuild_layer_list()
                self._composer_refresh_group_controls()
                self._composer_refresh_region_controls()

            self._composer_rebuild_trigger_list()
            self._composer_refresh_sync_target_list()
            self._composer_refresh()
            self._composer_invalidate_validation()
        finally:
            self._composer_history_restoring = False
            self._composer_update_history_buttons()

    def _composer_undo(self):
        if not self._composer_history_undo:
            return
        current = self._composer_state_snapshot()
        previous = self._composer_history_undo.pop()
        self._composer_history_redo.append(current)
        self._composer_restore_state(previous)
        self.status_label.setText("Composer: Undo")

    def _composer_redo(self):
        if not self._composer_history_redo:
            return
        current = self._composer_state_snapshot()
        next_state = self._composer_history_redo.pop()
        self._composer_history_undo.append(current)
        if len(self._composer_history_undo) > self._composer_history_limit:
            del self._composer_history_undo[0]
        self._composer_restore_state(next_state)
        self.status_label.setText("Composer: Redo")

    def _composer_new_layer_id(self):
        value = f"L{self._composer_layer_counter}"
        self._composer_layer_counter += 1
        return value

    def _composer_new_group_id(self):
        value = f"G{self._composer_group_counter}"
        self._composer_group_counter += 1
        return value

    def _composer_duplicate_layer(self, row=None):
        if row is None:
            row = self.composer_layers.currentRow()
        if not (0 <= row < len(self._composer_layers)):
            return
        self._composer_history_checkpoint()
        original = self._composer_layers[row]
        duplicate = copy.deepcopy(original)
        old_id = original.get("_authoring_id")
        new_id = self._composer_new_layer_id()
        duplicate["_authoring_id"] = new_id
        self._composer_layers.insert(row + 1, duplicate)

        group_id = original.get("_group_id")
        if group_id:
            group = self._composer_group_by_id(group_id)
            if group is not None:
                members = list(group.get("members", ()))
                if old_id in members:
                    position = members.index(old_id) + 1
                    members.insert(position, new_id)
                    group["members"] = members

        self._composer_rebuild_layer_list()
        self.composer_layers.setCurrentRow(row + 1)
        self._composer_refresh_group_controls()
        self._composer_refresh()
        self._composer_invalidate_validation()

    def _composer_duplicate_group(self):
        item = self.composer_groups.currentItem()
        if item is None:
            return
        source_group = self._composer_group_by_id(
            item.data(Qt.ItemDataRole.UserRole)
        )
        if source_group is None:
            return
        self._composer_history_checkpoint()

        member_ids = list(source_group.get("members", ()))
        id_map = {}
        copied_layers = []
        source_positions = []
        for index, layer in enumerate(self._composer_layers):
            if layer.get("_authoring_id") not in member_ids:
                continue
            duplicate = copy.deepcopy(layer)
            old_id = duplicate.get("_authoring_id")
            new_id = self._composer_new_layer_id()
            id_map[old_id] = new_id
            duplicate["_authoring_id"] = new_id
            copied_layers.append(duplicate)
            source_positions.append(index)

        if not copied_layers:
            return

        new_group = copy.deepcopy(source_group)
        new_group_id = self._composer_new_group_id()
        new_group["id"] = new_group_id
        new_group["name"] = f"{source_group.get('name', 'Group')} Copy"
        new_group["members"] = [
            id_map[member]
            for member in member_ids
            if member in id_map
        ]
        for layer in copied_layers:
            layer["_group_id"] = new_group_id

        insert_at = max(source_positions) + 1
        self._composer_layers[insert_at:insert_at] = copied_layers
        self._composer_groups.append(new_group)
        self._composer_rebuild_layer_list()
        self._composer_refresh_group_controls(select_id=new_group_id)
        self._composer_refresh()
        self._composer_invalidate_validation()

    def _composer_duplicate_trigger(self):
        row = self.composer_trigger_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        self._composer_history_checkpoint()
        self._composer_triggers.insert(
            row + 1,
            copy.deepcopy(self._composer_triggers[row]),
        )
        self._composer_rebuild_trigger_list()
        self.composer_trigger_list.setCurrentRow(row + 1)
        self._composer_refresh_source_preview()
        self._composer_invalidate_validation()

    def _composer_duplicate_current(self):
        current = self.composer_layer_stack.currentItem()
        data = (
            current.data(0, Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        if (
            isinstance(data, dict)
            and data.get("kind") == "group"
        ):
            self._composer_duplicate_group()
        elif self.composer_groups.hasFocus() and self.composer_groups.currentItem():
            self._composer_duplicate_group()
        elif (
            self.composer_trigger_list.hasFocus()
            and self.composer_trigger_list.currentRow() >= 0
        ):
            self._composer_duplicate_trigger()
        else:
            self._composer_duplicate_layer()

    def _composer_copy_layers(self, rows=None):
        if rows is None:
            rows = self._composer_selected_layer_rows()
        layers = [
            copy.deepcopy(self._composer_layers[row])
            for row in rows
            if 0 <= row < len(self._composer_layers)
        ]
        if not layers:
            return
        self._composer_clipboard = {
            "kind": "layers",
            "layers": layers,
        }
        self._composer_update_history_buttons()

    def _composer_copy_group(self):
        item = self.composer_groups.currentItem()
        if item is None:
            return
        group = self._composer_group_by_id(
            item.data(Qt.ItemDataRole.UserRole)
        )
        if group is None:
            return
        member_ids = list(group.get("members", ()))
        layers = [
            copy.deepcopy(layer)
            for layer in self._composer_layers
            if layer.get("_authoring_id") in member_ids
        ]
        self._composer_clipboard = {
            "kind": "group",
            "group": copy.deepcopy(group),
            "layers": layers,
        }
        self._composer_update_history_buttons()

    def _composer_copy_trigger(self):
        row = self.composer_trigger_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        self._composer_clipboard = {
            "kind": "trigger",
            "triggers": [copy.deepcopy(self._composer_triggers[row])],
        }
        self._composer_update_history_buttons()

    def _composer_copy_current(self):
        current = self.composer_layer_stack.currentItem()
        data = (
            current.data(0, Qt.ItemDataRole.UserRole)
            if current is not None
            else None
        )
        if (
            isinstance(data, dict)
            and data.get("kind") == "group"
        ):
            self._composer_copy_group()
        elif self.composer_groups.hasFocus() and self.composer_groups.currentItem():
            self._composer_copy_group()
        elif (
            self.composer_trigger_list.hasFocus()
            and self.composer_trigger_list.currentRow() >= 0
        ):
            self._composer_copy_trigger()
        else:
            self._composer_copy_layers()

    def _composer_validate_pasted_trigger(self, raw):
        trigger = copy.deepcopy(raw)
        for key in (
            "region",
            "motion_start_region",
            "motion_end_region",
        ):
            name = trigger.get(key)
            if name and name not in self._composer_regions:
                raise ValueError(
                    f"Clipboard references missing named region: {name}"
                )
        return trigger

    def _composer_paste_clipboard(self):
        if not self._composer_clipboard:
            return
        payload = copy.deepcopy(self._composer_clipboard)
        try:
            kind = payload.get("kind")
            if kind == "layers":
                imported = []
                for raw in payload.get("layers", ()):
                    layer = self._composer_validate_imported_layer(raw)
                    layer["_authoring_id"] = self._composer_new_layer_id()
                    layer.pop("_group_id", None)
                    imported.append(layer)
                if not imported:
                    return
                self._composer_history_checkpoint()
                row = self.composer_layers.currentRow()
                insert_at = (
                    row + 1
                    if 0 <= row < len(self._composer_layers)
                    else len(self._composer_layers)
                )
                self._composer_layers[insert_at:insert_at] = imported

            elif kind == "group":
                raw_group = copy.deepcopy(payload.get("group", {}))
                source_layers = list(payload.get("layers", ()))
                validated = [
                    self._composer_validate_imported_layer(raw)
                    for raw in source_layers
                ]
                if not validated:
                    return
                self._composer_history_checkpoint()
                new_group_id = self._composer_new_group_id()
                id_map = {}
                imported = []
                for layer in validated:
                    old_id = layer.get("_authoring_id")
                    new_id = self._composer_new_layer_id()
                    id_map[old_id] = new_id
                    layer["_authoring_id"] = new_id
                    layer["_group_id"] = new_group_id
                    imported.append(layer)

                raw_group["id"] = new_group_id
                raw_group["name"] = (
                    f"{raw_group.get('name', 'Group')} Copy"
                )
                raw_group["members"] = [
                    id_map[member]
                    for member in raw_group.get("members", ())
                    if member in id_map
                ]
                row = self.composer_layers.currentRow()
                insert_at = (
                    row + 1
                    if 0 <= row < len(self._composer_layers)
                    else len(self._composer_layers)
                )
                self._composer_layers[insert_at:insert_at] = imported
                self._composer_groups.append(raw_group)

            elif kind == "trigger":
                imported = [
                    self._composer_validate_pasted_trigger(raw)
                    for raw in payload.get("triggers", ())
                ]
                if not imported:
                    return
                self._composer_history_checkpoint()
                self._composer_triggers.extend(imported)

            else:
                raise ValueError(f"Unsupported clipboard kind: {kind}")

            self._composer_ensure_layer_ids()
            self._composer_sync_active_model_into_targets()
            self._composer_rebuild_layer_list()
            self._composer_refresh_group_controls()
            self._composer_rebuild_trigger_list()
            self._composer_refresh()
            self._composer_invalidate_validation()
            self.status_label.setText("Composer clipboard pasted.")
        except Exception as exc:
            self.status_label.setText(
                "Composer paste refused safely: "
                f"{type(exc).__name__}: {exc}"
            )

    def _composer_group_create_from_selection(self):
        self._composer_history_checkpoint()
        self._composer_ensure_layer_ids()
        rows = self._composer_selected_layer_rows()
        if not rows:
            return
        group_id = f"G{self._composer_group_counter}"
        self._composer_group_counter += 1
        members = []
        for row in rows:
            layer = self._composer_layers[row]
            layer["_group_id"] = group_id
            members.append(layer["_authoring_id"])
        group = {"id": group_id, "name": f"Group {self._composer_group_counter - 1}", "enabled": True, "opacity": 1.0, "timeline_offset": 0.0, "speed_multiplier": 1.0, "region": None, "members": members}
        self._composer_groups.append(group)
        if self._composer_current_device_class:
            self._composer_target_groups[self._composer_current_device_class] = self._composer_groups
        self._composer_refresh_group_controls(select_id=group_id)
        self._composer_refresh()
        self._composer_invalidate_validation()

    def _composer_group_delete_selected(self):
        item = self.composer_groups.currentItem()
        if item is not None:
            self._composer_history_checkpoint()
        if item is None:
            return
        group_id = item.data(Qt.ItemDataRole.UserRole)
        self._composer_groups[:] = [group for group in self._composer_groups if group.get("id") != group_id]
        for layer in self._composer_layers:
            if layer.get("_group_id") == group_id:
                layer.pop("_group_id", None)
        self._composer_refresh_group_controls()
        self._composer_refresh()

    def _composer_group_move(self, delta):
        item = self.composer_groups.currentItem()
        if item is not None:
            self._composer_history_checkpoint()
        if item is None:
            return
        group_id = item.data(Qt.ItemDataRole.UserRole)
        member_layers = [layer for layer in self._composer_layers if layer.get("_group_id") == group_id]
        if not member_layers:
            return
        remainder = [layer for layer in self._composer_layers if layer.get("_group_id") != group_id]
        first = min(self._composer_layers.index(layer) for layer in member_layers)
        insert_at = max(0, min(len(remainder), first + int(delta)))
        self._composer_layers[:] = remainder[:insert_at] + member_layers + remainder[insert_at:]
        self._composer_rebuild_layer_list()
        self._composer_refresh_group_controls(select_id=group_id)
        self._composer_refresh()

    def _composer_group_property_changed(self, *args):
        if self._composer_updating:
            return
        self._composer_history_checkpoint()
        item = self.composer_groups.currentItem()
        if item is None:
            return
        group = self._composer_group_by_id(item.data(Qt.ItemDataRole.UserRole))
        if group is None:
            return
        group.update({"name": self.composer_group_name.text().strip() or group["id"], "enabled": bool(self.composer_group_enabled.currentData()), "opacity": self.composer_group_opacity.value(), "timeline_offset": self.composer_group_timeline_offset.value(), "speed_multiplier": self.composer_group_speed.value(), "region": self.composer_group_region.currentData()})
        self._composer_refresh_group_controls(select_id=group["id"])
        self._composer_refresh()

    @staticmethod
    def _composer_flatten_grouped_layers(layers, groups):
        group_map = {group.get("id"): group for group in groups}
        flattened = []
        for source in layers:
            layer = dict(source)
            group = group_map.get(layer.get("_group_id"))
            if group is not None:
                if not group.get("enabled", True):
                    continue
                layer["opacity"] = float(layer.get("opacity", 1.0)) * float(group.get("opacity", 1.0))
                layer["timeline_delay"] = float(layer.get("timeline_delay", 0.0)) + float(group.get("timeline_offset", 0.0))
                layer["speed_multiplier"] = float(layer.get("speed_multiplier", 1.0)) * float(group.get("speed_multiplier", 1.0))
                if group.get("region"):
                    layer["group_region"] = group["region"]
            layer.pop("_authoring_id", None)
            layer.pop("_group_id", None)
            flattened.append(layer)
        return flattened

    def _composer_add_layer(self, kind):
        self._composer_history_checkpoint()
        layer = self._composer_default_layer(kind)
        layer["_authoring_id"] = f"L{self._composer_layer_counter}"
        self._composer_layer_counter += 1

        if kind == "Cell":
            rows, columns, active = self._composer_active_geometry()
            active_set = set(active)
            preferred = (
                min(max(0, rows // 2), rows - 1),
                min(max(0, columns // 2), columns - 1),
            )
            cell = (
                preferred
                if preferred in active_set
                else (
                    min(active_set)
                    if active_set
                    else (0, 0)
                )
            )
            layer["row"], layer["column"] = cell

        self._composer_layers.append(layer)
        self.composer_layers.addItem(QListWidgetItem(kind))
        self.composer_layers.setCurrentRow(self.composer_layers.count() - 1)
        self._composer_refresh()

    def _composer_remove_layer(self):
        row = self.composer_layers.currentRow()
        if 0 <= row < len(self._composer_layers):
            self._composer_history_checkpoint()
        if not (0 <= row < len(self._composer_layers)):
            return
        removed = self._composer_layers[row]
        del self._composer_layers[row]
        member_id = removed.get("_authoring_id")
        for group in self._composer_groups:
            group["members"] = [member for member in group.get("members", ()) if member != member_id]
        self._composer_groups[:] = [group for group in self._composer_groups if group.get("members")]
        self.composer_layers.takeItem(row)
        self._composer_refresh_group_controls()
        if self.composer_layers.count():
            self.composer_layers.setCurrentRow(min(row, self.composer_layers.count() - 1))
        self._composer_refresh()

    def _composer_move_layer(self, delta):
        row = self.composer_layers.currentRow()
        if 0 <= row < len(self._composer_layers):
            self._composer_history_checkpoint()
        other = row + int(delta)
        if not (0 <= row < len(self._composer_layers) and 0 <= other < len(self._composer_layers)):
            return
        self._composer_layers[row], self._composer_layers[other] = (
            self._composer_layers[other], self._composer_layers[row]
        )
        item = self.composer_layers.takeItem(row)
        self.composer_layers.insertItem(other, item)
        self.composer_layers.setCurrentRow(other)
        self._composer_refresh()

    def _composer_select_layer(self, row):
        if not (0 <= row < len(self._composer_layers)):
            self.composer_kind.setText("No layer selected")
            return
        layer = self._composer_layers[row]
        self._composer_updating = True
        try:
            self.composer_kind.setText(layer["kind"])
            self.composer_colour = tuple(layer["colour"])
            self.composer_colour2 = tuple(layer["colour2"])
            self.composer_opacity.setValue(float(layer["opacity"]))
            self.composer_row.setValue(int(layer["row"]))
            self.composer_column.setValue(int(layer["column"]))
            self.composer_direction.setCurrentText(layer["direction"])
            self.composer_duration.setValue(float(layer["duration"]))
            self.composer_layer_delay.setValue(float(layer.get("timeline_delay", 0.0)))
            self.composer_layer_timeline_duration.setValue(float(layer.get("timeline_duration", 2.0)))
            playback_index = self.composer_layer_playback.findData(layer.get("playback", "once"))
            self.composer_layer_playback.setCurrentIndex(playback_index if playback_index >= 0 else 0)
            self.composer_layer_phase.setValue(float(layer.get("phase_offset", 0.0)))
            self.composer_layer_fade_in.setValue(float(layer.get("fade_in", 0.0)))
            self.composer_layer_fade_out.setValue(float(layer.get("fade_out", 0.0)))
            self.composer_layer_speed_multiplier.setValue(float(layer.get("speed_multiplier", 1.0)))
            index = self.composer_motion_mode.findData(layer.get("motion_mode", "none"))
            self.composer_motion_mode.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_motion_direction.findData(layer.get("motion_direction", "left-to-right"))
            self.composer_motion_direction.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_motion_start_kind.findData(layer.get("motion_start_kind", "normalized"))
            self.composer_motion_start_kind.setCurrentIndex(index if index >= 0 else 0)
            self.composer_motion_start_row.setValue(float(layer.get("motion_start_row", 0.5)))
            self.composer_motion_start_column.setValue(float(layer.get("motion_start_column", 0.0)))
            self.composer_motion_start_cell_row.setValue(int(layer.get("motion_start_cell_row", 0)))
            self.composer_motion_start_cell_column.setValue(int(layer.get("motion_start_cell_column", 0)))
            index = self.composer_motion_start_region.findData(layer.get("motion_start_region"))
            self.composer_motion_start_region.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_motion_end_kind.findData(layer.get("motion_end_kind", "normalized"))
            self.composer_motion_end_kind.setCurrentIndex(index if index >= 0 else 0)
            self.composer_motion_end_row.setValue(float(layer.get("motion_end_row", 0.5)))
            self.composer_motion_end_column.setValue(float(layer.get("motion_end_column", 1.0)))
            self.composer_motion_end_cell_row.setValue(int(layer.get("motion_end_cell_row", 0)))
            self.composer_motion_end_cell_column.setValue(int(layer.get("motion_end_cell_column", 0)))
            index = self.composer_motion_end_region.findData(layer.get("motion_end_region"))
            self.composer_motion_end_region.setCurrentIndex(index if index >= 0 else 0)
            self.composer_motion_head_width.setValue(float(layer.get("motion_head_width", 0.08)))
            self.composer_motion_trail.setValue(float(layer.get("motion_trail", 0.20)))
            index = self.composer_colour_mode.findData(layer.get("colour_mode", "static"))
            self.composer_colour_mode.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_spatial_palette.findData(bool(layer.get("spatial_palette", False)))
            self.composer_spatial_palette.setCurrentIndex(index if index >= 0 else 0)
            self._composer_refresh_palette_list(layer)
            region_index = self.composer_layer_region.findData(
                layer.get("region")
            )
            self.composer_layer_region.setCurrentIndex(
                region_index if region_index >= 0 else 0
            )
            self._composer_update_colour_buttons()
            self.composer_matrix.selected = (int(layer["row"]), int(layer["column"]))
            self.composer_matrix.update()
        finally:
            self._composer_updating = False
        self._composer_refresh_bulk_editor()

    def _composer_matrix_cell(self, row, column):
        current = self.composer_layers.currentRow()
        if not (0 <= current < len(self._composer_layers)) or self._composer_layers[current]["kind"] != "Cell":
            self._composer_add_layer("Cell")
            current = self.composer_layers.currentRow()
        layer = self._composer_layers[current]
        layer["row"] = int(row)
        layer["column"] = int(column)
        self._composer_select_layer(current)
        self._composer_refresh()

    @staticmethod
    def _composer_mix_colour(a, b, amount):
        amount = max(0.0, min(1.0, float(amount)))
        return tuple(
            round(a[index] * (1.0 - amount) + b[index] * amount)
            for index in range(3)
        )

    @classmethod
    def _composer_sample_stops(cls, stops, position):
        ordered = sorted(
            (
                max(0.0, min(1.0, float(stop[0]))),
                tuple(int(channel) for channel in stop[1]),
            )
            for stop in stops
        )
        if not ordered:
            return (0, 0, 0)
        position = max(0.0, min(1.0, float(position)))
        if position <= ordered[0][0]:
            return ordered[0][1]
        if position >= ordered[-1][0]:
            return ordered[-1][1]
        for index in range(1, len(ordered)):
            left_pos, left_colour = ordered[index - 1]
            right_pos, right_colour = ordered[index]
            if position <= right_pos:
                span = max(1e-9, right_pos - left_pos)
                return cls._composer_mix_colour(
                    left_colour,
                    right_colour,
                    (position - left_pos) / span,
                )
        return ordered[-1][1]

    @classmethod
    def _composer_colour_for(cls, item, phase, spatial_position=None):
        mode = item.get("colour_mode", "static")
        primary = tuple(item.get("colour", (80, 120, 255)))
        secondary = tuple(item.get("colour2", (255, 80, 160)))
        position = float(phase) % 1.0
        if bool(item.get("spatial_palette", False)) and spatial_position is not None:
            position = (float(spatial_position) + position) % 1.0
        if mode == "static":
            return primary
        if mode == "two-colour":
            return cls._composer_mix_colour(primary, secondary, position)
        return cls._composer_sample_stops(item.get("palette_stops", ()), position)

    def _composer_refresh_palette_list(self, layer=None, select_row=None):
        if layer is None:
            row = self.composer_layers.currentRow()
            if not (0 <= row < len(self._composer_layers)):
                return
            layer = self._composer_layers[row]
        stops = sorted(layer.get("palette_stops", ()))
        self.composer_palette_list.blockSignals(True)
        try:
            self.composer_palette_list.clear()
            for position, colour in stops:
                self.composer_palette_list.addItem(
                    f"{float(position):.2f}  RGB {tuple(colour)}"
                )
            if stops:
                row = min(max(0, int(select_row or 0)), len(stops) - 1)
                self.composer_palette_list.setCurrentRow(row)
        finally:
            self.composer_palette_list.blockSignals(False)
        self._composer_palette_selected(self.composer_palette_list.currentRow())

    def _composer_palette_selected(self, stop_row):
        layer_row = self.composer_layers.currentRow()
        if not (0 <= layer_row < len(self._composer_layers)):
            return
        stops = sorted(self._composer_layers[layer_row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        self._composer_updating = True
        try:
            self.composer_palette_position.setValue(float(stops[stop_row][0]))
            self.composer_palette_colour.setText(f"RGB {tuple(stops[stop_row][1])}")
        finally:
            self._composer_updating = False

    def _composer_palette_position_changed(self, value):
        if self._composer_updating:
            return
        layer_row = self.composer_layers.currentRow()
        stop_row = self.composer_palette_list.currentRow()
        if not (0 <= layer_row < len(self._composer_layers)):
            return
        stops = sorted(self._composer_layers[layer_row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        stops[stop_row] = (float(value), tuple(stops[stop_row][1]))
        stops.sort(key=lambda item: item[0])
        self._composer_layers[layer_row]["palette_stops"] = stops
        self._composer_refresh_palette_list(self._composer_layers[layer_row], stop_row)
        self._composer_refresh()

    def _composer_palette_add_stop(self):
        row = self.composer_layers.currentRow()
        if not (0 <= row < len(self._composer_layers)):
            return
        stops = list(self._composer_layers[row].get("palette_stops", ()))
        position = 0.5
        colour = self._composer_sample_stops(stops, position) if stops else self.composer_colour
        stops.append((position, colour))
        stops.sort(key=lambda item: item[0])
        self._composer_layers[row]["palette_stops"] = stops
        self._composer_refresh_palette_list(self._composer_layers[row], 1)
        self._composer_refresh()

    def _composer_palette_remove_stop(self):
        row = self.composer_layers.currentRow()
        stop_row = self.composer_palette_list.currentRow()
        if not (0 <= row < len(self._composer_layers)):
            return
        stops = sorted(self._composer_layers[row].get("palette_stops", ()))
        if len(stops) <= 2 or not (0 <= stop_row < len(stops)):
            return
        del stops[stop_row]
        self._composer_layers[row]["palette_stops"] = stops
        self._composer_refresh_palette_list(self._composer_layers[row], min(stop_row, len(stops) - 1))
        self._composer_refresh()

    def _composer_palette_move(self, delta):
        row = self.composer_layers.currentRow()
        stop_row = self.composer_palette_list.currentRow()
        if not (0 <= row < len(self._composer_layers)):
            return
        stops = sorted(self._composer_layers[row].get("palette_stops", ()))
        other = stop_row + int(delta)
        if not (0 <= stop_row < len(stops) and 0 <= other < len(stops)):
            return
        colours = [stop[1] for stop in stops]
        colours[stop_row], colours[other] = colours[other], colours[stop_row]
        positions = [stop[0] for stop in stops]
        stops = list(zip(positions, colours))
        self._composer_layers[row]["palette_stops"] = stops
        self._composer_refresh_palette_list(self._composer_layers[row], other)
        self._composer_refresh()

    def _composer_palette_pick_colour(self):
        row = self.composer_layers.currentRow()
        stop_row = self.composer_palette_list.currentRow()
        if not (0 <= row < len(self._composer_layers)):
            return
        stops = sorted(self._composer_layers[row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        initial = tuple(stops[stop_row][1])
        colour = QColorDialog.getColor(QColor(*initial), self, "Choose palette stop colour")
        if not colour.isValid():
            return
        stops[stop_row] = (
            stops[stop_row][0],
            (colour.red(), colour.green(), colour.blue()),
        )
        self._composer_layers[row]["palette_stops"] = stops
        self._composer_refresh_palette_list(self._composer_layers[row], stop_row)
        self._composer_refresh()

    def _composer_refresh_trigger_palette_list(self, trigger=None, select_row=None):
        if trigger is None:
            row = self.composer_trigger_list.currentRow()
            if not (0 <= row < len(self._composer_triggers)):
                return
            trigger = self._composer_triggers[row]
        stops = sorted(trigger.get("palette_stops", ()))
        self.composer_trigger_palette_list.blockSignals(True)
        try:
            self.composer_trigger_palette_list.clear()
            for position, colour in stops:
                self.composer_trigger_palette_list.addItem(
                    f"{float(position):.2f}  RGB {tuple(colour)}"
                )
            if stops:
                row = min(max(0, int(select_row or 0)), len(stops) - 1)
                self.composer_trigger_palette_list.setCurrentRow(row)
        finally:
            self.composer_trigger_palette_list.blockSignals(False)
        self._composer_trigger_palette_selected(
            self.composer_trigger_palette_list.currentRow()
        )

    def _composer_trigger_palette_selected(self, stop_row):
        trigger_row = self.composer_trigger_list.currentRow()
        if not (0 <= trigger_row < len(self._composer_triggers)):
            return
        stops = sorted(self._composer_triggers[trigger_row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        self._composer_updating = True
        try:
            self.composer_trigger_palette_position.setValue(float(stops[stop_row][0]))
            self.composer_trigger_palette_colour.setText(f"RGB {tuple(stops[stop_row][1])}")
        finally:
            self._composer_updating = False

    def _composer_trigger_palette_position_changed(self, value):
        if self._composer_updating:
            return
        trigger_row = self.composer_trigger_list.currentRow()
        stop_row = self.composer_trigger_palette_list.currentRow()
        if not (0 <= trigger_row < len(self._composer_triggers)):
            return
        stops = sorted(self._composer_triggers[trigger_row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        stops[stop_row] = (float(value), tuple(stops[stop_row][1]))
        stops.sort(key=lambda item: item[0])
        self._composer_triggers[trigger_row]["palette_stops"] = stops
        self._composer_refresh_trigger_palette_list(self._composer_triggers[trigger_row], stop_row)
        self._composer_refresh_source_preview()

    def _composer_trigger_palette_add_stop(self):
        row = self.composer_trigger_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        stops = list(self._composer_triggers[row].get("palette_stops", ()))
        position = 0.5
        colour = self._composer_sample_stops(stops, position) if stops else self._composer_trigger_colour
        stops.append((position, colour))
        stops.sort(key=lambda item: item[0])
        self._composer_triggers[row]["palette_stops"] = stops
        self._composer_refresh_trigger_palette_list(self._composer_triggers[row], 1)
        self._composer_refresh_source_preview()

    def _composer_trigger_palette_remove_stop(self):
        row = self.composer_trigger_list.currentRow()
        stop_row = self.composer_trigger_palette_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        stops = sorted(self._composer_triggers[row].get("palette_stops", ()))
        if len(stops) <= 2 or not (0 <= stop_row < len(stops)):
            return
        del stops[stop_row]
        self._composer_triggers[row]["palette_stops"] = stops
        self._composer_refresh_trigger_palette_list(self._composer_triggers[row], min(stop_row, len(stops) - 1))
        self._composer_refresh_source_preview()

    def _composer_trigger_palette_move(self, delta):
        row = self.composer_trigger_list.currentRow()
        stop_row = self.composer_trigger_palette_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        stops = sorted(self._composer_triggers[row].get("palette_stops", ()))
        other = stop_row + int(delta)
        if not (0 <= stop_row < len(stops) and 0 <= other < len(stops)):
            return
        colours = [stop[1] for stop in stops]
        colours[stop_row], colours[other] = colours[other], colours[stop_row]
        positions = [stop[0] for stop in stops]
        stops = list(zip(positions, colours))
        self._composer_triggers[row]["palette_stops"] = stops
        self._composer_refresh_trigger_palette_list(self._composer_triggers[row], other)
        self._composer_refresh_source_preview()

    def _composer_trigger_palette_pick_colour(self):
        row = self.composer_trigger_list.currentRow()
        stop_row = self.composer_trigger_palette_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        stops = sorted(self._composer_triggers[row].get("palette_stops", ()))
        if not (0 <= stop_row < len(stops)):
            return
        initial = tuple(stops[stop_row][1])
        colour = QColorDialog.getColor(QColor(*initial), self, "Choose trigger palette stop colour")
        if not colour.isValid():
            return
        stops[stop_row] = (
            stops[stop_row][0],
            (colour.red(), colour.green(), colour.blue()),
        )
        self._composer_triggers[row]["palette_stops"] = stops
        self._composer_refresh_trigger_palette_list(self._composer_triggers[row], stop_row)
        self._composer_refresh_source_preview()

    def _composer_pick_colour(self, secondary):
        initial = self.composer_colour2 if secondary else self.composer_colour
        colour = QColorDialog.getColor(QColor(*initial), self, "Choose layer colour")
        if not colour.isValid():
            return
        value = (colour.red(), colour.green(), colour.blue())
        if secondary:
            self.composer_colour2 = value
        else:
            self.composer_colour = value
        self._composer_property_changed()

    def _composer_update_colour_buttons(self):
        self.composer_colour_button.setText("#{:02X}{:02X}{:02X}".format(*self.composer_colour))
        self.composer_colour2_button.setText("#{:02X}{:02X}{:02X}".format(*self.composer_colour2))

    def _composer_property_changed(self, *args):
        if self._composer_updating:
            return
        row = self.composer_layers.currentRow()
        if 0 <= row < len(self._composer_layers):
            self._composer_history_checkpoint()
        if not (0 <= row < len(self._composer_layers)):
            return
        self._composer_layers[row].update({
            "colour": tuple(self.composer_colour),
            "colour2": tuple(self.composer_colour2),
            "opacity": self.composer_opacity.value(),
            "row": self.composer_row.value(),
            "column": self.composer_column.value(),
            "direction": self.composer_direction.currentText(),
            "duration": self.composer_duration.value(),
            "timeline_delay": self.composer_layer_delay.value(),
            "timeline_duration": self.composer_layer_timeline_duration.value(),
            "playback": self.composer_layer_playback.currentData(),
            "phase_offset": self.composer_layer_phase.value(),
            "fade_in": self.composer_layer_fade_in.value(),
            "fade_out": self.composer_layer_fade_out.value(),
            "speed_multiplier": self.composer_layer_speed_multiplier.value(),
            "motion_mode": self.composer_motion_mode.currentData(),
            "motion_direction": self.composer_motion_direction.currentData(),
            "motion_start_kind": self.composer_motion_start_kind.currentData(),
            "motion_start_row": self.composer_motion_start_row.value(),
            "motion_start_column": self.composer_motion_start_column.value(),
            "motion_start_cell_row": self.composer_motion_start_cell_row.value(),
            "motion_start_cell_column": self.composer_motion_start_cell_column.value(),
            "motion_start_region": self.composer_motion_start_region.currentData(),
            "motion_end_kind": self.composer_motion_end_kind.currentData(),
            "motion_end_row": self.composer_motion_end_row.value(),
            "motion_end_column": self.composer_motion_end_column.value(),
            "motion_end_cell_row": self.composer_motion_end_cell_row.value(),
            "motion_end_cell_column": self.composer_motion_end_cell_column.value(),
            "motion_end_region": self.composer_motion_end_region.currentData(),
            "motion_head_width": self.composer_motion_head_width.value(),
            "motion_trail": self.composer_motion_trail.value(),
            "colour_mode": self.composer_colour_mode.currentData(),
            "spatial_palette": bool(self.composer_spatial_palette.currentData()),
            "region": self.composer_layer_region.currentData(),
        })
        self._composer_refresh()

    def _composer_default_trigger(self):
        return {
            "source": "keyboard",
            "action": "press",
            "code": "",
            "destination": (self._composer_current_device_class or "keyboard"),
            "response": "pulse-all",
            "origin": "entire-target",
            "direction": 1,
            "relative_row": 0.5,
            "relative_column": 0.5,
            "region": None,
            "colour": (255, 120, 40),
            "duration": 0.6,
            "delay": 0.0,
            "playback": "once",
            "phase_offset": 0.0,
            "fade_in": 0.0,
            "fade_out": 0.0,
            "speed_multiplier": 1.0,
            "motion_mode": "none",
            "motion_direction": "left-to-right",
            "motion_start_kind": "event",
            "motion_start_row": 0.5,
            "motion_start_column": 0.0,
            "motion_start_cell_row": 0,
            "motion_start_cell_column": 0,
            "motion_start_region": None,
            "motion_end_kind": "normalized",
            "motion_end_row": 0.5,
            "motion_end_column": 1.0,
            "motion_end_cell_row": 0,
            "motion_end_cell_column": 0,
            "motion_end_region": None,
            "motion_head_width": 0.08,
            "motion_trail": 0.20,
            "colour_mode": "static",
            "palette_stops": [
                (0.0, (255, 120, 40)),
                (1.0, (255, 255, 255)),
            ],
            "spatial_palette": False,
            "row": 0,
            "column": 0,
        }

    def _composer_trigger_label(self, trigger):
        source = str(trigger["source"]).title()
        action = str(trigger["action"]).title()
        code = str(trigger.get("code", "")).strip()
        destination = "All" if trigger["destination"] == "*" else str(trigger["destination"]).title()
        code_text = f" [{code}]" if code else ""
        return f"{source} {action}{code_text} → {destination}"

    def _composer_rebuild_trigger_list(self):
        current = self.composer_trigger_list.currentRow()
        self.composer_trigger_list.blockSignals(True)
        self.composer_trigger_list.clear()
        for trigger in self._composer_triggers:
            self.composer_trigger_list.addItem(QListWidgetItem(self._composer_trigger_label(trigger)))
        self.composer_trigger_list.blockSignals(False)
        if self.composer_trigger_list.count():
            self.composer_trigger_list.setCurrentRow(
                min(max(0, current), self.composer_trigger_list.count() - 1)
            )

    def _composer_add_trigger(self):
        trigger = self._composer_default_trigger()
        self._composer_triggers.append(trigger)
        self.composer_trigger_list.addItem(QListWidgetItem(self._composer_trigger_label(trigger)))
        self.composer_trigger_list.setCurrentRow(self.composer_trigger_list.count() - 1)
        self._composer_refresh_source_preview()

    def _composer_remove_trigger(self):
        row = self.composer_trigger_list.currentRow()
        if not (0 <= row < len(self._composer_triggers)):
            return
        del self._composer_triggers[row]
        self.composer_trigger_list.takeItem(row)
        if self.composer_trigger_list.count():
            self.composer_trigger_list.setCurrentRow(min(row, self.composer_trigger_list.count() - 1))
        self._composer_refresh_source_preview()

    def _composer_select_trigger(self, row):
        if not (0 <= row < len(self._composer_triggers)):
            return
        trigger = self._composer_triggers[row]
        self._composer_updating = True
        try:
            for combo, value in (
                (self.composer_trigger_source, trigger["source"]),
                (self.composer_trigger_action, trigger["action"]),
                (self.composer_trigger_response, trigger["response"]),
                (
                    self.composer_trigger_origin,
                    trigger.get("origin", "entire-target"),
                ),
                (
                    self.composer_trigger_direction,
                    trigger.get("direction", 1),
                ),
            ):
                index = combo.findData(value)
                if index >= 0:
                    combo.setCurrentIndex(index)
            destination_index = self.composer_trigger_destination.findData(trigger["destination"])
            if destination_index < 0:
                destination_index = self.composer_trigger_destination.findData("current")
            self.composer_trigger_destination.setCurrentIndex(destination_index)
            self.composer_trigger_code.setText(str(trigger.get("code", "")))
            region_index = self.composer_trigger_region.findData(
                trigger.get("region")
            )
            self.composer_trigger_region.setCurrentIndex(
                region_index if region_index >= 0 else 0
            )
            self._composer_trigger_colour = tuple(trigger["colour"])
            self.composer_trigger_duration.setValue(float(trigger["duration"]))
            self.composer_trigger_delay.setValue(float(trigger.get("delay", 0.0)))
            playback_index = self.composer_trigger_playback.findData(trigger.get("playback", "once"))
            self.composer_trigger_playback.setCurrentIndex(playback_index if playback_index >= 0 else 0)
            self.composer_trigger_phase.setValue(float(trigger.get("phase_offset", 0.0)))
            self.composer_trigger_fade_in.setValue(float(trigger.get("fade_in", 0.0)))
            self.composer_trigger_fade_out.setValue(float(trigger.get("fade_out", 0.0)))
            self.composer_trigger_speed_multiplier.setValue(float(trigger.get("speed_multiplier", 1.0)))
            index = self.composer_trigger_motion_mode.findData(trigger.get("motion_mode", "none"))
            self.composer_trigger_motion_mode.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_trigger_motion_direction.findData(trigger.get("motion_direction", "left-to-right"))
            self.composer_trigger_motion_direction.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_trigger_motion_start_kind.findData(trigger.get("motion_start_kind", "event"))
            self.composer_trigger_motion_start_kind.setCurrentIndex(index if index >= 0 else 0)
            self.composer_trigger_motion_start_row.setValue(float(trigger.get("motion_start_row", 0.5)))
            self.composer_trigger_motion_start_column.setValue(float(trigger.get("motion_start_column", 0.0)))
            self.composer_trigger_motion_start_cell_row.setValue(int(trigger.get("motion_start_cell_row", 0)))
            self.composer_trigger_motion_start_cell_column.setValue(int(trigger.get("motion_start_cell_column", 0)))
            index = self.composer_trigger_motion_start_region.findData(trigger.get("motion_start_region"))
            self.composer_trigger_motion_start_region.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_trigger_motion_end_kind.findData(trigger.get("motion_end_kind", "normalized"))
            self.composer_trigger_motion_end_kind.setCurrentIndex(index if index >= 0 else 0)
            self.composer_trigger_motion_end_row.setValue(float(trigger.get("motion_end_row", 0.5)))
            self.composer_trigger_motion_end_column.setValue(float(trigger.get("motion_end_column", 1.0)))
            self.composer_trigger_motion_end_cell_row.setValue(int(trigger.get("motion_end_cell_row", 0)))
            self.composer_trigger_motion_end_cell_column.setValue(int(trigger.get("motion_end_cell_column", 0)))
            index = self.composer_trigger_motion_end_region.findData(trigger.get("motion_end_region"))
            self.composer_trigger_motion_end_region.setCurrentIndex(index if index >= 0 else 0)
            self.composer_trigger_motion_head_width.setValue(float(trigger.get("motion_head_width", 0.08)))
            self.composer_trigger_motion_trail.setValue(float(trigger.get("motion_trail", 0.20)))
            index = self.composer_trigger_colour_mode.findData(trigger.get("colour_mode", "static"))
            self.composer_trigger_colour_mode.setCurrentIndex(index if index >= 0 else 0)
            index = self.composer_trigger_spatial_palette.findData(bool(trigger.get("spatial_palette", False)))
            self.composer_trigger_spatial_palette.setCurrentIndex(index if index >= 0 else 0)
            self._composer_refresh_trigger_palette_list(trigger)
            self.composer_trigger_relative_row.setValue(
                float(trigger.get("relative_row", 0.5))
            )
            self.composer_trigger_relative_column.setValue(
                float(trigger.get("relative_column", 0.5))
            )
            self.composer_trigger_row.setValue(int(trigger["row"]))
            self.composer_trigger_column.setValue(int(trigger["column"]))
            self._composer_update_trigger_colour_button()
        finally:
            self._composer_updating = False

    def _composer_pick_trigger_colour(self):
        colour = QColorDialog.getColor(
            QColor(*self._composer_trigger_colour),
            self,
            "Choose trigger response colour",
        )
        if not colour.isValid():
            return
        self._composer_trigger_colour = (colour.red(), colour.green(), colour.blue())
        self._composer_update_trigger_colour_button()
        self._composer_trigger_property_changed()

    def _composer_update_trigger_colour_button(self):
        self.composer_trigger_colour_button.setText(
            "#{:02X}{:02X}{:02X}".format(*self._composer_trigger_colour)
        )

    def _composer_trigger_property_changed(self, *args):
        if self._composer_updating:
            return
        row = self.composer_trigger_list.currentRow()
        if 0 <= row < len(self._composer_triggers):
            self._composer_history_checkpoint()
        if not (0 <= row < len(self._composer_triggers)):
            return
        destination = self.composer_trigger_destination.currentData()
        if destination == "current":
            destination = (
                self._composer_current_device_class
                or self._composer_normalize_device_class(self.composer_device_class_combo.currentText())
                or "keyboard"
            )
        trigger = self._composer_triggers[row]
        trigger.update({
            "source": self.composer_trigger_source.currentData(),
            "action": self.composer_trigger_action.currentData(),
            "code": self.composer_trigger_code.text().strip(),
            "destination": destination,
            "response": self.composer_trigger_response.currentData(),
            "origin": self.composer_trigger_origin.currentData(),
            "direction": self.composer_trigger_direction.currentData(),
            "relative_row": self.composer_trigger_relative_row.value(),
            "relative_column": self.composer_trigger_relative_column.value(),
            "region": self.composer_trigger_region.currentData(),
            "colour": tuple(self._composer_trigger_colour),
            "duration": self.composer_trigger_duration.value(),
            "delay": self.composer_trigger_delay.value(),
            "playback": self.composer_trigger_playback.currentData(),
            "phase_offset": self.composer_trigger_phase.value(),
            "fade_in": self.composer_trigger_fade_in.value(),
            "fade_out": self.composer_trigger_fade_out.value(),
            "speed_multiplier": self.composer_trigger_speed_multiplier.value(),
            "motion_mode": self.composer_trigger_motion_mode.currentData(),
            "motion_direction": self.composer_trigger_motion_direction.currentData(),
            "motion_start_kind": self.composer_trigger_motion_start_kind.currentData(),
            "motion_start_row": self.composer_trigger_motion_start_row.value(),
            "motion_start_column": self.composer_trigger_motion_start_column.value(),
            "motion_start_cell_row": self.composer_trigger_motion_start_cell_row.value(),
            "motion_start_cell_column": self.composer_trigger_motion_start_cell_column.value(),
            "motion_start_region": self.composer_trigger_motion_start_region.currentData(),
            "motion_end_kind": self.composer_trigger_motion_end_kind.currentData(),
            "motion_end_row": self.composer_trigger_motion_end_row.value(),
            "motion_end_column": self.composer_trigger_motion_end_column.value(),
            "motion_end_cell_row": self.composer_trigger_motion_end_cell_row.value(),
            "motion_end_cell_column": self.composer_trigger_motion_end_cell_column.value(),
            "motion_end_region": self.composer_trigger_motion_end_region.currentData(),
            "motion_head_width": self.composer_trigger_motion_head_width.value(),
            "motion_trail": self.composer_trigger_motion_trail.value(),
            "colour_mode": self.composer_trigger_colour_mode.currentData(),
            "spatial_palette": bool(self.composer_trigger_spatial_palette.currentData()),
            "row": self.composer_trigger_row.value(),
            "column": self.composer_trigger_column.value(),
        })
        item = self.composer_trigger_list.item(row)
        if item is not None:
            item.setText(self._composer_trigger_label(trigger))
        self._composer_refresh_source_preview()

    def _composer_metadata_changed(self, *args):
        self._composer_refresh_source_preview()
        self._composer_invalidate_validation()

    def _composer_refresh(self):
        self._composer_update_colour_buttons()
        preview_layers = []
        for layer in self._composer_flatten_grouped_layers(
            self._composer_layers,
            self._composer_groups,
        ):
            active, local, phase, envelope = self._composer_timeline_state(
                elapsed=self._composer_preview_time,
                delay=layer.get("timeline_delay", 0.0),
                duration=layer.get("timeline_duration", 2.0),
                playback=layer.get("playback", "once"),
                phase_offset=layer.get("phase_offset", 0.0),
                fade_in=layer.get("fade_in", 0.0),
                fade_out=layer.get("fade_out", 0.0),
                speed_multiplier=layer.get("speed_multiplier", 1.0),
            )
            if not active:
                continue
            preview_layer = dict(layer)
            preview_layer["opacity"] = float(layer.get("opacity", 1.0)) * envelope
            preview_layer["colour"] = self._composer_colour_for(layer, phase)
            if layer.get("colour_mode", "static") != "static":
                preview_layer["colour2"] = self._composer_colour_for(
                    layer,
                    (phase + 0.5) % 1.0,
                )
            if preview_layer.get("kind") == "Pulse":
                pulse = (math.sin(phase * (2.0 * math.pi)) + 1.0) / 2.0
                preview_layer["opacity"] *= pulse
            preview_layers.append(preview_layer)
        self.composer_matrix.set_composition(
            preview_layers,
            self._composer_regions,
        )

        row = self.composer_layers.currentRow()
        if 0 <= row < len(self._composer_layers):
            layer = self._composer_layers[row]
            active, local, phase, envelope = self._composer_timeline_state(
                elapsed=self._composer_preview_time,
                delay=layer.get("timeline_delay", 0.0),
                duration=layer.get("timeline_duration", 2.0),
                playback=layer.get("playback", "once"),
                phase_offset=layer.get("phase_offset", 0.0),
                fade_in=layer.get("fade_in", 0.0),
                fade_out=layer.get("fade_out", 0.0),
                speed_multiplier=layer.get("speed_multiplier", 1.0),
            )
            if active and layer.get("motion_mode", "none") != "none":
                if layer.get("motion_mode") == "directional":
                    direction = layer.get("motion_direction", "left-to-right")
                    if direction == "right-to-left":
                        nr, nc = 0.5, 1.0 - phase
                    elif direction == "top-to-bottom":
                        nr, nc = phase, 0.5
                    elif direction == "bottom-to-top":
                        nr, nc = 1.0 - phase, 0.5
                    else:
                        nr, nc = 0.5, phase
                else:
                    sr, sc = layer.get("motion_start_row", 0.5), layer.get("motion_start_column", 0.0)
                    er, ec = layer.get("motion_end_row", 0.5), layer.get("motion_end_column", 1.0)
                    nr, nc = sr + (er - sr) * phase, sc + (ec - sc) * phase
                rows, columns, active_cells = self._composer_active_geometry()
                if active_cells:
                    raw = (nr * max(0, rows - 1), nc * max(0, columns - 1))
                    self.composer_matrix.selected = min(
                        active_cells,
                        key=lambda cell: (cell[0] - raw[0]) ** 2 + (cell[1] - raw[1]) ** 2,
                    )
                    self.composer_matrix.update()

        self._composer_update_timeline_widgets()
        self._composer_refresh_source_preview()

    def _composer_identity_changed(self, *_args):
        self._validated_developer_source = None
        self.preview_enabled = False
        self.spec = None
        self.specs = []

        if self._composer_output_path is not None:
            self.source_edit.document().setModified(True)

        self._update_developer_workflow_state()

    def _composer_generated_source(self):
        if getattr(self, "_composer_raw_python_mode", False):
            return self.source_edit.toPlainText()

        name = self.composer_name.text().strip() or "Visual Effect"
        effect_id = self._creator_slug(self.composer_id.text()) or "visual-effect"
        description = (
            self.composer_description.text().strip()
            or "Created with Serpent Visual Composer."
        )
        class_name = self._creator_class_name(name)
        if self._composer_current_device_class:
            self._composer_target_layers[
                self._composer_current_device_class
            ] = self._composer_layers
            self._composer_target_geometries[
                self._composer_current_device_class
            ] = self._composer_target_payload()
            self._composer_target_regions[
                self._composer_current_device_class
            ] = self._composer_regions
            self._composer_target_groups[
                self._composer_current_device_class
            ] = self._composer_groups

        if self._composer_is_synchronized():
            target_layers = {
                device_class: tuple(
                    self._composer_flatten_grouped_layers(
                        layers,
                        self._composer_target_groups.get(device_class, ()),
                    )
                )
                for device_class, layers
                in self._composer_target_layers.items()
            }
        else:
            device_class = (
                self._composer_current_device_class
                or self._composer_normalize_device_class(
                    self.composer_device_class_combo.currentText()
                )
                or "keyboard"
            )
            target_layers = {
                device_class: tuple(
                    self._composer_flatten_grouped_layers(
                        self._composer_layers,
                        self._composer_groups,
                    )
                )
            }

        if self._composer_is_synchronized():
            target_regions = {
                device_class: {
                    name: tuple(cells)
                    for name, cells in regions.items()
                }
                for device_class, regions
                in self._composer_target_regions.items()
                if device_class in target_layers
            }
        else:
            only_target = next(iter(target_layers))
            target_regions = {
                only_target: {
                    name: tuple(cells)
                    for name, cells in self._composer_regions.items()
                }
            }

        unsupported_targets = sorted(
            set(target_layers) - {"keyboard", "mouse"}
        )
        if unsupported_targets:
            raise ValueError(
                "Current Serpent plugin render-target support is limited "
                "to keyboard/mouse. Visual Composer can retain future "
                "target models, but cannot generate/install them yet: "
                + ", ".join(unsupported_targets)
            )

        animated = any(
            layer["kind"] == "Pulse"
            for layers in target_layers.values()
            for layer in layers
        )
        target_layers_literal = repr(target_layers)
        target_regions_literal = repr(target_regions)
        render_targets = tuple(target_layers)

        triggers = tuple(dict(trigger) for trigger in self._composer_triggers)
        trigger_sources = {trigger["source"] for trigger in triggers}
        input_capabilities = tuple(
            capability
            for capability in ("keyboard", "mouse")
            if capability in trigger_sources or "any" in trigger_sources
        )
        triggers_literal = repr(triggers)
        animated = animated or bool(triggers)
        animated = animated or any(
            (
                float(layer.get("timeline_delay", 0.0)) > 0.0
                or layer.get("playback", "once") != "once"
                or float(layer.get("phase_offset", 0.0)) != 0.0
                or float(layer.get("fade_in", 0.0)) > 0.0
                or float(layer.get("fade_out", 0.0)) > 0.0
                or float(layer.get("speed_multiplier", 1.0)) != 1.0
            )
            for layers in target_layers.values()
            for layer in layers
        )

        design_rows, design_columns, _ = self._composer_active_geometry()

        composer_project = {
            "schema": 1,
            "name": name,
            "id": effect_id,
            "description": description,
            "state": self._composer_state_snapshot(),
        }
        composer_project_literal = repr(composer_project)

        template = '''from __future__ import annotations

import math

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
)
from serpent_core.effect_sdk import (
    EffectCanvas,
    event_cell,
    event_matches,
    event_timestamp,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec
from serpent_core.geometry import (
    directional_position,
    spatial_position_count,
)

# Authoring geometry only. Runtime rendering still uses EffectTarget.
# target.device_class selects the coordinated per-device visual composition.
_COMPOSER_DESIGN_ROWS = __DESIGN_ROWS__
_COMPOSER_DESIGN_COLUMNS = __DESIGN_COLUMNS__
_TARGET_LAYERS = __TARGET_LAYERS__
_TARGET_REGIONS = __TARGET_REGIONS__
_TRIGGERS = __TRIGGERS__

# Visual Composer round-trip authoring payload. Runtime ignores this constant.
SERPENT_COMPOSER_PROJECT = __COMPOSER_PROJECT__

def _region_cells(name, target):
    if not name:
        return tuple(target.active_cells)
    configured = set(
        _TARGET_REGIONS.get(
            target.device_class,
            {},
        ).get(name, ())
    )
    return tuple(
        cell
        for cell in target.active_cells
        if cell in configured
    )


def _timeline_state(
    *,
    elapsed,
    delay,
    duration,
    playback,
    phase_offset,
    fade_in,
    fade_out,
    speed_multiplier,
):
    duration = max(0.05, float(duration))
    delay = max(0.0, float(delay))
    speed_multiplier = max(0.05, float(speed_multiplier))
    local = float(elapsed) * speed_multiplier - delay
    if local < 0.0:
        return False, local, 0.0, 0.0
    if playback == "loop":
        phase = (local / duration) % 1.0
    elif playback == "ping-pong":
        cycle = (local / duration) % 2.0
        phase = cycle if cycle <= 1.0 else 2.0 - cycle
    else:
        if local > duration:
            return False, local, 1.0, 0.0
        phase = min(1.0, local / duration)
    phase = (phase + float(phase_offset)) % 1.0
    envelope = 1.0
    fade_in = max(0.0, float(fade_in))
    fade_out = max(0.0, float(fade_out))
    if fade_in > 0.0:
        envelope = min(envelope, local / fade_in)
    if playback == "once" and fade_out > 0.0:
        envelope = min(envelope, max(0.0, (duration - local) / fade_out))
    return True, local, phase, max(0.0, min(1.0, envelope))


def _nearest_active_cell(position, target):
    if not target.active_cells:
        return None
    row, column = position
    return min(
        target.active_cells,
        key=lambda cell: (
            (float(cell[0]) - float(row)) ** 2
            + (float(cell[1]) - float(column)) ** 2
        ),
    )


def _normalized_position(row_fraction, column_fraction, target):
    return (
        float(row_fraction) * max(0, target.rows - 1),
        float(column_fraction) * max(0, target.columns - 1),
    )


def _region_centroid(name, target):
    cells = _region_cells(name, target)
    if not cells:
        return None
    return (
        sum(cell[0] for cell in cells) / len(cells),
        sum(cell[1] for cell in cells) / len(cells),
    )


def _anchor_position(
    *,
    kind,
    normalized_row,
    normalized_column,
    cell_row,
    cell_column,
    region,
    target,
    event=None,
):
    if kind == "event" and event is not None:
        # Direct event-cell geometry is valid only on the same device class.
        if _event_device_class(event) == target.device_class:
            cell = event_cell(event)
            if cell in set(target.active_cells):
                return (float(cell[0]), float(cell[1]))
        # Cross-device event origins deliberately fall back to the configured
        # normalized authoring anchor; source cells are never copied blindly.
        return _normalized_position(normalized_row, normalized_column, target)

    if kind == "cell":
        cell = (int(cell_row), int(cell_column))
        if cell in set(target.active_cells):
            return (float(cell[0]), float(cell[1]))
        nearest = _nearest_active_cell(cell, target)
        return None if nearest is None else (float(nearest[0]), float(nearest[1]))

    if kind == "region":
        centroid = _region_centroid(region, target)
        if centroid is not None:
            return centroid

    return _normalized_position(normalized_row, normalized_column, target)


def _lerp_position(start, end, phase):
    amount = max(0.0, min(1.0, float(phase)))
    return (
        float(start[0]) + (float(end[0]) - float(start[0])) * amount,
        float(start[1]) + (float(end[1]) - float(start[1])) * amount,
    )


def _directional_head(direction, phase, target):
    phase = max(0.0, min(1.0, float(phase)))
    if direction == "right-to-left":
        return _normalized_position(0.5, 1.0 - phase, target)
    if direction == "top-to-bottom":
        return _normalized_position(phase, 0.5, target)
    if direction == "bottom-to-top":
        return _normalized_position(1.0 - phase, 0.5, target)
    return _normalized_position(0.5, phase, target)


def _motion_strength(cell, head, target, width, trail, direction=None):
    row_scale = max(1.0, float(target.rows - 1))
    column_scale = max(1.0, float(target.columns - 1))
    dr = (float(cell[0]) - float(head[0])) / row_scale
    dc = (float(cell[1]) - float(head[1])) / column_scale
    distance = (dr * dr + dc * dc) ** 0.5
    radius = max(0.01, float(width))
    if distance <= radius:
        return max(0.0, 1.0 - distance / radius)

    trail = max(0.0, float(trail))
    if trail <= 0.0 or direction is None:
        return 0.0

    if direction == "right-to-left":
        behind, along, cross = dc > 0.0, abs(dc), abs(dr)
    elif direction == "top-to-bottom":
        behind, along, cross = dr < 0.0, abs(dr), abs(dc)
    elif direction == "bottom-to-top":
        behind, along, cross = dr > 0.0, abs(dr), abs(dc)
    else:
        behind, along, cross = dc < 0.0, abs(dc), abs(dr)

    if not behind or along > trail or cross > radius:
        return 0.0
    return max(0.0, (1.0 - along / trail) * (1.0 - cross / radius))


def _mix_colour(a, b, amount):
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(
        round(a[index] * (1.0 - amount) + b[index] * amount)
        for index in range(3)
    )


def _sample_stops(stops, position):
    ordered = sorted(
        (
            max(0.0, min(1.0, float(stop[0]))),
            tuple(int(channel) for channel in stop[1]),
        )
        for stop in stops
    )
    if not ordered:
        return (0, 0, 0)
    position = max(0.0, min(1.0, float(position)))
    if position <= ordered[0][0]:
        return ordered[0][1]
    if position >= ordered[-1][0]:
        return ordered[-1][1]
    for index in range(1, len(ordered)):
        left_pos, left_colour = ordered[index - 1]
        right_pos, right_colour = ordered[index]
        if position <= right_pos:
            span = max(1e-9, right_pos - left_pos)
            return _mix_colour(
                left_colour,
                right_colour,
                (position - left_pos) / span,
            )
    return ordered[-1][1]


def _colour_for(item, phase, target=None, cell=None):
    mode = item.get("colour_mode", "static")
    primary = tuple(item.get("colour", (80, 120, 255)))
    secondary = tuple(item.get("colour2", (255, 80, 160)))
    position = float(phase) % 1.0
    if bool(item.get("spatial_palette", False)) and target is not None and cell is not None:
        direction = item.get("direction", "Horizontal")
        spatial = (
            float(cell[0]) / max(1, target.rows - 1)
            if direction == "Vertical"
            else float(cell[1]) / max(1, target.columns - 1)
        )
        position = (spatial + position) % 1.0
    if mode == "static":
        return primary
    if mode == "two-colour":
        return _mix_colour(primary, secondary, position)
    return _sample_stops(item.get("palette_stops", ()), position)


def _mix(a, b, amount):
    amount = max(0.0, min(1.0, float(amount)))
    return tuple(
        round(a[index] * (1.0 - amount) + b[index] * amount)
        for index in range(3)
    )

def _trigger_matches(trigger, event):
    action = trigger["action"]
    source = trigger["source"]
    code = trigger["code"]

    def matches(source_prefix, kind):
        matched = event_matches(
            event,
            kind=kind,
            source_prefix=source_prefix,
        )
        if not matched:
            return False
        if code and event.code != code:
            return False
        return True

    if source == "keyboard":
        return matches("keyboard:", f"key-{action}")
    if source == "mouse":
        return matches("mouse:", f"mouse-{action}")
    return (
        matches("keyboard:", f"key-{action}")
        or matches("mouse:", f"mouse-{action}")
    )

def _event_device_class(event):
    if str(event.source).startswith("keyboard:"):
        return "keyboard"
    if str(event.source).startswith("mouse:"):
        return "mouse"
    return None


def _destination_cell(trigger, event, target):
    origin = trigger.get("origin", "entire-target")
    active = set(target.active_cells)

    if origin == "fixed-cell":
        cell = (
            int(trigger.get("row", 0)),
            int(trigger.get("column", 0)),
        )
        return cell if cell in active else None

    if origin == "relative-position":
        row = round(
            float(trigger.get("relative_row", 0.5))
            * max(0, target.rows - 1)
        )
        column = round(
            float(trigger.get("relative_column", 0.5))
            * max(0, target.columns - 1)
        )
        cell = (int(row), int(column))
        return cell if cell in active else None

    if origin == "event-cell":
        # Event Cell is same-device geometry only. Cross-device reactions
        # must choose Relative Position or Fixed Cell explicitly.
        if _event_device_class(event) != target.device_class:
            return None
        cell = event_cell(event)
        return cell if cell in active else None

    return None


def _cell_distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


class __CLASS__(Effect):
    definition = EffectDefinition(
        id=__ID__,
        colours=2,
        animated=__ANIMATED__,
        speed=__ANIMATED__,
        spatial=True,
    )

    def __init__(self):
        self._composer_trigger_events = []

    def handle_event(self, event: EffectEvent) -> None:
        for trigger in _TRIGGERS:
            if _trigger_matches(trigger, event):
                self._composer_trigger_events.append(
                    (event_timestamp(event), trigger, event)
                )

    def render(self, elapsed: float, parameters: EffectParameters, target: EffectTarget) -> EffectFrame:
        target.validate()
        canvas = EffectCanvas(target)
        active = set(target.active_cells)

        layers = _TARGET_LAYERS.get(target.device_class)
        if layers is None:
            return canvas.frame()

        for layer in layers:
            layer_active_now, layer_local_time, layer_phase, layer_envelope = _timeline_state(
                elapsed=elapsed,
                delay=layer.get("timeline_delay", 0.0),
                duration=layer.get("timeline_duration", 2.0),
                playback=layer.get("playback", "once"),
                phase_offset=layer.get("phase_offset", 0.0),
                fade_in=layer.get("fade_in", 0.0),
                fade_out=layer.get("fade_out", 0.0),
                speed_multiplier=layer.get("speed_multiplier", 1.0),
            )
            if not layer_active_now:
                continue
            kind = layer["kind"]
            opacity = float(layer["opacity"]) * layer_envelope
            colour = _colour_for(layer, layer_phase)
            layer_cells = _region_cells(
                layer.get("region"),
                target,
            )
            if layer.get("group_region"):
                group_cells = set(_region_cells(layer.get("group_region"), target))
                layer_cells = tuple(cell for cell in layer_cells if cell in group_cells)
            layer_active = set(layer_cells)

            motion_mode = layer.get("motion_mode", "none")
            motion_direction = layer.get("motion_direction", "left-to-right")
            motion_head = None
            if motion_mode == "directional":
                motion_head = _directional_head(motion_direction, layer_phase, target)
            elif motion_mode == "point-to-point":
                motion_start = _anchor_position(
                    kind=layer.get("motion_start_kind", "normalized"),
                    normalized_row=layer.get("motion_start_row", 0.5),
                    normalized_column=layer.get("motion_start_column", 0.0),
                    cell_row=layer.get("motion_start_cell_row", 0),
                    cell_column=layer.get("motion_start_cell_column", 0),
                    region=layer.get("motion_start_region"),
                    target=target,
                )
                motion_end = _anchor_position(
                    kind=layer.get("motion_end_kind", "normalized"),
                    normalized_row=layer.get("motion_end_row", 0.5),
                    normalized_column=layer.get("motion_end_column", 1.0),
                    cell_row=layer.get("motion_end_cell_row", 0),
                    cell_column=layer.get("motion_end_cell_column", 0),
                    region=layer.get("motion_end_region"),
                    target=target,
                )
                motion_head = _lerp_position(motion_start, motion_end, layer_phase)

            if motion_head is None:
                motion_strength = {cell: 1.0 for cell in layer_cells}
            else:
                motion_strength = {
                    cell: _motion_strength(
                        cell,
                        motion_head,
                        target,
                        layer.get("motion_head_width", 0.08),
                        layer.get("motion_trail", 0.20),
                        motion_direction if motion_mode == "directional" else None,
                    )
                    for cell in layer_cells
                }

            if kind == "Fill":
                for cell in layer_cells:
                    canvas.mix(
                        cell,
                        _colour_for(layer, layer_phase, target, cell),
                        opacity * motion_strength.get(cell, 0.0),
                    )

            elif kind == "Cell":
                cell = (int(layer["row"]), int(layer["column"]))
                if cell in active and cell in layer_active:
                    canvas.mix(
                        cell,
                        _colour_for(layer, layer_phase, target, cell),
                        opacity * motion_strength.get(cell, 0.0),
                    )

            elif kind == "Gradient":
                second = tuple(layer["colour2"])
                vertical = layer["direction"] == "Vertical"
                for row, column in layer_cells:
                    amount = (
                        row / max(1, target.rows - 1)
                        if vertical
                        else column / max(1, target.columns - 1)
                    )
                    mixed_colour = (
                        _mix(colour, second, amount)
                        if layer.get("colour_mode", "static") == "static"
                        else _colour_for(
                            layer,
                            layer_phase,
                            target,
                            (row, column),
                        )
                    )
                    canvas.mix(
                        (row, column),
                        mixed_colour,
                        opacity * motion_strength.get((row, column), 0.0),
                    )

            elif kind == "Pulse":
                duration = max(0.1, float(layer["duration"]))
                phase = (math.sin(layer_phase * (2.0 * math.pi)) + 1.0) / 2.0
                for cell in layer_cells:
                    canvas.mix(
                        cell,
                        _colour_for(layer, layer_phase, target, cell),
                        opacity * phase * motion_strength.get(cell, 0.0),
                    )

        alive = []
        for started_at, trigger, event in self._composer_trigger_events:
            raw_age = max(0.0, elapsed - started_at)
            delay = max(0.0, float(trigger.get("delay", 0.0)))
            duration = max(0.05, float(trigger["duration"]))
            if raw_age > delay + duration:
                continue

            alive.append((started_at, trigger, event))

            destination = trigger["destination"]
            if destination != "*" and destination != target.device_class:
                continue

            trigger_active_now, trigger_local_time, trigger_phase, trigger_envelope = _timeline_state(
                elapsed=raw_age,
                delay=delay,
                duration=duration,
                playback=trigger.get("playback", "once"),
                phase_offset=trigger.get("phase_offset", 0.0),
                fade_in=trigger.get("fade_in", 0.0),
                fade_out=trigger.get("fade_out", 0.0),
                speed_multiplier=trigger.get("speed_multiplier", 1.0),
            )
            if not trigger_active_now:
                continue

            progress = trigger_phase
            strength = trigger_envelope
            colour = _colour_for(trigger, trigger_phase)
            response = trigger["response"]
            motion_mode = trigger.get("motion_mode", "none")
            motion_direction = trigger.get("motion_direction", "left-to-right")
            trigger_motion_head = None
            if motion_mode == "directional":
                trigger_motion_head = _directional_head(motion_direction, trigger_phase, target)
            elif motion_mode == "point-to-point":
                motion_start = _anchor_position(
                    kind=trigger.get("motion_start_kind", "event"),
                    normalized_row=trigger.get("motion_start_row", 0.5),
                    normalized_column=trigger.get("motion_start_column", 0.0),
                    cell_row=trigger.get("motion_start_cell_row", 0),
                    cell_column=trigger.get("motion_start_cell_column", 0),
                    region=trigger.get("motion_start_region"),
                    target=target,
                    event=event,
                )
                motion_end = _anchor_position(
                    kind=trigger.get("motion_end_kind", "normalized"),
                    normalized_row=trigger.get("motion_end_row", 0.5),
                    normalized_column=trigger.get("motion_end_column", 1.0),
                    cell_row=trigger.get("motion_end_cell_row", 0),
                    cell_column=trigger.get("motion_end_cell_column", 0),
                    region=trigger.get("motion_end_region"),
                    target=target,
                    event=event,
                )
                trigger_motion_head = _lerp_position(motion_start, motion_end, trigger_phase)

            trigger_cells = _region_cells(
                trigger.get("region"),
                target,
            )
            trigger_active = set(trigger_cells)
            origin_cell = _destination_cell(trigger, event, target)
            if trigger_motion_head is not None:
                moving_cell = _nearest_active_cell(trigger_motion_head, target)
                if moving_cell is not None:
                    origin_cell = moving_cell

            if response == "pulse-cell":
                if origin_cell is None:
                    origin_cell = (
                        int(trigger["row"]),
                        int(trigger["column"]),
                    )
                if origin_cell in active and origin_cell in trigger_active:
                    canvas.mix(
                        origin_cell,
                        _colour_for(trigger, trigger_phase, target, origin_cell),
                        strength,
                    )

            elif response == "ripple":
                if origin_cell is None:
                    continue

                max_distance = max(
                    (
                        _cell_distance(origin_cell, cell)
                        for cell in trigger_cells
                    ),
                    default=0,
                )
                radius = progress * max(1, max_distance)

                for cell in trigger_cells:
                    distance = _cell_distance(origin_cell, cell)
                    band = max(
                        0.0,
                        1.0 - abs(distance - radius),
                    )
                    if band > 0.0:
                        canvas.mix(
                            cell,
                            _colour_for(trigger, trigger_phase, target, cell),
                            band * strength,
                        )

            elif response == "sweep":
                direction = int(trigger.get("direction", 1))
                position_count = max(
                    1,
                    spatial_position_count(
                        trigger_cells,
                        direction,
                    ),
                )
                half_width = max(
                    1.0 / position_count,
                    0.05,
                )
                head = progress

                for row, column in trigger_cells:
                    position = directional_position(
                        row,
                        column,
                        target.rows,
                        target.columns,
                        direction,
                    )
                    band = max(
                        0.0,
                        1.0
                        - abs(position - head) / half_width,
                    )
                    if band > 0.0:
                        canvas.mix(
                            (row, column),
                            _colour_for(trigger, trigger_phase, target, (row, column)),
                            band * strength,
                        )

            else:
                for cell in trigger_cells:
                    canvas.mix(
                        cell,
                        _colour_for(trigger, trigger_phase, target, cell),
                        strength,
                    )

        self._composer_trigger_events = alive

        frame = canvas.frame()
        frame.validate()
        return frame

SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id=__ID__,
        name=__NAME__,
        description=__DESCRIPTION__,
        effect_class=__CLASS__,
        input_capabilities=__INPUT_CAPABILITIES__,
        render_targets=__RENDER_TARGETS__,
        parameters=(
            EffectParameterSpec(
                id="colour1",
                label="Primary colour",
                kind="colour",
                default=(80, 120, 255),
            ),
            EffectParameterSpec(
                id="colour2",
                label="Secondary colour",
                kind="colour",
                default=(255, 80, 160),
            ),
        ),
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
'''
        return (
            template
            .replace("__TARGET_LAYERS__", target_layers_literal)
            .replace("__TARGET_REGIONS__", target_regions_literal)
            .replace("__TRIGGERS__", triggers_literal)
            .replace("__COMPOSER_PROJECT__", composer_project_literal)
            .replace("__INPUT_CAPABILITIES__", repr(input_capabilities))
            .replace("__RENDER_TARGETS__", repr(render_targets))
            .replace("__DESIGN_ROWS__", repr(design_rows))
            .replace("__DESIGN_COLUMNS__", repr(design_columns))
            .replace("__CLASS__", class_name)
            .replace("__ID__", repr(effect_id))
            .replace("__NAME__", repr(name))
            .replace("__DESCRIPTION__", repr(description))
            .replace("__ANIMATED__", repr(animated))
        )

    def _composer_refresh_source_preview(self):
        try:
            generated = self._composer_generated_source()
            ast.parse(generated)
        except Exception as exc:
            self.composer_source_preview.setPlainText(
                f"Generation error: {type(exc).__name__}: {exc}"
            )
            return
        self.composer_source_preview.setPlainText(generated)

    def _composer_generate_to_source(self):
        try:
            generated = self._composer_generated_source()
            ast.parse(generated)
        except Exception as exc:
            self.status_label.setText(
                f"Visual Composer generation blocked: "
                f"{type(exc).__name__}: {exc}"
            )
            return None
        self.stop_live_preview(silent=True)
        if self._composer_output_path is not None:
            self.loaded_path = Path(self._composer_output_path)
            self.path_edit.setPlainText(str(self.loaded_path))
            self.composer_file_label.setText(
                f"Plugin file: {self.loaded_path}"
            )
        else:
            self.loaded_path = None
            self.path_edit.clear()
            self.composer_file_label.setText("Plugin file: not chosen")
        self.source_edit.setPlainText(generated)
        self.source_edit.document().setModified(True)
        self._validated_developer_source = None
        self.preview_enabled = False
        self.spec = None
        self.specs = []
        self.effect_combo.clear()
        self.effect_combo.setEnabled(False)
        self.preview.clear_frame()
        self.elapsed = 0.0
        self._update_developer_workflow_state()
        self.status_label.setText(
            "Visual composition generated normal Serpent Python. "
            "Validate it before previewing or installing."
        )
        return generated

    def _composer_generate_and_validate(self):
        generated = self._composer_generate_to_source()
        if generated is None:
            return False
        return self.validate_source()

    def _composer_open_generated_code(self):
        if not self.source_edit.toPlainText().strip():
            generated = self._composer_generate_to_source()
            if not generated:
                return False
        self.source_edit.setVisible(True)
        self.source_edit.setFocus()
        self._composer_set_action_status(
            "Advanced Python focused. Edits here share Validate, Save, Preview, and Install."
        )
        return True

    def _composer_choose_output_file(self):
        effect_id = self._creator_slug(self.composer_id.text())
        suggested_name = (effect_id or "serpent-effect") + ".py"
        project_dir = ROOT / "projects" / "effects"
        project_dir.mkdir(parents=True, exist_ok=True)
        start = (
            Path(self._composer_output_path)
            if self._composer_output_path is not None
            else project_dir / suggested_name
        )
        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Create Composer Plugin File",
            str(start),
            "Python effect (*.py);;All files (*)",
        )
        if not filename:
            return False
        path = Path(filename).expanduser()
        if path.suffix.casefold() != ".py":
            path = path.with_suffix(".py")
        self._composer_output_path = path
        self.loaded_path = path

        path_id = self._creator_slug(path.stem)
        current_id = self._creator_slug(self.composer_id.text())
        current_name = self.composer_name.text().strip()
        if current_id in {"", "my-visual-effect", "visual-effect"} and path_id:
            self.composer_id.setText(path_id)
        if current_name in {"", "My Visual Effect", "Visual Effect"} and path_id:
            self.composer_name.setText(
                " ".join(part.capitalize() for part in path_id.split("-"))
            )

        self.path_edit.setPlainText(str(path))
        self.composer_file_label.setText(f"Plugin file: {path}")
        self.status_label.setText(
            "Composer plugin file selected. Your visual composition was "
            "preserved. Generate + Validate & Preview, then Save."
        )
        self._update_developer_workflow_state()
        return True

    def _composer_legacy_project_payload(self, tree):
        """Recover known pre-metadata Visual Composer output without executing it."""
        literal_names = {
            "_COMPOSER_DESIGN_ROWS",
            "_COMPOSER_DESIGN_COLUMNS",
            "_TARGET_LAYERS",
            "_TARGET_REGIONS",
            "_TRIGGERS",
        }
        literals = {}

        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [
                target.id
                for target in node.targets
                if isinstance(target, ast.Name)
            ]
            for name in names:
                if name not in literal_names:
                    continue
                try:
                    literals[name] = ast.literal_eval(node.value)
                except (ValueError, TypeError, SyntaxError):
                    raise ValueError(
                        f"legacy Composer field {name} is not a safe literal"
                    )

        if not literal_names.issubset(literals):
            return None

        function_names = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
        }
        required_generator_fingerprints = {
            "_region_cells",
            "_timeline_state",
            "_colour_for",
            "_trigger_matches",
        }
        if not required_generator_fingerprints.issubset(function_names):
            return None

        plugin_call = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name)
                and target.id == "SERPENT_EFFECT_PLUGINS"
                for target in node.targets
            ):
                continue
            for call in ast.walk(node.value):
                if not isinstance(call, ast.Call):
                    continue
                func = call.func
                call_name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else ""
                )
                if call_name == "EffectPluginSpec":
                    plugin_call = call
                    break
            if plugin_call is not None:
                break

        if plugin_call is None:
            return None

        plugin_fields = {}
        for keyword in plugin_call.keywords:
            if keyword.arg not in {
                "id",
                "name",
                "description",
                "render_targets",
                "input_capabilities",
            }:
                continue
            try:
                plugin_fields[keyword.arg] = ast.literal_eval(keyword.value)
            except (ValueError, TypeError, SyntaxError):
                if keyword.arg in {"id", "name", "description"}:
                    raise ValueError(
                        f"legacy Composer plugin field {keyword.arg} "
                        "is not a safe literal"
                    )

        effect_id = plugin_fields.get("id")
        effect_name = plugin_fields.get("name")
        description = plugin_fields.get("description")
        if not isinstance(effect_id, str) or not effect_id.strip():
            return None
        if not isinstance(effect_name, str) or not effect_name.strip():
            return None
        if not isinstance(description, str):
            description = "Created with Serpent Visual Composer."

        rows = literals["_COMPOSER_DESIGN_ROWS"]
        columns = literals["_COMPOSER_DESIGN_COLUMNS"]
        target_layers_raw = literals["_TARGET_LAYERS"]
        target_regions_raw = literals["_TARGET_REGIONS"]
        triggers_raw = literals["_TRIGGERS"]

        if (
            not isinstance(rows, int)
            or isinstance(rows, bool)
            or not 1 <= rows <= 64
            or not isinstance(columns, int)
            or isinstance(columns, bool)
            or not 1 <= columns <= 64
        ):
            raise ValueError("legacy Composer geometry is outside the supported 1..64 range")

        if not isinstance(target_layers_raw, dict) or not target_layers_raw:
            raise ValueError("legacy Composer target layers are missing")
        if not isinstance(target_regions_raw, dict):
            raise ValueError("legacy Composer target regions are invalid")
        if not isinstance(triggers_raw, (tuple, list)):
            raise ValueError("legacy Composer triggers are invalid")

        target_layers = {}
        target_groups = {}
        target_regions = {}
        target_region_selections = {}
        target_geometries = {}

        for device_class, raw_layers in target_layers_raw.items():
            if not isinstance(device_class, str) or not device_class:
                raise ValueError("legacy Composer target name is invalid")
            if not isinstance(raw_layers, (tuple, list)):
                raise ValueError(
                    f"legacy Composer layers for {device_class!r} are invalid"
                )

            layers = []
            for layer in raw_layers:
                if not isinstance(layer, dict) or "kind" not in layer:
                    raise ValueError(
                        f"legacy Composer layer for {device_class!r} is invalid"
                    )
                layers.append(copy.deepcopy(layer))

            raw_regions = target_regions_raw.get(device_class, {})
            if not isinstance(raw_regions, dict):
                raise ValueError(
                    f"legacy Composer regions for {device_class!r} are invalid"
                )

            regions = {}
            for region_name, cells in raw_regions.items():
                if not isinstance(region_name, str):
                    raise ValueError("legacy Composer region name is invalid")
                if not isinstance(cells, (tuple, list, set)):
                    raise ValueError(
                        f"legacy Composer region {region_name!r} cells are invalid"
                    )
                normalized_cells = []
                for cell in cells:
                    if (
                        not isinstance(cell, (tuple, list))
                        or len(cell) != 2
                        or not all(isinstance(value, int) for value in cell)
                    ):
                        raise ValueError(
                            f"legacy Composer region {region_name!r} "
                            "contains an invalid cell"
                        )
                    row, column = int(cell[0]), int(cell[1])
                    if 0 <= row < rows and 0 <= column < columns:
                        normalized_cells.append((row, column))
                regions[region_name] = tuple(normalized_cells)

            existing_geometry = self._composer_target_geometries.get(
                device_class
            )
            geometry = None
            if isinstance(existing_geometry, dict):
                try:
                    existing_rows = int(existing_geometry.get("rows", 0))
                    existing_columns = int(
                        existing_geometry.get("columns", 0)
                    )
                except (TypeError, ValueError):
                    existing_rows = 0
                    existing_columns = 0
                if existing_rows == rows and existing_columns == columns:
                    geometry = copy.deepcopy(existing_geometry)

            if geometry is None:
                geometry = {
                    "rows": rows,
                    "columns": columns,
                    "active_cells": tuple(
                        (row, column)
                        for row in range(rows)
                        for column in range(columns)
                    ),
                    "device_class": device_class,
                }

            target_layers[device_class] = layers
            target_groups[device_class] = []
            target_regions[device_class] = regions
            target_region_selections[device_class] = set()
            target_geometries[device_class] = geometry

        triggers = []
        for trigger in triggers_raw:
            if not isinstance(trigger, dict):
                raise ValueError("legacy Composer trigger is invalid")
            triggers.append(copy.deepcopy(trigger))

        render_targets = plugin_fields.get("render_targets")
        active_device_class = None
        if isinstance(render_targets, (tuple, list)):
            for candidate in render_targets:
                if candidate in target_layers:
                    active_device_class = candidate
                    break
        if active_device_class is None:
            active_device_class = next(iter(target_layers))

        state = {
            "active_device_class": active_device_class,
            "target_layers": target_layers,
            "target_groups": target_groups,
            "target_regions": target_regions,
            "target_region_selections": target_region_selections,
            "target_geometries": target_geometries,
            "triggers": triggers,
            "layer_counter": sum(
                len(layers) for layers in target_layers.values()
            ),
            "group_counter": 0,
        }

        return {
            "schema": 1,
            "name": effect_name,
            "id": effect_id,
            "description": description,
            "state": state,
            "legacy_import": True,
        }

    def _composer_load_installed_effect(self):
        installed_dir = (ROOT / "plugins" / "effects").resolve()

        filename, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Open Installed Effect",
            str(installed_dir),
            "Python effect (*.py);;All files (*)",
        )
        if not filename:
            return False

        source_path = Path(filename).expanduser()

        try:
            resolved = source_path.resolve()
        except OSError as exc:
            self._composer_set_action_status(
                "Could not resolve installed effect path: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        if resolved.parent != installed_dir:
            self._composer_set_action_status(
                "Open Installed Effect is read-only and accepts files only from "
                f"{installed_dir}."
            )
            return False

        try:
            source_text = resolved.read_text(encoding="utf-8")
            tree = ast.parse(source_text, filename=str(resolved))
        except (OSError, UnicodeError, SyntaxError) as exc:
            self._composer_set_action_status(
                "Could not read installed effect: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        effect_ids = []
        for candidate in ast.walk(tree):
            if not isinstance(candidate, ast.Call):
                continue
            func = candidate.func
            call_name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else ""
            )
            if call_name != "EffectPluginSpec":
                continue

            for keyword in candidate.keywords:
                if keyword.arg != "id":
                    continue
                try:
                    value = ast.literal_eval(keyword.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(value, str) and value.strip():
                    effect_ids.append(value.strip())
                break

        effect_ids = list(dict.fromkeys(effect_ids))
        if not effect_ids:
            self._composer_set_action_status(
                "Selected installed effect file exposes no literal EffectPluginSpec id."
            )
            return False

        origin_id = effect_ids[0]

        developer_index = self.mode_combo.findData(self.MODE_DEVELOPER)
        if developer_index >= 0:
            self.mode_combo.setCurrentIndex(developer_index)

        return self._composer_load_installed_source_in_memory(
            origin_id,
            source_text,
            virtual_name=resolved.name,
        )

    @staticmethod
    def _composer_raw_python_identity(tree, source_path):
        identity = {
            "name": source_path.stem.replace("-", " ").replace("_", " ").title(),
            "id": EffectsWorkshopPanel._creator_slug(source_path.stem),
            "description": "Advanced Python effect.",
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            call_name = (
                func.id if isinstance(func, ast.Name)
                else func.attr if isinstance(func, ast.Attribute)
                else ""
            )
            if call_name != "EffectPluginSpec":
                continue
            values = {}
            for keyword in node.keywords:
                if keyword.arg not in {"id", "name", "description"}:
                    continue
                try:
                    value = ast.literal_eval(keyword.value)
                except (ValueError, TypeError, SyntaxError):
                    continue
                if isinstance(value, str) and value.strip():
                    values[keyword.arg] = value.strip()
            if "id" in values:
                identity["id"] = EffectsWorkshopPanel._creator_slug(values["id"])
            if "name" in values:
                identity["name"] = values["name"]
            if "description" in values:
                identity["description"] = values["description"]
            break
        if not identity["id"]:
            identity["id"] = "advanced-python-effect"
        return identity

    def _composer_enter_raw_python_state(self, tree, source_path):
        identity = self._composer_raw_python_identity(tree, source_path)
        self.composer_name.setText(identity["name"])
        self.composer_id.setText(identity["id"])
        self.composer_description.setText(identity["description"])
        empty_state = {
            "intent": "device-specific",
            "active_device_class": None,
            "target_layers": {},
            "target_groups": {},
            "target_regions": {},
            "target_region_selections": {},
            "target_geometries": {},
            "triggers": [],
            "layer_counter": 1,
            "group_counter": 1,
        }
        self._composer_restore_state(empty_state)
        self._composer_history_undo.clear()
        self._composer_history_redo.clear()
        self._composer_clipboard = None
        self._composer_update_history_buttons()
        self._composer_raw_python_mode = True

    def _composer_leave_raw_python_state(self):
        self._composer_raw_python_mode = False

    def _composer_load_installed_source_in_memory(
        self,
        effect_id,
        source_text,
        *,
        virtual_name=None,
    ):
        source_text = str(source_text)
        effect_id = str(effect_id).strip()
        virtual_path = Path(
            virtual_name
            or f"{self._creator_slug(effect_id or 'installed-effect')}.py"
        )

        try:
            tree = ast.parse(source_text, filename=str(virtual_path))
        except SyntaxError as exc:
            self._composer_set_action_status(
                "Could not open installed effect in memory: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        payload_node = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "SERPENT_COMPOSER_PROJECT"
                for target in node.targets
            ):
                payload_node = node.value
                break

        raw_python = False
        payload = None

        if payload_node is None:
            try:
                payload = self._composer_legacy_project_payload(tree)
            except ValueError as exc:
                self._composer_set_action_status(
                    f"Legacy Composer recovery refused: {exc}"
                )
                return False
            if payload is None:
                raw_python = True
        else:
            try:
                payload = ast.literal_eval(payload_node)
            except (ValueError, TypeError, SyntaxError) as exc:
                self._composer_set_action_status(
                    "Composer metadata is not a safe literal payload: "
                    f"{type(exc).__name__}: {exc}"
                )
                return False

        if raw_python:
            self._composer_enter_raw_python_state(tree, virtual_path)
        else:
            if not isinstance(payload, dict) or payload.get("schema") != 1:
                self._composer_set_action_status(
                    "Unsupported Visual Composer project metadata version."
                )
                return False

            state = payload.get("state")
            if not isinstance(state, dict):
                self._composer_set_action_status(
                    "Visual Composer project metadata does not contain restorable state."
                )
                return False

            try:
                self.composer_name.setText(
                    str(payload.get("name", "Visual Effect"))
                )
                self.composer_id.setText(
                    self._creator_slug(
                        str(payload.get("id", "visual-effect"))
                    )
                )
                self.composer_description.setText(
                    str(
                        payload.get(
                            "description",
                            "Created with Serpent Visual Composer.",
                        )
                    )
                )
                self._composer_restore_state(state)
                self._composer_leave_raw_python_state()
            except (KeyError, TypeError, ValueError) as exc:
                self._composer_set_action_status(
                    "Visual Composer state could not be restored: "
                    f"{type(exc).__name__}: {exc}"
                )
                return False

        self._composer_output_path = None
        self.loaded_path = None
        self._composer_installed_origin_id = effect_id

        display = (
            "Unsaved — derived from installed effect "
            f"{effect_id}"
        )
        self.path_edit.setPlainText(display)
        self.composer_file_label.setText(
            f"Plugin file: {display}"
        )

        self.source_edit.setPlainText(source_text)
        self.source_edit.document().setModified(False)
        self.composer_source_preview.setPlainText(source_text)

        self._validated_developer_source = None
        self.preview_enabled = False
        self.spec = None
        self.specs = []
        self._update_developer_workflow_state()
        self._composer_refresh_source_preview()

        if raw_python:
            self.source_edit.setFocus()

        self._composer_set_action_status(
            f"Opened installed effect {effect_id!r} in memory. "
            "No project file was created. Save/Save As creates your derived effect."
        )
        return True

    def _composer_load_effect(
        self,
        checked=False,
        start_dir=None,
        source_path=None,
        *,
        template_copy=False,
    ):
        project_dir = ROOT / "projects" / "effects"
        project_dir.mkdir(parents=True, exist_ok=True)

        if source_path is None:
            initial_dir = (
                Path(start_dir)
                if start_dir is not None
                else project_dir
            )

            filename, _selected_filter = QFileDialog.getOpenFileName(
                self,
                "Open Effect",
                str(initial_dir),
                "Python effect (*.py);;All files (*)",
            )
            if not filename:
                return False

            source_path = Path(filename).expanduser()
        else:
            source_path = Path(source_path).expanduser()
        try:
            source = source_path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(source_path))
        except (OSError, UnicodeError, SyntaxError) as exc:
            self._composer_set_action_status(
                "Could not open effect: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        payload_node = None
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if any(
                isinstance(target, ast.Name)
                and target.id == "SERPENT_COMPOSER_PROJECT"
                for target in node.targets
            ):
                payload_node = node.value
                break

        legacy_import = False
        raw_python = False
        if payload_node is None:
            try:
                payload = self._composer_legacy_project_payload(tree)
            except ValueError as exc:
                self._composer_set_action_status(
                    f"Legacy Composer recovery refused: {exc}"
                )
                return False
            if payload is None:
                raw_python = True
                payload = None
            else:
                legacy_import = True
        else:
            try:
                payload = ast.literal_eval(payload_node)
            except (ValueError, TypeError, SyntaxError) as exc:
                self._composer_set_action_status(
                    "Composer metadata is not a safe literal payload: "
                    f"{type(exc).__name__}: {exc}"
                )
                return False

        if not raw_python:
            if not isinstance(payload, dict) or payload.get("schema") != 1:
                self._composer_set_action_status(
                    "Unsupported Visual Composer project metadata version."
                )
                return False
            state = payload.get("state")
            if not isinstance(state, dict):
                self._composer_set_action_status(
                    "Visual Composer project metadata does not contain restorable state."
                )
                return False
            try:
                self.composer_name.setText(str(payload.get("name", "Visual Effect")))
                self.composer_id.setText(
                    self._creator_slug(str(payload.get("id", "visual-effect")))
                )
                self.composer_description.setText(
                    str(payload.get("description", "Created with Serpent Visual Composer."))
                )
                self._composer_restore_state(state)
            except (KeyError, TypeError, ValueError) as exc:
                self._composer_set_action_status(
                    "Visual Composer state could not be restored: "
                    f"{type(exc).__name__}: {exc}"
                )
                return False

        if raw_python:
            self._composer_enter_raw_python_state(tree, source_path)
        else:
            self._composer_leave_raw_python_state()

        try:
            installed_dir = (ROOT / "plugins" / "effects").resolve()
            resolved = source_path.resolve()
            loaded_from_install = resolved.parent == installed_dir
        except OSError:
            loaded_from_install = False

        if loaded_from_install:
            if raw_python:
                base_id = self._creator_slug(source_path.stem) or "installed-effect"
            else:
                base_id = (
                    self._creator_slug(self.composer_id.text())
                    or self._creator_slug(source_path.stem)
                    or "installed-effect"
                )

            suffix = "-template" if template_copy else ""
            candidate_name = f"{base_id}{suffix}.py"
            output_path = project_dir / candidate_name

            if template_copy:
                counter = 2
                while output_path.exists():
                    output_path = project_dir / (
                        f"{base_id}-template-{counter}.py"
                    )
                    counter += 1
        else:
            output_path = source_path

        self._composer_output_path = output_path
        self.loaded_path = output_path
        self._composer_installed_origin_id = None

        if loaded_from_install:
            try:
                self._atomic_write(output_path, source)
            except (OSError, RuntimeError, UnicodeError) as exc:
                self._composer_set_action_status(
                    "Could not create safe installed-effect working copy: "
                    f"{type(exc).__name__}: {exc}"
                )
                return False

        self.path_edit.setPlainText(str(output_path))
        self.composer_file_label.setText(f"Plugin file: {output_path}")
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(False)
        self.composer_source_preview.setPlainText(source)
        self._validated_developer_source = None
        self.preview_enabled = False
        self.spec = None
        self.specs = []
        self._update_developer_workflow_state()
        self._composer_refresh_source_preview()

        if raw_python:
            self.source_edit.setFocus()
            if loaded_from_install:
                self._composer_set_action_status(
                    "Installed effect opened as a safe Advanced Python template: "
                    f"{output_path}. The installed source is untouched. "
                    "Rename its effect identity before installing if you want to keep both effects."
                )
            else:
                self._composer_set_action_status(
                    "Opened as Advanced Python. Visual controls were not reconstructed; "
                    "Guide, Validate, Save, Preview, Install, and contextual Uninstall remain available."
                )
        elif legacy_import and loaded_from_install:
            self._composer_set_action_status(
                "Recovered legacy Composer effect into a safe authoring working copy: "
                f"{output_path}. Rename/edit it, Generate + Validate, Save, then Install."
            )
        elif legacy_import:
            self._composer_set_action_status(
                "Recovered legacy Composer effect. Rename/edit it, Generate + Validate, "
                "Save, then Install."
            )
        elif loaded_from_install:
            self._composer_set_action_status(
                "Loaded installed Composer effect into a safe authoring working copy: "
                f"{output_path}. Generate + Validate, Save, then Install."
            )
        else:
            self._composer_set_action_status(
                "Composer effect loaded. Modify it, then Generate + Validate, Save, and Install."
            )
        return True

    def _composer_set_action_status(self, message):
        text = str(message).strip()
        if hasattr(self, "composer_action_status"):
            self.composer_action_status.setText(text)
        self.status_label.setText(text)

    def _composer_validated_source_for_save(self):
        try:
            generated = self._composer_generated_source()
            ast.parse(generated)
        except (RuntimeError, ValueError, TypeError, SyntaxError) as exc:
            raise RuntimeError(
                "Composer generation is currently invalid: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        current = self.source_edit.toPlainText()
        validated = (
            bool(current.strip())
            and self.preview_enabled
            and self.spec is not None
            and self._validated_developer_source == current
        )
        if not validated:
            raise RuntimeError(
                "Generate + Validate Preview successfully before saving."
            )
        if generated != current:
            raise RuntimeError(
                "Visual controls changed since the validated source was generated. "
                "Generate + Validate Preview again before saving."
            )
        return current

    def _composer_save_as(self):
        project_dir = ROOT / "projects" / "effects"
        project_dir.mkdir(parents=True, exist_ok=True)
        effect_id = self._creator_slug(self.composer_id.text()) or "visual-effect"
        suggested = project_dir / f"{effect_id}.py"

        filename, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "Save Effect As",
            str(suggested),
            "Python effect (*.py);;All files (*)",
        )
        if not filename:
            self._composer_set_action_status("Save As cancelled.")
            return False

        destination = Path(filename).expanduser()
        if destination.suffix.lower() != ".py":
            destination = destination.with_suffix(".py")

        try:
            source = self._composer_validated_source_for_save()
        except RuntimeError as exc:
            self._composer_set_action_status(f"Save As blocked: {exc}")
            return False

        previous_output = self._composer_output_path
        previous_loaded = self.loaded_path
        try:
            self._composer_output_path = destination
            self.loaded_path = destination
            self.path_edit.setPlainText(str(destination))
            self.composer_file_label.setText(f"Plugin file: {destination}")
            self._atomic_write(destination, source)
            self.source_edit.document().setModified(False)
            if not destination.is_file():
                raise RuntimeError("atomic writer did not create the selected file.")
            if destination.read_text(encoding="utf-8") != source:
                raise RuntimeError("saved file does not match the validated source.")
        except (OSError, RuntimeError, UnicodeError) as exc:
            self._composer_output_path = previous_output
            self.loaded_path = previous_loaded
            if previous_loaded is not None:
                self.path_edit.setPlainText(str(previous_loaded))
                self.composer_file_label.setText(f"Plugin file: {previous_loaded}")
            self._composer_set_action_status(
                f"Save As failed: {type(exc).__name__}: {exc}"
            )
            return False

        self._composer_installed_origin_id = None
        self._composer_set_action_status(f"Saved As: {destination}")
        self._update_developer_workflow_state()
        return True

    def _installed_plugin_path_for_id(self, effect_id):
        plugins_dir = (ROOT / "plugins" / "effects").resolve()
        matches = []

        for path in sorted(plugins_dir.glob("*.py")):
            try:
                source = path.read_text(encoding="utf-8")
                tree = ast.parse(source, filename=str(path))
            except (OSError, UnicodeError, SyntaxError):
                continue

            found = False
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(target, ast.Name)
                    and target.id == "SERPENT_EFFECT_PLUGINS"
                    for target in node.targets
                ):
                    continue
                for call in ast.walk(node.value):
                    if not isinstance(call, ast.Call):
                        continue
                    func = call.func
                    call_name = (
                        func.id
                        if isinstance(func, ast.Name)
                        else func.attr
                        if isinstance(func, ast.Attribute)
                        else ""
                    )
                    if call_name != "EffectPluginSpec":
                        continue
                    for keyword in call.keywords:
                        if keyword.arg != "id":
                            continue
                        try:
                            value = ast.literal_eval(keyword.value)
                        except (ValueError, TypeError, SyntaxError):
                            continue
                        if value == effect_id:
                            found = True
                            break
                    if found:
                        break
                if found:
                    break

            if found:
                resolved = path.resolve()
                if resolved.parent == plugins_dir:
                    matches.append(resolved)

        if len(matches) == 1:
            return matches[0]
        if not matches:
            return None
        raise RuntimeError(
            f"Multiple installed plugin files register effect id {effect_id!r}."
        )

    def _composer_uninstall_current(self):
        from serpent_core.effects import reload_effect_plugins

        effect_id = self._creator_slug(self.composer_id.text())
        if not effect_id:
            self._composer_set_action_status(
                "Uninstall failed: the Composer Effect ID is empty."
            )
            return False

        try:
            path = self._installed_plugin_path_for_id(effect_id)
        except RuntimeError as exc:
            self._composer_set_action_status(f"Uninstall failed: {exc}")
            return False

        if path is None:
            self._composer_set_action_status(
                f"Not installed: {effect_id}. The authoring project was not touched."
            )
            return False

        plugins_dir = (ROOT / "plugins" / "effects").resolve()
        try:
            resolved = path.resolve()
        except OSError as exc:
            self._composer_set_action_status(
                f"Uninstall failed resolving plugin path: {exc}"
            )
            return False

        if resolved.parent != plugins_dir:
            self._composer_set_action_status(
                "Uninstall refused: target is outside the user plugins/effects directory."
            )
            return False

        try:
            self.stop_live_preview(silent=True)
        except Exception:
            pass

        previous_bytes = None
        try:
            previous_bytes = resolved.read_bytes()
            resolved.unlink()

            process = subprocess.run(
                [
                    str(ROOT / "serpent.py"),
                    "effect",
                    "reload",
                ],
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                    or "serpent effect reload failed"
                )

            reload_effect_plugins()
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            if previous_bytes is not None and not resolved.exists():
                try:
                    resolved.write_bytes(previous_bytes)
                    subprocess.run(
                        [
                            str(ROOT / "serpent.py"),
                            "effect",
                            "reload",
                        ],
                        text=True,
                        capture_output=True,
                        timeout=8,
                    )
                    reload_effect_plugins()
                except Exception:
                    pass

            self._composer_set_action_status(
                f"Uninstall failed safely: {type(exc).__name__}: {exc}"
            )
            return False

        try:
            self._sync_installed_catalog_after_mutation(
                removed_effect_id=effect_id,
                navigate=True,
            )
        except RuntimeError as exc:
            self._composer_set_action_status(
                f"Uninstalled file but catalog synchronization failed: {exc}"
            )
            return False

        self._update_developer_workflow_state()

        self._composer_set_action_status(
            f"Uninstalled: {effect_id}. "
            "Authoring project/source file preserved."
        )
        return True

    def _composer_save_generated(self):
        if getattr(self, "_composer_installed_origin_id", None):
            self._composer_set_action_status(
                "Installed effects are read-only origins. "
                "Save creates a separate user project."
            )
            return self._composer_save_as()

        if self._composer_output_path is None:
            self._composer_set_action_status(
                "Save needs an authoring file first. Use New Effect or Save As."
            )
            return False
        try:
            source = self._composer_validated_source_for_save()
        except RuntimeError as exc:
            self._composer_set_action_status(f"Save blocked: {exc}")
            return False

        self.loaded_path = Path(self._composer_output_path)
        self.path_edit.setPlainText(str(self.loaded_path))
        self.composer_file_label.setText(f"Plugin file: {self.loaded_path}")
        try:
            self._atomic_write(self.loaded_path, source)
            self.source_edit.document().setModified(False)
            if not self.loaded_path.is_file():
                raise RuntimeError("the authoring file was not created.")
            if self.loaded_path.read_text(encoding="utf-8") != source:
                raise RuntimeError("saved file does not match the validated source.")
        except (OSError, UnicodeError, RuntimeError) as exc:
            self._composer_set_action_status(
                f"Save failed: {type(exc).__name__}: {exc}"
            )
            return False
        self._composer_set_action_status(f"Saved: {self.loaded_path}")
        return True

    def _composer_install_generated(self):
        if self._composer_output_path is None:
            self.status_label.setText(
                "Choose Create Plugin File… first so the Composer effect has "
                "an authoring source file before installation."
            )
            return False

        self.loaded_path = Path(self._composer_output_path)
        self.path_edit.setPlainText(str(self.loaded_path))

        expected_id = self._creator_slug(self.composer_id.text())
        filename_id = self._creator_slug(self.loaded_path.stem)

        if (
            expected_id in {"my-visual-effect", "visual-effect"}
            and filename_id
            and filename_id != expected_id
        ):
            self.status_label.setText(
                "Install blocked: the Composer still uses its template Effect ID "
                f"{expected_id!r}, while the project file is {filename_id!r}. "
                "Set the intended Effect ID, then Generate + Validate again."
            )
            return False

        if self.spec is not None and expected_id and self.spec.id != expected_id:
            self.status_label.setText(
                "Composer identity changed after generation/validation. "
                f"Current Composer ID is {expected_id!r}, but validated source "
                f"registers {self.spec.id!r}. Generate + Validate again before installing."
            )
            return False

        current_generated = self._composer_generated_source()
        current_editor_source = self.source_edit.toPlainText()
        if current_editor_source != current_generated:
            self._validated_developer_source = None
            self.preview_enabled = False
            self.status_label.setText(
                "Composer state changed since the last generation. "
                "Run Generate + Validate Preview again before installing."
            )
            self._update_developer_workflow_state()
            return False

        before = self.status_label.text()
        result = self.promote_effect()
        after = self.status_label.text().strip()
        if result is False:
            self._composer_set_action_status(after or "Install did not complete.")
            return False
        self._composer_set_action_status(after or f"Installed: {expected_id}")
        return True if result is None else result

    def _toggle_effect_guide(self, checked):
        self.guide_toggle_button.setText(
            "Python / Effect Guide ▾" if checked else "Python / Effect Guide ▸"
        )
        self.guide_container.setVisible(
            bool(checked)
            and not self._is_installed_mode()
            and self.authoring_surface_combo.currentData() == "composer"
        )

    def _populate_effect_guide(self, query=""):
        query = str(query).strip().casefold()
        previous = (
            self.guide_topics.currentItem().data(
                Qt.ItemDataRole.UserRole
            )
            if self.guide_topics.currentItem() is not None
            else None
        )

        self.guide_topics.blockSignals(True)
        self.guide_topics.clear()

        for index, topic in enumerate(self.GUIDE_TOPICS):
            searchable = " ".join(
                (
                    topic["title"],
                    topic["symbols"],
                    topic["body"],
                )
            ).casefold()
            if query and query not in searchable:
                continue

            item = QListWidgetItem(topic["title"])
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(topic["symbols"])
            self.guide_topics.addItem(item)

            if index == previous:
                self.guide_topics.setCurrentItem(item)

        if (
            self.guide_topics.currentRow() < 0
            and self.guide_topics.count()
        ):
            self.guide_topics.setCurrentRow(0)

        self.guide_topics.blockSignals(False)
        self._show_current_guide_topic()

    def _filter_effect_guide(self, text):
        self._populate_effect_guide(text)

    def _guide_topic_changed(self, current, previous):
        self._show_current_guide_topic()

    def _show_current_guide_topic(self):
        item = self.guide_topics.currentItem()
        if item is None:
            self.guide_title.setText("No matching guide topic")
            self.guide_symbols.clear()
            self.guide_text.clear()
            self.guide_snippet.clear()
            self.guide_insert_button.setEnabled(False)
            self.guide_insert_button.setText("Insert Snippet")
            return

        index = item.data(Qt.ItemDataRole.UserRole)
        topic = self.GUIDE_TOPICS[int(index)]

        self.guide_title.setText(topic["title"])
        self.guide_symbols.setText(
            "Authoritative symbols: " + topic["symbols"]
        )
        self.guide_text.setPlainText(topic["body"])
        self.guide_snippet.setPlainText(topic["snippet"])

        has_snippet = bool(topic["snippet"].strip())
        self.guide_insert_button.setEnabled(has_snippet)
        self.guide_insert_button.setText(
            topic["snippet_label"]
            if has_snippet
            else "No snippet for this topic"
        )

    def _insert_guide_snippet(self):
        item = self.guide_topics.currentItem()
        if item is None:
            return

        topic = self.GUIDE_TOPICS[
            int(item.data(Qt.ItemDataRole.UserRole))
        ]
        snippet = topic["snippet"]
        if not snippet.strip():
            return

        cursor = self.source_edit.textCursor()
        if (
            cursor.position() > 0
            and not self.source_edit.toPlainText()[
                : cursor.position()
            ].endswith("\n")
        ):
            cursor.insertText("\n")

        cursor.insertText(snippet)
        self.source_edit.setTextCursor(cursor)
        self.source_edit.setFocus()

        self.status_label.setText(
            f"Inserted Guide snippet: {topic['title']}. "
            "Review and adapt it to your effect, then Validate & Preview."
        )

    def _update_developer_workflow_state(self):
        if self._is_installed_mode():
            return

        source = self.source_edit.toPlainText()
        has_source = bool(source.strip())
        validated = (
            has_source
            and self.preview_enabled
            and self.spec is not None
            and self._validated_developer_source == source
        )
        stale_validation = (
            has_source
            and self._validated_developer_source is not None
            and self._validated_developer_source != source
        )

        self.validate_button.setEnabled(has_source)
        self.save_button.setEnabled(has_source)
        self.promote_button.setEnabled(validated)
        if hasattr(self, "composer_save"):
            self.composer_save.setEnabled(has_source)
        if hasattr(self, "composer_install"):
            self.composer_install.setEnabled(validated)
        if hasattr(self, "composer_uninstall"):
            effect_id = self._creator_slug(self.composer_id.text())
            installed_path = self._installed_plugin_path_for_id(effect_id) if effect_id else None
            self.composer_uninstall.setEnabled(installed_path is not None)

        if not has_source:
            message = (
                "Step 1 — Start with New Effect… or Browse… an "
                "existing plugin."
            )
        elif stale_validation:
            message = (
                "Step 2 — Source changed since validation. Keep editing, "
                "then Validate & Preview again."
            )
        elif not validated:
            message = (
                "Step 3 — Source is ready. Validate & Preview it in the "
                "isolated worker."
            )
        else:
            message = (
                "Step 4 — Validated and preview-ready. Install to Serpent "
                "when you are happy with it."
            )

        self.developer_step_status.setText(message)

    def _developer_source_changed(self):
        if not self._is_installed_mode():
            self._update_developer_workflow_state()

    def _handle_reply(self, action, payload):
        if not payload.get("ok"):
            self.preview_enabled = False
            errors = payload.get("errors") or ["Unknown worker error"]
            self.status_label.setText(
                f"{payload.get('stage', action).title()} failed safely:\n"
                + "\n".join("✗ " + item for item in errors)
            )
            return

        if action == "load":
            self._apply_specs(payload)
            self.preview_enabled = self.spec is not None
            warnings = "\n".join(
                "! " + item for item in payload.get("warnings") or []
            )
            self.status_label.setText(
                f"Validated in asynchronous worker: {len(self.specs)} effect(s)."
                + (("\n" + warnings) if warnings else "")
            )
            if self.preview_enabled:
                self.render_now()
            return

        if action in {"select", "reset", "event"}:
            if action in {"select", "reset"}:
                self.preview_enabled = True
            self.render_now()
            return

        if action == "render":
            self.preview.set_frame(_Frame(payload["frame"]))

    def _apply_specs(self, payload):
        old = self.effect_combo.currentData()

        clear = getattr(self.effect_parameters, "_clear", None)
        if callable(clear):
            clear()
        cache = getattr(self.effect_parameters, "_cache", None)
        if isinstance(cache, dict):
            cache.clear()

        self.specs = [_Spec(item) for item in payload.get("specs") or []]

        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for spec in self.specs:
            self.effect_combo.addItem(spec.name, spec.id)

        preferred = payload.get("effect_id") or old
        index = self.effect_combo.findData(preferred)
        if index >= 0:
            self.effect_combo.setCurrentIndex(index)

        self.effect_combo.blockSignals(False)
        self.effect_combo.setEnabled(bool(self.specs))
        self._adopt_selected_spec()

    def _adopt_selected_spec(self):
        effect_id = self.effect_combo.currentData()
        self.spec = next(
            (spec for spec in self.specs if spec.id == effect_id),
            None,
        )
        if self.spec is not None:
            self.effect_parameters.set_spec(self.spec)

    def _browse_directory(self):
        plugin_directory = (ROOT / "plugins" / "effects").resolve()
        remembered = self.settings.value(
            "effect_lab/last_directory",
            "",
        )

        if remembered:
            candidate = Path(str(remembered)).expanduser()
            if candidate.is_dir():
                return candidate

        return plugin_directory

    def _remember_directory(self, path):
        directory = Path(path).expanduser().resolve()
        if directory.is_file():
            directory = directory.parent
        if directory.is_dir():
            self.settings.setValue(
                "effect_lab/last_directory",
                str(directory),
            )

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Serpent effect plugin",
            str(self._browse_directory()),
            "Python files (*.py);;All files (*)",
        )
        if path:
            self._remember_directory(path)
            self.path_edit.setPlainText(path)
            self.load_file()

    def load_file(self):
        raw = self.path_edit.toPlainText().strip()
        if not raw:
            self.status_label.setText("Choose a plugin file first.")
            return

        path = Path(raw).expanduser()
        try:
            source = path.read_text(encoding="utf-8")
        except Exception as exc:
            self.status_label.setText(
                f"Load failed: {type(exc).__name__}: {exc}"
            )
            return

        self.loaded_path = path.resolve()
        self._remember_directory(self.loaded_path)
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(False)
        self.validate_source()

    def validate_source(self):
        self.preview_enabled = False
        previous = self.effect_combo.currentData()

        # An in-memory template derived from an installed effect can register a
        # different candidate id (for example "spectrum-template" vs "spectrum").
        # Prefer the candidate source's literal plugin id when the combo still
        # carries the installed origin id.
        try:
            candidate_tree = ast.parse(self.source_edit.toPlainText())
            candidate_ids = []
            for candidate in ast.walk(candidate_tree):
                if not isinstance(candidate, ast.Call):
                    continue
                func = candidate.func
                call_name = (
                    func.id
                    if isinstance(func, ast.Name)
                    else func.attr
                    if isinstance(func, ast.Attribute)
                    else ""
                )
                if call_name != "EffectPluginSpec":
                    continue
                for keyword in candidate.keywords:
                    if keyword.arg != "id":
                        continue
                    try:
                        value = ast.literal_eval(keyword.value)
                    except (ValueError, TypeError, SyntaxError):
                        continue
                    if isinstance(value, str) and value.strip():
                        candidate_ids.append(value.strip())
                    break
            candidate_ids = list(dict.fromkeys(candidate_ids))
            if candidate_ids and previous not in candidate_ids:
                previous = candidate_ids[0]
        except SyntaxError:
            # The isolated worker remains authoritative for syntax diagnostics.
            pass

        # User-requested validation has priority over disposable preview work.
        # A render/event may be dropped; a Validate click must never be.
        if self._pending is not None:
            self._pending = None
            self.watchdog.stop()
            if self.worker.state() != QProcess.ProcessState.NotRunning:
                self.worker.kill()
                self.worker.waitForFinished(250)

        return self._send(
            "load",
            {
                "source": self.source_edit.toPlainText(),
                "effect_id": previous,
            },
        )

    def select_effect(self, *args):
        self._adopt_selected_spec()
        if self.spec is None:
            return
        self.elapsed = 0.0
        self.preview_enabled = False
        self._send("select", {"effect_id": self.spec.id})

    def reset_effect(self, *args):
        if self.spec is None:
            self.preview.clear_frame()
            return
        self.elapsed = 0.0
        self.preview_enabled = False
        self._send("reset")

    def inject_key(self, row, column):
        if self.spec is None or not self.preview_enabled:
            return
        self._send(
            "event",
            {
                "event": {
                    "kind": "key-press",
                    "timestamp": self.elapsed,
                    "source": (
                        f"{self._preview_target().get('device_class', 'device')}:"
                        "effect-lab"
                    ),
                    "code": f"LAB_R{row}_C{column}",
                    "value": 1,
                    "row": row,
                    "column": column,
                }
            },
        )

    def inject_mouse(self):
        if self.spec is None or not self.preview_enabled:
            return
        self._send(
            "event",
            {
                "event": {
                    "kind": "mouse-press",
                    "timestamp": self.elapsed,
                    "source": "mouse:effect-lab",
                    "code": "BTN_LEFT",
                    "value": 1,
                }
            },
        )

    def advance_frame(self):
        if self.spec is None or not self.preview_enabled:
            return
        if self._pending is not None:
            return

        self.elapsed += self.FRAME_INTERVAL_MS / 1000.0
        self.render_now()

    def render_now(self, *args):
        if (
            self.spec is None
            or not self.preview_enabled
            or self._pending is not None
        ):
            return

        self._send(
            "render",
            {
                "elapsed": self.elapsed,
                "target": self._preview_target(),
                "parameters": self.effect_parameters.values(),
            },
        )

    def _atomic_save(self):
        if self.loaded_path is None:
            raise RuntimeError("Load a plugin file before saving.")

        fd, temporary = tempfile.mkstemp(
            prefix=self.loaded_path.name + ".",
            dir=str(self.loaded_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(self.source_edit.toPlainText())
            os.replace(temporary, self.loaded_path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def save_source(self):
        # Saving is intentionally a two-step authoring operation now:
        # Validate first, then Save. This avoids blocking/synchronous validation.
        if not self.preview_enabled:
            self.status_label.setText(
                "Validate the current candidate successfully before saving."
            )
            return
        try:
            self._atomic_save()
            self.source_edit.document().setModified(False)
            self.status_label.setText(
                f"Saved atomically: {self.loaded_path}"
            )
        except Exception as exc:
            self.status_label.setText(
                f"Save failed: {type(exc).__name__}: {exc}"
            )

    def save_and_reload(self):
        if not self.preview_enabled:
            self.status_label.setText(
                "Validate the current candidate successfully before hot reload."
            )
            return

        try:
            plugins = (ROOT / "plugins" / "effects").resolve()
            path = self.loaded_path.resolve() if self.loaded_path else None
            if path is None or plugins not in path.parents:
                raise RuntimeError(
                    "Hot reload is only available for files inside "
                    "~/.local/share/serpent/plugins/effects."
                )

            self._atomic_save()
            process = subprocess.run(
                [str(ROOT / "serpent.py"), "effect", "reload"],
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                )

            self.source_edit.document().setModified(False)
            self.status_label.setText(
                "Saved and hot-reloaded installed user effects.\n"
                + process.stdout.strip()
            )
        except Exception as exc:
            self.status_label.setText(
                f"Save/reload failed safely: {type(exc).__name__}: {exc}"
            )

    def _live_preview_arguments(self):
        if self.spec is None:
            raise RuntimeError("Validate an effect before starting live preview.")

        arguments = [
            str(ROOT / "serpent.py"),
            "sync",
            "preview-start",
            self.spec.id,
            "--owner-pid",
            str(os.getpid()),
        ]

        values = self.effect_parameters.values()
        for key in ("colour1", "colour2", "speed", "direction"):
            if key not in values:
                continue
            value = values[key]
            arguments.append("--" + key)
            if key in {"colour1", "colour2"}:
                arguments.extend(str(component) for component in value)
            else:
                arguments.append(str(value))

        return arguments

    def start_live_preview(self):
        if not self.preview_enabled or self.spec is None:
            self.status_label.setText(
                "Validate the current candidate before starting live preview."
            )
            return

        if self.source_edit.document().isModified():
            self.status_label.setText(
                "Physical preview uses installed plugin source. "
                "Save + Hot Reload the current editor changes first."
            )
            return

        try:
            process = subprocess.run(
                self._live_preview_arguments(),
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                )
            self._live_preview_active = True
            self.live_preview_start_button.setEnabled(False)
            self.live_preview_stop_button.setEnabled(True)
            self.live_preview_label.setText(
                f"Physical preview: LIVE — {self.spec.id}\n"
                "Saved profile remains unchanged."
            )
            self.status_label.setText(process.stdout.strip())
        except Exception as exc:
            self._live_preview_active = False
            self.status_label.setText(
                f"Live preview failed safely: {type(exc).__name__}: {exc}"
            )

    def stop_live_preview(self, *, silent=False):
        if not self._live_preview_active and silent:
            return True

        try:
            process = subprocess.run(
                [str(ROOT / "serpent.py"), "sync", "preview-stop"],
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                )
            self._live_preview_active = False
            self.live_preview_start_button.setEnabled(True)
            self.live_preview_stop_button.setEnabled(False)
            self.live_preview_label.setText("Physical preview: inactive")
            if not silent:
                self.status_label.setText(process.stdout.strip())
            return True
        except Exception as exc:
            if not silent:
                self.status_label.setText(
                    f"Could not stop live preview safely: "
                    f"{type(exc).__name__}: {exc}"
                )
            return False

    def closeEvent(self, event):
        self.stop_live_preview(silent=True)
        self.watchdog.stop()
        if self.worker.state() != QProcess.ProcessState.NotRunning:
            self.worker.kill()
            self.worker.waitForFinished(300)
        super().closeEvent(event)

class EffectsWorkshopPanel(EffectLabPanel):
    """First-class installed-effect workspace with preserved developer tooling."""

    MODE_INSTALLED = "installed"
    MODE_DEVELOPER = "developer"

    GUIDE_TOPICS = (
        {
            "title": "Getting Started",
            "symbols": "New Effect… · Validate & Preview · Install to Serpent",
            "body": (
                "Developer mode follows one safe loop:\n\n"
                "1. Create or load normal Python effect source.\n"
                "2. Edit the source in this Workshop.\n"
                "3. Validate it in the isolated effect worker and preview it.\n"
                "4. Install the exact validated source into Installed Effects.\n\n"
                "Editing after validation intentionally locks installation "
                "until the source is validated again."
            ),
            "snippet": "",
            "snippet_label": "No snippet — workflow topic",
        },
        {
            "title": "Effect Anatomy",
            "symbols": "Effect · EffectDefinition · render() · EffectFrame",
            "body": (
                "Every effect is an Effect subclass with an EffectDefinition "
                "and a render(elapsed, parameters, target) method. render() "
                "returns a complete EffectFrame. Non-reactive effects can "
                "inherit the default no-op handle_event().\n\n"
                "Keep effect-specific geometry, timing, state and composition "
                "inside the effect. The SDK owns contracts and helpers, not "
                "your artistic policy."
            ),
            "snippet": (
                "def render(self, elapsed, parameters, target):\n"
                "    target.validate()\n"
                "    # Build and return a complete frame here.\n"
            ),
            "snippet_label": "Insert render skeleton",
        },
        {
            "title": "Matrix / EffectCanvas",
            "symbols": "EffectCanvas · target.active_cells · canvas.mix() · canvas.frame()",
            "body": (
                "EffectTarget describes rows, columns and the active-cell "
                "topology. EffectCanvas is the preferred frame-storage and "
                "finalization helper when its semantics match your effect.\n\n"
                "Canvas automatically keeps inactive cells safe. Effects still "
                "own the decision about which cells to paint and how colours "
                "compose."
            ),
            "snippet": (
                "canvas = EffectCanvas(target)\n"
                "canvas.mix((row, column), parameters.colour1, 1.0)\n"
                "return canvas.frame()\n"
            ),
            "snippet_label": "Insert Canvas paint",
        },
        {
            "title": "Parameters",
            "symbols": "EffectParameters · EffectParameterSpec · EffectPluginSpec",
            "body": (
                "Runtime values arrive through EffectParameters. The plugin "
                "metadata tells Serpent and the GUI which controls to expose. "
                "Supported parameter kinds include colour, integer, number, "
                "choice and boolean.\n\n"
                "Do not invent GUI-only effect settings: declare public "
                "controls in EffectParameterSpec so every frontend sees the "
                "same contract."
            ),
            "snippet": (
                "EffectParameterSpec(\n"
                "    id=\"speed\",\n"
                "    label=\"Speed\",\n"
                "    kind=\"integer\",\n"
                "    default=5,\n"
                "    minimum=1,\n"
                "    maximum=10,\n"
                "),\n"
            ),
            "snippet_label": "Insert parameter declaration",
        },
        {
            "title": "Animation & Lifecycle",
            "symbols": "animation_age · animation_phase · animation_alive · prune_expired",
            "body": (
                "Use the lifecycle helpers for mechanics that match their "
                "contracts instead of duplicating elapsed-minus-started_at "
                "math. animation_phase() normalizes age against duration; "
                "animation_alive() uses an inclusive lifetime; prune_expired() "
                "preserves state order while removing expired states.\n\n"
                "Durations and artistic timing remain effect-owned."
            ),
            "snippet": (
                "phase = animation_phase(\n"
                "    elapsed,\n"
                "    state.started_at,\n"
                "    duration,\n"
                "    clamp=True,\n"
                ")\n"
            ),
            "snippet_label": "Insert normalized phase",
        },
        {
            "title": "Keyboard & Mouse Events",
            "symbols": "event_matches · event_cell · event_timestamp · EffectEvent",
            "body": (
                "Reactive effects receive presentation-neutral EffectEvent "
                "objects through handle_event(). Use event_matches() for the "
                "kind/source contract, event_cell() for logical keyboard "
                "position and event_timestamp() for effect time.\n\n"
                "Declare keyboard/mouse input capabilities in EffectPluginSpec "
                "only when the effect actually consumes them."
            ),
            "snippet": (
                "if event_matches(\n"
                "    event,\n"
                "    kind=\"key-press\",\n"
                "    source_prefix=\"keyboard:\",\n"
                "):\n"
                "    cell = event_cell(event)\n"
                "    if cell is None:\n"
                "        return\n"
                "    started_at = event_timestamp(event)\n"
            ),
            "snippet_label": "Insert keyboard event match",
        },
        {
            "title": "Deterministic Randomness",
            "symbols": "event_seed · event_rng",
            "body": (
                "Reactive procedural geometry should be reproducible. "
                "event_seed() derives a stable 64-bit seed from the event, "
                "an effect-owned serial and an effect-owned namespace. "
                "The serial distinguishes otherwise identical events.\n\n"
                "Keep serial counters and namespace choices inside your effect."
            ),
            "snippet": (
                "seed = event_seed(\n"
                "    event,\n"
                "    serial=serial,\n"
                "    namespace=\"my-effect-keyboard\",\n"
                ")\n"
            ),
            "snippet_label": "Insert stable event seed",
        },
        {
            "title": "Spatial Motion",
            "symbols": "SPATIAL_DIRECTIONS · directional_position · spatial_position_count",
            "body": (
                "Serpent's spatial directions are stable scalar values. "
                "directional_position() maps a matrix cell onto the selected "
                "direction axis so gradients, sweeps and bands can stay "
                "topology-aware.\n\n"
                "Use target rows/columns and active topology rather than "
                "hard-coding the 6×22 keyboard into reusable effect logic."
            ),
            "snippet": (
                "position = directional_position(\n"
                "    row,\n"
                "    column,\n"
                "    target.rows,\n"
                "    target.columns,\n"
                "    parameters.direction,\n"
                ")\n"
            ),
            "snippet_label": "Insert directional position",
        },
        {
            "title": "Reactive State",
            "symbols": "handle_event() · started_at · prune_expired",
            "body": (
                "Reactive effects normally create small effect-owned state "
                "objects when events arrive, then render/prune those states as "
                "elapsed time advances. State shapes, durations, serials, "
                "geometry and overlap policy stay local to the effect.\n\n"
                "Avoid creating a second reactive framework inside a plugin."
            ),
            "snippet": (
                "self._states = prune_expired(\n"
                "    self._states,\n"
                "    elapsed,\n"
                "    lambda state: duration,\n"
                ")\n"
            ),
            "snippet_label": "Insert state pruning",
        },
        {
            "title": "Validate, Preview & Install",
            "symbols": "isolated worker · synthetic events · Install to Serpent",
            "body": (
                "Validate & Preview sends candidate source to the isolated "
                "Workshop worker. Synthetic key/mouse controls exercise "
                "reactive code without owning real input devices.\n\n"
                "Install to Serpent is deliberately a separate action. Only "
                "the exact source snapshot that last validated can be promoted "
                "into the normal Installed Effects catalog."
            ),
            "snippet": "",
            "snippet_label": "No snippet — safety topic",
        },
    )

    def __init__(self, parameter_editor_class, parent=None):
        self._workshop_mode = self.MODE_INSTALLED
        self._installed_specs = []
        self._developer_specs = []
        self._validated_developer_source = None
        self._composer_layers = []
        self._composer_target_layers = {}
        self._composer_target_geometries = {}
        self._composer_target_regions = {}
        self._composer_target_region_selections = {}
        self._composer_target_groups = {}
        self._composer_groups = []
        self._composer_group_counter = 1
        self._composer_layer_counter = 1
        self._composer_preset_directory = ROOT / "presets" / "effects_workshop"
        self._composer_history_undo = []
        self._composer_history_redo = []
        self._composer_history_limit = 64
        self._composer_history_restoring = False
        self._composer_clipboard = None
        self._composer_stack_syncing = False
        self._composer_bulk_updating = False
        self._composer_bulk_dirty = set()
        self._composer_regions = {}
        self._composer_region_selection = set()
        self._composer_current_device_class = None
        self._composer_triggers = []
        self._composer_trigger_colour = (255, 120, 40)
        self._composer_preview_playing = False
        self._composer_preview_time = 0.0
        self._composer_updating = False
        self._composer_raw_python_mode = False
        self._composer_installed_origin_id = None
        super().__init__(parameter_editor_class, parent)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Installed Effects", self.MODE_INSTALLED)
        self.mode_combo.addItem("Developer", self.MODE_DEVELOPER)

        self.authoring_surface_combo = QComboBox(self)
        self.authoring_surface_combo.addItem("Unified Workshop", "composer")
        self.authoring_surface_label = QLabel("Authoring surface")
        self.authoring_surface_combo.setVisible(False)
        self.authoring_surface_label.setVisible(False)

        self.developer_workflow_container = QWidget(self)
        developer_workflow_layout = QVBoxLayout(
            self.developer_workflow_container
        )
        developer_workflow_layout.setContentsMargins(0, 6, 0, 10)
        developer_workflow_layout.setSpacing(4)

        self.developer_workflow_title = QLabel(
            "Create an effect in four steps"
        )
        developer_title_font = self.developer_workflow_title.font()
        developer_title_font.setPointSize(
            developer_title_font.pointSize() + 2
        )
        developer_title_font.setBold(True)
        self.developer_workflow_title.setFont(developer_title_font)

        self.developer_workflow_help = QLabel(
            "1  Create or load source   →   "
            "2  Edit Python   →   "
            "3  Validate & preview   →   "
            "4  Install to Serpent"
        )
        self.developer_workflow_help.setWordWrap(True)

        self.developer_step_status = QLabel(
            "Step 1 — Start with New Effect… or Browse… an existing plugin."
        )
        self.developer_step_status.setWordWrap(True)

        developer_workflow_layout.addWidget(
            self.developer_workflow_title
        )
        developer_workflow_layout.addWidget(
            self.developer_workflow_help
        )
        developer_workflow_layout.addWidget(
            self.developer_step_status
        )

        self.guide_toggle_button = QPushButton("Python / Effect Guide ▾")
        self.guide_toggle_button.setCheckable(True)
        self.guide_toggle_button.setChecked(True)
        self.guide_toggle_button.setToolTip(
            "Show or hide Serpent's in-GUI effect SDK guide."
        )

        self.guide_container = QWidget(self)
        guide_layout = QVBoxLayout(self.guide_container)
        guide_layout.setContentsMargins(0, 0, 0, 8)
        guide_layout.setSpacing(6)

        self.guide_search = QLineEdit()
        self.guide_search.setPlaceholderText(
            "Search the Python / Effect Guide…"
        )
        self.guide_search.setClearButtonEnabled(True)

        self.guide_topics = QListWidget()
        self.guide_topics.setMaximumHeight(150)

        self.guide_title = QLabel()
        guide_title_font = self.guide_title.font()
        guide_title_font.setBold(True)
        guide_title_font.setPointSize(
            guide_title_font.pointSize() + 1
        )
        self.guide_title.setFont(guide_title_font)

        self.guide_symbols = QLabel()
        self.guide_symbols.setWordWrap(True)

        self.guide_text = QPlainTextEdit()
        self.guide_text.setReadOnly(True)
        self.guide_text.setMaximumHeight(170)

        self.guide_snippet = QPlainTextEdit()
        self.guide_snippet.setReadOnly(True)
        self.guide_snippet.setMaximumHeight(120)

        self.guide_insert_button = QPushButton("Insert Snippet")
        self.guide_insert_button.setToolTip(
            "Insert this small SDK snippet at the current source-editor cursor. "
            "The Guide never replaces the whole effect."
        )

        guide_details = QWidget(self)
        guide_details_layout = QVBoxLayout(guide_details)
        guide_details_layout.setContentsMargins(0, 0, 0, 0)
        guide_details_layout.addWidget(self.guide_title)
        guide_details_layout.addWidget(self.guide_symbols)
        guide_details_layout.addWidget(self.guide_text)
        guide_details_layout.addWidget(self.guide_snippet)
        guide_details_layout.addWidget(self.guide_insert_button)

        guide_splitter = QSplitter(Qt.Orientation.Horizontal)
        guide_splitter.addWidget(self.guide_topics)
        guide_splitter.addWidget(guide_details)
        guide_splitter.setSizes([190, 520])

        guide_layout.addWidget(self.guide_search)
        guide_layout.addWidget(guide_splitter)

        self.composer_container = QWidget(self)
        composer_layout = QVBoxLayout(self.composer_container)
        composer_layout.setContentsMargins(0, 0, 0, 8)
        composer_layout.setSpacing(7)

        composer_intro = QLabel(
            "Visual Composer v1 — build ordinary Serpent Python from visual "
            "layers. Generated source still validates through the existing isolated worker."
        )
        composer_intro.setWordWrap(True)
        composer_layout.addWidget(composer_intro)

        composer_file_row = QHBoxLayout()
        self.composer_create_file = QPushButton("Create Plugin File…")
        self.composer_create_file.setToolTip(
            "Choose the authoring .py file for this visual composition. "
            "The current Composer layers/triggers are preserved."
        )
        self.composer_load_file = QPushButton("Open Authoring Project…")
        self.composer_load_file.setToolTip(
            "Open a saved Composer authoring project or compatible effect file."
        )
        self.composer_load_installed = QPushButton("Open Installed Effect…")
        self.composer_load_installed.setToolTip(
            "Open an installed user effect. Composer-authored effects reconstruct visually; other Python effects open in Advanced Python."
        )
        self.composer_file_label = QLabel("Plugin file: not chosen")
        self.composer_file_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        composer_file_row.addWidget(self.composer_create_file)
        composer_file_row.addWidget(self.composer_load_file)
        composer_file_row.addWidget(self.composer_load_installed)
        composer_file_row.addWidget(self.composer_file_label, 1)
        composer_layout.addLayout(composer_file_row)

        metadata_row = QWidget(self)
        metadata_form = QFormLayout(metadata_row)
        self.composer_name = QLineEdit("My Visual Effect")
        self.composer_id = QLineEdit("my-visual-effect")
        self.composer_description = QLineEdit("Created with Serpent Visual Composer.")
        metadata_form.addRow("Effect name", self.composer_name)
        metadata_form.addRow("Effect ID", self.composer_id)
        metadata_form.addRow("Description", self.composer_description)
        composer_layout.addWidget(metadata_row)

        intent_row = QWidget(self)
        intent_form = QFormLayout(intent_row)

        self.composer_intent_combo = QComboBox(self)
        self.composer_intent_combo.addItem(
            "Device-Specific",
            "device-specific",
        )
        self.composer_intent_combo.addItem(
            "Synchronized Multi-Target",
            "synchronized",
        )

        self.composer_device_class_combo = QComboBox(self)
        self.composer_device_class_combo.setEditable(True)
        self.composer_device_class_combo.addItems(
            ("keyboard", "mouse")
        )

        self.composer_sync_targets = QListWidget(self)
        self.composer_sync_targets.setMaximumHeight(100)

        sync_buttons = QWidget(self)
        sync_buttons_layout = QHBoxLayout(sync_buttons)
        sync_buttons_layout.setContentsMargins(0, 0, 0, 0)
        self.composer_add_target = QPushButton("+ Add Target")
        self.composer_remove_target = QPushButton("Remove Target")
        sync_buttons_layout.addWidget(self.composer_add_target)
        sync_buttons_layout.addWidget(self.composer_remove_target)
        sync_buttons_layout.addStretch()

        self.composer_target_identity_note = QLabel(
            "Device-Specific generates one render-target branch. "
            "Synchronized Multi-Target keeps one effect identity but "
            "stores a separate visual composition per device class."
        )
        self.composer_target_identity_note.setWordWrap(True)

        intent_form.addRow("Effect scope", self.composer_intent_combo)
        intent_form.addRow(
            "Device class",
            self.composer_device_class_combo,
        )
        intent_form.addRow(
            "Synchronized targets",
            self.composer_sync_targets,
        )
        intent_form.addRow(sync_buttons)
        intent_form.addRow(self.composer_target_identity_note)
        composer_layout.addWidget(intent_row)

        geometry_row = QWidget(self)
        geometry_form = QFormLayout(geometry_row)

        self.composer_target_combo = QComboBox(self)
        for index in range(self.target_combo.count()):
            self.composer_target_combo.addItem(
                self.target_combo.itemText(index),
                self.target_combo.itemData(index),
            )
        self.composer_target_combo.addItem(
            "Custom Matrix…",
            {"custom": True},
        )

        self.composer_rows = QSpinBox(self)
        self.composer_rows.setRange(1, 64)
        self.composer_rows.setValue(6)
        self.composer_columns = QSpinBox(self)
        self.composer_columns.setRange(1, 64)
        self.composer_columns.setValue(22)

        geometry_form.addRow(
            "Design target",
            self.composer_target_combo,
        )
        geometry_form.addRow(
            "Matrix rows",
            self.composer_rows,
        )
        geometry_form.addRow(
            "Matrix columns",
            self.composer_columns,
        )

        self.composer_geometry_note = QLabel(
            "Installed targets use their fixture topology. Custom Matrix "
            "creates an all-active synthetic target so you can design for "
            "hardware you do not currently own."
        )
        self.composer_geometry_note.setWordWrap(True)
        geometry_form.addRow(self.composer_geometry_note)

        composer_layout.addWidget(geometry_row)

        self.composer_matrix = ComposerMatrix(self)
        composer_layout.addWidget(self.composer_matrix)

        region_box = QGroupBox("Visual Regions & Matrix Selection", self)
        region_layout = QVBoxLayout(region_box)

        region_toolbar = QHBoxLayout()
        self.composer_region_edit = QPushButton("Region Edit")
        self.composer_region_edit.setCheckable(True)
        self.composer_region_mode = QComboBox(self)
        self.composer_region_mode.addItem("Add", "add")
        self.composer_region_mode.addItem("Subtract", "subtract")
        self.composer_region_mode.addItem("Toggle", "toggle")
        self.composer_region_select_all = QPushButton("Select All")
        self.composer_region_clear = QPushButton("Clear")
        self.composer_region_invert = QPushButton("Invert")
        for widget in (
            self.composer_region_edit,
            self.composer_region_mode,
            self.composer_region_select_all,
            self.composer_region_clear,
            self.composer_region_invert,
        ):
            region_toolbar.addWidget(widget)
        region_layout.addLayout(region_toolbar)

        region_splitter = QSplitter(Qt.Orientation.Horizontal)
        region_list_panel = QWidget(self)
        region_list_layout = QVBoxLayout(region_list_panel)
        region_list_layout.setContentsMargins(0, 0, 0, 0)
        region_list_layout.addWidget(QLabel("Named regions"))
        self.composer_region_list = QListWidget(self)
        self.composer_region_list.setMaximumHeight(140)
        region_list_layout.addWidget(self.composer_region_list)

        region_editor_panel = QWidget(self)
        region_editor_form = QFormLayout(region_editor_panel)
        region_editor_form.setContentsMargins(0, 0, 0, 0)
        self.composer_region_name = QLineEdit(self)
        self.composer_region_name.setPlaceholderText(
            "e.g. WASD, Border, Logo, Mouse Accent"
        )
        region_editor_form.addRow("Region name", self.composer_region_name)
        region_actions = QHBoxLayout()
        self.composer_region_new = QPushButton("New From Selection")
        self.composer_region_rename = QPushButton("Rename Selected")
        self.composer_region_delete = QPushButton("Delete")
        region_actions.addWidget(self.composer_region_new)
        region_actions.addWidget(self.composer_region_rename)
        region_actions.addWidget(self.composer_region_delete)
        region_editor_form.addRow(region_actions)
        note = QLabel(
            "Regions are Composer-only authoring metadata and compile "
            "into ordinary cell tuples."
        )
        note.setWordWrap(True)
        region_editor_form.addRow(note)

        region_splitter.addWidget(region_list_panel)
        region_splitter.addWidget(region_editor_panel)
        region_splitter.setSizes([320, 520])
        region_layout.addWidget(region_splitter)
        composer_layout.addWidget(region_box)

        composer_splitter = QSplitter(Qt.Orientation.Horizontal)

        layers_panel = QWidget(self)
        layers_layout = QVBoxLayout(layers_panel)
        layers_layout.setContentsMargins(0, 0, 0, 0)
        layers_layout.addWidget(QLabel("Visual Layer Stack"))
        self.composer_layer_stack = QTreeWidget(self)
        self.composer_layer_stack.setHeaderLabels(["Painter stack"])
        self.composer_layer_stack.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        self.composer_layer_stack.setMinimumHeight(240)
        self.composer_layer_stack.setToolTip(
            "Groups are collapsible presentation only. "
            "Painter order remains Composer metadata."
        )
        layers_layout.addWidget(self.composer_layer_stack)

        self.composer_layers = QListWidget(self)
        self.composer_layers.setVisible(False)
        layers_layout.addWidget(self.composer_layers)

        add_row = QHBoxLayout()
        self.composer_add_fill = QPushButton("+ Fill")
        self.composer_add_cell = QPushButton("+ Cell")
        self.composer_add_gradient = QPushButton("+ Gradient")
        self.composer_add_pulse = QPushButton("+ Pulse")
        for button in (
            self.composer_add_fill,
            self.composer_add_cell,
            self.composer_add_gradient,
            self.composer_add_pulse,
        ):
            add_row.addWidget(button)
        layers_layout.addLayout(add_row)

        edit_row = QHBoxLayout()
        self.composer_remove = QPushButton("Remove")
        self.composer_up = QPushButton("Move Up")
        self.composer_down = QPushButton("Move Down")
        edit_row.addWidget(self.composer_remove)
        edit_row.addWidget(self.composer_up)
        edit_row.addWidget(self.composer_down)
        layers_layout.addLayout(edit_row)

        history_row = QHBoxLayout()
        self.composer_undo = QPushButton("Undo")
        self.composer_redo = QPushButton("Redo")
        self.composer_duplicate = QPushButton("Duplicate")
        self.composer_copy = QPushButton("Copy")
        self.composer_paste = QPushButton("Paste")
        for button in (
            self.composer_undo,
            self.composer_redo,
            self.composer_duplicate,
            self.composer_copy,
            self.composer_paste,
        ):
            history_row.addWidget(button)
        layers_layout.addLayout(history_row)

        self.composer_layers.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection
        )
        groups_box = QGroupBox("Selected Group Properties", self)
        groups_layout = QVBoxLayout(groups_box)
        self.composer_groups = QListWidget(self)
        self.composer_groups.setVisible(False)
        groups_layout.addWidget(self.composer_groups)
        group_buttons = QHBoxLayout()
        self.composer_group_create = QPushButton("Group Selected")
        self.composer_group_delete = QPushButton("Delete Group")
        self.composer_group_up = QPushButton("Group Up")
        self.composer_group_down = QPushButton("Group Down")
        for button in (self.composer_group_create, self.composer_group_delete, self.composer_group_up, self.composer_group_down):
            group_buttons.addWidget(button)
        groups_layout.addLayout(group_buttons)
        group_form = QFormLayout()
        self.composer_group_name = QLineEdit(self)
        self.composer_group_enabled = QComboBox(self)
        self.composer_group_enabled.addItem("Enabled", True)
        self.composer_group_enabled.addItem("Disabled", False)
        self.composer_group_opacity = QDoubleSpinBox(self)
        self.composer_group_opacity.setRange(0.0, 1.0)
        self.composer_group_opacity.setValue(1.0)
        self.composer_group_timeline_offset = QDoubleSpinBox(self)
        self.composer_group_timeline_offset.setRange(-120.0, 120.0)
        self.composer_group_timeline_offset.setSuffix(" s")
        self.composer_group_speed = QDoubleSpinBox(self)
        self.composer_group_speed.setRange(0.05, 10.0)
        self.composer_group_speed.setValue(1.0)
        self.composer_group_region = QComboBox(self)
        self.composer_group_region.addItem("Entire Target", None)
        group_form.addRow("Name", self.composer_group_name)
        group_form.addRow("State", self.composer_group_enabled)
        group_form.addRow("Opacity", self.composer_group_opacity)
        group_form.addRow("Timeline offset", self.composer_group_timeline_offset)
        group_form.addRow("Speed multiplier", self.composer_group_speed)
        group_form.addRow("Shared region", self.composer_group_region)
        groups_layout.addLayout(group_form)
        layers_layout.addWidget(groups_box)

        bulk_box = QGroupBox("Bulk Edit Selected Layers", self)
        bulk_form = QFormLayout(bulk_box)
        self.composer_bulk_summary = QLabel(
            "Select two or more layers for bulk editing",
            self,
        )
        self.composer_bulk_summary.setWordWrap(True)
        bulk_form.addRow(self.composer_bulk_summary)

        self.composer_bulk_opacity = QLineEdit(self)
        self.composer_bulk_opacity.setPlaceholderText("Mixed")
        bulk_form.addRow("Opacity", self.composer_bulk_opacity)

        self.composer_bulk_region = QComboBox(self)
        bulk_form.addRow("Region", self.composer_bulk_region)

        self.composer_bulk_delay = QLineEdit(self)
        self.composer_bulk_delay.setPlaceholderText("Mixed")
        bulk_form.addRow("Timeline delay", self.composer_bulk_delay)

        self.composer_bulk_speed = QLineEdit(self)
        self.composer_bulk_speed.setPlaceholderText("Mixed")
        bulk_form.addRow("Speed multiplier", self.composer_bulk_speed)

        self.composer_bulk_colour_mode = QComboBox(self)
        self.composer_bulk_colour_mode.addItem("Mixed", "__mixed__")
        self.composer_bulk_colour_mode.addItem("Static", "static")
        self.composer_bulk_colour_mode.addItem("Two-Colour", "two-colour")
        self.composer_bulk_colour_mode.addItem("Palette Cycle", "palette-cycle")
        self.composer_bulk_colour_mode.addItem("Keyframes", "keyframes")
        bulk_form.addRow("Colour mode", self.composer_bulk_colour_mode)

        self.composer_bulk_motion_mode = QComboBox(self)
        self.composer_bulk_motion_mode.addItem("Mixed", "__mixed__")
        self.composer_bulk_motion_mode.addItem("None", "none")
        self.composer_bulk_motion_mode.addItem("Directional", "directional")
        self.composer_bulk_motion_mode.addItem(
            "Point-to-Point",
            "point-to-point",
        )
        bulk_form.addRow("Motion mode", self.composer_bulk_motion_mode)

        self.composer_bulk_apply = QPushButton("Apply Bulk Changes", self)
        bulk_form.addRow(self.composer_bulk_apply)
        layers_layout.addWidget(bulk_box)

        preset_box = QGroupBox("Preset Library", self)
        preset_layout = QVBoxLayout(preset_box)
        preset_filter = QHBoxLayout()
        self.composer_preset_search = QLineEdit(self)
        self.composer_preset_search.setPlaceholderText("Search presets…")
        self.composer_preset_kind = QComboBox(self)
        self.composer_preset_kind.addItem("All kinds", None)
        self.composer_preset_kind.addItem("Layer", "layer")
        self.composer_preset_kind.addItem("Group", "group")
        self.composer_preset_kind.addItem("Trigger", "trigger")
        self.composer_preset_kind.addItem("Composition", "composition")
        self.composer_preset_target = QLineEdit(self)
        self.composer_preset_target.setPlaceholderText("Target class")
        preset_filter.addWidget(self.composer_preset_search, 2)
        preset_filter.addWidget(self.composer_preset_kind, 1)
        preset_filter.addWidget(self.composer_preset_target, 1)
        preset_layout.addLayout(preset_filter)
        self.composer_preset_list = QListWidget(self)
        preset_layout.addWidget(self.composer_preset_list)
        preset_meta = QFormLayout()
        self.composer_preset_name = QLineEdit(self)
        self.composer_preset_description = QLineEdit(self)
        preset_meta.addRow("Preset name", self.composer_preset_name)
        preset_meta.addRow("Description", self.composer_preset_description)
        preset_layout.addLayout(preset_meta)
        preset_save = QHBoxLayout()
        self.composer_preset_save_layer = QPushButton("Save Layer")
        self.composer_preset_save_group = QPushButton("Save Group")
        self.composer_preset_save_trigger = QPushButton("Save Trigger")
        self.composer_preset_save_composition = QPushButton("Save Composition")
        for button in (
            self.composer_preset_save_layer,
            self.composer_preset_save_group,
            self.composer_preset_save_trigger,
            self.composer_preset_save_composition,
        ):
            preset_save.addWidget(button)
        preset_layout.addLayout(preset_save)
        preset_actions = QHBoxLayout()
        self.composer_preset_apply = QPushButton("Apply Preset")
        self.composer_preset_delete = QPushButton("Delete Preset")
        self.composer_preset_refresh = QPushButton("Refresh")
        preset_actions.addWidget(self.composer_preset_apply)
        preset_actions.addWidget(self.composer_preset_delete)
        preset_actions.addWidget(self.composer_preset_refresh)
        preset_layout.addLayout(preset_actions)
        layers_layout.addWidget(preset_box)

        properties_panel = QWidget(self)
        properties_columns = QHBoxLayout(properties_panel)
        properties_columns.setContentsMargins(0, 0, 0, 0)
        properties_left_widget = QWidget(properties_panel)
        properties_right_widget = QWidget(properties_panel)
        properties_form = QFormLayout(properties_left_widget)
        properties_form_right = QFormLayout(properties_right_widget)
        properties_form.setContentsMargins(0, 0, 8, 0)
        properties_form_right.setContentsMargins(8, 0, 0, 0)
        properties_columns.addWidget(properties_left_widget, 1)
        properties_columns.addWidget(properties_right_widget, 1)
        self.composer_kind = QLabel("No layer selected")
        properties_form.addRow("Layer type", self.composer_kind)

        self.composer_colour_button = QPushButton("Primary colour")
        self.composer_colour2_button = QPushButton("Secondary colour")
        self.composer_colour = (80, 120, 255)
        self.composer_colour2 = (255, 80, 160)
        properties_form.addRow("Colour", self.composer_colour_button)
        properties_form.addRow("Second colour", self.composer_colour2_button)

        self.composer_opacity = QDoubleSpinBox(self)
        self.composer_opacity.setRange(0.0, 1.0)
        self.composer_opacity.setSingleStep(0.05)
        self.composer_opacity.setValue(1.0)
        properties_form.addRow("Opacity", self.composer_opacity)

        self.composer_row = QSpinBox(self)
        self.composer_row.setRange(0, 63)
        self.composer_column = QSpinBox(self)
        self.composer_column.setRange(0, 63)
        properties_form.addRow("Row", self.composer_row)
        properties_form.addRow("Column", self.composer_column)

        self.composer_direction = QComboBox(self)
        self.composer_direction.addItems(("Horizontal", "Vertical"))
        properties_form.addRow("Gradient direction", self.composer_direction)

        self.composer_duration = QDoubleSpinBox(self)
        self.composer_duration.setRange(0.1, 30.0)
        self.composer_duration.setSingleStep(0.1)
        self.composer_duration.setValue(1.5)
        self.composer_duration.setSuffix(" s")
        properties_form.addRow("Pulse duration", self.composer_duration)

        self.composer_layer_delay = QDoubleSpinBox(self)
        self.composer_layer_delay.setRange(0.0, 120.0)
        self.composer_layer_delay.setSingleStep(0.05)
        self.composer_layer_delay.setSuffix(" s")
        properties_form.addRow("Timeline delay", self.composer_layer_delay)

        self.composer_layer_timeline_duration = QDoubleSpinBox(self)
        self.composer_layer_timeline_duration.setRange(0.05, 120.0)
        self.composer_layer_timeline_duration.setValue(2.0)
        self.composer_layer_timeline_duration.setSuffix(" s")
        properties_form.addRow("Timeline duration", self.composer_layer_timeline_duration)

        self.composer_layer_playback = QComboBox(self)
        self.composer_layer_playback.addItem("Once", "once")
        self.composer_layer_playback.addItem("Loop", "loop")
        self.composer_layer_playback.addItem("Ping-Pong", "ping-pong")
        properties_form.addRow("Playback", self.composer_layer_playback)

        self.composer_layer_phase = QDoubleSpinBox(self)
        self.composer_layer_phase.setRange(0.0, 1.0)
        self.composer_layer_phase.setSingleStep(0.05)
        properties_form.addRow("Phase offset", self.composer_layer_phase)

        self.composer_layer_fade_in = QDoubleSpinBox(self)
        self.composer_layer_fade_in.setRange(0.0, 120.0)
        self.composer_layer_fade_in.setSuffix(" s")
        properties_form.addRow("Fade in", self.composer_layer_fade_in)

        self.composer_layer_fade_out = QDoubleSpinBox(self)
        self.composer_layer_fade_out.setRange(0.0, 120.0)
        self.composer_layer_fade_out.setSuffix(" s")
        properties_form.addRow("Fade out", self.composer_layer_fade_out)

        self.composer_layer_speed_multiplier = QDoubleSpinBox(self)
        self.composer_layer_speed_multiplier.setRange(0.05, 10.0)
        self.composer_layer_speed_multiplier.setValue(1.0)
        properties_form.addRow("Speed multiplier", self.composer_layer_speed_multiplier)

        self.composer_layer_timeline_bar = QProgressBar(self)
        self.composer_layer_timeline_bar.setRange(0, 1000)
        properties_form.addRow("Visual time bar", self.composer_layer_timeline_bar)

        self.composer_motion_mode = QComboBox(self)
        self.composer_motion_mode.addItem("None", "none")
        self.composer_motion_mode.addItem("Directional", "directional")
        self.composer_motion_mode.addItem("Point-to-Point", "point-to-point")
        properties_form.addRow("Motion mode", self.composer_motion_mode)

        self.composer_motion_direction = QComboBox(self)
        self.composer_motion_direction.addItem("Left → Right", "left-to-right")
        self.composer_motion_direction.addItem("Right → Left", "right-to-left")
        self.composer_motion_direction.addItem("Top → Bottom", "top-to-bottom")
        self.composer_motion_direction.addItem("Bottom → Top", "bottom-to-top")
        properties_form.addRow("Motion direction", self.composer_motion_direction)

        self.composer_motion_start_kind = QComboBox(self)
        self.composer_motion_start_kind.addItem("Normalized Position", "normalized")
        self.composer_motion_start_kind.addItem("Fixed Cell", "cell")
        self.composer_motion_start_kind.addItem("Named Region", "region")
        properties_form.addRow("Start anchor", self.composer_motion_start_kind)

        self.composer_motion_start_row = QDoubleSpinBox(self)
        self.composer_motion_start_row.setRange(0.0, 1.0)
        self.composer_motion_start_row.setSingleStep(0.05)
        self.composer_motion_start_row.setValue(0.5)
        self.composer_motion_start_column = QDoubleSpinBox(self)
        self.composer_motion_start_column.setRange(0.0, 1.0)
        self.composer_motion_start_column.setSingleStep(0.05)
        properties_form.addRow("Start normalized row", self.composer_motion_start_row)
        properties_form_right.addRow("Start normalized column", self.composer_motion_start_column)

        self.composer_motion_start_cell_row = QSpinBox(self)
        self.composer_motion_start_cell_row.setRange(0, 63)
        self.composer_motion_start_cell_column = QSpinBox(self)
        self.composer_motion_start_cell_column.setRange(0, 63)
        properties_form_right.addRow("Start cell row", self.composer_motion_start_cell_row)
        properties_form_right.addRow("Start cell column", self.composer_motion_start_cell_column)

        self.composer_motion_start_region = QComboBox(self)
        self.composer_motion_start_region.addItem("—", None)
        properties_form_right.addRow("Start region", self.composer_motion_start_region)

        self.composer_motion_end_kind = QComboBox(self)
        self.composer_motion_end_kind.addItem("Normalized Position", "normalized")
        self.composer_motion_end_kind.addItem("Fixed Cell", "cell")
        self.composer_motion_end_kind.addItem("Named Region", "region")
        properties_form_right.addRow("End anchor", self.composer_motion_end_kind)

        self.composer_motion_end_row = QDoubleSpinBox(self)
        self.composer_motion_end_row.setRange(0.0, 1.0)
        self.composer_motion_end_row.setSingleStep(0.05)
        self.composer_motion_end_row.setValue(0.5)
        self.composer_motion_end_column = QDoubleSpinBox(self)
        self.composer_motion_end_column.setRange(0.0, 1.0)
        self.composer_motion_end_column.setSingleStep(0.05)
        self.composer_motion_end_column.setValue(1.0)
        properties_form_right.addRow("End normalized row", self.composer_motion_end_row)
        properties_form_right.addRow("End normalized column", self.composer_motion_end_column)

        self.composer_motion_end_cell_row = QSpinBox(self)
        self.composer_motion_end_cell_row.setRange(0, 63)
        self.composer_motion_end_cell_column = QSpinBox(self)
        self.composer_motion_end_cell_column.setRange(0, 63)
        properties_form_right.addRow("End cell row", self.composer_motion_end_cell_row)
        properties_form_right.addRow("End cell column", self.composer_motion_end_cell_column)

        self.composer_motion_end_region = QComboBox(self)
        self.composer_motion_end_region.addItem("—", None)
        properties_form_right.addRow("End region", self.composer_motion_end_region)

        self.composer_motion_head_width = QDoubleSpinBox(self)
        self.composer_motion_head_width.setRange(0.01, 1.0)
        self.composer_motion_head_width.setSingleStep(0.01)
        self.composer_motion_head_width.setValue(0.08)
        properties_form_right.addRow("Head width", self.composer_motion_head_width)

        self.composer_motion_trail = QDoubleSpinBox(self)
        self.composer_motion_trail.setRange(0.0, 1.0)
        self.composer_motion_trail.setSingleStep(0.01)
        self.composer_motion_trail.setValue(0.20)
        properties_form_right.addRow("Trail length", self.composer_motion_trail)

        self.composer_colour_mode = QComboBox(self)
        self.composer_colour_mode.addItem("Static", "static")
        self.composer_colour_mode.addItem("Two-Colour", "two-colour")
        self.composer_colour_mode.addItem("Palette Cycle", "palette-cycle")
        self.composer_colour_mode.addItem("Keyframes", "keyframes")
        properties_form_right.addRow("Colour mode", self.composer_colour_mode)

        self.composer_spatial_palette = QComboBox(self)
        self.composer_spatial_palette.addItem("Temporal only", False)
        self.composer_spatial_palette.addItem("Spatial + temporal", True)
        properties_form_right.addRow("Palette mapping", self.composer_spatial_palette)

        self.composer_palette_list = QListWidget(self)
        self.composer_palette_list.setMinimumHeight(96)
        self.composer_palette_list.setMaximumHeight(112)
        properties_form_right.addRow("Colour stops", self.composer_palette_list)

        palette_buttons = QHBoxLayout()
        self.composer_palette_add = QPushButton("Add")
        self.composer_palette_remove = QPushButton("Remove")
        self.composer_palette_up = QPushButton("↑")
        self.composer_palette_down = QPushButton("↓")
        palette_buttons.addWidget(self.composer_palette_add)
        palette_buttons.addWidget(self.composer_palette_remove)
        palette_buttons.addWidget(self.composer_palette_up)
        palette_buttons.addWidget(self.composer_palette_down)
        properties_form_right.addRow("Stops", palette_buttons)

        self.composer_palette_position = QDoubleSpinBox(self)
        self.composer_palette_position.setRange(0.0, 1.0)
        self.composer_palette_position.setSingleStep(0.05)
        properties_form_right.addRow("Stop position", self.composer_palette_position)

        self.composer_palette_colour = QPushButton("Choose stop colour…")
        properties_form_right.addRow("Stop colour", self.composer_palette_colour)

        self.composer_layer_region = QComboBox(self)
        self.composer_layer_region.addItem("Entire Target", None)
        properties_form_right.addRow("Layer mask", self.composer_layer_region)

        composer_splitter.addWidget(layers_panel)
        composer_splitter.addWidget(properties_panel)
        composer_splitter.setSizes([360, 420])
        composer_layout.addWidget(composer_splitter)

        trigger_box = QGroupBox("Reactive Trigger Editor", self)
        trigger_layout = QVBoxLayout(trigger_box)

        trigger_intro = QLabel(
            "Event source and render destination are independent. "
            "A keyboard event can animate the mouse, a mouse event can "
            "animate the keyboard, or either can animate all synchronized targets."
        )
        trigger_intro.setWordWrap(True)
        trigger_layout.addWidget(trigger_intro)

        trigger_splitter = QSplitter(Qt.Orientation.Horizontal)

        trigger_list_panel = QWidget(self)
        trigger_list_layout = QVBoxLayout(trigger_list_panel)
        trigger_list_layout.setContentsMargins(0, 0, 0, 0)

        self.composer_trigger_list = QListWidget(self)
        self.composer_trigger_list.setMaximumHeight(150)
        trigger_list_layout.addWidget(self.composer_trigger_list)

        trigger_button_row = QHBoxLayout()
        self.composer_trigger_add = QPushButton("+ Add Trigger")
        self.composer_trigger_remove = QPushButton("Remove Trigger")
        trigger_button_row.addWidget(self.composer_trigger_add)
        trigger_button_row.addWidget(self.composer_trigger_remove)
        trigger_list_layout.addLayout(trigger_button_row)

        trigger_properties = QWidget(self)
        trigger_columns = QHBoxLayout(trigger_properties)
        trigger_columns.setContentsMargins(0, 0, 0, 0)
        trigger_left_widget = QWidget(trigger_properties)
        trigger_right_widget = QWidget(trigger_properties)
        trigger_form = QFormLayout(trigger_left_widget)
        trigger_form_right = QFormLayout(trigger_right_widget)
        trigger_form.setContentsMargins(0, 0, 8, 0)
        trigger_form_right.setContentsMargins(8, 0, 0, 0)
        trigger_columns.addWidget(trigger_left_widget, 1)
        trigger_columns.addWidget(trigger_right_widget, 1)

        self.composer_trigger_source = QComboBox(self)
        self.composer_trigger_source.addItem("Keyboard", "keyboard")
        self.composer_trigger_source.addItem("Mouse", "mouse")
        self.composer_trigger_source.addItem("Any", "any")
        trigger_form.addRow("Event source", self.composer_trigger_source)

        self.composer_trigger_action = QComboBox(self)
        self.composer_trigger_action.addItem("Press", "press")
        self.composer_trigger_action.addItem("Release", "release")
        trigger_form.addRow("Action", self.composer_trigger_action)

        self.composer_trigger_code = QLineEdit(self)
        self.composer_trigger_code.setPlaceholderText(
            "Optional key/button code; blank = any"
        )
        trigger_form.addRow("Key / button code", self.composer_trigger_code)

        self.composer_trigger_destination = QComboBox(self)
        self.composer_trigger_destination.addItem(
            "Current Composition", "current"
        )
        self.composer_trigger_destination.addItem(
            "Keyboard", "keyboard"
        )
        self.composer_trigger_destination.addItem(
            "Mouse", "mouse"
        )
        self.composer_trigger_destination.addItem(
            "All Synchronized Targets", "*"
        )
        trigger_form.addRow(
            "Render destination",
            self.composer_trigger_destination,
        )

        self.composer_trigger_response = QComboBox(self)
        self.composer_trigger_response.addItem(
            "Pulse All Cells", "pulse-all"
        )
        self.composer_trigger_response.addItem(
            "Pulse One Cell", "pulse-cell"
        )
        self.composer_trigger_response.addItem(
            "Spatial Ripple", "ripple"
        )
        self.composer_trigger_response.addItem(
            "Directional Sweep", "sweep"
        )
        trigger_form.addRow("Response", self.composer_trigger_response)
        self.composer_trigger_region = QComboBox(self)
        self.composer_trigger_region.addItem("Entire Target", None)
        trigger_form.addRow("Response mask", self.composer_trigger_region)

        self.composer_trigger_origin = QComboBox(self)
        self.composer_trigger_origin.addItem(
            "Entire Target", "entire-target"
        )
        self.composer_trigger_origin.addItem(
            "Fixed Cell", "fixed-cell"
        )
        self.composer_trigger_origin.addItem(
            "Event Cell", "event-cell"
        )
        self.composer_trigger_origin.addItem(
            "Relative Position", "relative-position"
        )
        trigger_form.addRow(
            "Response origin",
            self.composer_trigger_origin,
        )

        self.composer_trigger_direction = QComboBox(self)
        self.composer_trigger_direction.addItem("Left → Right", 1)
        self.composer_trigger_direction.addItem("Right → Left", 2)
        self.composer_trigger_direction.addItem("Top → Bottom", 3)
        self.composer_trigger_direction.addItem("Bottom → Top", 4)
        trigger_form.addRow(
            "Motion direction",
            self.composer_trigger_direction,
        )

        self.composer_trigger_relative_row = QDoubleSpinBox(self)
        self.composer_trigger_relative_row.setRange(0.0, 1.0)
        self.composer_trigger_relative_row.setSingleStep(0.05)
        self.composer_trigger_relative_row.setValue(0.5)
        trigger_form.addRow(
            "Relative row",
            self.composer_trigger_relative_row,
        )

        self.composer_trigger_relative_column = QDoubleSpinBox(self)
        self.composer_trigger_relative_column.setRange(0.0, 1.0)
        self.composer_trigger_relative_column.setSingleStep(0.05)
        self.composer_trigger_relative_column.setValue(0.5)
        trigger_form.addRow(
            "Relative column",
            self.composer_trigger_relative_column,
        )

        self.composer_trigger_colour_button = QPushButton(
            "#FF7828", self
        )
        trigger_form.addRow(
            "Trigger colour",
            self.composer_trigger_colour_button,
        )

        self.composer_trigger_duration = QDoubleSpinBox(self)
        self.composer_trigger_duration.setRange(0.05, 30.0)
        self.composer_trigger_duration.setSingleStep(0.05)
        self.composer_trigger_duration.setValue(0.6)
        self.composer_trigger_duration.setSuffix(" s")
        trigger_form.addRow(
            "Response duration",
            self.composer_trigger_duration,
        )

        self.composer_trigger_delay = QDoubleSpinBox(self)
        self.composer_trigger_delay.setRange(0.0, 120.0)
        self.composer_trigger_delay.setSuffix(" s")
        trigger_form.addRow("Trigger delay", self.composer_trigger_delay)

        self.composer_trigger_playback = QComboBox(self)
        self.composer_trigger_playback.addItem("Once", "once")
        self.composer_trigger_playback.addItem("Loop", "loop")
        self.composer_trigger_playback.addItem("Ping-Pong", "ping-pong")
        trigger_form.addRow("Trigger playback", self.composer_trigger_playback)

        self.composer_trigger_phase = QDoubleSpinBox(self)
        self.composer_trigger_phase.setRange(0.0, 1.0)
        trigger_form.addRow("Trigger phase offset", self.composer_trigger_phase)

        self.composer_trigger_fade_in = QDoubleSpinBox(self)
        self.composer_trigger_fade_in.setRange(0.0, 120.0)
        self.composer_trigger_fade_in.setSuffix(" s")
        trigger_form.addRow("Trigger fade in", self.composer_trigger_fade_in)

        self.composer_trigger_fade_out = QDoubleSpinBox(self)
        self.composer_trigger_fade_out.setRange(0.0, 120.0)
        self.composer_trigger_fade_out.setSuffix(" s")
        trigger_form.addRow("Trigger fade out", self.composer_trigger_fade_out)

        self.composer_trigger_speed_multiplier = QDoubleSpinBox(self)
        self.composer_trigger_speed_multiplier.setRange(0.05, 10.0)
        self.composer_trigger_speed_multiplier.setValue(1.0)
        trigger_form.addRow("Trigger speed multiplier", self.composer_trigger_speed_multiplier)

        self.composer_trigger_timeline_bar = QProgressBar(self)
        self.composer_trigger_timeline_bar.setRange(0, 1000)
        trigger_form.addRow("Trigger time bar", self.composer_trigger_timeline_bar)

        self.composer_trigger_motion_mode = QComboBox(self)
        self.composer_trigger_motion_mode.addItem("None", "none")
        self.composer_trigger_motion_mode.addItem("Directional", "directional")
        self.composer_trigger_motion_mode.addItem("Point-to-Point", "point-to-point")
        trigger_form.addRow("Motion mode", self.composer_trigger_motion_mode)

        self.composer_trigger_motion_direction = QComboBox(self)
        self.composer_trigger_motion_direction.addItem("Left → Right", "left-to-right")
        self.composer_trigger_motion_direction.addItem("Right → Left", "right-to-left")
        self.composer_trigger_motion_direction.addItem("Top → Bottom", "top-to-bottom")
        self.composer_trigger_motion_direction.addItem("Bottom → Top", "bottom-to-top")
        trigger_form.addRow("Motion direction", self.composer_trigger_motion_direction)

        self.composer_trigger_motion_start_kind = QComboBox(self)
        self.composer_trigger_motion_start_kind.addItem("Event Position", "event")
        self.composer_trigger_motion_start_kind.addItem("Normalized Position", "normalized")
        self.composer_trigger_motion_start_kind.addItem("Fixed Cell", "cell")
        self.composer_trigger_motion_start_kind.addItem("Named Region", "region")
        trigger_form.addRow("Motion start", self.composer_trigger_motion_start_kind)

        self.composer_trigger_motion_start_row = QDoubleSpinBox(self)
        self.composer_trigger_motion_start_row.setRange(0.0, 1.0)
        self.composer_trigger_motion_start_row.setValue(0.5)
        self.composer_trigger_motion_start_column = QDoubleSpinBox(self)
        self.composer_trigger_motion_start_column.setRange(0.0, 1.0)
        trigger_form_right.addRow("Motion start normalized row", self.composer_trigger_motion_start_row)
        trigger_form_right.addRow("Motion start normalized column", self.composer_trigger_motion_start_column)

        self.composer_trigger_motion_start_cell_row = QSpinBox(self)
        self.composer_trigger_motion_start_cell_row.setRange(0, 63)
        self.composer_trigger_motion_start_cell_column = QSpinBox(self)
        self.composer_trigger_motion_start_cell_column.setRange(0, 63)
        trigger_form_right.addRow("Motion start cell row", self.composer_trigger_motion_start_cell_row)
        trigger_form_right.addRow("Motion start cell column", self.composer_trigger_motion_start_cell_column)

        self.composer_trigger_motion_start_region = QComboBox(self)
        self.composer_trigger_motion_start_region.addItem("—", None)
        trigger_form_right.addRow("Motion start region", self.composer_trigger_motion_start_region)

        self.composer_trigger_motion_end_kind = QComboBox(self)
        self.composer_trigger_motion_end_kind.addItem("Normalized Position", "normalized")
        self.composer_trigger_motion_end_kind.addItem("Fixed Cell", "cell")
        self.composer_trigger_motion_end_kind.addItem("Named Region", "region")
        trigger_form_right.addRow("Motion end", self.composer_trigger_motion_end_kind)

        self.composer_trigger_motion_end_row = QDoubleSpinBox(self)
        self.composer_trigger_motion_end_row.setRange(0.0, 1.0)
        self.composer_trigger_motion_end_row.setValue(0.5)
        self.composer_trigger_motion_end_column = QDoubleSpinBox(self)
        self.composer_trigger_motion_end_column.setRange(0.0, 1.0)
        self.composer_trigger_motion_end_column.setValue(1.0)
        trigger_form_right.addRow("Motion end normalized row", self.composer_trigger_motion_end_row)
        trigger_form_right.addRow("Motion end normalized column", self.composer_trigger_motion_end_column)

        self.composer_trigger_motion_end_cell_row = QSpinBox(self)
        self.composer_trigger_motion_end_cell_row.setRange(0, 63)
        self.composer_trigger_motion_end_cell_column = QSpinBox(self)
        self.composer_trigger_motion_end_cell_column.setRange(0, 63)
        trigger_form_right.addRow("Motion end cell row", self.composer_trigger_motion_end_cell_row)
        trigger_form_right.addRow("Motion end cell column", self.composer_trigger_motion_end_cell_column)

        self.composer_trigger_motion_end_region = QComboBox(self)
        self.composer_trigger_motion_end_region.addItem("—", None)
        trigger_form_right.addRow("Motion end region", self.composer_trigger_motion_end_region)

        self.composer_trigger_motion_head_width = QDoubleSpinBox(self)
        self.composer_trigger_motion_head_width.setRange(0.01, 1.0)
        self.composer_trigger_motion_head_width.setValue(0.08)
        trigger_form_right.addRow("Motion head width", self.composer_trigger_motion_head_width)

        self.composer_trigger_motion_trail = QDoubleSpinBox(self)
        self.composer_trigger_motion_trail.setRange(0.0, 1.0)
        self.composer_trigger_motion_trail.setValue(0.20)
        trigger_form_right.addRow("Motion trail", self.composer_trigger_motion_trail)

        self.composer_trigger_colour_mode = QComboBox(self)
        self.composer_trigger_colour_mode.addItem("Static", "static")
        self.composer_trigger_colour_mode.addItem("Two-Colour", "two-colour")
        self.composer_trigger_colour_mode.addItem("Palette Cycle", "palette-cycle")
        self.composer_trigger_colour_mode.addItem("Keyframes", "keyframes")
        trigger_form_right.addRow("Colour mode", self.composer_trigger_colour_mode)

        self.composer_trigger_spatial_palette = QComboBox(self)
        self.composer_trigger_spatial_palette.addItem("Temporal only", False)
        self.composer_trigger_spatial_palette.addItem("Spatial + temporal", True)
        trigger_form_right.addRow("Palette mapping", self.composer_trigger_spatial_palette)

        self.composer_trigger_palette_list = QListWidget(self)
        self.composer_trigger_palette_list.setMinimumHeight(96)
        self.composer_trigger_palette_list.setMaximumHeight(112)
        trigger_form_right.addRow("Colour stops", self.composer_trigger_palette_list)

        trigger_palette_buttons = QHBoxLayout()
        self.composer_trigger_palette_add = QPushButton("Add")
        self.composer_trigger_palette_remove = QPushButton("Remove")
        self.composer_trigger_palette_up = QPushButton("↑")
        self.composer_trigger_palette_down = QPushButton("↓")
        trigger_palette_buttons.addWidget(self.composer_trigger_palette_add)
        trigger_palette_buttons.addWidget(self.composer_trigger_palette_remove)
        trigger_palette_buttons.addWidget(self.composer_trigger_palette_up)
        trigger_palette_buttons.addWidget(self.composer_trigger_palette_down)
        trigger_form_right.addRow("Stops", trigger_palette_buttons)

        self.composer_trigger_palette_position = QDoubleSpinBox(self)
        self.composer_trigger_palette_position.setRange(0.0, 1.0)
        self.composer_trigger_palette_position.setSingleStep(0.05)
        trigger_form_right.addRow("Stop position", self.composer_trigger_palette_position)

        self.composer_trigger_palette_colour = QPushButton("Choose stop colour…")
        trigger_form_right.addRow("Stop colour", self.composer_trigger_palette_colour)

        self.composer_trigger_row = QSpinBox(self)
        self.composer_trigger_row.setRange(0, 63)
        self.composer_trigger_column = QSpinBox(self)
        self.composer_trigger_column.setRange(0, 63)
        trigger_form_right.addRow("Response row", self.composer_trigger_row)
        trigger_form_right.addRow(
            "Response column",
            self.composer_trigger_column,
        )

        trigger_splitter.addWidget(trigger_list_panel)
        trigger_splitter.addWidget(trigger_properties)
        trigger_splitter.setSizes([330, 470])
        trigger_layout.addWidget(trigger_splitter)
        composer_layout.addWidget(trigger_box)

        timeline_row = QHBoxLayout()
        timeline_row.addWidget(QLabel("Offline Timeline Preview"))
        self.composer_timeline_play = QPushButton("Play")
        self.composer_timeline_pause = QPushButton("Pause")
        self.composer_timeline_reset = QPushButton("Reset")
        self.composer_time = QDoubleSpinBox(self)
        self.composer_time.setRange(0.0, 30.0)
        self.composer_time.setSingleStep(0.05)
        self.composer_time.setSuffix(" s")
        self.composer_timeline_progress = QProgressBar(self)
        self.composer_timeline_progress.setRange(0, 1000)
        timeline_row.addWidget(self.composer_timeline_play)
        timeline_row.addWidget(self.composer_timeline_pause)
        timeline_row.addWidget(self.composer_timeline_reset)
        timeline_row.addWidget(self.composer_time)
        timeline_row.addWidget(self.composer_timeline_progress, 1)
        composer_layout.addLayout(timeline_row)

        output_row = QHBoxLayout()
        self.composer_generate = QPushButton("Generate Python")
        self.composer_validate = QPushButton("Generate + Validate & Preview")
        self.composer_open_code = QPushButton("Open Generated Code")
        self.composer_save = QPushButton("Save")
        self.composer_save_as = QPushButton("Save As…")
        self.composer_save_as.setToolTip("Save the current Composer effect to a new authoring file.")
        self.composer_install = QPushButton("Install to Serpent")
        self.composer_uninstall = QPushButton("Uninstall from Serpent")
        self.composer_uninstall.setToolTip("Remove only the installed plugin copy; keep the authoring project file.")
        self.composer_action_status = QLabel("")
        self.composer_action_status.setWordWrap(True)
        self.composer_save.setToolTip(
            "Save the validated Composer-generated Python to the chosen plugin file."
        )
        self.composer_install.setToolTip(
            "Install the currently validated Composer-generated effect into Serpent."
        )
        output_row.addWidget(self.composer_generate)
        output_row.addWidget(self.composer_validate)
        output_row.addWidget(self.composer_open_code)
        output_row.addWidget(self.composer_save)
        output_row.addWidget(self.composer_save_as)
        output_row.addWidget(self.composer_install)
        output_row.addWidget(self.composer_uninstall)
        output_row.addWidget(self.composer_action_status, 1)
        output_row.addStretch()
        composer_layout.addLayout(output_row)

        self.composer_source_preview = QPlainTextEdit(self)
        self.composer_source_preview.setReadOnly(True)
        self.composer_source_preview.setMaximumHeight(190)
        self.composer_source_preview.setPlaceholderText(
            "Generated ordinary Serpent Python appears here."
        )
        self.composer_source_preview.setVisible(False)
        self.composer_open_code.setText("Focus Python Code")
        unified_code_label = QLabel("Advanced Python — canonical source for Validate, Save, Preview, and Install.")
        unified_code_label.setWordWrap(True)
        composer_layout.addWidget(unified_code_label)
        composer_layout.addWidget(self.source_edit)

        self.catalog_search = QLineEdit()
        self.catalog_search.setPlaceholderText("Search installed effects…")
        self.catalog_search.setClearButtonEnabled(True)

        self.catalog_count_label = QLabel()
        self.catalog_list = QListWidget()
        self.catalog_list.setMaximumHeight(170)
        self.catalog_list.setAlternatingRowColors(True)

        self.catalog_use_template = QPushButton("Use Selected as Template")
        self.catalog_use_template.setToolTip(
            "Open the selected installed software effect in Developer Workshop "
            "as a separate authoring copy. The installed effect is never edited in place."
        )

        catalog_header = QWidget(self)
        catalog_header_layout = QHBoxLayout(catalog_header)
        catalog_header_layout.setContentsMargins(0, 0, 0, 0)
        catalog_header_layout.addWidget(QLabel("Installed effect catalog"))
        catalog_header_layout.addStretch()
        catalog_header_layout.addWidget(self.catalog_use_template)
        catalog_header_layout.addWidget(self.catalog_count_label)

        self.effect_name_label = QLabel()
        effect_name_font = self.effect_name_label.font()
        effect_name_font.setPointSize(effect_name_font.pointSize() + 2)
        effect_name_font.setBold(True)
        self.effect_name_label.setFont(effect_name_font)

        self.effect_description_label = QLabel()
        self.effect_description_label.setWordWrap(True)

        self.effect_capability_label = QLabel()
        self.effect_capability_label.setWordWrap(True)

        self.live_preview_context_label = QLabel(
            "Physical preview follows the active synchronized members. "
            "The Preview target selector below affects only the in-memory preview."
        )
        self.live_preview_context_label.setWordWrap(True)

        self.defaults_button = QPushButton("Restore Defaults")
        self.scene_save_callback = None
        self.scene_update_callback = None
        self.save_scene_button = QPushButton("Save as Scene…")
        self.update_scene_button = QPushButton("Update Selected Scene")
        self.save_scene_button.setToolTip(
            "Capture Serpent's current scene topology and use the current "
            "Workshop effect for the selected preview target."
        )
        self.update_scene_button.setToolTip(
            "Update the selected saved scene with the current Workshop "
            "effect while preserving its topology and brightness."
        )

        self.test_key_button = QPushButton("Test Key Press")
        self.test_mouse_button = QPushButton("Test Mouse Press")
        self.test_key_button.setToolTip(
            "Inject a synthetic keyboard event into the selected installed effect."
        )
        self.test_mouse_button.setToolTip(
            "Inject a synthetic mouse event into the selected installed effect."
        )

        self.workshop_mode_label = QLabel(
            "Browse and preview installed Serpent effects. "
            "Switch to Developer for source editing and isolated candidate execution."
        )
        self.workshop_mode_label.setWordWrap(True)

        mode_row = QWidget(self)
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(QLabel("Workspace"))
        mode_layout.addWidget(self.mode_combo, 1)

        layout = self.layout()
        if layout is not None:
            layout.insertWidget(0, mode_row)
            layout.insertWidget(1, self.workshop_mode_label)

            authoring_row = QWidget(self)
            authoring_layout = QHBoxLayout(authoring_row)
            authoring_layout.setContentsMargins(0, 0, 0, 0)
            authoring_layout.addWidget(self.authoring_surface_label)
            authoring_layout.addWidget(self.authoring_surface_combo)
            authoring_layout.addStretch()
            self.authoring_row = authoring_row
            layout.insertWidget(2, authoring_row)

            layout.insertWidget(3, self.developer_workflow_container)
            layout.insertWidget(4, self.composer_container)
            layout.insertWidget(5, catalog_header)
            layout.insertWidget(8, self.catalog_search)
            layout.insertWidget(9, self.catalog_list)
            layout.insertWidget(10, self.effect_name_label)
            layout.insertWidget(11, self.effect_description_label)
            layout.insertWidget(12, self.live_preview_context_label)

            details_row = QWidget(self)
            details_layout = QHBoxLayout(details_row)
            details_layout.setContentsMargins(0, 0, 0, 0)
            details_layout.addWidget(self.effect_capability_label, 1)
            details_layout.addWidget(self.test_key_button)
            details_layout.addWidget(self.test_mouse_button)
            details_layout.addWidget(self.defaults_button)
            layout.insertWidget(13, details_row)

            scene_row = QWidget(self)
            scene_layout = QHBoxLayout(scene_row)
            scene_layout.setContentsMargins(0, 0, 0, 0)
            scene_layout.addWidget(QLabel("Scenes"))
            scene_layout.addWidget(self.save_scene_button)
            scene_layout.addWidget(self.update_scene_button)
            scene_layout.addStretch()
            layout.insertWidget(14, scene_row)

            # Keep Effects Workshop + preview/results contiguous.
            # Python / Effect Guide follows the complete Workshop surface.
            layout.addWidget(self.guide_toggle_button)
            layout.addWidget(self.guide_container)

            self._installed_only_widgets = (
                catalog_header,
                self.catalog_search,
                self.catalog_list,
                self.effect_name_label,
                self.effect_description_label,
                self.live_preview_context_label,
                details_row,
                scene_row,
            )
        else:
            self._installed_only_widgets = ()

        self._retitle_workshop()
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        # EffectsWorkshopPanel subclasses EffectLabPanel; there is no nested
        # self.effect_lab child. Wire the refresh callback directly on self.
        self.effect_catalog_refresh_callback = (
            self._sync_installed_catalog_after_mutation
        )
        self.catalog_search.textChanged.connect(self._filter_catalog)
        self.catalog_list.currentItemChanged.connect(self._catalog_selection_changed)
        self.defaults_button.clicked.connect(self._restore_installed_defaults)
        self.save_scene_button.clicked.connect(self._save_workshop_scene)
        self.update_scene_button.clicked.connect(
            self._update_selected_scene
        )
        self.test_key_button.clicked.connect(self._test_installed_key_press)
        self.test_mouse_button.clicked.connect(self._test_installed_mouse_press)

        self.live_preview_refresh_timer = QTimer(self)
        self.live_preview_refresh_timer.setSingleShot(True)
        self.live_preview_refresh_timer.setInterval(300)
        self.live_preview_refresh_timer.timeout.connect(
            self._refresh_live_preview
        )
        self.effect_parameters.changed.connect(
            self._schedule_live_preview_refresh
        )
        self.source_edit.textChanged.connect(
            self._developer_source_changed
        )
        self.guide_toggle_button.toggled.connect(
            self._toggle_effect_guide
        )
        self.guide_search.textChanged.connect(
            self._filter_effect_guide
        )
        self.guide_topics.currentItemChanged.connect(
            self._guide_topic_changed
        )
        self.guide_insert_button.clicked.connect(
            self._insert_guide_snippet
        )

        self.authoring_surface_combo.currentIndexChanged.connect(
            self._authoring_surface_changed
        )
        self.composer_add_fill.clicked.connect(lambda: self._composer_add_layer("Fill"))
        self.composer_add_cell.clicked.connect(lambda: self._composer_add_layer("Cell"))
        self.composer_add_gradient.clicked.connect(lambda: self._composer_add_layer("Gradient"))
        self.composer_add_pulse.clicked.connect(lambda: self._composer_add_layer("Pulse"))
        self.composer_remove.clicked.connect(self._composer_remove_layer)
        self.composer_up.clicked.connect(lambda: self._composer_move_layer(-1))
        self.composer_down.clicked.connect(lambda: self._composer_move_layer(1))
        self.composer_undo.clicked.connect(self._composer_undo)
        self.composer_redo.clicked.connect(self._composer_redo)
        self.composer_duplicate.clicked.connect(self._composer_duplicate_current)
        self.composer_copy.clicked.connect(self._composer_copy_current)
        self.composer_paste.clicked.connect(self._composer_paste_clipboard)
        self.composer_bulk_opacity.textEdited.connect(
            lambda *_: self._composer_bulk_mark_dirty("opacity")
        )
        self.composer_bulk_delay.textEdited.connect(
            lambda *_: self._composer_bulk_mark_dirty("timeline_delay")
        )
        self.composer_bulk_speed.textEdited.connect(
            lambda *_: self._composer_bulk_mark_dirty("speed_multiplier")
        )
        self.composer_bulk_region.currentIndexChanged.connect(
            lambda *_: self._composer_bulk_mark_dirty("region")
        )
        self.composer_bulk_colour_mode.currentIndexChanged.connect(
            lambda *_: self._composer_bulk_mark_dirty("colour_mode")
        )
        self.composer_bulk_motion_mode.currentIndexChanged.connect(
            lambda *_: self._composer_bulk_mark_dirty("motion_mode")
        )
        self.composer_bulk_apply.clicked.connect(
            self._composer_bulk_apply_changes
        )
        self.composer_layers.currentRowChanged.connect(self._composer_select_layer)
        self.composer_layer_stack.itemSelectionChanged.connect(
            self._composer_stack_selection_changed
        )
        self.composer_layer_stack.currentItemChanged.connect(
            self._composer_stack_current_changed
        )
        self.composer_group_create.clicked.connect(self._composer_group_create_from_selection)
        self.composer_group_delete.clicked.connect(self._composer_group_delete_selected)
        self.composer_group_up.clicked.connect(lambda: self._composer_group_move(-1))
        self.composer_group_down.clicked.connect(lambda: self._composer_group_move(1))
        self.composer_groups.currentRowChanged.connect(self._composer_group_selected)
        self.composer_group_name.editingFinished.connect(self._composer_group_property_changed)
        self.composer_group_enabled.currentIndexChanged.connect(self._composer_group_property_changed)
        self.composer_group_opacity.valueChanged.connect(self._composer_group_property_changed)
        self.composer_group_timeline_offset.valueChanged.connect(self._composer_group_property_changed)
        self.composer_group_speed.valueChanged.connect(self._composer_group_property_changed)
        self.composer_group_region.currentIndexChanged.connect(self._composer_group_property_changed)
        self.composer_preset_search.textChanged.connect(self._composer_preset_refresh_library)
        self.composer_preset_kind.currentIndexChanged.connect(self._composer_preset_refresh_library)
        self.composer_preset_target.textChanged.connect(self._composer_preset_refresh_library)
        self.composer_preset_save_layer.clicked.connect(lambda: self._composer_preset_save("layer"))
        self.composer_preset_save_group.clicked.connect(lambda: self._composer_preset_save("group"))
        self.composer_preset_save_trigger.clicked.connect(lambda: self._composer_preset_save("trigger"))
        self.composer_preset_save_composition.clicked.connect(lambda: self._composer_preset_save("composition"))
        self.composer_preset_apply.clicked.connect(self._composer_preset_apply_selected)
        self.composer_preset_delete.clicked.connect(self._composer_preset_delete_selected)
        self.composer_preset_refresh.clicked.connect(self._composer_preset_refresh_library)
        self._composer_update_history_buttons()
        self._composer_rebuild_visual_stack()
        self._composer_refresh_bulk_editor()
        self._composer_preset_refresh_library()
        self.composer_matrix.cellSelected.connect(self._composer_matrix_cell)
        self.composer_matrix.regionSelectionChanged.connect(
            self._composer_region_selection_changed
        )
        self.composer_region_edit.toggled.connect(
            self._composer_region_edit_toggled
        )
        self.composer_region_mode.currentIndexChanged.connect(
            self._composer_region_mode_changed
        )
        self.composer_region_select_all.clicked.connect(
            self._composer_region_select_all_cells
        )
        self.composer_region_clear.clicked.connect(
            self._composer_region_clear_selection
        )
        self.composer_region_invert.clicked.connect(
            self._composer_region_invert_selection
        )
        self.composer_region_new.clicked.connect(
            self._composer_region_create
        )
        self.composer_region_rename.clicked.connect(
            self._composer_region_rename_selected
        )
        self.composer_region_delete.clicked.connect(
            self._composer_region_delete_selected
        )
        self.composer_region_list.currentRowChanged.connect(
            self._composer_region_list_selected
        )
        self.composer_timeline_play.clicked.connect(self._composer_timeline_play_clicked)
        self.composer_timeline_pause.clicked.connect(self._composer_timeline_pause_clicked)
        self.composer_timeline_reset.clicked.connect(self._composer_timeline_reset_clicked)
        self.composer_time.valueChanged.connect(self._composer_timeline_scrub_changed)
        self.composer_colour_button.clicked.connect(lambda: self._composer_pick_colour(False))
        self.composer_colour2_button.clicked.connect(lambda: self._composer_pick_colour(True))
        self.composer_opacity.valueChanged.connect(self._composer_property_changed)
        self.composer_row.valueChanged.connect(self._composer_property_changed)
        self.composer_column.valueChanged.connect(self._composer_property_changed)
        self.composer_direction.currentTextChanged.connect(self._composer_property_changed)
        self.composer_duration.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_delay.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_timeline_duration.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_playback.currentIndexChanged.connect(self._composer_property_changed)
        self.composer_layer_phase.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_fade_in.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_fade_out.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_speed_multiplier.valueChanged.connect(self._composer_property_changed)
        for widget in (
            self.composer_motion_mode,
            self.composer_motion_direction,
            self.composer_motion_start_kind,
            self.composer_motion_start_region,
            self.composer_motion_end_kind,
            self.composer_motion_end_region,
        ):
            widget.currentIndexChanged.connect(self._composer_property_changed)
        for widget in (
            self.composer_motion_start_row,
            self.composer_motion_start_column,
            self.composer_motion_start_cell_row,
            self.composer_motion_start_cell_column,
            self.composer_motion_end_row,
            self.composer_motion_end_column,
            self.composer_motion_end_cell_row,
            self.composer_motion_end_cell_column,
            self.composer_motion_head_width,
            self.composer_motion_trail,
        ):
            widget.valueChanged.connect(self._composer_property_changed)
        self.composer_layer_region.currentIndexChanged.connect(
            self._composer_property_changed
        )
        self.composer_colour_mode.currentIndexChanged.connect(self._composer_property_changed)
        self.composer_spatial_palette.currentIndexChanged.connect(self._composer_property_changed)
        self.composer_palette_list.currentRowChanged.connect(self._composer_palette_selected)
        self.composer_palette_position.valueChanged.connect(self._composer_palette_position_changed)
        self.composer_palette_add.clicked.connect(self._composer_palette_add_stop)
        self.composer_palette_remove.clicked.connect(self._composer_palette_remove_stop)
        self.composer_palette_up.clicked.connect(lambda: self._composer_palette_move(-1))
        self.composer_palette_down.clicked.connect(lambda: self._composer_palette_move(1))
        self.composer_palette_colour.clicked.connect(self._composer_palette_pick_colour)
        self.composer_generate.clicked.connect(self._composer_generate_to_source)
        self.composer_validate.clicked.connect(self._composer_generate_and_validate)
        self.composer_open_code.clicked.connect(self._composer_open_generated_code)
        self.composer_name.textChanged.connect(self._composer_identity_changed)
        self.composer_id.textChanged.connect(self._composer_identity_changed)
        self.composer_description.textChanged.connect(self._composer_identity_changed)

        self.composer_create_file.clicked.connect(self._composer_choose_output_file)
        self.composer_load_file.clicked.connect(self._composer_load_effect)
        self.composer_load_installed.clicked.connect(self._composer_load_installed_effect)
        self.catalog_use_template.clicked.connect(
            self._open_selected_installed_as_template
        )
        self.composer_save.clicked.connect(self._composer_save_generated)
        self.composer_save_as.clicked.connect(self._composer_save_as)
        self.composer_install.clicked.connect(self._composer_install_generated)
        self.composer_uninstall.clicked.connect(self._composer_uninstall_current)
        self.composer_name.textChanged.connect(self._composer_metadata_changed)
        self.composer_id.textChanged.connect(self._composer_metadata_changed)
        self.composer_description.textChanged.connect(self._composer_metadata_changed)

        self.composer_trigger_add.clicked.connect(
            self._composer_add_trigger
        )
        self.composer_trigger_remove.clicked.connect(
            self._composer_remove_trigger
        )
        self.composer_trigger_list.currentRowChanged.connect(
            self._composer_select_trigger
        )
        self.composer_trigger_source.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_action.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_code.textChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_destination.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_response.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_region.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_origin.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_direction.currentIndexChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_relative_row.valueChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_relative_column.valueChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_duration.valueChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_delay.valueChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_playback.currentIndexChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_phase.valueChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_fade_in.valueChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_fade_out.valueChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_speed_multiplier.valueChanged.connect(self._composer_trigger_property_changed)
        for widget in (
            self.composer_trigger_motion_mode,
            self.composer_trigger_motion_direction,
            self.composer_trigger_motion_start_kind,
            self.composer_trigger_motion_start_region,
            self.composer_trigger_motion_end_kind,
            self.composer_trigger_motion_end_region,
        ):
            widget.currentIndexChanged.connect(self._composer_trigger_property_changed)
        for widget in (
            self.composer_trigger_motion_start_row,
            self.composer_trigger_motion_start_column,
            self.composer_trigger_motion_start_cell_row,
            self.composer_trigger_motion_start_cell_column,
            self.composer_trigger_motion_end_row,
            self.composer_trigger_motion_end_column,
            self.composer_trigger_motion_end_cell_row,
            self.composer_trigger_motion_end_cell_column,
            self.composer_trigger_motion_head_width,
            self.composer_trigger_motion_trail,
        ):
            widget.valueChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_row.valueChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_column.valueChanged.connect(
            self._composer_trigger_property_changed
        )
        self.composer_trigger_colour_button.clicked.connect(
            self._composer_pick_trigger_colour
        )
        self.composer_trigger_colour_mode.currentIndexChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_spatial_palette.currentIndexChanged.connect(self._composer_trigger_property_changed)
        self.composer_trigger_palette_list.currentRowChanged.connect(self._composer_trigger_palette_selected)
        self.composer_trigger_palette_position.valueChanged.connect(self._composer_trigger_palette_position_changed)
        self.composer_trigger_palette_add.clicked.connect(self._composer_trigger_palette_add_stop)
        self.composer_trigger_palette_remove.clicked.connect(self._composer_trigger_palette_remove_stop)
        self.composer_trigger_palette_up.clicked.connect(lambda: self._composer_trigger_palette_move(-1))
        self.composer_trigger_palette_down.clicked.connect(lambda: self._composer_trigger_palette_move(1))
        self.composer_trigger_palette_colour.clicked.connect(self._composer_trigger_palette_pick_colour)

        self.composer_intent_combo.currentIndexChanged.connect(
            self._composer_intent_changed
        )
        self.composer_device_class_combo.currentTextChanged.connect(
            self._composer_device_class_changed
        )
        self.composer_sync_targets.currentRowChanged.connect(
            self._composer_sync_target_selected
        )
        self.composer_add_target.clicked.connect(
            self._composer_add_sync_target
        )
        self.composer_remove_target.clicked.connect(
            self._composer_remove_sync_target
        )
        self.composer_target_combo.currentIndexChanged.connect(
            self._composer_target_changed
        )
        self.composer_rows.valueChanged.connect(
            self._composer_custom_geometry_changed
        )
        self.composer_columns.valueChanged.connect(
            self._composer_custom_geometry_changed
        )

        self._populate_effect_guide()
        self._composer_add_layer("Fill")
        self._composer_target_changed()
        self._composer_initialize_target_models()
        self._composer_add_trigger()
        self._composer_intent_changed()
        self._authoring_surface_changed()

        self._load_installed_specs()
        self._populate_catalog()
        self._apply_workshop_visibility()
        self._select_installed_default()
        self._setup_workshop_shortcuts()

    def _setup_workshop_shortcuts(self):
        self._composer_shortcut_actions = []

        def add_action(label, sequence, callback, *, composer_only=False):
            action = QAction(label, self)
            action.setShortcut(QKeySequence(sequence))
            action.setShortcutContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            action.triggered.connect(callback)
            self.addAction(action)
            if composer_only:
                self._composer_shortcut_actions.append(action)
            return action

        self.shortcut_undo_action = add_action(
            "Composer Undo", "Ctrl+Z", self._composer_undo,
            composer_only=True,
        )
        self.shortcut_redo_action = add_action(
            "Composer Redo", "Ctrl+Shift+Z", self._composer_redo,
            composer_only=True,
        )
        self.shortcut_redo_alt_action = add_action(
            "Composer Redo Alternate", "Ctrl+Y", self._composer_redo,
            composer_only=True,
        )
        self.shortcut_copy_action = add_action(
            "Composer Copy", "Ctrl+C", self._composer_copy_current,
            composer_only=True,
        )
        self.shortcut_paste_action = add_action(
            "Composer Paste", "Ctrl+V", self._composer_paste_clipboard,
            composer_only=True,
        )
        self.shortcut_duplicate_action = add_action(
            "Composer Duplicate", "Ctrl+D", self._composer_duplicate_current,
            composer_only=True,
        )
        self.shortcut_save_action = add_action(
            "Save Workshop Source", "Ctrl+S", self._shortcut_save_source,
        )
        self.shortcut_validate_action = add_action(
            "Validate & Preview", "Ctrl+Enter", self._shortcut_validate_source,
        )

        application = QApplication.instance()
        if application is not None:
            application.focusChanged.connect(
                self._workshop_shortcut_focus_changed
            )
        self.mode_combo.currentIndexChanged.connect(
            self._update_workshop_shortcut_state
        )
        self.authoring_surface_combo.currentIndexChanged.connect(
            self._update_workshop_shortcut_state
        )
        self._update_workshop_shortcut_state()

    def _workshop_text_editing_focus(self):
        widget = QApplication.focusWidget()
        while widget is not None:
            if isinstance(
                widget,
                (
                    QPlainTextEdit,
                    QLineEdit,
                    QSpinBox,
                    QDoubleSpinBox,
                    QComboBox,
                ),
            ):
                return True
            if widget is self:
                break
            widget = widget.parentWidget()
        return False

    def _composer_shortcuts_available(self):
        return (
            not self._is_installed_mode()
            and self.authoring_surface_combo.currentData() == "composer"
            and not self._workshop_text_editing_focus()
        )

    def _workshop_shortcut_focus_changed(self, old, current):
        self._update_workshop_shortcut_state()

    def _update_workshop_shortcut_state(self, *args):
        enabled = self._composer_shortcuts_available()
        for action in self._composer_shortcut_actions:
            action.setEnabled(enabled)

    def _shortcut_save_source(self):
        if self.save_button.isEnabled():
            self.save_source()

    def _shortcut_validate_source(self):
        if self.validate_button.isEnabled():
            self.validate_source()

    def _retitle_workshop(self):
        for label in self.findChildren(QLabel):
            if label.text() == "Effect Lab — Safe Editor":
                label.setText("Effects Workshop")
            elif label.text().startswith(
                "Edit Python and preview synthetic output"
            ):
                label.setText(
                    "Browse, configure, and preview installed effects. "
                    "Developer mode preserves the isolated effect-authoring lab."
                )
        self.status_label.setText(
            "Effects Workshop ready. Installed Effects uses Serpent's public "
            "effect registry; Developer mode keeps candidate code isolated."
        )

    def _is_installed_mode(self):
        return self._workshop_mode == self.MODE_INSTALLED

    @staticmethod
    def _builtin_template_source_for_id(effect_id):
        from serpent_core.effects import get_effect_plugin_spec

        spec = get_effect_plugin_spec(str(effect_id))
        effect_class = getattr(spec, "effect_class", None)
        if effect_class is None:
            raise RuntimeError(
                f"Registered effect {effect_id!r} exposes no effect class."
            )

        module_name = str(getattr(effect_class, "__module__", "")).strip()
        class_name = str(getattr(effect_class, "__name__", "")).strip()
        if not module_name or not class_name:
            raise RuntimeError(
                f"Registered effect {effect_id!r} has no importable implementation class."
            )

        template_id = self_id = (
            EffectsWorkshopPanel._creator_slug(str(effect_id)) + "-template"
        )
        template_name = f"{spec.name} Template"
        description = (
            f"Editable Serpent template derived from built-in effect "
            f"{spec.name!r}. Original effect: {effect_id}."
        )

        parameter_lines = []
        for parameter in tuple(getattr(spec, "parameters", ()) or ()):
            parameter_lines.append(
                "        EffectParameterSpec("
                f"id={parameter.id!r}, "
                f"label={parameter.label!r}, "
                f"kind={parameter.kind!r}, "
                f"default={parameter.default!r}, "
                f"minimum={parameter.minimum!r}, "
                f"maximum={parameter.maximum!r}, "
                f"choices={tuple(parameter.choices)!r}"
                "),"
            )
        parameters_block = "\n".join(parameter_lines)

        return f"""from __future__ import annotations

# Generated by Serpent Developer Workshop from installed built-in effect:
#   {effect_id}
# This is a separate authoring template. The installed built-in is untouched.
# Override only the methods you want to change.

from {module_name} import {class_name} as _InstalledBaseEffect
from dataclasses import replace
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec

class Effect(_InstalledBaseEffect):
    # Keep the installed renderer, but give the derived candidate its own identity.
    definition = replace(
        _InstalledBaseEffect.definition,
        id={template_id!r},
    )

SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id={template_id!r},
        name={template_name!r},
        description={description!r},
        effect_class=Effect,
        input_capabilities={tuple(getattr(spec, 'input_capabilities', ()) or ())!r},
        render_targets={tuple(getattr(spec, 'render_targets', ()) or ())!r},
        parameters=(
{parameters_block}
        ),
    ),
)
"""

    def _materialize_builtin_template(self, effect_id):
        project_dir = ROOT / "projects" / "effects"
        project_dir.mkdir(parents=True, exist_ok=True)
        template_source = self._builtin_template_source_for_id(effect_id)
        base_id = self._creator_slug(str(effect_id)) or "built-in-effect"
        output_path = project_dir / f"{base_id}-template.py"
        counter = 2
        while output_path.exists():
            output_path = project_dir / f"{base_id}-template-{counter}.py"
            counter += 1
        self._atomic_write(output_path, template_source)
        return output_path

    def _open_selected_installed_as_template(self):
        if not self._is_installed_mode():
            self._composer_set_action_status(
                "Installed-effect authoring starts from Installed Effects."
            )
            return False

        effect_id = str(self.effect_combo.currentData() or "").strip()
        if not effect_id:
            self._composer_set_action_status(
                "Select an installed effect first."
            )
            return False

        try:
            source_path = self._installed_plugin_path_for_id(effect_id)
        except RuntimeError as exc:
            self._composer_set_action_status(
                f"Installed-effect authoring refused: {exc}"
            )
            return False

        try:
            if source_path is not None:
                source_text = source_path.read_text(encoding="utf-8")
                virtual_name = source_path.name
            else:
                source_text = self._builtin_template_source_for_id(effect_id)
                virtual_name = f"{self._creator_slug(effect_id)}.py"
        except (OSError, RuntimeError, UnicodeError, ValueError) as exc:
            self._composer_set_action_status(
                "Installed-effect authoring could not load source: "
                f"{type(exc).__name__}: {exc}"
            )
            return False

        developer_index = self.mode_combo.findData(self.MODE_DEVELOPER)
        if developer_index < 0:
            self._composer_set_action_status(
                "Developer Workshop mode is unavailable."
            )
            return False

        self.mode_combo.setCurrentIndex(developer_index)

        return self._composer_load_installed_source_in_memory(
            effect_id,
            source_text,
            virtual_name=virtual_name,
        )

    def _sync_installed_catalog_after_mutation(
        self,
        select_effect_id=None,
        removed_effect_id=None,
        navigate=True,
    ):
        if navigate:
            installed_index = self.mode_combo.findData(self.MODE_INSTALLED)
            if (
                installed_index >= 0
                and self.mode_combo.currentIndex() != installed_index
            ):
                self.mode_combo.setCurrentIndex(installed_index)

        # Never rely on mode-switch side effects alone. Rebuild the authoritative
        # in-process snapshot and visible Installed Effects controls explicitly.
        self._load_installed_specs()
        self._populate_combo(self._installed_specs)
        self._populate_catalog()

        installed_ids = {spec.id for spec in self._installed_specs}

        if removed_effect_id and removed_effect_id in installed_ids:
            raise RuntimeError(
                f"Removed effect {removed_effect_id!r} is still present after "
                "registry/catalog synchronization."
            )

        if select_effect_id and select_effect_id not in installed_ids:
            raise RuntimeError(
                f"Installed effect {select_effect_id!r} did not appear after "
                "registry/catalog synchronization."
            )

        if select_effect_id:
            effect_index = self.effect_combo.findData(select_effect_id)
            if effect_index < 0:
                raise RuntimeError(
                    f"Installed effect {select_effect_id!r} is in the registry "
                    "but missing from the Installed Effects combo."
                )
            self.effect_combo.setCurrentIndex(effect_index)
            self._adopt_installed_spec()
            self.reset_effect()
        elif self.effect_combo.count():
            self._select_installed_default()
        else:
            self.spec = None
            self.specs = []
            self.effect_combo.setEnabled(False)
            self.catalog_list.clear()
            self.catalog_count_label.setText("0 of 0")
            self.preview.clear_frame()
            self._update_live_preview_context()

        return True

    def _refresh_installed_catalog_after_mutation(self):
        return self._sync_installed_catalog_after_mutation()

    def _mode_changed(self, *args):
        mode = self.mode_combo.currentData()
        if mode not in (self.MODE_INSTALLED, self.MODE_DEVELOPER):
            return
        if mode == self._workshop_mode:
            return

        if self._workshop_mode == self.MODE_DEVELOPER:
            self._developer_specs = list(self.specs)

        self.live_preview_refresh_timer.stop()
        self.stop_live_preview(silent=True)
        self._workshop_mode = mode
        self.preview.clear_frame()
        self.elapsed = 0.0
        self.preview_enabled = False
        self._apply_workshop_visibility()

        if self._is_installed_mode():
            self._load_installed_specs()
            self._populate_combo(self._installed_specs)
            self._populate_catalog()
            self._select_installed_default()
            self.workshop_mode_label.setText(
                "Installed Effects — browse the registered catalog, adjust "
                "metadata-driven controls, and preview safely in memory."
            )
        else:
            self._populate_combo(self._developer_specs)
            self._adopt_selected_spec()
            self.workshop_mode_label.setText(
                "Developer — edit source and execute candidate effects only "
                "inside the existing isolated worker."
            )
            self.status_label.setText(
                "Developer mode — create, edit, validate, preview, then "
                "install an effect without leaving the Workshop."
            )
            self._update_developer_workflow_state()

    def _apply_workshop_visibility(self):
        developer = not self._is_installed_mode()

        for widget in self._installed_only_widgets:
            widget.setVisible(not developer)

        self.test_key_button.setVisible(not developer)
        self.test_mouse_button.setVisible(not developer)
        self.defaults_button.setVisible(not developer)

        self.developer_workflow_container.setVisible(developer)
        self.authoring_row.setVisible(developer)

        composer = (
            developer
            and self.authoring_surface_combo.currentData() == "composer"
        )
        code = developer and not composer

        self.composer_container.setVisible(composer)
        guide_available = developer and composer
        self.guide_toggle_button.setVisible(guide_available)
        self.guide_container.setVisible(
            guide_available and self.guide_toggle_button.isChecked()
        )

        for widget in (
            self.path_edit,
            self.browse_button,
            self.load_button,
            self.new_effect_button,
            self.validate_button,
            self.save_button,
            self.reload_button,
            self.promote_button,
            self.source_edit,
            self.mouse_event_button,
        ):
            widget.setVisible(code)

        self.preview.setToolTip(
            "Installed preview. Reactive keyboard effects can be stimulated "
            "by clicking a cell."
            if not developer
            else "Click a cell to inject a synthetic key press."
        )

    def _handle_reply(self, action, payload):
        super()._handle_reply(action, payload)

        if (
            action == "load"
            and payload.get("ok")
            and not self._is_installed_mode()
            and self.preview_enabled
            and self.spec is not None
        ):
            self._validated_developer_source = (
                self.source_edit.toPlainText()
            )
            self._update_developer_workflow_state()

    @staticmethod
    def _creator_slug(value):
        value = str(value).strip().casefold().replace("_", "-")
        slug = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in value)
        while "--" in slug:
            slug = slug.replace("--", "-")
        return slug.strip("-")

    @staticmethod
    def _creator_class_name(name):
        words = [part for part in "".join(
            ch if ch.isalnum() else " " for ch in str(name)
        ).split() if part]
        result = "".join(word[:1].upper() + word[1:] for word in words) or "NewEffect"
        if result[0].isdigit():
            result = "Effect" + result
        if not result.endswith("Effect"):
            result += "Effect"
        return result

    @classmethod
    def _effect_template(cls, *, name, effect_id, description, template):
        effect_id = cls._creator_slug(effect_id)
        class_name = cls._creator_class_name(name)
        name_literal = repr(str(name).strip())
        id_literal = repr(effect_id)
        description_literal = repr(str(description).strip() or f"Custom {name} effect.")
        reactive = template.startswith("Reactive")
        animated = template == "Animated Matrix"
        capabilities = ()
        if template == "Reactive Keyboard":
            capabilities = ("keyboard",)
        elif template == "Reactive Mouse":
            capabilities = ("mouse",)
        elif template == "Reactive Keyboard + Mouse":
            capabilities = ("keyboard", "mouse")
        render_targets = ("keyboard", "mouse")

        imports = """from __future__ import annotations

import math

from serpent_core.effects.base import (
    Effect,
    EffectDefinition,
    EffectEvent,
    EffectFrame,
    EffectParameters,
    EffectTarget,
    scale_colour,
)
from serpent_core.effects.plugin import EffectParameterSpec, EffectPluginSpec
from gui.notifications import notify_error, notify_info, notify_warning
"""
        if reactive:
            imports += "from serpent_core.effect_sdk import event_cell, event_matches, event_timestamp\n"

        definition = f"""

class {class_name}(Effect):
    definition = EffectDefinition(
        id={id_literal},
        colours=2,
        animated={str(animated or reactive)},
        speed={str(animated or reactive)},
        spatial={str(reactive)},
    )
"""

        if reactive:
            match_blocks = []
            if "keyboard" in capabilities:
                match_blocks.append("""        if event_matches(event, kind="key-press", source_prefix="keyboard:"):
            cell = event_cell(event)
            if cell is not None:
                self._pulses.append((event_timestamp(event), cell))
""")
            if "mouse" in capabilities:
                match_blocks.append("""        if event_matches(event, kind="mouse-press", source_prefix="mouse:"):
            cell = event_cell(event) or (0, 0)
            self._pulses.append((event_timestamp(event), cell))
""")
            body = """
    def __init__(self):
        self._pulses = []

    def handle_event(self, event: EffectEvent) -> None:
""" + "".join(match_blocks) + """
    def render(self, elapsed: float, parameters: EffectParameters, target: EffectTarget) -> EffectFrame:
        target.validate()
        lifetime = max(0.15, 1.25 - 0.1 * int(parameters.speed))
        self._pulses = [item for item in self._pulses if 0.0 <= elapsed - item[0] <= lifetime]
        active = set(target.active_cells)
        pixels = []
        for row in range(target.rows):
            rendered = []
            for column in range(target.columns):
                if (row, column) not in active:
                    rendered.append((0, 0, 0))
                    continue
                intensity = 0.0
                for started_at, (origin_row, origin_column) in self._pulses:
                    age = elapsed - started_at
                    distance = abs(row - origin_row) + abs(column - origin_column)
                    intensity = max(intensity, max(0.0, 1.0 - age / lifetime - distance * 0.12))
                base = tuple(
                    round(parameters.colour1[i] * (1.0 - intensity) + parameters.colour2[i] * intensity)
                    for i in range(3)
                )
                rendered.append(scale_colour(base, parameters.brightness))
            pixels.append(tuple(rendered))
        frame = EffectFrame(target.rows, target.columns, tuple(pixels))
        frame.validate()
        return frame
"""
        elif animated:
            body = """
    def render(self, elapsed: float, parameters: EffectParameters, target: EffectTarget) -> EffectFrame:
        target.validate()
        phase = (math.sin(elapsed * max(1, int(parameters.speed))) + 1.0) / 2.0
        colour = tuple(
            round(parameters.colour1[i] * (1.0 - phase) + parameters.colour2[i] * phase)
            for i in range(3)
        )
        active = set(target.active_cells)
        pixels = tuple(
            tuple(scale_colour(colour, parameters.brightness) if (row, column) in active else (0, 0, 0)
                  for column in range(target.columns))
            for row in range(target.rows)
        )
        frame = EffectFrame(target.rows, target.columns, pixels)
        frame.validate()
        return frame
"""
        else:
            body = """
    def render(self, elapsed: float, parameters: EffectParameters, target: EffectTarget) -> EffectFrame:
        target.validate()
        active = set(target.active_cells)
        pixels = tuple(
            tuple(scale_colour(parameters.colour1, parameters.brightness) if (row, column) in active else (0, 0, 0)
                  for column in range(target.columns))
            for row in range(target.rows)
        )
        frame = EffectFrame(target.rows, target.columns, pixels)
        frame.validate()
        return frame
"""

        params = """(
            EffectParameterSpec(id="colour1", label="Primary colour", kind="colour", default=(40, 80, 255)),
            EffectParameterSpec(id="colour2", label="Secondary colour", kind="colour", default=(255, 80, 160)),
"""
        if animated or reactive:
            params += '            EffectParameterSpec(id="speed", label="Speed", kind="integer", default=5, minimum=1, maximum=10),\n'
        params += "        )"
        metadata = f"""

SERPENT_EFFECT_PLUGINS = (
    EffectPluginSpec(
        id={id_literal},
        name={name_literal},
        description={description_literal},
        effect_class={class_name},
        input_capabilities={capabilities!r},
        render_targets={render_targets!r},
        parameters={params},
    ),
)

for plugin in SERPENT_EFFECT_PLUGINS:
    plugin.validate()
"""
        return imports + definition + body + metadata

    def create_new_effect(self):
        if self._is_installed_mode():
            index = self.mode_combo.findData(self.MODE_DEVELOPER)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)

        dialog = QDialog(self)
        dialog.setWindowTitle("Create New Effect")
        form = QFormLayout(dialog)
        name_edit = QLineEdit("My Effect", dialog)
        id_edit = QLineEdit("my-effect", dialog)
        description_edit = QLineEdit("A custom Serpent effect.", dialog)
        template_combo = QComboBox(dialog)
        for item in (
            "Blank / Static",
            "Animated Matrix",
            "Reactive Keyboard",
            "Reactive Mouse",
            "Reactive Keyboard + Mouse",
        ):
            template_combo.addItem(item)
        form.addRow("Name", name_edit)
        form.addRow("Effect ID", id_edit)
        form.addRow("Description", description_edit)
        form.addRow("Template", template_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Create")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)

        def sync_id(text):
            if not id_edit.property("serpent-manual-id"):
                id_edit.setText(self._creator_slug(text))
        name_edit.textChanged.connect(sync_id)
        id_edit.textEdited.connect(lambda _text: id_edit.setProperty("serpent-manual-id", True))

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        name = name_edit.text().strip()
        effect_id = self._creator_slug(id_edit.text())
        if not name or not effect_id:
            notify_warning(self, "Effect details required", "Name and Effect ID are required.")
            return

        source = self._effect_template(
            name=name,
            effect_id=effect_id,
            description=description_edit.text(),
            template=template_combo.currentText(),
        )
        self.stop_live_preview(silent=True)
        try:
            generated_tree = ast.parse(source, filename=f"<new effect {effect_id}>")
        except SyntaxError as exc:
            notify_warning(
                self,
                "Generated effect invalid",
                f"The generated effect template could not be parsed: {exc}",
            )
            return
        self._composer_enter_raw_python_state(
            generated_tree,
            Path(f"{effect_id}.py"),
        )
        self.loaded_path = None
        self._composer_output_path = None
        self._composer_installed_origin_id = None
        self.path_edit.clear()
        if hasattr(self, "composer_file_label"):
            self.composer_file_label.setText("Plugin file: not chosen")
        self.source_edit.setPlainText(source)
        self.source_edit.document().setModified(True)
        self._validated_developer_source = None
        self.specs = []
        self.spec = None
        self.effect_combo.clear()
        self.effect_combo.setEnabled(False)
        self.preview.clear_frame()
        self.preview_enabled = False
        self.elapsed = 0.0
        self.status_label.setText(
            f"New effect {effect_id!r} created from "
            f"{template_combo.currentText()!r}. Edit the generated Python, "
            "then press Validate & Preview. Nothing is installed until "
            "Install to Serpent is pressed."
        )
        self._update_developer_workflow_state()
        self.source_edit.setFocus()

    @staticmethod
    def _promotion_filename(effect_id):
        stem = "".join(
            character.casefold()
            if character.isalnum()
            else "_"
            for character in str(effect_id)
        ).strip("_")
        while "__" in stem:
            stem = stem.replace("__", "_")
        if not stem:
            raise RuntimeError(
                "Effect ID cannot be converted into an install filename."
            )
        return stem + ".py"

    @staticmethod
    def _atomic_write(path, source):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=path.name + ".",
            dir=str(path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(source)
            os.replace(temporary, path)
        finally:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass

    def _promotion_destination(self):
        if self.spec is None:
            raise RuntimeError(
                "Validate and select exactly one Developer effect first."
            )

        plugins = (ROOT / "plugins" / "effects").resolve()
        loaded = (
            self.loaded_path.resolve()
            if self.loaded_path is not None
            else None
        )

        if loaded is not None and plugins in loaded.parents:
            return loaded

        return plugins / self._promotion_filename(self.spec.id)

    def _rollback_promotion(
        self,
        destination,
        previous_bytes,
        *,
        reload_registry=True,
    ):
        destination = Path(destination)

        try:
            if previous_bytes is None:
                destination.unlink(missing_ok=True)
            else:
                fd, temporary = tempfile.mkstemp(
                    prefix=destination.name + ".rollback.",
                    dir=str(destination.parent),
                )
                try:
                    with os.fdopen(fd, "wb") as handle:
                        handle.write(previous_bytes)
                    os.replace(temporary, destination)
                finally:
                    try:
                        os.unlink(temporary)
                    except FileNotFoundError:
                        pass
        finally:
            if reload_registry:
                try:
                    subprocess.run(
                        [
                            str(ROOT / "serpent.py"),
                            "effect",
                            "reload",
                        ],
                        text=True,
                        capture_output=True,
                        timeout=8,
                    )
                except Exception:
                    pass

                try:
                    from serpent_core.effects import (
                        reload_effect_plugins,
                    )
                    reload_effect_plugins()
                except Exception:
                    pass

    def promote_effect(self):
        if self._is_installed_mode():
            self.status_label.setText(
                "Switch to Developer mode to install an authored effect."
            )
            return

        if (
            not self.preview_enabled
            or self.spec is None
            or self._validated_developer_source is None
        ):
            self.status_label.setText(
                "Validate the current Developer effect successfully "
                "before installing it."
            )
            return

        source = self.source_edit.toPlainText()
        if source != self._validated_developer_source:
            self.status_label.setText(
                "Source changed after validation. Validate again before "
                "installing."
            )
            return

        if len(self.specs) != 1:
            self.status_label.setText(
                "Install Effect requires a source file containing exactly "
                "one effect plugin."
            )
            return

        try:
            ast.parse(source)
            destination = self._promotion_destination()

            from serpent_core.effects import (
                effect_ids,
                reload_effect_plugins,
            )

            current_ids = set(effect_ids())
            plugins = (ROOT / "plugins" / "effects").resolve()
            loaded = (
                self.loaded_path.resolve()
                if self.loaded_path is not None
                else None
            )
            updating_loaded_plugin = (
                loaded is not None
                and plugins in loaded.parents
                and loaded == destination
            )

            if (
                self.spec.id in current_ids
                and not destination.exists()
                and not updating_loaded_plugin
            ):
                raise RuntimeError(
                    f"Effect ID {self.spec.id!r} is already installed "
                    "by another module. Serpent will not overwrite it."
                )

            update = destination.exists()
            action = "Update" if update else "Install"
            answer = QMessageBox.question(
                self,
                f"{action} effect",
                (
                    f"{action} {self.spec.name!r} ({self.spec.id})?\n\n"
                    f"Destination:\n{destination}\n\n"
                    "The source will be written atomically and the user "
                    "effect registry will be reloaded immediately."
                ),
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

            previous_bytes = (
                destination.read_bytes()
                if destination.exists()
                else None
            )

            self.stop_live_preview(silent=True)
            self._atomic_write(destination, source)

            try:
                process = subprocess.run(
                    [
                        str(ROOT / "serpent.py"),
                        "effect",
                        "reload",
                    ],
                    text=True,
                    capture_output=True,
                    timeout=8,
                )
                if process.returncode:
                    raise RuntimeError(
                        (process.stderr or process.stdout).strip()
                    )

                reload_effect_plugins(
                    required_effect_id=self.spec.id,
                )
            except Exception:
                self._rollback_promotion(
                    destination,
                    previous_bytes,
                )
                raise

            promoted_id = self.spec.id
            promoted_name = self.spec.name

            self.loaded_path = destination.resolve()
            self.path_edit.setPlainText(str(self.loaded_path))
            self.source_edit.document().setModified(False)
            self._validated_developer_source = source
            self._remember_directory(self.loaded_path)

            self._sync_installed_catalog_after_mutation(
                select_effect_id=promoted_id,
                navigate=True,
            )

            verb = "Updated" if update else "Installed"
            self.status_label.setText(
                f"{verb} {promoted_name} ({promoted_id}). "
                "It is now available as a normal Installed Effect."
            )
        except Exception as exc:
            self.status_label.setText(
                f"Install/update failed safely: "
                f"{type(exc).__name__}: {exc}"
            )
        finally:
            if not self._is_installed_mode():
                self._update_developer_workflow_state()

    def _current_scene_target(self):
        payload = self.target_combo.currentData()
        if not isinstance(payload, dict):
            raise RuntimeError("Workshop preview target is invalid.")

        device_class = str(
            payload.get("device_class", "")
        ).strip().casefold()

        if device_class in {"keyboard", "mouse"}:
            return device_class

        # Generic/device fixtures are valid for in-memory preview but cannot
        # identify which individual-scene effect slot should be replaced.
        raise RuntimeError(
            "Select a Keyboard or Mouse preview target before saving "
            "or updating an individual scene."
        )

    def _select_preview_target_class(self, target):
        target = str(target).strip().casefold()
        if target not in {"keyboard", "mouse"}:
            return False

        for index in range(self.target_combo.count()):
            payload = self.target_combo.itemData(index)
            if not isinstance(payload, dict):
                continue
            device_class = str(
                payload.get("device_class", "")
            ).strip().casefold()
            if device_class == target:
                self.target_combo.setCurrentIndex(index)
                return True

        return False

    def _scene_parameter_values(self):
        if self.spec is None:
            return {}

        allowed = {"colour1", "colour2", "speed", "direction"}
        values = self.effect_parameters.values()
        return {
            key: (
                tuple(value)
                if key in {"colour1", "colour2"}
                else value
            )
            for key, value in values.items()
            if key in allowed
        }

    def _save_workshop_scene(self):
        if (
            not self._is_installed_mode()
            or self.spec is None
            or self.scene_save_callback is None
        ):
            self.status_label.setText(
                "Scene integration is not available."
            )
            return

        self.stop_live_preview(silent=True)

        try:
            target = self._current_scene_target()
        except RuntimeError as exc:
            self.status_label.setText(str(exc))
            return

        scene = self.scene_save_callback(
            self.spec.id,
            self._scene_parameter_values(),
            target,
        )
        if scene is not None:
            self.status_label.setText(
                f"Saved scene {scene.name} from the current Workshop effect."
            )

    def _update_selected_scene(self):
        if (
            not self._is_installed_mode()
            or self.spec is None
            or self.scene_update_callback is None
        ):
            self.status_label.setText(
                "Select a scene in the Scenes tab before updating it."
            )
            return

        self.stop_live_preview(silent=True)

        try:
            target = self._current_scene_target()
        except RuntimeError as exc:
            self.status_label.setText(str(exc))
            return

        scene = self.scene_update_callback(
            self.spec.id,
            self._scene_parameter_values(),
            target,
        )
        if scene is not None:
            self.status_label.setText(
                f"Updated scene {scene.name} from the current Workshop effect."
            )

    @staticmethod
    @staticmethod
    def _scene_effect_candidates(scene):
        if scene.mode == "synchronized":
            groups = getattr(scene, "groups", ())
            if groups:
                candidates = []
                from serpent_core.scenes import _effect_from_dict
                for group in groups:
                    if not isinstance(group, dict):
                        continue
                    effect_id = group.get("effect")
                    if not isinstance(effect_id, str):
                        continue
                    try:
                        spec = get_effect_plugin_spec(effect_id)
                    except Exception:
                        spec = None
                    params = {}
                    if spec is not None:
                        for parameter in spec.parameters:
                            if parameter.id in group:
                                params[parameter.id] = copy.deepcopy(group[parameter.id])
                    effect = _effect_from_dict(
                        {"id": effect_id, "parameters": params},
                        synchronized=True,
                    )
                    candidates.append(("synchronized", effect))
                return candidates
            if scene.effect is not None:
                return [("synchronized", scene.effect)]
            return []

        device_effects = [
            ("keyboard", device.effect)
            for device in scene.devices
            if device.effect is not None
        ]
        zone_effects = [
            ("mouse", zone.effect)
            for device in scene.devices
            for zone in device.zones
        ]
        return device_effects + zone_effects

    def load_scene(self, scene):
        if not self._is_installed_mode():
            index = self.mode_combo.findData(self.MODE_INSTALLED)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)

        self.live_preview_refresh_timer.stop()
        self.stop_live_preview(silent=True)

        candidates = self._scene_effect_candidates(scene)
        if not candidates:
            self.status_label.setText(
                f"{scene.name}: scene contains no effect configuration "
                "that the Workshop can display."
            )
            return False

        target, effect = candidates[0]
        if target in {"keyboard", "mouse"}:
            self._select_preview_target_class(target)

        effect_index = self.effect_combo.findData(effect.id)
        if effect_index < 0:
            self.status_label.setText(
                f"{scene.name}: effect {effect.id!r} is not installed."
            )
            return False

        self.effect_combo.setCurrentIndex(effect_index)
        self._adopt_installed_spec()

        values = effect.parameter_dict()
        if values:
            self.effect_parameters.load_values(values)

        self.reset_effect()

        context = (
            "synchronized"
            if scene.mode == "synchronized"
            else target
        )
        self.status_label.setText(
            f"Loaded {scene.name} into Workshop "
            f"({context} effect: {effect.id})."
        )
        return True

    def _schedule_live_preview_refresh(self, *args):
        if (
            self._is_installed_mode()
            and self._live_preview_active
            and self.spec is not None
        ):
            self.live_preview_refresh_timer.start()

    def _refresh_live_preview(self):
        if (
            not self._is_installed_mode()
            or not self._live_preview_active
            or self.spec is None
        ):
            return

        try:
            process = subprocess.run(
                self._live_preview_arguments(),
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                )

            self.live_preview_label.setText(
                f"Physical preview: LIVE — {self.spec.name}\n"
                "Parameter changes sync automatically · "
                "saved profile remains unchanged."
            )
            self.status_label.setText(
                f"{self.spec.name}: live preview updated."
            )
        except Exception as exc:
            # The backend owns rollback/preservation semantics for a failed
            # preview-start. Keep the GUI session state explicit and let the
            # user stop/retry rather than guessing backend state.
            self.live_preview_label.setText(
                f"Physical preview: LIVE — refresh error\n"
                "Use Stop Live Preview to return to saved synchronization."
            )
            self.status_label.setText(
                f"Live preview update failed safely: "
                f"{type(exc).__name__}: {exc}"
            )

    def _update_live_preview_context(self):
        if not self._is_installed_mode() or self.spec is None:
            return

        targets = ", ".join(
            item.title()
            for item in (self.spec.render_targets or ())
        ) or "Unspecified"

        self.live_preview_context_label.setText(
            f"Physical support: {targets}. "
            "LIVE preview follows the active synchronized members; "
            "the Preview target selector affects only the in-memory canvas."
        )

    def _populate_catalog(self):
        selected_id = self.effect_combo.currentData()
        query = self.catalog_search.text().strip().casefold()

        self.catalog_list.blockSignals(True)
        self.catalog_list.clear()

        visible = 0
        for spec in self._installed_specs:
            searchable = " ".join(
                (
                    spec.id,
                    spec.name,
                    spec.description,
                    " ".join(spec.input_capabilities or ()),
                    " ".join(spec.render_targets or ()),
                )
            ).casefold()
            if query and query not in searchable:
                continue

            reactive = bool(spec.input_capabilities)
            suffix = "  •  Reactive" if reactive else ""
            item = QListWidgetItem(spec.name + suffix)
            item.setData(Qt.ItemDataRole.UserRole, spec.id)
            item.setToolTip(spec.description)
            self.catalog_list.addItem(item)
            visible += 1

            if spec.id == selected_id:
                self.catalog_list.setCurrentItem(item)

        self.catalog_count_label.setText(
            f"{visible} of {len(self._installed_specs)}"
        )

        if self.catalog_list.currentRow() < 0 and self.catalog_list.count():
            self.catalog_list.setCurrentRow(0)

        self.catalog_list.blockSignals(False)

    def _filter_catalog(self, *args):
        if not self._is_installed_mode():
            return
        current_id = self.effect_combo.currentData()
        self._populate_catalog()

        for row in range(self.catalog_list.count()):
            item = self.catalog_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == current_id:
                self.catalog_list.setCurrentRow(row)
                return

    def _catalog_selection_changed(self, current, previous):
        if not self._is_installed_mode() or current is None:
            return

        effect_id = current.data(Qt.ItemDataRole.UserRole)
        index = self.effect_combo.findData(effect_id)
        if index < 0 or index == self.effect_combo.currentIndex():
            return

        self.effect_combo.setCurrentIndex(index)

    def _sync_catalog_selection(self):
        if not self._is_installed_mode():
            return
        effect_id = self.effect_combo.currentData()
        for row in range(self.catalog_list.count()):
            item = self.catalog_list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == effect_id:
                if self.catalog_list.currentRow() != row:
                    self.catalog_list.blockSignals(True)
                    self.catalog_list.setCurrentRow(row)
                    self.catalog_list.blockSignals(False)
                return

    def _restore_installed_defaults(self):
        if not self._is_installed_mode() or self.spec is None:
            return
        self.effect_parameters.set_spec(self.spec)
        self.reset_effect()
        self.status_label.setText(
            f"{self.spec.name}: parameter defaults restored."
        )

    def _populate_combo(self, specs):
        previous = self.effect_combo.currentData()
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for spec in specs:
            self.effect_combo.addItem(spec.name, spec.id)
        index = self.effect_combo.findData(previous)
        if index >= 0:
            self.effect_combo.setCurrentIndex(index)
        self.effect_combo.blockSignals(False)
        self.effect_combo.setEnabled(bool(specs))
        self.specs = list(specs)

    def _load_installed_specs(self):
        from serpent_core.effects import effect_ids, get_effect_plugin_spec

        self._installed_specs = [
            get_effect_plugin_spec(effect_id)
            for effect_id in effect_ids()
        ]

    def _select_installed_default(self):
        if not self._is_installed_mode():
            return
        if not self._installed_specs:
            self.spec = None
            self.effect_combo.setEnabled(False)
            self.status_label.setText("No installed effects are available.")
            return

        if self.effect_combo.count() != len(self._installed_specs):
            self._populate_combo(self._installed_specs)

        if self.effect_combo.currentIndex() < 0:
            self.effect_combo.setCurrentIndex(0)

        self._adopt_installed_spec()
        self.reset_effect()

    def _adopt_installed_spec(self):
        effect_id = self.effect_combo.currentData()
        self.spec = next(
            (spec for spec in self._installed_specs if spec.id == effect_id),
            None,
        )
        if self.spec is None:
            return
        self.effect_parameters.set_spec(self.spec)
        capabilities = ", ".join(
            item.title()
            for item in (self.spec.input_capabilities or ())
        ) or "None"
        targets = ", ".join(
            item.title()
            for item in (self.spec.render_targets or ())
        ) or "Unspecified"

        self.effect_name_label.setText(self.spec.name)
        self.effect_description_label.setText(self.spec.description)
        self.effect_capability_label.setText(
            f"Reactive input: {capabilities}   •   Targets: {targets}"
        )
        self._update_live_preview_context()

        inputs = set(self.spec.input_capabilities or ())
        targets_set = set(self.spec.render_targets or ())
        self.test_key_button.setEnabled("keyboard" in inputs)
        self.test_mouse_button.setEnabled("mouse" in inputs)

        if "keyboard" not in targets_set:
            self.test_key_button.setEnabled(False)
        if "mouse" not in targets_set:
            self.test_mouse_button.setEnabled(False)

        self._sync_catalog_selection()

        if inputs:
            self.status_label.setText(
                f"{self.spec.name} — reactive preview ready. "
                "Use the test controls or click a preview cell."
            )
        else:
            self.status_label.setText(
                f"{self.spec.name} — ready for offline preview."
            )

    def _apply_specs(self, payload):
        # Worker replies always belong to Developer mode. Keep them available
        # without displacing the installed catalog when the user is browsing.
        old = self.effect_combo.currentData()
        specs = [_Spec(item) for item in payload.get("specs") or []]
        self._developer_specs = specs
        if self._is_installed_mode():
            return

        self.specs = specs
        self.effect_combo.blockSignals(True)
        self.effect_combo.clear()
        for spec in specs:
            self.effect_combo.addItem(spec.name, spec.id)

        preferred = payload.get("effect_id") or old
        index = self.effect_combo.findData(preferred)
        if index >= 0:
            self.effect_combo.setCurrentIndex(index)

        self.effect_combo.blockSignals(False)
        self.effect_combo.setEnabled(bool(specs))
        self._adopt_selected_spec()

    def select_effect(self, *args):
        if not self._is_installed_mode():
            return super().select_effect(*args)

        self.live_preview_refresh_timer.stop()
        self.stop_live_preview(silent=True)
        self._adopt_installed_spec()
        if self.spec is not None:
            self.reset_effect()

    def _installed_target(self):
        from serpent_core.effects.base import EffectTarget

        raw = self._preview_target()
        active_cells = tuple(
            (int(cell[0]), int(cell[1]))
            for cell in raw.get("active_cells", ())
        )
        if not active_cells:
            active_cells = tuple(
                (row, column)
                for row in range(int(raw["rows"]))
                for column in range(int(raw["columns"]))
            )
        target = EffectTarget(
            rows=int(raw["rows"]),
            columns=int(raw["columns"]),
            active_cells=active_cells,
            device_class=(
                str(raw["device_class"])
                if raw.get("device_class") is not None
                else None
            ),
        )
        target.validate()
        return target

    def _installed_parameters(self):
        from serpent_core.effects.base import EffectParameters

        values = {
            "brightness": 100.0,
            "colour1": (255, 255, 255),
            "colour2": (0, 0, 0),
            "speed": 2,
            "direction": 1,
        }
        for parameter in self.spec.parameters:
            if parameter.id in values:
                values[parameter.id] = parameter.default
        for key, value in self.effect_parameters.values().items():
            if key in values:
                values[key] = (
                    tuple(value)
                    if key in {"colour1", "colour2"}
                    else value
                )
        return EffectParameters(**values)

    def reset_effect(self, *args):
        if not self._is_installed_mode():
            return super().reset_effect(*args)

        if self.spec is None:
            self.preview.clear_frame()
            return

        from serpent_core.effects import reset_effect_instance

        try:
            reset_effect_instance(self.spec.id)
            self.elapsed = 0.0
            self.preview_enabled = True
            self.render_now()
        except Exception as exc:
            self.preview_enabled = False
            self.preview.clear_frame()
            self.status_label.setText(
                f"Installed preview reset failed: {type(exc).__name__}: {exc}"
            )

    def _inject_installed_event(
        self,
        *,
        kind,
        source,
        code,
        row=None,
        column=None,
    ):
        if not self._is_installed_mode() or self.spec is None:
            return

        from serpent_core.effects import get_effect
        from serpent_core.effects.base import EffectEvent

        try:
            effect = get_effect(self.spec.id)
            effect.handle_event(
                EffectEvent(
                    kind=kind,
                    timestamp=self.elapsed,
                    source=source,
                    code=code,
                    value=1,
                    row=row,
                    column=column,
                )
            )
            self.render_now()
            self.status_label.setText(
                f"{self.spec.name}: synthetic {kind} injected."
            )
        except Exception as exc:
            self.status_label.setText(
                f"Synthetic preview event failed safely: "
                f"{type(exc).__name__}: {exc}"
            )

    def _test_installed_key_press(self):
        target = self._installed_target()
        if not target.active_cells:
            return
        row, column = target.active_cells[len(target.active_cells) // 2]
        self.inject_key(row, column)

    def _test_installed_mouse_press(self):
        self.inject_mouse()

    def inject_key(self, row, column):
        if self._is_installed_mode():
            if not self.test_key_button.isEnabled():
                return
            return self._inject_installed_event(
                kind="key-press",
                source="keyboard:workshop-preview",
                code=f"WORKSHOP_R{row}_C{column}",
                row=row,
                column=column,
            )
        return super().inject_key(row, column)

    def inject_mouse(self):
        if self._is_installed_mode():
            if not self.test_mouse_button.isEnabled():
                return
            return self._inject_installed_event(
                kind="mouse-press",
                source="mouse:workshop-preview",
                code="BTN_LEFT",
            )
        return super().inject_mouse()

    def advance_frame(self):
        if not self._is_installed_mode():
            return super().advance_frame()

        if self.spec is None or not self.preview_enabled:
            return
        self.elapsed += self.FRAME_INTERVAL_MS / 1000.0
        self.render_now()

    def render_now(self, *args):
        if not self._is_installed_mode():
            return super().render_now(*args)

        if self.spec is None or not self.preview_enabled:
            return

        from serpent_core.effects import render_effect

        try:
            frame = render_effect(
                self.spec.id,
                self.elapsed,
                self._installed_parameters(),
                self._installed_target(),
            )
            self.preview.set_frame(frame)
        except Exception as exc:
            self.preview.clear_frame()
            self.status_label.setText(
                f"Installed preview failed safely: {type(exc).__name__}: {exc}"
            )

    def start_live_preview(self):
        if not self._is_installed_mode():
            return super().start_live_preview()

        if not self.preview_enabled or self.spec is None:
            self.status_label.setText(
                "Select an installed effect before starting live preview."
            )
            return

        self.live_preview_refresh_timer.stop()

        try:
            process = subprocess.run(
                self._live_preview_arguments(),
                text=True,
                capture_output=True,
                timeout=8,
            )
            if process.returncode:
                raise RuntimeError(
                    (process.stderr or process.stdout).strip()
                )
            self._live_preview_active = True
            self.live_preview_start_button.setEnabled(False)
            self.live_preview_stop_button.setEnabled(True)
            self.live_preview_label.setText(
                f"Physical preview: LIVE — {self.spec.name}\n"
                "Parameter changes sync automatically · "
                "saved profile remains unchanged."
            )
            self.status_label.setText(
                f"{self.spec.name}: physical live preview started."
            )
        except Exception as exc:
            self._live_preview_active = False
            self.live_preview_start_button.setEnabled(True)
            self.live_preview_stop_button.setEnabled(False)
            self.live_preview_label.setText(
                "Physical preview: inactive"
            )
            self.status_label.setText(
                f"Live preview failed safely: {type(exc).__name__}: {exc}"
            )

    def stop_live_preview(self, *, silent=False):
        timer = getattr(self, "live_preview_refresh_timer", None)
        if timer is not None:
            timer.stop()
        return super().stop_live_preview(silent=silent)

    def hideEvent(self, event):
        # A physical preview is deliberately scoped to the visible Workshop.
        # Leaving the tab, hiding the window, or otherwise hiding this panel
        # restores the saved synchronization state.
        self.stop_live_preview(silent=True)
        super().hideEvent(event)

