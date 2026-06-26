from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from engine.database.schema import CREATE_TABLES_SQL, SCHEMA_VERSION
from engine.domain.enums import AnalysisLevel, ScanAction, TransitionCandidateKind
from engine.domain.models import EnergySegment, Track, TransitionCandidate


def _parse_datetime(value: str | None) -> datetime | None:
  if not value:
    return None
  return datetime.fromisoformat(value)


def _row_get(row: sqlite3.Row, key: str, default: object = None) -> object:
  if key in row.keys():
    return row[key]
  return default


def _row_to_track(row: sqlite3.Row, candidates: list[TransitionCandidate], energy: list[EnergySegment]) -> Track:
  return Track(
    id=row["id"],
    path=row["path"],
    title=row["title"],
    artist=row["artist"],
    duration=row["duration"],
    file_size=row["file_size"],
    file_mtime=row["file_mtime"],
    bpm=row["bpm"],
    loudness_avg=row["loudness_avg"],
    loudness_peak=row["loudness_peak"],
    key=row["key"],
    content_start_sec=_row_get(row, "content_start_sec"),
    content_end_sec=_row_get(row, "content_end_sec"),
    analysis_level=AnalysisLevel(row["analysis_level"]),
    analyzed_at=_parse_datetime(row["analyzed_at"]),
    transition_candidates=candidates,
    energy_map=energy,
  )


class TrackRepository:
  def __init__(self, db_path: Path) -> None:
    self._db_path = db_path
    self._db_path.parent.mkdir(parents=True, exist_ok=True)
    self._conn = sqlite3.connect(self._db_path)
    self._conn.row_factory = sqlite3.Row
    self._conn.execute("PRAGMA foreign_keys = ON")
    self._initialize()

  def close(self) -> None:
    self._conn.close()

  def __enter__(self) -> TrackRepository:
    return self

  def __exit__(self, *args: object) -> None:
    self.close()

  def _initialize(self) -> None:
    self._conn.executescript(CREATE_TABLES_SQL)
    self._migrate_schema()
    self._conn.execute(
      "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
      ("version", str(SCHEMA_VERSION)),
    )
    self._conn.commit()

  def _migrate_schema(self) -> None:
    columns = {row[1] for row in self._conn.execute("PRAGMA table_info(tracks)")}
    if "content_start_sec" not in columns:
      self._conn.execute("ALTER TABLE tracks ADD COLUMN content_start_sec REAL")
    if "content_end_sec" not in columns:
      self._conn.execute("ALTER TABLE tracks ADD COLUMN content_end_sec REAL")

  def get_by_path(self, path: str) -> Track | None:
    row = self._conn.execute("SELECT * FROM tracks WHERE path = ?", (path,)).fetchone()
    if row is None:
      return None
    return self._hydrate_track(row)

  def get_by_id(self, track_id: int) -> Track | None:
    row = self._conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if row is None:
      return None
    return self._hydrate_track(row)

  def list_all(self) -> list[Track]:
    rows = self._conn.execute("SELECT * FROM tracks ORDER BY path").fetchall()
    return [self._hydrate_track(row) for row in rows]

  def list_for_quick_analysis(self, *, include_analyzed: bool = False) -> list[Track]:
    if include_analyzed:
      rows = self._conn.execute("SELECT * FROM tracks ORDER BY path").fetchall()
    else:
      rows = self._conn.execute(
        "SELECT * FROM tracks WHERE analysis_level = 'none' ORDER BY path"
      ).fetchall()
    return [self._hydrate_track(row) for row in rows]

  def list_for_deep_analysis(self, *, include_analyzed: bool = False) -> list[Track]:
    if include_analyzed:
      rows = self._conn.execute(
        """
        SELECT * FROM tracks
        WHERE bpm IS NOT NULL AND analysis_level IN ('quick', 'deep')
        ORDER BY path
        """
      ).fetchall()
    else:
      rows = self._conn.execute(
        """
        SELECT * FROM tracks
        WHERE bpm IS NOT NULL AND analysis_level = 'quick'
        ORDER BY path
        """
      ).fetchall()
    return [self._hydrate_track(row) for row in rows]

  def list_mixable(self) -> list[Track]:
    rows = self._conn.execute(
      """
      SELECT * FROM tracks
      WHERE bpm IS NOT NULL AND analysis_level IN ('quick', 'deep')
      ORDER BY path
      """
    ).fetchall()
    return [self._hydrate_track(row) for row in rows]

  def list_paths(self) -> set[str]:
    rows = self._conn.execute("SELECT path FROM tracks").fetchall()
    return {row["path"] for row in rows}

  def upsert_file_record(
    self,
    path: str,
    title: str,
    artist: str,
    file_size: int,
    file_mtime: float,
    duration: float | None = None,
  ) -> ScanAction:
    existing = self.get_by_path(path)
    if existing is None:
      self._conn.execute(
        """
        INSERT INTO tracks (path, title, artist, duration, file_size, file_mtime)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (path, title, artist, duration, file_size, file_mtime),
      )
      self._conn.commit()
      return ScanAction.ADDED

    file_changed = existing.file_size != file_size or existing.file_mtime != file_mtime
    if file_changed:
      self._conn.execute(
        """
        UPDATE tracks
        SET title = ?, artist = ?, duration = ?, file_size = ?, file_mtime = ?,
            bpm = NULL, loudness_avg = NULL, loudness_peak = NULL, key = NULL,
            content_start_sec = NULL, content_end_sec = NULL,
            analysis_level = 'none', analyzed_at = NULL
        WHERE id = ?
        """,
        (title, artist, duration, file_size, file_mtime, existing.id),
      )
      self._conn.execute("DELETE FROM energy_segments WHERE track_id = ?", (existing.id,))
      self._conn.execute("DELETE FROM transition_candidates WHERE track_id = ?", (existing.id,))
      self._conn.commit()
      return ScanAction.UPDATED

    if title != existing.title or artist != existing.artist or duration != existing.duration:
      self._conn.execute(
        "UPDATE tracks SET title = ?, artist = ?, duration = ? WHERE id = ?",
        (title, artist, duration, existing.id),
      )
      self._conn.commit()
      return ScanAction.UNCHANGED

    return ScanAction.UNCHANGED

  def remove_missing_paths(self, valid_paths: set[str]) -> int:
    stored = self.list_paths()
    to_remove = stored - valid_paths
    if not to_remove:
      return 0
    for path in to_remove:
      self._conn.execute("DELETE FROM tracks WHERE path = ?", (path,))
    self._conn.commit()
    return len(to_remove)

  def save_quick_analysis(
    self,
    track_id: int,
    duration: float,
    bpm: float,
    loudness_avg: float,
    loudness_peak: float,
    *,
    content_start_sec: float = 0.0,
    content_end_sec: float | None = None,
    key: str | None = None,
  ) -> None:
    self._conn.execute(
      """
      UPDATE tracks
      SET duration = ?, bpm = ?, loudness_avg = ?, loudness_peak = ?, key = ?,
          content_start_sec = ?, content_end_sec = ?,
          analysis_level = 'quick', analyzed_at = ?
      WHERE id = ?
      """,
      (
        duration,
        bpm,
        loudness_avg,
        loudness_peak,
        key,
        content_start_sec,
        content_end_sec,
        datetime.now().isoformat(),
        track_id,
      ),
    )
    self._conn.commit()

  def save_deep_analysis(
    self,
    track_id: int,
    energy_map: list[EnergySegment],
    candidates: list[TransitionCandidate],
  ) -> None:
    self._conn.execute("DELETE FROM energy_segments WHERE track_id = ?", (track_id,))
    self._conn.execute("DELETE FROM transition_candidates WHERE track_id = ?", (track_id,))

    for segment in energy_map:
      self._conn.execute(
        """
        INSERT INTO energy_segments (track_id, start_sec, end_sec, energy)
        VALUES (?, ?, ?, ?)
        """,
        (track_id, segment.start_sec, segment.end_sec, segment.energy),
      )

    for candidate in candidates:
      self._conn.execute(
        """
        INSERT INTO transition_candidates (track_id, position_sec, kind, confidence)
        VALUES (?, ?, ?, ?)
        """,
        (track_id, candidate.position_sec, candidate.kind.value, candidate.confidence),
      )

    self._conn.execute(
      """
      UPDATE tracks SET analysis_level = 'deep', analyzed_at = ? WHERE id = ?
      """,
      (datetime.now().isoformat(), track_id),
    )
    self._conn.commit()

  def _hydrate_track(self, row: sqlite3.Row) -> Track:
    track_id = row["id"]
    candidates_rows = self._conn.execute(
      "SELECT * FROM transition_candidates WHERE track_id = ? ORDER BY position_sec",
      (track_id,),
    ).fetchall()
    energy_rows = self._conn.execute(
      "SELECT * FROM energy_segments WHERE track_id = ? ORDER BY start_sec",
      (track_id,),
    ).fetchall()

    candidates = [
      TransitionCandidate(
        id=r["id"],
        track_id=r["track_id"],
        position_sec=r["position_sec"],
        kind=TransitionCandidateKind(r["kind"]),
        confidence=r["confidence"],
      )
      for r in candidates_rows
    ]
    energy = [
      EnergySegment(start_sec=r["start_sec"], end_sec=r["end_sec"], energy=r["energy"])
      for r in energy_rows
    ]
    return _row_to_track(row, candidates, energy)
