from __future__ import annotations

import json
import re
from pathlib import Path

from engine.database.repository import TrackRepository
from engine.domain.models import MixSession
from engine.mix_generator.session_store import load_mix_recipe, save_mix_recipe

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_recipe_name(name: str) -> str:
  cleaned = _INVALID_FILENAME_CHARS.sub("", name.strip())
  cleaned = re.sub(r"\s+", " ", cleaned)
  return cleaned[:80]


def recipe_file_stem(name: str) -> str:
  stem = sanitize_recipe_name(name).replace(" ", "_")
  return stem or "mix"


def recipe_path_for_name(name: str, *, mixes_dir: Path) -> Path:
  return mixes_dir / f"{recipe_file_stem(name)}.json"


def list_recipe_files(mixes_dir: Path) -> list[Path]:
  if not mixes_dir.exists():
    return []
  return sorted(mixes_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)


def format_recipe_list_label(path: Path) -> str:
  try:
    data = json.loads(path.read_text(encoding="utf-8"))
  except (OSError, json.JSONDecodeError):
    return path.stem

  name = data.get("name")
  generator = data.get("generator") or {}
  if not name:
    name = generator.get("name") or path.stem

  mode = data.get("start_mode", "?")
  track_count = len(data.get("tracks", []))
  seed = generator.get("seed")
  seed_hint = f", seed {seed}" if seed is not None else ""
  return f"{name}  ({mode}, {track_count} тр.{seed_hint})"


def validate_recipe_tracks(session: MixSession, repo: TrackRepository) -> list[str]:
  problems: list[str] = []
  for item in session.tracks:
    track = repo.get_by_id(item.track_id)
    if track is None:
      problems.append(f"трек id={item.track_id} не найден в библиотеке")
      continue
    if not Path(track.path).exists():
      problems.append(f"файл отсутствует: {track.path}")
  return problems


def load_recipe_file(path: Path) -> tuple[MixSession, object]:
  return load_mix_recipe(path)


def save_recipe_file(
  session: MixSession,
  path: Path,
  *,
  metadata,
) -> Path:
  save_mix_recipe(session, path, metadata=metadata)
  return path
