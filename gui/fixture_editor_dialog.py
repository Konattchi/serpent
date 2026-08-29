from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QInputDialog,
    QPushButton,
    QSpinBox,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from serpent_core.fixture_editor import FixtureDocument, FixtureEditorError
from serpent_core.fixture_discovery import DiscoveredDevice, discover_razer_devices


class FixtureEditorDialog(QDialog):
    """Candidate-only structured Fixture Schema v1 editor."""

    DEVICE_CLASSES = ("keyboard", "mouse", "mousepad", "headset", "keypad", "other")
    BACKENDS = ("software-rgb-sysfs", "hardware-effects-sysfs")

    def __init__(self, parent=None, *, fixture_dir: Path | None = None):
        super().__init__(parent)
        self.fixture_dir = fixture_dir or (Path.home() / ".local/share/serpent/fixtures")
        self.document: FixtureDocument | None = None
        self.source_path: Path | None = None
        self.reference_document: FixtureDocument | None = None
        self.reference_path: Path | None = None
        self.reference_differences: list[tuple[str, Any, Any]] = []
        self.auto_draft_document: FixtureDocument | None = None
        self.workflow_state = "Draft"

        self.setWindowTitle("Serpent Fixture Editor — Serpent")
        self.resize(860, 700)
        self.setMinimumSize(680, 520)

        outer = QVBoxLayout(self)
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.editor_body = QWidget()
        root = QVBoxLayout(self.editor_body)
        root.addWidget(QLabel("<h2>Fixture Editor</h2>"))
        intro = QLabel(
            "Create and edit Fixture Schema v1 candidates with structured controls. "
            "This editor validates and exports JSON only; it does not install fixtures."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        toolbar = QHBoxLayout()
        self.new_button = QPushButton("New")
        self.open_button = QPushButton("Open…")
        self.discover_button = QPushButton("Discover Device…")
        self.validate_button = QPushButton("Validate")
        self.export_button = QPushButton("Export Candidate…")
        toolbar.addWidget(self.new_button)
        toolbar.addWidget(self.open_button)
        toolbar.addWidget(self.discover_button)
        toolbar.addStretch(1)
        toolbar.addWidget(self.validate_button)
        toolbar.addWidget(self.export_button)
        root.addLayout(toolbar)

        state_row = QHBoxLayout()
        self.state_label = QLabel("State: Draft")
        self.state_label.setToolTip(
            "Draft → Needs Review / Matches Reference → Validated → Exported"
        )
        state_row.addWidget(self.state_label)
        state_row.addStretch(1)
        root.addLayout(state_row)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_general_tab(), "General")
        self.tabs.addTab(self._build_detection_tab(), "Detection")
        self.tabs.addTab(self._build_zones_tab(), "Zones")
        self.tabs.addTab(self._build_effects_tab(), "Effects")
        self.tabs.addTab(self._build_optional_tab(), "Advanced Sections")
        self.tabs.addTab(self._build_raw_tab(), "Advanced JSON")
        root.addWidget(self.tabs, 1)

        self.status_label = QLabel("Candidate-only editor. Installed fixtures remain untouched.")
        self.status_label.setWordWrap(True)
        root.addWidget(self.status_label)

        self.reference_group = QGroupBox("Reference Review")
        self.reference_group.setMaximumHeight(120)
        self.reference_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        reference_layout = QVBoxLayout(self.reference_group)
        self.reference_summary_label = QLabel("")
        self.reference_summary_label.setWordWrap(True)
        reference_layout.addWidget(self.reference_summary_label)
        self.reference_details = QTextEdit()
        self.reference_details.setReadOnly(True)
        self.reference_details.setMaximumHeight(120)
        self.reference_details.setVisible(False)
        reference_layout.addWidget(self.reference_details)
        reference_buttons = QHBoxLayout()
        self.details_button = QPushButton("Show Details")
        self.details_button.setCheckable(True)
        self.apply_reference_button = QPushButton("Apply Reference Values")
        self.keep_draft_button = QPushButton("Keep Auto-Draft")
        self.reset_autodraft_button = QPushButton("Reset to Auto-Draft")
        self.reset_autodraft_button.setVisible(False)
        reference_buttons.addWidget(self.details_button)
        reference_buttons.addWidget(self.apply_reference_button)
        reference_buttons.addWidget(self.keep_draft_button)
        reference_buttons.addWidget(self.reset_autodraft_button)
        reference_buttons.addStretch(1)
        reference_layout.addLayout(reference_buttons)
        self.reference_group.setVisible(False)

        self.details_button.toggled.connect(self._toggle_reference_details)
        self.apply_reference_button.clicked.connect(self.apply_reference_values)
        self.keep_draft_button.clicked.connect(self.keep_auto_draft)
        self.reset_autodraft_button.clicked.connect(self.reset_to_auto_draft)

        self.editor_scroll.setWidget(self.editor_body)
        outer.addWidget(self.editor_scroll, 1)

        # Keep review state/actions visible even when the form itself is scrolled.
        outer.addWidget(self.reference_group, 0)

        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(close)
        outer.addLayout(row)

        self.new_button.clicked.connect(self.new_document)
        self.open_button.clicked.connect(self.open_document)
        self.discover_button.clicked.connect(self.discover_device)
        self.validate_button.clicked.connect(self.validate_current)
        self.export_button.clicked.connect(self.export_candidate)
        self.refresh_raw_button.clicked.connect(self.refresh_raw_json)
        self.apply_raw_button.clicked.connect(self.apply_raw_json)
        self.backend_combo.currentTextChanged.connect(self._update_backend_visibility)
        self._connect_dirty_tracking()

        self.new_document()

    def _set_workflow_state(self, state: str) -> None:
        self.workflow_state = state
        self.state_label.setText(f"State: {state}")
        self.export_button.setEnabled(state in ("Validated", "Exported"))

    def _mark_dirty(self, *args) -> None:
        if self.workflow_state in ("Validated", "Exported", "Matches Reference"):
            self._set_workflow_state("Draft")
            self.status_label.setText(
                "Draft changed after validation/reference reconciliation. Validate again before export."
            )

    def _connect_dirty_tracking(self) -> None:
        for widget in (
            self.id_edit, self.manufacturer_edit, self.model_edit, self.variant_edit,
            self.vendor_edit, self.product_edit, self.required_endpoint_edit,
            self.service_edit, self.linked_zone_edit, self.openrazer_name_edit,
            self.serial_edit, self.generated_prefixes_edit,
        ):
            widget.textEdited.connect(self._mark_dirty)

        for combo in (
            self.class_combo, self.backend_combo, self.serial_policy_combo,
        ):
            combo.currentTextChanged.connect(self._mark_dirty)

        for spin in (self.rows_spin, self.columns_spin):
            spin.valueChanged.connect(self._mark_dirty)

        for check in (
            self.render_only_check, self.safety_check, self.performance_check, self.input_check,
        ):
            check.toggled.connect(self._mark_dirty)

        self.zones_table.itemChanged.connect(self._mark_dirty)
        self.effects_table.itemChanged.connect(self._mark_dirty)
        self.safety_edit.textChanged.connect(self._mark_dirty)
        self.performance_edit.textChanged.connect(self._mark_dirty)
        self.input_edit.textChanged.connect(self._mark_dirty)

    def _toggle_reference_details(self, checked: bool) -> None:
        self.reference_details.setVisible(checked)
        self.details_button.setText("Hide Details" if checked else "Show Details")
        self.reference_group.setMaximumHeight(220 if checked else 120)

    def reset_to_auto_draft(self) -> None:
        if self.auto_draft_document is None:
            self.status_label.setText("No auto-draft snapshot is available.")
            return

        snapshot = FixtureDocument(copy.deepcopy(self.auto_draft_document.data), source_path=None)
        self._load_into_form(snapshot, None)
        self.reference_document = None
        self.reference_path = None
        self.reference_differences = []
        self.reset_autodraft_button.setVisible(False)
        self._set_workflow_state("Draft")
        self.status_label.setText(
            "Restored the original hardware auto-draft. Run reference review or Validate when ready."
        )

    def _build_general_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        identity = QGroupBox("Identity")
        form = QFormLayout(identity)
        self.id_edit = QLineEdit()
        self.manufacturer_edit = QLineEdit()
        self.model_edit = QLineEdit()
        self.class_combo = QComboBox()
        self.class_combo.setEditable(True)
        self.class_combo.addItems(self.DEVICE_CLASSES)
        self.variant_edit = QLineEdit()
        self.vendor_edit = QLineEdit()
        self.product_edit = QLineEdit()

        form.addRow("Fixture ID", self.id_edit)
        form.addRow("Manufacturer", self.manufacturer_edit)
        form.addRow("Model", self.model_edit)
        form.addRow("Device class", self.class_combo)
        form.addRow("Variant", self.variant_edit)
        form.addRow("USB vendor ID", self.vendor_edit)
        form.addRow("USB product ID", self.product_edit)
        layout.addWidget(identity)

        backend = QGroupBox("Backend and matrix")
        bform = QFormLayout(backend)
        self.backend_combo = QComboBox()
        self.backend_combo.setEditable(True)
        self.backend_combo.addItems(self.BACKENDS)
        self.required_endpoint_edit = QLineEdit()
        self.service_label = QLabel("Service (optional)")
        self.service_edit = QLineEdit()
        self.linked_zone_label = QLabel("Linked source zone (optional)")
        self.linked_zone_edit = QLineEdit()
        self.rows_spin = QSpinBox()
        self.rows_spin.setRange(1, 1024)
        self.columns_spin = QSpinBox()
        self.columns_spin.setRange(1, 1024)
        self.render_only_check = QCheckBox("Render-only fixture (omit input block)")

        bform.addRow("Backend type", self.backend_combo)
        bform.addRow("Required sysfs endpoint", self.required_endpoint_edit)
        bform.addRow(self.service_label, self.service_edit)
        bform.addRow(self.linked_zone_label, self.linked_zone_edit)
        bform.addRow("Matrix rows", self.rows_spin)
        bform.addRow("Matrix columns", self.columns_spin)
        bform.addRow("", self.render_only_check)
        layout.addWidget(backend)
        layout.addStretch(1)
        return page

    def _build_detection_tab(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.openrazer_name_edit = QLineEdit()
        self.serial_edit = QLineEdit()
        self.serial_policy_combo = QComboBox()
        self.serial_policy_combo.setEditable(True)
        self.serial_policy_combo.addItems(("", "preferred", "required", "ignore"))
        self.generated_prefixes_edit = QLineEdit()
        self.generated_prefixes_edit.setPlaceholderText("Comma-separated prefixes")

        form.addRow("OpenRazer name contains", self.openrazer_name_edit)
        form.addRow("Serial", self.serial_edit)
        form.addRow("Serial policy", self.serial_policy_combo)
        form.addRow("Generated serial prefixes", self.generated_prefixes_edit)
        return page

    def _build_zones_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Explicit lighting zones. Leave the table empty to use Serpent's synthesized full-matrix region."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.zones_table = QTableWidget(0, 9)
        self.zones_table.setHorizontalHeaderLabels(
            (
                "ID",
                "Name",
                "Type",
                "Columns",
                "Visible",
                "Confirmed",
                "Controllable",
                "Sync Groupable",
                "Notes",
            )
        )
        layout.addWidget(self.zones_table, 1)

        row = QHBoxLayout()
        self.add_zone_button = QPushButton("Add Zone")
        self.remove_zone_button = QPushButton("Remove Selected")
        self.add_zone_button.clicked.connect(self._add_zone)
        self.remove_zone_button.clicked.connect(self._remove_zone)
        row.addWidget(self.add_zone_button)
        row.addWidget(self.remove_zone_button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_effects_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Structured effect definitions. Extra JSON preserves effect-specific fields such as "
            "backend, speed, speeds, or directions."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.effects_table = QTableWidget(0, 5)
        self.effects_table.setHorizontalHeaderLabels(
            ("ID", "Endpoint", "Payload JSON", "Colours", "Extra JSON")
        )
        layout.addWidget(self.effects_table, 1)

        row = QHBoxLayout()
        self.add_effect_button = QPushButton("Add Effect")
        self.remove_effect_button = QPushButton("Remove Selected")
        self.add_effect_button.clicked.connect(lambda: self._add_effect("", {}))
        self.remove_effect_button.clicked.connect(self._remove_effect)
        row.addWidget(self.add_effect_button)
        row.addWidget(self.remove_effect_button)
        row.addStretch(1)
        layout.addLayout(row)
        return page

    def _build_optional_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Optional complex Schema v1 sections remain explicit and lossless. "
            "They are not required for render-only fixture authoring."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.safety_check = QCheckBox("Include Safety")
        self.safety_edit = QTextEdit()
        self.performance_check = QCheckBox("Include Performance")
        self.performance_edit = QTextEdit()
        self.input_check = QCheckBox("Include Input")
        self.input_edit = QTextEdit()

        telemetry_group = QGroupBox("Telemetry")
        telemetry_layout = QVBoxLayout(telemetry_group)
        telemetry_note = QLabel(
            "Read-only device telemetry. Enable only capabilities the device meaningfully exposes."
        )
        telemetry_note.setWordWrap(True)
        self.telemetry_battery_check = QCheckBox("Battery percentage")
        self.telemetry_charging_check = QCheckBox("Charging state")
        telemetry_layout.addWidget(telemetry_note)
        telemetry_layout.addWidget(self.telemetry_battery_check)
        telemetry_layout.addWidget(self.telemetry_charging_check)
        layout.addWidget(telemetry_group)

        for check, edit, label in (
            (self.safety_check, self.safety_edit, "Safety JSON object"),
            (self.performance_check, self.performance_edit, "Performance JSON object"),
            (self.input_check, self.input_edit, "Input JSON object"),
        ):
            layout.addWidget(check)
            layout.addWidget(QLabel(label))
            edit.setMaximumHeight(130)
            edit.setPlaceholderText("{}")
            edit.setEnabled(False)
            check.toggled.connect(edit.setEnabled)
            layout.addWidget(edit)
        return page

    def _build_raw_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        note = QLabel(
            "Lossless escape hatch. Unknown fields are preserved. "
            "Apply JSON replaces the in-memory candidate."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.raw_edit = QTextEdit()
        layout.addWidget(self.raw_edit, 1)

        row = QHBoxLayout()
        self.refresh_raw_button = QPushButton("Refresh from Form")
        self.apply_raw_button = QPushButton("Apply JSON")
        row.addStretch(1)
        row.addWidget(self.refresh_raw_button)
        row.addWidget(self.apply_raw_button)
        layout.addLayout(row)
        return page

    @staticmethod
    def _table_text(table: QTableWidget, row: int, col: int) -> str:
        item = table.item(row, col)
        return item.text().strip() if item else ""

    @staticmethod
    def _table_set(table: QTableWidget, row: int, col: int, value: Any) -> None:
        table.setItem(row, col, QTableWidgetItem("" if value is None else str(value)))

    @staticmethod
    def _bool_text(value: str, default: bool = True) -> bool:
        text = value.strip().lower()
        if not text:
            return default
        if text in ("true", "1", "yes", "on"):
            return True
        if text in ("false", "0", "no", "off"):
            return False
        raise FixtureEditorError(f"Expected boolean value, got {value!r}")

    @staticmethod
    def _object_text(value: str, label: str) -> dict[str, Any]:
        if not value.strip():
            return {}
        data = json.loads(value)
        if not isinstance(data, dict):
            raise FixtureEditorError(f"{label} must be a JSON object.")
        return data

    def _update_backend_visibility(self) -> None:
        software = self.backend_combo.currentText() == "software-rgb-sysfs"
        self.service_label.setVisible(software)
        self.service_edit.setVisible(software)
        self.linked_zone_label.setVisible(software)
        self.linked_zone_edit.setVisible(software)

    def _add_zone(self, zone_id: str = "", zone: dict[str, Any] | None = None) -> None:
        zone = copy.deepcopy(zone or {})
        mapping = zone.get("mapping", {})
        columns = mapping.get("columns", []) if isinstance(mapping, dict) else []
        row = self.zones_table.rowCount()
        self.zones_table.insertRow(row)

        values = (
            zone_id,
            zone.get("name", ""),
            zone.get("type", ""),
            ",".join(str(x) for x in columns),
            str(zone.get("visible", True)).lower(),
            str(zone.get("confirmed", True)).lower(),
            str(zone.get("controllable", True)).lower(),
            str(
                zone.get(
                    "sync_groupable",
                    bool(
                        zone.get(
                            "controllable",
                            zone.get("confirmed", True),
                        )
                    ),
                )
            ).lower(),
            zone.get("notes", ""),
        )
        for col, value in enumerate(values):
            self._table_set(self.zones_table, row, col, value)

    def _remove_zone(self) -> None:
        rows = sorted({i.row() for i in self.zones_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.zones_table.removeRow(row)

    def _add_effect(self, effect_id: str, effect: dict[str, Any]) -> None:
        effect = copy.deepcopy(effect)
        row = self.effects_table.rowCount()
        self.effects_table.insertRow(row)

        endpoint = effect.pop("endpoint", "")
        payload = effect.pop("payload", None)
        colours = effect.pop("colours", "")
        extra = "" if not effect else json.dumps(effect, separators=(",", ":"), ensure_ascii=False)

        values = (
            effect_id,
            endpoint,
            "" if payload is None else json.dumps(payload, separators=(",", ":")),
            colours,
            extra,
        )
        for col, value in enumerate(values):
            self._table_set(self.effects_table, row, col, value)

    def _remove_effect(self) -> None:
        rows = sorted({i.row() for i in self.effects_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.effects_table.removeRow(row)

    def _base_document(self) -> FixtureDocument:
        if self.document is not None:
            return FixtureDocument(copy.deepcopy(self.document.data), source_path=self.source_path)
        return FixtureDocument.new(
            fixture_id=self.id_edit.text().strip() or "new-fixture",
            manufacturer=self.manufacturer_edit.text().strip(),
            model=self.model_edit.text().strip(),
            device_class=self.class_combo.currentText().strip() or "other",
            vendor_id=self.vendor_edit.text().strip() or "0000",
            product_id=self.product_edit.text().strip() or "0000",
            backend_type=self.backend_combo.currentText(),
            rows=self.rows_spin.value(),
            columns=self.columns_spin.value(),
        )

    def current_document(self) -> FixtureDocument:
        doc = self._base_document()

        doc.set("schema_version", 1)
        doc.set("id", self.id_edit.text().strip())
        doc.set("manufacturer", self.manufacturer_edit.text().strip())
        doc.set("model", self.model_edit.text().strip())
        doc.set("device_class", self.class_combo.currentText().strip())
        doc.set(
            "usb",
            {
                "vendor_id": self.vendor_edit.text().strip().upper(),
                "product_id": self.product_edit.text().strip().upper(),
            },
        )

        variant = self.variant_edit.text().strip()
        if variant:
            doc.set("variant", variant)
        else:
            doc.remove("variant")

        detection: dict[str, Any] = {}
        if self.openrazer_name_edit.text().strip():
            detection["openrazer_name_contains"] = self.openrazer_name_edit.text().strip()
        if self.serial_edit.text().strip():
            detection["serial"] = self.serial_edit.text().strip()
        if self.serial_policy_combo.currentText().strip():
            detection["serial_policy"] = self.serial_policy_combo.currentText().strip()
        prefixes = [x.strip() for x in self.generated_prefixes_edit.text().split(",") if x.strip()]
        if prefixes:
            detection["generated_serial_prefixes"] = prefixes
        if detection:
            doc.set("detection", detection)
        else:
            doc.remove("detection")

        doc.set_matrix(self.rows_spin.value(), self.columns_spin.value())
        capabilities = copy.deepcopy(doc.get("capabilities", {}))
        capabilities["brightness"] = True
        doc.set("capabilities", capabilities)

        telemetry = {}
        if self.telemetry_battery_check.isChecked():
            telemetry["battery"] = True
        if self.telemetry_charging_check.isChecked():
            telemetry["charging"] = True
        if telemetry:
            doc.set("telemetry", telemetry)
        else:
            doc.remove("telemetry")
        doc.set_backend(
            self.backend_combo.currentText(),
            sysfs_required_endpoint=self.required_endpoint_edit.text().strip() or None,
            service=self.service_edit.text().strip() or None,
            linked_source_zone=self.linked_zone_edit.text().strip() or None,
        )

        doc.clear_zones()
        for row in range(self.zones_table.rowCount()):
            zone_id = self._table_text(self.zones_table, row, 0)
            if not zone_id:
                continue
            columns = [
                int(part.strip(), 0)
                for part in self._table_text(self.zones_table, row, 3).split(",")
                if part.strip()
            ]
            doc.set_zone(
                zone_id,
                name=self._table_text(self.zones_table, row, 1),
                zone_type=self._table_text(self.zones_table, row, 2),
                columns=columns,
                visible=self._bool_text(self._table_text(self.zones_table, row, 4)),
                confirmed=self._bool_text(self._table_text(self.zones_table, row, 5)),
                controllable=self._bool_text(self._table_text(self.zones_table, row, 6)),
                notes=self._table_text(self.zones_table, row, 8) or None,
            )
            doc.set_zone_sync_groupable(
                zone_id,
                self._bool_text(
                    self._table_text(self.zones_table, row, 7)
                ),
            )

        effects: dict[str, Any] = {}
        for row in range(self.effects_table.rowCount()):
            effect_id = self._table_text(self.effects_table, row, 0)
            if not effect_id:
                continue
            effect = self._object_text(
                self._table_text(self.effects_table, row, 4),
                "Effect Extra JSON",
            )
            endpoint = self._table_text(self.effects_table, row, 1)
            payload = self._table_text(self.effects_table, row, 2)
            colours = self._table_text(self.effects_table, row, 3)

            if endpoint:
                effect["endpoint"] = endpoint
            if payload:
                effect["payload"] = json.loads(payload)
            if colours:
                effect["colours"] = int(colours, 0)
            effects[effect_id] = effect
        doc.set("effects", effects)

        for check, edit, path, label in (
            (self.safety_check, self.safety_edit, "safety", "Safety"),
            (self.performance_check, self.performance_edit, "performance", "Performance"),
            (self.input_check, self.input_edit, "input", "Input"),
        ):
            if check.isChecked():
                doc.set(path, self._object_text(edit.toPlainText(), label))
            else:
                doc.remove(path)

        if self.render_only_check.isChecked():
            doc.ensure_render_only()

        return doc

    def _load_into_form(self, doc: FixtureDocument, source_path: Path | None) -> None:
        self.document = doc
        doc.apply_reference_sync_groupability()
        self.source_path = source_path

        self.id_edit.setText(str(doc.get("id", "")))
        self.manufacturer_edit.setText(str(doc.get("manufacturer", "")))
        self.model_edit.setText(str(doc.get("model", "")))
        self.class_combo.setCurrentText(str(doc.get("device_class", "other")))
        self.variant_edit.setText(str(doc.get("variant", "")))
        self.vendor_edit.setText(str(doc.get("usb.vendor_id", "")))
        self.product_edit.setText(str(doc.get("usb.product_id", "")))

        self.backend_combo.setCurrentText(str(doc.get("backend.type", "software-rgb-sysfs")))
        self.required_endpoint_edit.setText(str(doc.get("backend.sysfs_required_endpoint", "")))
        self.service_edit.setText(str(doc.get("backend.service", "")))
        self.linked_zone_edit.setText(str(doc.get("backend.linked_source_zone", "")))

        self.rows_spin.setValue(int(doc.get("capabilities.matrix.rows", 1)))
        self.columns_spin.setValue(int(doc.get("capabilities.matrix.columns", 1)))
        telemetry = doc.get("telemetry", {})
        if not isinstance(telemetry, dict):
            telemetry = {}
        legacy_battery = bool(doc.get("capabilities.battery", False))
        self.telemetry_battery_check.setChecked(
            bool(telemetry.get("battery", legacy_battery))
        )
        self.telemetry_charging_check.setChecked(
            bool(telemetry.get("charging", legacy_battery))
        )
        self.render_only_check.setChecked(doc.get("input") is None)

        self.openrazer_name_edit.setText(str(doc.get("detection.openrazer_name_contains", "")))
        self.serial_edit.setText(str(doc.get("detection.serial", "")))
        self.serial_policy_combo.setCurrentText(str(doc.get("detection.serial_policy", "")))
        self.generated_prefixes_edit.setText(
            ", ".join(str(x) for x in doc.get("detection.generated_serial_prefixes", []))
        )

        self.zones_table.setRowCount(0)
        for zone_id, zone in doc.get("zones", {}).items():
            self._add_zone(zone_id, zone)

        self.effects_table.setRowCount(0)
        for effect_id, effect in doc.get("effects", {}).items():
            self._add_effect(effect_id, effect)

        for check, edit, path in (
            (self.safety_check, self.safety_edit, "safety"),
            (self.performance_check, self.performance_edit, "performance"),
            (self.input_check, self.input_edit, "input"),
        ):
            value = doc.get(path)
            present = isinstance(value, dict)
            check.setChecked(present)
            edit.setPlainText(json.dumps(value or {}, indent=2, ensure_ascii=False))
            edit.setEnabled(present)

        self.raw_edit.setPlainText(doc.to_json())
        self._update_backend_visibility()
        self.status_label.setText(
            f"Opened {source_path}. Installed fixture remains untouched."
            if source_path
            else "New candidate. Nothing is written until Export Candidate is used."
        )
        self._set_workflow_state("Draft")

    def new_document(self) -> None:
        doc = FixtureDocument.new(
            fixture_id="new-fixture",
            manufacturer="",
            model="",
            device_class="mousepad",
            vendor_id="0000",
            product_id="0000",
            backend_type="software-rgb-sysfs",
            rows=1,
            columns=1,
        )
        doc.set_backend(
            "software-rgb-sysfs",
            sysfs_required_endpoint="matrix_effect_static",
        )
        doc.ensure_render_only()
        self._load_into_form(doc, None)

    def load_path(self, path: Path) -> None:
        self._load_into_form(FixtureDocument.open(path), path)



    @staticmethod
    def _deep_differences(left: Any, right: Any, path: str = "") -> list[tuple[str, Any, Any]]:
        differences: list[tuple[str, Any, Any]] = []
        if isinstance(left, dict) and isinstance(right, dict):
            keys = sorted(set(left) | set(right))
            for key in keys:
                child = f"{path}.{key}" if path else str(key)
                if key not in left:
                    differences.append((child, "<missing>", copy.deepcopy(right[key])))
                elif key not in right:
                    differences.append((child, copy.deepcopy(left[key]), "<missing>"))
                else:
                    differences.extend(
                        FixtureEditorDialog._deep_differences(left[key], right[key], child)
                    )
            return differences

        if isinstance(left, list) and isinstance(right, list):
            if left != right:
                differences.append((path, copy.deepcopy(left), copy.deepcopy(right)))
            return differences

        if left != right:
            differences.append((path, copy.deepcopy(left), copy.deepcopy(right)))
        return differences

    def _find_installed_reference(self, device: DiscoveredDevice) -> tuple[Path, FixtureDocument] | None:
        if not self.fixture_dir.is_dir():
            return None

        for path in sorted(self.fixture_dir.glob("*.json")):
            try:
                candidate = FixtureDocument.open(path)
            except Exception:
                continue
            if (
                str(candidate.get("usb.vendor_id", "")).upper() == device.vendor_id.upper()
                and str(candidate.get("usb.product_id", "")).upper() == device.product_id.upper()
            ):
                return path, candidate
        return None

    def _format_reference_differences(
        self,
        differences: list[tuple[str, Any, Any]],
        *,
        limit: int = 12,
    ) -> str:
        if not differences:
            return "No semantic differences."
        lines = []
        for path, draft_value, reference_value in differences[:limit]:
            lines.append(
                f"• {path}\n"
                f"  draft: {draft_value!r}\n"
                f"  reference: {reference_value!r}"
            )
        if len(differences) > limit:
            lines.append(f"• …and {len(differences) - limit} more difference(s)")
        return "\n".join(lines)

    def _hide_reference_review(self) -> None:
        self.reference_group.setVisible(False)
        self.reference_summary_label.clear()
        self.reference_details.clear()
        self.reference_details.setVisible(False)
        self.details_button.setChecked(False)
        self.reference_group.setMaximumHeight(120)
        self.reset_autodraft_button.setVisible(False)
        self.reference_differences = []

    def apply_reference_values(self) -> None:
        if self.reference_document is None:
            self.status_label.setText("No installed reference is available to apply.")
            self._hide_reference_review()
            return

        reference = FixtureDocument(
            copy.deepcopy(self.reference_document.data),
            source_path=self.reference_document.source_path,
        )
        reference.apply_reference_sync_groupability()
        reference_path = self.reference_path
        reconciled = FixtureDocument(copy.deepcopy(reference.data), source_path=None)
        self._load_into_form(reconciled, None)

        # _load_into_form resets only the edited document; preserve the comparison source.
        self.reference_document = reference
        self.reference_path = reference_path

        after = self.current_document()
        if after.semantically_equal(reference):
            self.status_label.setText(
                "Draft matches installed reference — no manual changes required."
            )
            self._set_workflow_state("Matches Reference")
            self.reference_summary_label.setText(
                "✓ Reference values applied. Draft matches installed reference."
            )
            self.reference_details.setPlainText(
                "No semantic differences remain. Validate once, then Export Candidate."
            )
            self.reference_details.setVisible(False)
            self.details_button.setChecked(False)
            self.reference_group.setMaximumHeight(120)
            self.apply_reference_button.setEnabled(False)
            self.keep_draft_button.setEnabled(False)
            self.reset_autodraft_button.setVisible(True)
            self.reference_group.setVisible(True)
            self.reference_differences = []
        else:
            remaining = self._deep_differences(after.data, reference.data)
            self.reference_differences = remaining
            self.status_label.setText(
                "Reference values applied, but the structured form still differs. Review before export."
            )
            self.reference_summary_label.setText(
                f"{len(remaining)} semantic difference(s) remain after applying the reference."
            )
            self.reference_details.setPlainText(
                self._format_reference_differences(remaining, limit=50)
            )
            self.reference_group.setVisible(True)

    def keep_auto_draft(self) -> None:
        count = len(self.reference_differences)
        self._set_workflow_state("Needs Review")
        self.status_label.setText(
            f"Auto-draft kept with {count} reference difference(s). "
            "Review flagged fields before export."
        )
        self.reference_summary_label.setText(
            f"Auto-draft retained. {count} reference difference(s) still need review."
        )
        self.apply_reference_button.setEnabled(True)
        self.keep_draft_button.setEnabled(False)
        self.reference_group.setVisible(True)

    def _compare_with_reference(self, device: DiscoveredDevice, *, offer_reconcile: bool = True) -> None:
        found = self._find_installed_reference(device)
        if found is None:
            self.reference_document = None
            self.reference_path = None
            self.reference_differences = []
            self._hide_reference_review()
            self.status_label.setText(
                f"Auto-draft created for {device.clean_model_name}. "
                "No installed reference matched this USB identity; review flagged fields."
            )
            return

        reference_path, reference = found
        reference = FixtureDocument(
            copy.deepcopy(reference.data),
            source_path=reference.source_path,
        )
        reference.apply_reference_sync_groupability()
        self.reference_document = reference
        self.reference_path = reference_path

        draft = self.current_document()
        differences = self._deep_differences(draft.data, reference.data)
        self.reference_differences = differences

        if not differences:
            self.status_label.setText(
                "Draft matches installed reference — no manual changes required."
            )
            self._set_workflow_state("Matches Reference")
            self.reference_summary_label.setText(
                f"✓ Draft matches installed reference: {reference_path.name}"
            )
            self.reference_details.setPlainText(
                "No semantic differences. You can Validate and Export Candidate as-is."
            )
            self.apply_reference_button.setEnabled(False)
            self.keep_draft_button.setEnabled(False)
            self.reference_group.setVisible(True)
            return

        self.status_label.setText(
            f"Installed reference found with {len(differences)} semantic difference(s). "
            "Review or apply the known-good reference values."
        )
        self._set_workflow_state("Needs Review")
        self.reference_summary_label.setText(
            f"Installed reference: {reference_path.name} — "
            f"{len(differences)} semantic difference(s) found."
        )
        self.reference_details.setPlainText(
            self._format_reference_differences(differences, limit=50)
        )
        self.apply_reference_button.setEnabled(bool(offer_reconcile))
        self.keep_draft_button.setEnabled(bool(offer_reconcile))
        self.reference_group.setVisible(True)


    def discover_device(self) -> None:
        try:
            devices = discover_razer_devices()
        except Exception as exc:
            self.status_label.setText(f"Device discovery failed: {exc}")
            return
        if not devices:
            self.status_label.setText("No Razer HID devices were discovered. Nothing was changed.")
            return
        labels = [f"{d.clean_model_name} — {d.vendor_id}:{d.product_id} — {d.driver or 'unknown driver'}" for d in devices]
        selected, ok = QInputDialog.getItem(self, "Select Detected Device", "Detected device:", labels, 0, False)
        if not ok:
            return
        self.new_document()
        self._apply_discovered_device(devices[labels.index(selected)])

    def _native_effect_from_endpoint(self, endpoint: str):
        suffix = endpoint.removeprefix("matrix_effect_")
        effect_id = {"none": "off"}.get(suffix, suffix)
        payload, colours = "none", 0
        if suffix == "static":
            payload, colours = "rgb", 1
        elif suffix in ("breath", "starlight"):
            payload, colours = "rgb", 2
        elif suffix == "reactive":
            payload, colours = "reactive", 1
        return effect_id, {"endpoint": endpoint, "payload": payload, "colours": colours}

    def _apply_discovered_device(self, device: DiscoveredDevice) -> None:
        self.id_edit.setText(device.suggested_fixture_id)
        self.manufacturer_edit.setText("Razer")
        self.model_edit.setText(device.clean_model_name)
        self.class_combo.setCurrentText(device.suggested_device_class)
        self.vendor_edit.setText(device.vendor_id)
        self.product_edit.setText(device.product_id)
        self.backend_combo.setCurrentText(device.suggested_backend)
        self.required_endpoint_edit.setText(device.required_endpoint or "")
        self.service_edit.clear()
        self.linked_zone_edit.clear()
        self.openrazer_name_edit.setText(device.clean_model_name)
        self.serial_edit.setText(device.serial or "")
        self.serial_policy_combo.setCurrentText("")
        self.generated_prefixes_edit.clear()
        self.rows_spin.setValue(1)
        self.columns_spin.setValue(1)
        self.zones_table.setRowCount(0)
        self.effects_table.setRowCount(0)
        for endpoint in device.native_effect_endpoints:
            effect_id, effect = self._native_effect_from_endpoint(endpoint)
            self._add_effect(effect_id, effect)
        render_only = device.suggested_device_class not in ("keyboard", "mouse")
        self.render_only_check.setChecked(render_only)
        if render_only:
            self.input_check.setChecked(False)
            self.input_edit.setPlainText("{}")
        review = "\n".join(f"• {item}" for item in device.review_items)
        message = (
            f"Detected {device.clean_model_name} ({device.vendor_id}:{device.product_id}).\n\n"
            f"Auto-filled from read-only evidence:\n"
            f"• model and USB identity\n"
            f"• brightness support: {'yes' if device.brightness_supported else 'no'}\n"
            f"• custom-frame support: {'yes' if device.custom_frame_supported else 'no'}\n"
            f"• required endpoint: {device.required_endpoint or 'none detected'}\n"
            f"• native effects: {len(device.native_effect_endpoints)}\n\n"
            f"Needs review:\n{review}\n\n"
            "No fixture was installed and no hardware bytes were written."
        )
        self.status_label.setText(
            f"Auto-draft created for {device.clean_model_name}. Review flagged fields, then Validate."
        )
        self.auto_draft_document = FixtureDocument(
            copy.deepcopy(self.current_document().data),
            source_path=None,
        )
        self._set_workflow_state("Draft")
        self._compare_with_reference(device, offer_reconcile=True)

    def open_document(self) -> None:
        source, _ = QFileDialog.getOpenFileName(
            self,
            "Open Serpent fixture",
            str(self.fixture_dir),
            "JSON files (*.json)",
        )
        if not source:
            return
        try:
            self.load_path(Path(source))
        except Exception as exc:
            self.status_label.setText(f"Could not open fixture: {exc}")

    def refresh_raw_json(self) -> None:
        try:
            doc = self.current_document()
            self.document = doc
            self.raw_edit.setPlainText(doc.to_json())
            self.status_label.setText("Advanced JSON refreshed from structured controls.")
        except Exception as exc:
            self.status_label.setText(f"Fixture form error: {exc}")

    def apply_raw_json(self) -> None:
        try:
            data = json.loads(self.raw_edit.toPlainText())
            if not isinstance(data, dict):
                raise FixtureEditorError("Fixture JSON root must be an object.")
            doc = FixtureDocument(data, source_path=self.source_path)
            doc.validate_data()
            self._load_into_form(doc, self.source_path)
            self.status_label.setText("Advanced JSON applied to the in-memory candidate.")
        except Exception as exc:
            self.status_label.setText(f"Invalid fixture JSON: {exc}")

    def validate_current(self) -> bool:
        try:
            doc = self.current_document()
            fixture = doc.validate_data()
        except Exception as exc:
            self.status_label.setText(f"Validation failed: {exc}")
            return False

        self.document = doc
        self.raw_edit.setPlainText(doc.to_json())
        self.status_label.setText(
            f"Valid Fixture Schema v1 candidate: {fixture.id} ({fixture.device_class}). "
            "Export Candidate is now enabled."
        )
        self._set_workflow_state("Validated")
        return True

    def export_path(self, destination: Path) -> Path:
        doc = self.current_document()
        doc.export(destination, validate=True)
        self.document = doc
        self.raw_edit.setPlainText(doc.to_json())
        return destination

    def export_candidate(self) -> None:
        try:
            doc = self.current_document()
            fixture_id = str(doc.get("id", "fixture")).strip() or "fixture"
            doc.validate_data()
        except Exception as exc:
            self.status_label.setText(f"Fixture validation failed: {exc}")
            return

        destination, _ = QFileDialog.getSaveFileName(
            self,
            "Export Fixture Candidate",
            str(Path.home() / "Downloads" / f"{fixture_id}.json"),
            "JSON files (*.json)",
        )
        if not destination:
            return

        try:
            path = self.export_path(Path(destination))
        except Exception as exc:
            self.status_label.setText(f"Fixture export failed: {exc}")
            return

        self.status_label.setText(
            f"Candidate exported to {path}. The installed fixture directory was not modified."
        )
        self._set_workflow_state("Exported")
