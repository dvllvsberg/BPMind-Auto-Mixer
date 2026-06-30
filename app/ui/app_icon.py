from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WINDOWS_APP_ID = "BPMind.AutoMixer"


def configure_platform_app_identity() -> None:
  """Отвязать окно от python.exe в панели задач Windows (dev-запуск)."""
  if sys.platform != "win32":
    return
  try:
    import ctypes

    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(_WINDOWS_APP_ID)
  except (AttributeError, OSError):
    pass


def application_icon() -> QIcon | None:
  """Иконка приложения: packaging/app.ico или assets/icon-master.png."""
  for relative in ("packaging/app.ico", "assets/icon-master.png"):
    path = _REPO_ROOT / relative
    if path.exists():
      return QIcon(str(path))
  return None
