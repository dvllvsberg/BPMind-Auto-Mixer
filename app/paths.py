from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

PORTABLE_FLAG_NAME = "portable.flag"
APP_DATA_DIR_NAME = "BPMind Auto Mixer"
_MIGRATION_MARKER = ".migrated_from_install"


def executable_dir() -> Path:
  """Папка с exe (или корень репозитория в dev)."""
  if getattr(sys, "frozen", False):
    return Path(sys.executable).resolve().parent
  return Path(__file__).resolve().parent.parent


def is_portable_mode() -> bool:
  """Portable: данные рядом с exe. Установщик — в %LOCALAPPDATA%."""
  forced = os.environ.get("BPMIND_PORTABLE", "").strip().lower()
  if forced in {"1", "true", "yes", "on"}:
    return True
  if forced in {"0", "false", "no", "off"}:
    return False
  if not getattr(sys, "frozen", False):
    return True
  return (executable_dir() / PORTABLE_FLAG_NAME).exists()


def application_root() -> Path:
  """Корень пользовательских данных (кэш, миксы, настройки)."""
  if is_portable_mode():
    return executable_dir()
  local_app_data = os.environ.get("LOCALAPPDATA")
  base = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
  return base / APP_DATA_DIR_NAME


def resource_root() -> Path:
  """Только для чтения: ресурсы PyInstaller (_MEIPASS) или корень репозитория."""
  if getattr(sys, "frozen", False):
    return Path(getattr(sys, "_MEIPASS", executable_dir()))
  return Path(__file__).resolve().parent.parent


# Совместимость со старым именем в коде.
PROJECT_ROOT = application_root()


def user_data_summary() -> str:
  if is_portable_mode():
    return f"portable ({application_root()})"
  return f"installed ({application_root()})"


def _migrate_legacy_data_from_install_dir(user_root: Path, install_dir: Path) -> None:
  if install_dir.resolve() == user_root.resolve():
    return
  marker = user_root / _MIGRATION_MARKER
  if marker.exists():
    return

  migrated = False
  user_root.mkdir(parents=True, exist_ok=True)
  for folder in ("cache", "mixes", "exports", "settings"):
    src = install_dir / folder
    if not src.is_dir() or not any(src.iterdir()):
      continue
    dst = user_root / folder
    if dst.exists():
      continue
    shutil.copytree(src, dst)
    migrated = True

  if migrated:
    marker.write_text(str(install_dir.resolve()), encoding="utf-8")


def default_db_path() -> Path:
  return application_root() / "cache" / "library.db"


def default_mix_path() -> Path:
  return application_root() / "cache" / "last_mix.json"


def default_library_profile_path() -> Path:
  return application_root() / "cache" / "library_profile.json"


def mixes_dir() -> Path:
  return application_root() / "mixes"


def exports_dir() -> Path:
  return application_root() / "exports"


def default_settings_path() -> Path:
  return application_root() / "settings" / "default.json"


def default_settings_example_path() -> Path:
  bundled = resource_root() / "settings" / "default.json.example"
  if bundled.exists():
    return bundled
  return application_root() / "settings" / "default.json.example"


def ensure_runtime_directories() -> None:
  """Создаёт рабочие папки и settings/default.json при первом запуске."""
  user_root = application_root()
  if not is_portable_mode() and getattr(sys, "frozen", False):
    _migrate_legacy_data_from_install_dir(user_root, executable_dir())

  for folder in ("cache", "mixes", "exports", "settings"):
    (user_root / folder).mkdir(parents=True, exist_ok=True)

  settings_path = default_settings_path()
  if settings_path.exists():
    return

  example_path = default_settings_example_path()
  if example_path.exists():
    shutil.copy(example_path, settings_path)
    return

  settings_path.write_text("{}", encoding="utf-8")


def load_settings() -> dict:
  path = default_settings_path()
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def save_settings(settings: dict) -> None:
  path = default_settings_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
