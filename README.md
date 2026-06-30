# BPMind Auto Mixer

Локальный авто-миксер для своей музыкальной библиотеки: анализ треков, сбор сета с переходами, воспроизведение и экспорт в WAV/MP3.

Репозиторий: [github.com/dvllvsberg/BPMind-Auto-Mixer](https://github.com/dvllvsberg/BPMind-Auto-Mixer)

## Скачать (Windows)

**Не нужен Python и PowerShell** — только распаковать и запустить.

1. Откройте [Releases](https://github.com/dvllvsberg/BPMind-Auto-Mixer/releases)
2. Скачайте **`BPMind-Auto-Mixer-Windows-portable.zip`** из последнего релиза
3. Распакуйте архив в любую папку (например `D:\Apps\BPMind`)
4. Запустите **`BPMind Auto Mixer.exe`**

При первом запуске рядом с exe создаются папки `cache/`, `mixes/`, `exports/`, `settings/`.

### Быстрый сценарий

1. Нажмите иконку **папки** → выберите каталог с музыкой
2. **Сканировать и анализировать**
3. Режим (calm / peak / wave / random) → **Построить микс**
4. **▶** в плеере

Параметры микса и переходов — в **⚙ Настройки** (шестерёнка).

| Действие | Описание |
|----------|----------|
| **Сохранить сет** | Рецепт в `mixes/` |
| **Открыть сет** | Загрузить рецепт с диска |
| **Экспорт аудио** | MP3 или WAV в `exports/` |

## Требования

- Windows 10/11 (x64)
- Аудиофайлы: MP3, FLAC, WAV и другие форматы, которые читает движок (`soundfile` / `librosa`)

## Разработка из исходников

Нужен Python 3.11+ (в CI и сборке — 3.12).

```powershell
cd "BPMind Auto Mixer"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy settings\default.json.example settings\default.json
python run_app.py
```

### Сборка portable exe (локально)

```powershell
pip install -r requirements.txt -r requirements-build.txt
pyinstaller packaging/bpmind.spec --noconfirm
```

Готовая папка: `dist/BPMind Auto Mixer/BPMind Auto Mixer.exe`

## CLI

```powershell
python run_engine.py scan "D:/Music"
python run_engine.py analyze
python run_engine.py deep-analyze
python run_engine.py mix --mode wave
python run_engine.py play
python run_engine.py export --format mp3
```

## Режимы микса

| Режим | Суть |
|-------|------|
| **calm** | Спокойная дуга энергии, длиннее фрагменты треков |
| **peak** | Ближе к пику громкости, сильнее groove-пары |
| **wave** | Синусоидальная волна: тихо → пик в середине → тихий финал |
| **random** | Без целевой дуги, умный скоринг BPM/groove |
| **from_track** | Сет с выбранного трека |

## Структура проекта

```
app/          # GUI (PySide6)
engine/       # анализ, генерация микса, плеер, экспорт
packaging/    # PyInstaller spec
cache/        # SQLite-библиотека, последний микс (локально)
mixes/        # сохранённые рецепты
exports/      # экспортированные WAV/MP3
settings/     # настройки пользователя
tests/        # pytest
docs/         # архитектура (Transition Engine и др.)
```

Подробнее о движке переходов: [docs/transition-engine.md](docs/transition-engine.md).

## Тесты

```powershell
pytest tests/
```

## Лицензия

Пока без лицензии — личный проект. При публикации можно добавить MIT.
