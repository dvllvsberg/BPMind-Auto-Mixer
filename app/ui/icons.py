from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QApplication, QPushButton, QStyle, QWidget


def folder_icon(widget: QWidget | None = None) -> QIcon:
  style = _style(widget)
  return style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)


def settings_icon(widget: QWidget | None = None) -> QIcon:
  for theme_name in ("preferences-system", "settings", "configure"):
    icon = QIcon.fromTheme(theme_name)
    if not icon.isNull():
      return icon
  return QIcon(_gear_pixmap(20))


def make_icon_button(
  icon: QIcon,
  *,
  tooltip: str,
  fixed_size: int = 34,
) -> QPushButton:
  button = QPushButton()
  button.setIcon(icon)
  button.setToolTip(tooltip)
  button.setFixedSize(fixed_size, fixed_size)
  button.setIconSize(QSize(fixed_size - 12, fixed_size - 12))
  button.setFlat(True)
  return button


def _style(widget: QWidget | None) -> QStyle:
  if widget is not None:
    return widget.style()
  app = QApplication.instance()
  if app is None:
    raise RuntimeError("QApplication is required for standard icons")
  return app.style()


def _gear_pixmap(size: int) -> QPixmap:
  pixmap = QPixmap(size, size)
  pixmap.fill(Qt.GlobalColor.transparent)
  painter = QPainter(pixmap)
  painter.setRenderHint(QPainter.RenderHint.Antialiasing)

  color = QColor("#c8c8c8")
  painter.setPen(QPen(color, 1.1))
  painter.setBrush(QBrush(color))

  center = size / 2
  outer = size * 0.42
  inner = size * 0.20
  teeth = 8
  points: list[QPointF] = []
  for index in range(teeth * 2):
    angle = math.tau * index / (teeth * 2) - math.pi / 2
    radius = outer if index % 2 == 0 else outer * 0.74
    points.append(
      QPointF(center + radius * math.cos(angle), center + radius * math.sin(angle)),
    )
  painter.drawPolygon(QPolygonF(points))
  painter.setBrush(Qt.BrushStyle.NoBrush)
  painter.drawEllipse(QPointF(center, center), inner, inner)
  painter.end()
  return pixmap
