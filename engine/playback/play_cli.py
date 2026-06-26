from __future__ import annotations

import sys
import time

from engine.playback.session_player import NowPlaying, PlayerState, SessionPlayer


def _track_label(now: NowPlaying) -> str:
  label = f"{now.track.artist} - {now.track.title}".strip(" -")
  bpm = f"{now.track.bpm:.1f}" if now.track.bpm else "?"
  return f"[{now.index}/{now.total}] {bpm} BPM  {label}"


def _print_track_if_changed(player: SessionPlayer, last_index: int | None) -> int | None:
  now = player.now_playing()
  if now and now.index != last_index:
    print(_track_label(now))
    return now.index
  return last_index


def run_interactive_player(player: SessionPlayer) -> None:
  import msvcrt

  print("Upravlenie: probel = pauza, N = sled., P = pred., Q = vyhod")
  player.play()
  last_index: int | None = None

  while True:
    last_index = _print_track_if_changed(player, last_index)

    if msvcrt.kbhit():
      key = msvcrt.getch()
      try:
        char = key.decode("utf-8").lower()
      except UnicodeDecodeError:
        char = ""

      if char == " ":
        state = player.toggle_pause()
        print("PAUZA" if state == PlayerState.PAUSED else "IGRAET")
      elif char == "n":
        if not player.next_track():
          print("KONEC SETA")
          break
        last_index = None
      elif char == "p":
        player.previous_track()
        last_index = None
      elif char == "q":
        player.stop()
        print("STOP")
        break

    if player.state == PlayerState.STOPPED:
      break

    time.sleep(0.05)

  player.wait_until_finished()


def run_simple_player(player: SessionPlayer) -> None:
  player.play()
  last_index: int | None = None

  while player.state != PlayerState.STOPPED:
    last_index = _print_track_if_changed(player, last_index)
    time.sleep(0.2)

  player.wait_until_finished()
  print("KONEC SETA")


def run_player(player: SessionPlayer, *, interactive: bool) -> None:
  if interactive and sys.platform == "win32":
    run_interactive_player(player)
  elif interactive:
    print("Interaktivnyj rezhim dostupen tolko v Windows. Zapusk bez klaviatury...")
    run_simple_player(player)
  else:
    run_simple_player(player)
