from __future__ import annotations

import os
from pathlib import Path

from mutagen import File as MutagenFile

from engine.database.repository import TrackRepository
from engine.domain.enums import ScanAction
from engine.domain.models import ScanResult

SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".wav", ".m4a"}


def _read_tags(path: Path) -> tuple[str, str, float | None]:
  title = path.stem
  artist = ""
  duration: float | None = None

  try:
    audio = MutagenFile(path, easy=True)
    if audio is not None:
      if audio.tags:
        title = str(audio.tags.get("title", [title])[0])
        artist = str(audio.tags.get("artist", [""])[0])
      if audio.info and hasattr(audio.info, "length"):
        duration = float(audio.info.length)
  except Exception:
    pass

  return title, artist, duration


class LibraryScanner:
  def __init__(self, repository: TrackRepository) -> None:
    self._repo = repository

  def scan(self, root: Path, *, remove_missing: bool = True) -> ScanResult:
    root = root.resolve()
    if not root.is_dir():
      raise NotADirectoryError(f"Not a directory: {root}")

    result = ScanResult()
    found_paths: set[str] = set()

    for dirpath, _, filenames in os.walk(root):
      for filename in filenames:
        path = Path(dirpath) / filename
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
          continue

        resolved = str(path.resolve())
        found_paths.add(resolved)
        stat = path.stat()
        title, artist, duration = _read_tags(path)

        action = self._repo.upsert_file_record(
          path=resolved,
          title=title,
          artist=artist,
          file_size=stat.st_size,
          file_mtime=stat.st_mtime,
          duration=duration,
          commit=False,
        )

        if action == ScanAction.ADDED:
          result.added += 1
        elif action == ScanAction.UPDATED:
          result.updated += 1
        else:
          result.unchanged += 1

    result.total = len(found_paths)

    self._repo.flush()

    if remove_missing:
      result.removed = self._repo.remove_missing_paths(found_paths)

    return result
