from __future__ import annotations

import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def default_db_path() -> Path:
  return PROJECT_ROOT / "cache" / "library.db"


def default_mix_path() -> Path:
  return PROJECT_ROOT / "cache" / "last_mix.json"


def default_library_profile_path() -> Path:
  return PROJECT_ROOT / "cache" / "library_profile.json"


def mixes_dir() -> Path:
  return PROJECT_ROOT / "mixes"


def exports_dir() -> Path:
  return PROJECT_ROOT / "exports"


def default_settings_path() -> Path:
  return PROJECT_ROOT / "settings" / "default.json"


def load_settings() -> dict:
  path = default_settings_path()
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def save_settings(settings: dict) -> None:
  path = default_settings_path()
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
