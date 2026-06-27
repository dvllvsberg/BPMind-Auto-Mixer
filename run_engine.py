from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
  sys.path.insert(0, str(PROJECT_ROOT))

from engine.analysis.quick_analysis_runner import QuickAnalysisRunner
from engine.analysis.deep_analysis_runner import DeepAnalysisRunner
from engine.database.repository import TrackRepository
from engine.domain.enums import StartMode, TransitionType
from engine.domain.models import Track
from app.mix_settings import resolve_mix_config
from app.paths import default_library_profile_path, exports_dir
from engine.export.session_renderer import SessionExportError, export_session
from engine.library.library_profile import load_library_profile
from engine.mix_generator.recipe_library import recipe_file_stem, validate_recipe_tracks
from engine.mix_generator.session_store import load_mix_recipe, load_mix_session, save_mix_session
from engine.mix_generator.mix_generator import MixGeneratorError
from engine.mix_pipeline import build_mix_session
from engine.playback.play_cli import run_player
from engine.transitions.modes import TransitionMode
from engine.transitions.planner import TransitionPlanConfig
from engine.playback.session_player import SessionPlayer
from engine.scanning.library_scanner import LibraryScanner


def default_db_path() -> Path:
  return PROJECT_ROOT / "cache" / "library.db"


def default_settings_path() -> Path:
  return PROJECT_ROOT / "settings" / "default.json"


def load_settings() -> dict:
  path = default_settings_path()
  if not path.exists():
    return {}
  return json.loads(path.read_text(encoding="utf-8"))


def default_mix_path() -> Path:
  return PROJECT_ROOT / "cache" / "last_mix.json"


def cmd_scan(args: argparse.Namespace) -> int:
  folder = Path(args.folder)
  db_path = Path(args.db) if args.db else default_db_path()

  with TrackRepository(db_path) as repo:
    scanner = LibraryScanner(repo)
    result = scanner.scan(folder)

  print(f"Сканирование: {folder}")
  print(f"База: {db_path}")
  print(f"  Всего файлов: {result.total}")
  print(f"  Добавлено:      {result.added}")
  print(f"  Обновлено:       {result.updated}")
  print(f"  Без изменений:  {result.unchanged}")
  print(f"  Удалено из БД:  {result.removed}")
  return 0


def cmd_list(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1

  with TrackRepository(db_path) as repo:
    tracks = repo.list_all()

  if not tracks:
    print("Библиотека пуста. Сначала выполните scan.")
    return 0

  for track in tracks:
    bpm = f"{track.bpm:.1f}" if track.bpm else "—"
    analysis = track.analysis_level.value
    print(f"[{analysis:5}] {bpm:>6} BPM  {track.artist} — {track.title}")

  print(f"\nВсего: {len(tracks)} треков")
  return 0


def _track_label(track) -> str:
  artist = track.artist.strip()
  title = track.title.strip() or Path(track.path).stem
  if artist:
    return f"{artist} - {title}"
  return title


def _format_trim(analysis: QuickAnalysisResult) -> str:
  if analysis.content_start_sec <= 0 and (
    analysis.content_end_sec is None or analysis.content_end_sec >= analysis.duration - 1
  ):
    return "-"
  end = analysis.content_end_sec if analysis.content_end_sec is not None else analysis.duration
  return f"{analysis.content_start_sec:.0f}-{end:.0f}s"


def cmd_analyze(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1

  if args.plain:
    return _cmd_analyze_plain(db_path, force=args.force)

  from rich.console import Console
  from rich.panel import Panel
  from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn, TimeElapsedColumn
  from rich.table import Table

  console = Console()
  rows: list[tuple[str, str, str, str]] = []

  with TrackRepository(db_path) as repo:
    pending = repo.list_for_quick_analysis(include_analyzed=args.force)
    if not pending:
      console.print("[yellow]Нет треков для анализа. Сначала выполните scan.[/]")
      return 0

    console.print(Panel.fit("[bold]BPMind Auto Mixer[/]  [cyan]быстрый анализ[/]", border_style="blue"))

    with Progress(
      SpinnerColumn(),
      TextColumn("[bold cyan]{task.description}"),
      BarColumn(bar_width=40),
      TaskProgressColumn(),
      TextColumn("•"),
      TimeElapsedColumn(),
      console=console,
      transient=False,
    ) as progress:
      task_id = progress.add_task("Загрузка...", total=len(pending))

      def on_start(track, index: int, total: int) -> None:
        label = _track_label(track)
        short = label if len(label) <= 48 else label[:45] + "..."
        progress.update(task_id, description=f"[{index}/{total}] {short}")

      def on_done(track, analysis, error) -> None:
        label = _track_label(track)
        if error:
          rows.append(("ERR", label, "-", error))
        else:
          assert analysis is not None
          rows.append(("OK", label, f"{analysis.bpm:.1f}", _format_trim(analysis)))
        progress.advance(task_id)

      runner = QuickAnalysisRunner(repo)
      result = runner.run(force=args.force, on_track_start=on_start, on_track_done=on_done)

  table = Table(title="Результаты анализа", show_header=True, header_style="bold magenta")
  table.add_column("#", style="dim", width=4)
  table.add_column("Статус", width=6)
  table.add_column("Трек")
  table.add_column("BPM", justify="right", width=8)
  table.add_column("Trim", width=12)

  for index, (status, label, bpm, trim_or_error) in enumerate(rows, start=1):
    style = "green" if status == "OK" else "red"
    bpm_col = bpm if status == "OK" else "-"
    trim_col = trim_or_error if status == "OK" else trim_or_error[:40]
    table.add_row(str(index), f"[{style}]{status}[/]", label, bpm_col, trim_col)

  console.print()
  console.print(table)
  console.print(
    f"\n[bold]Готово:[/] {result.analyzed} OK, {result.failed} ошибок, всего {result.total}"
  )

  return 1 if result.failed else 0


def _cmd_analyze_plain(db_path: Path, *, force: bool) -> int:
  def on_done(track, analysis, error) -> None:
    label = _track_label(track)
    if error:
      print(f"  Ошибка: {error}")
    else:
      assert analysis is not None
      trim = ""
      if _format_trim(analysis) != "-":
        trim = f"  trim {_format_trim(analysis)}"
      print(f"  OK  {analysis.bpm:>6.1f} BPM  {label}{trim}")

  with TrackRepository(db_path) as repo:
    runner = QuickAnalysisRunner(repo)
    result = runner.run(force=force, on_track_done=on_done)

  print(f"\nБыстрый анализ завершён")
  print(f"  К обработке: {result.total}")
  print(f"  Проанализировано: {result.analyzed}")
  print(f"  Ошибок: {result.failed}")

  if result.total == 0:
    print("  Нет треков для анализа. Сначала выполните scan.")
  elif result.failed:
    return 1

  return 0


def cmd_deep_analyze(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1

  def on_done(track, analysis, error) -> None:
    label = _track_label(track)
    if error:
      print(f"  Ошибка: {error}")
      return
    assert analysis is not None
    print(
      f"  OK  {len(analysis.energy_map):>3} сегм.  "
      f"{len(analysis.transition_candidates):>2} точек  {label}"
    )

  with TrackRepository(db_path) as repo:
    pending = repo.list_for_deep_analysis(include_analyzed=args.force)
    if not pending:
      print("Нет треков для глубокого анализа. Сначала выполните analyze.")
      return 0

    print(f"Глубокий анализ: {len(pending)} треков...")
    runner = DeepAnalysisRunner(repo)
    result = runner.run(force=args.force, on_track_done=on_done)

  print(f"\nГлубокий анализ завершён")
  print(f"  К обработке: {result.total}")
  print(f"  Проанализировано: {result.analyzed}")
  print(f"  Ошибок: {result.failed}")
  return 1 if result.failed else 0


def cmd_mix(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1

  settings = load_settings()
  try:
    start_mode = StartMode(args.mode)
  except ValueError:
    print(f"Неизвестный режим: {args.mode}")
    print("Доступно: random, calm, peak, wave, from_track")
    return 1

  if start_mode == StartMode.FROM_TRACK and args.start_track is None:
    print("Для режима from_track укажите --start-track ID")
    return 1

  config = resolve_mix_config(
    settings,
    load_library_profile(default_library_profile_path()),
    mode=start_mode,
  )
  if args.length is not None:
    config = replace(config, session_length=args.length)
  if args.crossfade is not None:
    config = replace(config, crossfade_duration_sec=args.crossfade)

  try:
    transition_mode = TransitionMode(args.transition_mode)
  except ValueError:
    print(f"Неизвестный режим переходов: {args.transition_mode}")
    print("Доступно: auto, fixed, random")
    return 1

  fixed_profile = TransitionType.SMOOTH_BLEND
  if args.transition:
    try:
      fixed_profile = TransitionType.parse(args.transition)
    except ValueError:
      print(f"Неизвестный профиль перехода: {args.transition}")
      print(
        "Доступно: smooth_blend, filter_sweep, echo_out, bass_swap, impact, "
        "reverse_swell, tape_stop, vinyl_brake, cut"
      )
      return 1

  plan_config = TransitionPlanConfig(
    mode=transition_mode,
    fixed_profile=fixed_profile,
    crossfade_duration_sec=config.crossfade_duration_sec,
    seed=args.transition_seed if args.transition_seed is not None else args.seed,
  )

  with TrackRepository(db_path) as repo:
    tracks = repo.list_mixable()
    track_by_id = {track.id: track for track in tracks if track.id is not None}

    try:
      session = build_mix_session(
        tracks,
        start_mode,
        config,
        start_track_id=args.start_track,
        mix_seed=args.seed,
        transition_mode=transition_mode,
        transition_plan_config=plan_config,
      )
    except MixGeneratorError as exc:
      print(f"Ошибка: {exc}")
      return 1

  output_path = Path(args.output) if args.output else default_mix_path()
  save_mix_session(session, output_path)

  print(f"Mix Session ({session.start_mode.value})")
  print(f"  Треков: {len(session.tracks)}")
  print(f"  Переходы: {transition_mode.value}")
  print(f"  Сохранено: {output_path}")
  print()

  for index, item in enumerate(session.tracks, start=1):
    track = track_by_id.get(item.track_id)
    if track is None:
      continue
    bpm = f"{track.bpm:.1f}" if track.bpm else "—"
    label = f"{track.artist} — {track.title}".strip(" —")
    until = f"{item.play_until_sec:.0f}s" if item.play_until_sec else "полностью"
    transition = next(
      (tr for tr in session.transitions if tr.from_track_id == item.track_id),
      None,
    )
    suffix = f"  [{transition.type.value}]" if transition is not None else ""
    print(f"  {index:>2}. [{bpm:>5} BPM] {label}  -> do {until}{suffix}")

  return 0


def cmd_play(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  mix_path = Path(args.mix) if args.mix else default_mix_path()

  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1
  if not mix_path.exists():
    print(f"Mix Session не найден: {mix_path}")
    print("Сначала выполните: python run_engine.py mix")
    return 1

  session = load_mix_session(mix_path)

  with TrackRepository(db_path) as repo:
    tracks_by_id: dict[int, Track] = {}
    for item in session.tracks:
      if item.track_id in tracks_by_id:
        continue
      track = repo.get_by_id(item.track_id)
      if track is None:
        print(f"Трек не найден в базе: id={item.track_id}")
        return 1
      tracks_by_id[item.track_id] = track

  player = SessionPlayer(session, tracks_by_id)

  print(f"Vosproizvedenie: {mix_path.name} ({session.start_mode.value})")
  try:
    run_player(player, interactive=args.interactive)
  except Exception as exc:
    print(f"Oshibka vosproizvedeniya: {exc}")
    return 1

  return 0


def cmd_export(args: argparse.Namespace) -> int:
  db_path = Path(args.db) if args.db else default_db_path()
  mix_path = Path(args.mix) if args.mix else default_mix_path()

  if not db_path.exists():
    print(f"База не найдена: {db_path}")
    return 1
  if not mix_path.exists():
    print(f"Mix Session не найден: {mix_path}")
    return 1

  session, metadata = load_mix_recipe(mix_path)

  if args.output:
    output_path = Path(args.output)
  else:
    exports_dir().mkdir(parents=True, exist_ok=True)
    stem = recipe_file_stem(metadata.name) if metadata.name else f"bpmind_{session.start_mode.value}"
    ext = ".mp3" if args.format == "mp3" else ".wav"
    output_path = exports_dir() / f"{stem}{ext}"

  with TrackRepository(db_path) as repo:
    tracks_by_id: dict[int, Track] = {}
    for item in session.tracks:
      track = repo.get_by_id(item.track_id)
      if track is None:
        print(f"Трек не найден в базе: id={item.track_id}")
        return 1
      tracks_by_id[item.track_id] = track

    problems = validate_recipe_tracks(session, repo)
    if problems:
      print("Экспорт невозможен:")
      for problem in problems:
        print(f"  - {problem}")
      return 1

    def on_progress(index: int, total: int, label: str) -> None:
      print(f"Рендер [{index}/{total}]: {label}")

    try:
      duration_sec = export_session(
        session,
        tracks_by_id,
        output_path,
        on_progress=on_progress,
        bitrate_kbps=args.bitrate,
      )
    except SessionExportError as exc:
      print(f"Ошибка: {exc}")
      return 1

  print(f"Экспорт готов: {output_path}")
  print(f"Длительность: {duration_sec / 60:.1f} мин ({duration_sec:.1f} с)")
  return 0


def cmd_export_wav(args: argparse.Namespace) -> int:
  args.format = "wav"
  return cmd_export(args)


def main() -> int:
  parser = argparse.ArgumentParser(description="BPMind Auto Mixer — engine CLI")
  parser.add_argument("--db", help="Путь к SQLite базе (по умолчанию cache/library.db)")

  sub = parser.add_subparsers(dest="command", required=True)

  scan_parser = sub.add_parser("scan", help="Сканировать папку с музыкой")
  scan_parser.add_argument("folder", help="Путь к папке")
  scan_parser.set_defaults(func=cmd_scan)

  list_parser = sub.add_parser("list", help="Показать треки в базе")
  list_parser.set_defaults(func=cmd_list)

  analyze_parser = sub.add_parser("analyze", help="Быстрый анализ: BPM, громкость, длительность")
  analyze_parser.add_argument(
    "--force",
    action="store_true",
    help="Переанализировать все треки, не только новые",
  )
  analyze_parser.add_argument(
    "--plain",
    action="store_true",
    help="Простой вывод без progress bar",
  )
  analyze_parser.set_defaults(func=cmd_analyze)

  deep_parser = sub.add_parser(
    "deep-analyze",
    help="Глубокий анализ: энергия, точки перехода, groove-профиль",
  )
  deep_parser.add_argument(
    "--force",
    action="store_true",
    help="Пересчитать deep даже для уже проанализированных треков",
  )
  deep_parser.set_defaults(func=cmd_deep_analyze)

  mix_parser = sub.add_parser("mix", help="Построить Mix Session")
  mix_parser.add_argument(
    "--mode",
    default="calm",
    choices=["random", "calm", "peak", "wave", "from_track"],
    help="Режим запуска (по умолчанию: calm)",
  )
  mix_parser.add_argument("--start-track", type=int, help="ID стартового трека для from_track")
  mix_parser.add_argument("--length", type=int, help="Длина сессии в треках")
  mix_parser.add_argument("--crossfade", type=float, help="Длительность crossfade в секундах")
  mix_parser.add_argument("--seed", type=int, help="Seed для воспроизводимости random (микс и random-переходы)")
  mix_parser.add_argument(
    "--transition-mode",
    default="auto",
    choices=["auto", "fixed", "random"],
    help="Режим выбора переходов (по умолчанию: auto)",
  )
  mix_parser.add_argument(
    "--transition",
    help="Профиль для fixed: smooth_blend, filter_sweep, echo_out, bass_swap, impact, "
    "tape_stop, vinyl_brake, reverse_swell, cut",
  )
  mix_parser.add_argument(
    "--transition-seed",
    type=int,
    help="Seed только для random-переходов (иначе --seed)",
  )
  mix_parser.add_argument("--output", help="Путь для сохранения mix JSON")
  mix_parser.set_defaults(func=cmd_mix)

  play_parser = sub.add_parser("play", help="Vosproizvesti Mix Session")
  play_parser.add_argument("--mix", help="Put k mix JSON (po umolchaniyu cache/last_mix.json)")
  play_parser.add_argument(
    "-i",
    "--interactive",
    action="store_true",
    help="Upravlenie s klaviatury: probel, N, P, Q",
  )
  play_parser.set_defaults(func=cmd_play)

  export_parser = sub.add_parser("export", help="Срендерить микс в WAV или MP3")
  export_parser.add_argument("--mix", help="Путь к рецепту JSON (по умолчанию cache/last_mix.json)")
  export_parser.add_argument("--output", help="Путь к выходному файлу (.wav или .mp3)")
  export_parser.add_argument(
    "--format",
    choices=["wav", "mp3"],
    default="mp3",
    help="Формат, если --output не задан (по умолчанию: mp3)",
  )
  export_parser.add_argument(
    "--bitrate",
    type=int,
    default=320,
    help="Битрейт MP3 в kbps (по умолчанию: 320)",
  )
  export_parser.set_defaults(func=cmd_export)

  export_wav_parser = sub.add_parser("export-wav", help="Срендерить микс в WAV (алиас export --format wav)")
  export_wav_parser.add_argument("--mix", help="Путь к рецепту JSON (по умолчанию cache/last_mix.json)")
  export_wav_parser.add_argument("--output", help="Путь к выходному WAV")
  export_wav_parser.set_defaults(func=cmd_export_wav)

  args = parser.parse_args()
  return args.func(args)


if __name__ == "__main__":
  raise SystemExit(main())
