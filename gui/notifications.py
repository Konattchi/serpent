from __future__ import annotations

import sys
from enum import Enum

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class NotificationLevel(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class NotificationCard(QFrame):
    def __init__(self, level, title, message, parent=None):
        super().__init__(parent)
        self.level = level
        self.title = str(title or "").strip()
        self.message = str(message or "").strip()
        self.setFrameShape(QFrame.Shape.StyledPanel)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 8, 10, 8)
        outer.setSpacing(6)

        heading_row = QHBoxLayout()
        heading = QLabel(self._heading_text())
        font = heading.font()
        font.setBold(True)
        heading.setFont(font)
        heading.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        copy_button = QPushButton("Copy")
        dismiss_button = QPushButton("Dismiss")
        copy_button.clicked.connect(self.copy_details)
        dismiss_button.clicked.connect(self.dismiss)

        heading_row.addWidget(heading, 1)
        heading_row.addWidget(copy_button)
        heading_row.addWidget(dismiss_button)

        body = QLabel(self.message)
        body.setWordWrap(True)
        body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        outer.addLayout(heading_row)
        outer.addWidget(body)

    def _heading_text(self):
        prefix = {
            NotificationLevel.INFO: "Info",
            NotificationLevel.WARNING: "Warning",
            NotificationLevel.ERROR: "Error",
        }[self.level]
        return f"{prefix}: {self.title}" if self.title else prefix

    def full_text(self):
        return f"{self._heading_text()}\n{self.message}".strip()

    def copy_details(self):
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self.full_text())

    def dismiss(self):
        parent = self.parentWidget()
        self.setParent(None)
        self.deleteLater()
        if isinstance(parent, NotificationCenter):
            parent._sync_visibility()


class NotificationCenter(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self.setVisible(False)

    def post(self, level, title, message):
        card = NotificationCard(level, title, message, self)
        self._layout.insertWidget(0, card)

        while self._layout.count() > 8:
            item = self._layout.takeAt(self._layout.count() - 1)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        self._sync_visibility()
        return card

    def _sync_visibility(self):
        self.setVisible(self._layout.count() > 0)


def _notification_center(parent):
    if parent is not None:
        try:
            window = parent.window()
        except Exception:
            window = None

        if window is not None:
            center = getattr(window, "notification_center", None)
            if isinstance(center, NotificationCenter):
                return center

    app = QApplication.instance()
    if app is not None:
        for window in app.topLevelWidgets():
            center = getattr(window, "notification_center", None)
            if isinstance(center, NotificationCenter):
                return center

    return None


def post_notification(parent, level, title, message):
    title_text = str(title or "").strip()
    message_text = str(message or "").strip()

    center = _notification_center(parent)
    if center is not None:
        center.post(level, title_text, message_text)
        return

    print(
        f"Serpent {level.value}: "
        + (f"{title_text}: " if title_text else "")
        + message_text,
        file=sys.stderr,
        flush=True,
    )


def notify_error(parent, title, message, *args, **kwargs):
    post_notification(parent, NotificationLevel.ERROR, title, message)


def notify_warning(parent, title, message, *args, **kwargs):
    post_notification(parent, NotificationLevel.WARNING, title, message)


def notify_info(parent, title, message, *args, **kwargs):
    post_notification(parent, NotificationLevel.INFO, title, message)


__all__ = [
    "NotificationCard",
    "NotificationCenter",
    "NotificationLevel",
    "notify_error",
    "notify_info",
    "notify_warning",
    "post_notification",
]
