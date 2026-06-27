from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from engine.analysis.intro_entry import intro_skip_sec as detect_intro_skip_sec
from engine.domain.models import MixSession, MixSessionTrack, PlannedTransition, Track
from engine.transitions.playback_rules import (
  incoming_play_start_sec,
  incoming_tape_spin_sec,
  outgoing_tape_brake_sec,
  outgoing_tape_silence_sec,
  outgoing_tape_tail_sec,
  transition_is_solo_tail,
)


class RegionKind(str, Enum):
  PLAY = "play"
  CROSSFADE = "crossfade"
  TAPE_STOP = "tape_stop"
  TAPE_START = "tape_start"
  SILENCE = "silence"
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
    start_sec = incoming_play_start_sec(
      item.play_from_sec,
      prev_transition,
      enable_crossfade=True,
      incoming_track_id=item.track_id,
    )

  spin_sec = 0.0
  intro_skip = 0.0
  if index > 0 and enable_crossfade:
    prev_item = session.tracks[index - 1]
    prev_transition = transitions_by_from.get(prev_item.track_id)
    spin_sec = incoming_tape_spin_sec(
      prev_transition,
      enable_crossfade=True,
      incoming_track_id=item.track_id,
    )
    if spin_sec > 0 and prev_transition is not None and transition_is_solo_tail(prev_transition.type):
      scan_sec = min(max(spin_sec * 4.0, 12.0), 60.0)
      intro_skip = detect_intro_skip_sec(track.path, item.play_from_sec, scan_sec=scan_sec)

  until_sec = _effective_until(item, track)
  next_transition = transitions_by_from.get(item.track_id) if index + 1 < len(session.tracks) else None
  fade_sec = next_transition.crossfade_duration_sec if next_transition and enable_crossfade else 0.0
  if next_transition is not None and enable_crossfade and transition_is_solo_tail(next_transition.type):
    fade_sec = outgoing_tape_tail_sec(next_transition)

  brake_sec = 0.0
  silence_sec = 0.0
  if next_transition is not None and enable_crossfade and transition_is_solo_tail(next_transition.type):
    brake_sec = outgoing_tape_brake_sec(next_transition)
    silence_sec = outgoing_tape_silence_sec(next_transition)

  main_end = until_sec
  if fade_sec > 0:
    main_end = max(start_sec, until_sec - fade_sec)

  main_duration = max(0.0, main_end - start_sec - intro_skip)
  output_duration = main_duration + fade_sec
  file_duration = track.duration or until_sec

  regions: list[TimelineRegion] = []
  session_start = session_offset_sec

  if intro_skip > 0:
    marker = min(2.0, max(0.35, intro_skip * 0.12))
    regions.append(TimelineRegion(session_start, session_start + marker, RegionKind.TRIM_START))
  elif item.play_from_sec > 0:
    marker = min(2.0, output_duration * 0.08)
    regions.append(TimelineRegion(session_start, session_start + marker, RegionKind.TRIM_START))

  regions.append(TimelineRegion(session_start, session_start + main_duration, RegionKind.PLAY))

  spin_duration = min(spin_sec, main_duration) if spin_sec > 0 else 0.0
  if spin_duration > 0:
    regions[-1] = TimelineRegion(
      session_start + spin_duration,
      session_start + main_duration,
      RegionKind.PLAY,
    )
    regions.insert(
      len(regions) - 1,
      TimelineRegion(session_start, session_start + spin_duration, RegionKind.TAPE_START),
    )

  if fade_sec > 0:
    tail_kind = RegionKind.TAPE_STOP
    if next_transition is not None and not transition_is_solo_tail(next_transition.type):
      tail_kind = RegionKind.CROSSFADE
      regions.append(
        TimelineRegion(
          session_start + main_duration,
          session_start + output_duration,
          tail_kind,
        )
      )
    else:
      if brake_sec > 0:
        regions.append(
          TimelineRegion(
            session_start + main_duration,
            session_start + main_duration + brake_sec,
            RegionKind.TAPE_STOP,
          )
        )
      if silence_sec > 0:
        regions.append(
          TimelineRegion(
            session_start + main_duration + brake_sec,
            session_start + output_duration,
            RegionKind.SILENCE,
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
