from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def application_root() -> Path:
  """Корень с пользовательскими данными: рядом с exe в сборке, иначе корень репозитория."""
  if getattr(sys, "frozen", False):
    return Path(sys.executable).resolve().parent
  return Path(__file__).resolve().parent.parent


def resource_root() -> Path:
  """Только для чтения: распакованные ресурсы PyInstaller (_MEIPASS) или корень репозитория."""
  if getattr(sys, "frozen", False):
    return Path(getattr(sys, "_MEIPASS", application_root()))
  return Path(__file__).resolve().parent.parent


# Совместимость со старым именем в коде.
PROJECT_ROOT = application_root()


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
  for folder in ("cache", "mixes", "exports", "settings"):
    (application_root() / folder).mkdir(parents=True, exist_ok=True)

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
