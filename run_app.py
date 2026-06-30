from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from app.paths import ensure_runtime_directories
from app.windows.main_window import MainWindow


def main() -> int:
  ensure_runtime_directories()
  app = QApplication(sys.argv)
  app.setApplicationName("BPMind Auto Mixer")
  window = MainWindow()
  window.show()
  return app.exec()


if __name__ == "__main__":
  raise SystemExit(main())
