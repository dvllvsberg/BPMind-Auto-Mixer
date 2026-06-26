from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from engine.domain.enums import StartMode, TransitionType
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition
from engine.mix_generator.recipe_metadata import RECIPE_SCHEMA_VERSION, MixRecipeMetadata


def _metadata_to_dict(metadata: MixRecipeMetadata | None) -> dict | None:
  if metadata is None:
    return None
  payload = {
    "name": metadata.name,
    "track_play_ratio": metadata.track_play_ratio,
    "groove_weight": metadata.groove_weight,
    "crossfade_duration_sec": metadata.crossfade_duration_sec,
    "session_length_tracks": metadata.session_length_tracks,
    "mix_settings_manual": metadata.mix_settings_manual,
  }
  if metadata.saved_at is not None:
    payload["saved_at"] = metadata.saved_at.isoformat()
  return payload


def _metadata_from_dict(data: dict | None) -> MixRecipeMetadata:
  if not data:
    return MixRecipeMetadata()
  saved_at = data.get("saved_at")
  return MixRecipeMetadata(
    name=data.get("name"),
    track_play_ratio=data.get("track_play_ratio"),
    groove_weight=data.get("groove_weight"),
    crossfade_duration_sec=data.get("crossfade_duration_sec"),
    session_length_tracks=data.get("session_length_tracks"),
    mix_settings_manual=data.get("mix_settings_manual"),
    saved_at=datetime.fromisoformat(saved_at) if saved_at else None,
  )


def mix_session_to_dict(session: MixSession, *, metadata: MixRecipeMetadata | None = None) -> dict:
  payload = {
    "schema_version": RECIPE_SCHEMA_VERSION,
    "start_mode": session.start_mode.value,
    "created_at": session.created_at.isoformat(),
    "tracks": [
      {
        "track_id": item.track_id,
        "play_from_sec": item.play_from_sec,
        "play_until_sec": item.play_until_sec,
      }
      for item in session.tracks
    ],
    "transitions": [
      {
        "from_track_id": item.from_track_id,
        "to_track_id": item.to_track_id,
        "type": item.type.value,
        "start_at_sec": item.start_at_sec,
        "crossfade_duration_sec": item.crossfade_duration_sec,
      }
      for item in session.transitions
    ],
  }
  generator = _metadata_to_dict(metadata)
  if generator is not None:
    payload["generator"] = generator
  if metadata is not None and metadata.name:
    payload["name"] = metadata.name
  if metadata is not None and metadata.saved_at is not None:
    payload["saved_at"] = metadata.saved_at.isoformat()
  return payload


def _session_from_dict(data: dict) -> MixSession:
  return MixSession(
    tracks=[
      MixSessionTrack(
        track_id=item["track_id"],
        play_from_sec=item.get("play_from_sec", 0.0),
        play_until_sec=item.get("play_until_sec"),
      )
      for item in data["tracks"]
    ],
    transitions=[
      PlannedTransition(
        from_track_id=item["from_track_id"],
        to_track_id=item["to_track_id"],
        type=TransitionType(item["type"]),
        start_at_sec=item["start_at_sec"],
        crossfade_duration_sec=item.get("crossfade_duration_sec", 8.0),
      )
      for item in data["transitions"]
    ],
    start_mode=StartMode(data["start_mode"]),
    created_at=datetime.fromisoformat(data["created_at"]),
  )


def save_mix_session(
  session: MixSession,
  path: Path,
  *,
  metadata: MixRecipeMetadata | None = None,
) -> None:
  path.parent.mkdir(parents=True, exist_ok=True)
  path.write_text(
    json.dumps(mix_session_to_dict(session, metadata=metadata), indent=2, ensure_ascii=False),
    encoding="utf-8",
  )


def save_mix_recipe(
  session: MixSession,
  path: Path,
  *,
  metadata: MixRecipeMetadata,
) -> None:
  recipe_metadata = MixRecipeMetadata(
    name=metadata.name,
    track_play_ratio=metadata.track_play_ratio,
    groove_weight=metadata.groove_weight,
    crossfade_duration_sec=metadata.crossfade_duration_sec,
    session_length_tracks=metadata.session_length_tracks,
    mix_settings_manual=metadata.mix_settings_manual,
    saved_at=metadata.saved_at or datetime.now(),
  )
  save_mix_session(session, path, metadata=recipe_metadata)


def load_mix_session(path: Path) -> MixSession:
  session, _metadata = load_mix_recipe(path)
  return session


def load_mix_recipe(path: Path) -> tuple[MixSession, MixRecipeMetadata]:
  data = json.loads(path.read_text(encoding="utf-8"))
  session = _session_from_dict(data)
  generator = data.get("generator")
  metadata = _metadata_from_dict(generator)
  name = data.get("name") or (generator.get("name") if generator else None)
  saved_at = data.get("saved_at")
  if name or saved_at:
    metadata = MixRecipeMetadata(
      name=name or metadata.name,
      track_play_ratio=metadata.track_play_ratio,
      groove_weight=metadata.groove_weight,
      crossfade_duration_sec=metadata.crossfade_duration_sec,
      session_length_tracks=metadata.session_length_tracks,
      mix_settings_manual=metadata.mix_settings_manual,
      saved_at=datetime.fromisoformat(saved_at) if saved_at else metadata.saved_at,
    )
  return session, metadata
