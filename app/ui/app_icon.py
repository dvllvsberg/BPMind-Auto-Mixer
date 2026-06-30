from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon

_REPO_ROOT = Path(__file__).resolve().parents[2]


def application_icon() -> QIcon | None:
  """Иконка приложения: packaging/app.ico или assets/icon-master.png."""
  for relative in ("packaging/app.ico", "assets/icon-master.png"):
    path = _REPO_ROOT / relative
    if path.exists():
      return QIcon(str(path))
  return None
