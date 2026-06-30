# BPMind Auto Mixer

Локальный авто-миксер для своей музыкальной библиотеки: анализ треков, сбор сета с переходами, воспроизведение и экспорт в WAV/MP3.

Репозиторий: [github.com/dvllvsberg/BPMind-Auto-Mixer](https://github.com/dvllvsberg/BPMind-Auto-Mixer)

## Скачать (Windows)

Сборки на [Releases](https://github.com/dvllvsberg/BPMind-Auto-Mixer/releases).

| Вариант | Файл | Данные |
|---------|------|--------|
| **Установщик** (рекомендуется) | `BPMind-Auto-Mixer-Windows-setup-*.exe` | `%LOCALAPPDATA%\BPMind Auto Mixer\` |
| **Portable** | `BPMind-Auto-Mixer-Windows-portable.zip` | рядом с exe |

1. Скачайте setup или zip из последнего релиза (для тестов — тег `*-beta*`).
2. Setup: запустите установщик. Portable: распакуйте в любую папку.
3. Запустите **BPMind Auto Mixer** из меню Пуск или `BPMind Auto Mixer.exe`.

Windows может показать SmartScreen для неподписанной сборки — «Подробнее» → «Выполнить в любом случае». Подробнее: [docs/distribution-beta.md](docs/distribution-beta.md).

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

### Сборка релиза (portable + setup)

```powershell
pip install -r requirements.txt -r requirements-build.txt
# Inno Setup 6: https://jrsoftware.org/isinfo.php
.\packaging\build_release.ps1 -Version 1.8.0-beta.1
```

См. [docs/distribution-beta.md](docs/distribution-beta.md) — подпись, CI, чеклист beta.

### Сборка portable exe (только PyInstaller)

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

## Документация

- [Roadmap и статус требований](docs/ROADMAP.md)
- [Beta-сборки и установщик](docs/distribution-beta.md)
- [Transition Engine (TEA)](docs/transition-engine.md)

## Тесты

```powershell
pytest tests/
```

## Лицензия

Пока без лицензии — личный проект. При публикации можно добавить MIT.
