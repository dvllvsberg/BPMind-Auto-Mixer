from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from engine.playback.timeline_plan import RegionKind, SessionTimeline

_REGION_COLORS = {
  RegionKind.PLAY: QColor(70, 130, 200, 180),
  RegionKind.CROSSFADE: QColor(220, 140, 60, 200),
  RegionKind.TRIM_START: QColor(90, 90, 90, 200),
  RegionKind.TRIM_END: QColor(90, 90, 90, 200),
}

_BACKGROUND = QColor(45, 45, 48)
_PLAYHEAD = QColor(255, 90, 70)
_BORDER = QColor(80, 80, 85)


def format_time(sec: float) -> str:
  total = max(0, int(sec))
  minutes, seconds = divmod(total, 60)
  return f"{minutes}:{seconds:02d}"


class MixTimelineWidget(QWidget):
  seek_requested = Signal(float)

  def __init__(self, parent: QWidget | None = None) -> None:
    super().__init__(parent)
    self._timeline: SessionTimeline | None = None
    self._position_sec = 0.0
    self._dragging = False
    self.setMinimumHeight(28)
    self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    self.setToolTip(
      "Зелёный/синий — воспроизведение, оранжевый — кроссфейд, "
      "серый — обрезанная тишина. Перетащите для перемотки."
    )

  def set_timeline(self, timeline: SessionTimeline | None) -> None:
    self._timeline = timeline
    self._position_sec = 0.0
    self.update()

  def set_position(self, sec: float) -> None:
    self._position_sec = max(0.0, sec)
    if self._timeline is not None:
      self._position_sec = min(self._position_sec, self._timeline.total_duration_sec)
    if not self._dragging:
      self.update()

  def position_sec(self) -> float:
    return self._position_sec

  def is_dragging(self) -> bool:
    return self._dragging

  def paintEvent(self, event) -> None:  # noqa: N802
    painter = QPainter(self)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(2, 6, max(1, self.width() - 4), self.height() - 12)
    painter.fillRect(rect, _BACKGROUND)
    painter.setPen(QPen(_BORDER, 1))
    painter.drawRoundedRect(rect, 3, 3)

    if self._timeline is None or self._timeline.total_duration_sec <= 0:
      painter.end()
      return

    total = self._timeline.total_duration_sec
    for plan in self._timeline.tracks:
      x1 = rect.left() + (plan.session_offset_sec / total) * rect.width()
      x2 = rect.left() + ((plan.session_offset_sec + plan.output_duration_sec) / total) * rect.width()
      track_rect = QRectF(x1, rect.top(), max(1.0, x2 - x1), rect.height())
      painter.fillRect(track_rect, QColor(55, 55, 60))

      for region in plan.regions:
        rx1 = rect.left() + (region.start_sec / total) * rect.width()
        rx2 = rect.left() + (region.end_sec / total) * rect.width()
        color = _REGION_COLORS.get(region.kind, QColor(100, 100, 100))
        painter.fillRect(QRectF(rx1, rect.top(), max(1.0, rx2 - rx1), rect.height()), color)

    play_x = rect.left() + (self._position_sec / total) * rect.width()
    painter.setPen(QPen(_PLAYHEAD, 2))
    painter.drawLine(QPointF(play_x, rect.top() - 2), QPointF(play_x, rect.bottom() + 2))
    painter.end()

  def mousePressEvent(self, event) -> None:  # noqa: N802
    if event.button() == Qt.MouseButton.LeftButton and self._timeline is not None:
      self._dragging = True
      self._set_position_from_mouse(event.position().x())
      event.accept()

  def mouseMoveEvent(self, event) -> None:  # noqa: N802
    if self._dragging and self._timeline is not None:
      self._set_position_from_mouse(event.position().x())
      event.accept()

  def mouseReleaseEvent(self, event) -> None:  # noqa: N802
    if self._dragging and event.button() == Qt.MouseButton.LeftButton:
      self._dragging = False
      self.seek_requested.emit(self._position_sec)
      event.accept()

  def _set_position_from_mouse(self, x: float) -> None:
    if self._timeline is None or self._timeline.total_duration_sec <= 0:
      return
    rect = QRectF(2, 6, max(1, self.width() - 4), self.height() - 12)
    ratio = (x - rect.left()) / rect.width()
    ratio = max(0.0, min(1.0, ratio))
    self._position_sec = ratio * self._timeline.total_duration_sec
    self.update()
