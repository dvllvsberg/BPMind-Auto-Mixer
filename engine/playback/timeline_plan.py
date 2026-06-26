from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track


class RegionKind(str, Enum):
  PLAY = "play"
  CROSSFADE = "crossfade"
  TRIM_START = "trim_start"
  TRIM_END = "trim_end"


@dataclass(frozen=True)
class TimelineRegion:
  start_sec: float
  end_sec: float
  kind: RegionKind


@dataclass(frozen=True)
class TrackOutputPlan:
  track_index: int
  track_id: int
  session_offset_sec: float
  output_duration_sec: float
  main_duration_sec: float
  crossfade_duration_sec: float
  play_from_sec: float
  play_until_sec: float
  file_duration_sec: float
  regions: tuple[TimelineRegion, ...]


@dataclass(frozen=True)
class PlaybackLocation:
  track_index: int
  local_output_sec: float
  in_crossfade: bool


@dataclass(frozen=True)
class SessionTimeline:
  tracks: tuple[TrackOutputPlan, ...]
  total_duration_sec: float

  def locate(self, session_sec: float) -> PlaybackLocation:
    if not self.tracks:
      return PlaybackLocation(track_index=0, local_output_sec=0.0, in_crossfade=False)

    clamped = max(0.0, min(session_sec, self.total_duration_sec))
    for plan in self.tracks:
      start = plan.session_offset_sec
      end = start + plan.output_duration_sec
      if clamped < end or plan is self.tracks[-1]:
        local = max(0.0, min(clamped - start, plan.output_duration_sec))
        in_crossfade = local > plan.main_duration_sec and plan.crossfade_duration_sec > 0
        return PlaybackLocation(
          track_index=plan.track_index,
          local_output_sec=local,
          in_crossfade=in_crossfade,
        )

    last = self.tracks[-1]
    return PlaybackLocation(
      track_index=last.track_index,
      local_output_sec=last.output_duration_sec,
      in_crossfade=False,
    )


def _transition_map(session: MixSession) -> dict[int, PlannedTransition]:
  return {transition.from_track_id: transition for transition in session.transitions}


def _effective_until(item: MixSessionTrack, track: Track) -> float:
  if item.play_until_sec is not None:
    return item.play_until_sec
  return track.duration or item.play_from_sec


def build_track_output_plan(
  index: int,
  session: MixSession,
  tracks_by_id: dict[int, Track],
  transitions_by_from: dict[int, PlannedTransition],
  *,
  enable_crossfade: bool,
  session_offset_sec: float,
) -> TrackOutputPlan | None:
  if index < 0 or index >= len(session.tracks):
    return None

  item = session.tracks[index]
  track = tracks_by_id.get(item.track_id)
  if track is None:
    return None

  start_sec = item.play_from_sec
  if index > 0 and enable_crossfade:
    prev_item = session.tracks[index - 1]
    prev_transition = transitions_by_from.get(prev_item.track_id)
    if prev_transition and prev_transition.to_track_id == item.track_id:
      start_sec = item.play_from_sec + prev_transition.crossfade_duration_sec

  until_sec = _effective_until(item, track)
  next_transition = transitions_by_from.get(item.track_id) if index + 1 < len(session.tracks) else None
  fade_sec = next_transition.crossfade_duration_sec if next_transition and enable_crossfade else 0.0

  main_end = until_sec
  if fade_sec > 0:
    main_end = max(start_sec, until_sec - fade_sec)

  main_duration = max(0.0, main_end - start_sec)
  output_duration = main_duration + fade_sec
  file_duration = track.duration or until_sec

  regions: list[TimelineRegion] = []
  session_start = session_offset_sec

  if item.play_from_sec > 0:
    marker = min(2.0, output_duration * 0.08)
    regions.append(TimelineRegion(session_start, session_start + marker, RegionKind.TRIM_START))

  regions.append(TimelineRegion(session_start, session_start + main_duration, RegionKind.PLAY))

  if fade_sec > 0:
    regions.append(
      TimelineRegion(
        session_start + main_duration,
        session_start + output_duration,
        RegionKind.CROSSFADE,
      )
    )

  if file_duration > until_sec:
    marker = min(2.0, output_duration * 0.08)
    regions.append(
      TimelineRegion(
        session_start + output_duration - marker,
        session_start + output_duration,
        RegionKind.TRIM_END,
      )
    )

  return TrackOutputPlan(
    track_index=index,
    track_id=item.track_id,
    session_offset_sec=session_offset_sec,
    output_duration_sec=output_duration,
    main_duration_sec=main_duration,
    crossfade_duration_sec=fade_sec,
    play_from_sec=item.play_from_sec,
    play_until_sec=until_sec,
    file_duration_sec=file_duration,
    regions=tuple(regions),
  )


def build_session_timeline(
  session: MixSession,
  tracks_by_id: dict[int, Track],
  *,
  enable_crossfade: bool = True,
) -> SessionTimeline:
  transitions_by_from = _transition_map(session)
  plans: list[TrackOutputPlan] = []
  offset = 0.0

  for index in range(len(session.tracks)):
    plan = build_track_output_plan(
      index,
      session,
      tracks_by_id,
      transitions_by_from,
      enable_crossfade=enable_crossfade,
      session_offset_sec=offset,
    )
    if plan is None:
      continue
    plans.append(plan)
    offset += plan.output_duration_sec

  return SessionTimeline(tracks=tuple(plans), total_duration_sec=offset)
