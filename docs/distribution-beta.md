# Beta-сборка для тестировщиков (Windows)

Первая публичная beta: **установщик** + **portable zip**. Данные пользователя не смешиваются с Program Files.

## Что скачивать

| Файл | Кому |
|------|------|
| `BPMind-Auto-Mixer-Windows-setup-X.Y.Z.exe` | Обычные пользователи — установка в меню Пуск |
| `BPMind-Auto-Mixer-Windows-portable.zip` | Продвинутые / без прав админа — распаковать куда угодно |

Оба варианта на [Releases](https://github.com/dvllvsberg/BPMind-Auto-Mixer/releases). Для beta ищите тег `v*-beta*`.

## Где лежат данные

| Режим | Папка |
|-------|--------|
| **Установщик** | `%LOCALAPPDATA%\BPMind Auto Mixer\` (`cache`, `mixes`, `exports`, `settings`) |
| **Portable** | Рядом с `BPMind Auto Mixer.exe` (файл-маркер `portable.flag`) |

При первом запуске установленной версии данные из старой папки рядом с exe (если были) копируются в AppData один раз.

Принудительно portable в любой сборке: переменная окружения `BPMIND_PORTABLE=1`.

## Сборка релиза (разработчик)

```powershell
pip install -r requirements.txt -r requirements-build.txt
# Inno Setup 6: https://jrsoftware.org/isinfo.php
.\packaging\build_release.ps1 -Version 1.8.0-beta.1
```

С подписью (если есть `.pfx`):

```powershell
$env:WINDOWS_SIGN_PFX_PATH = "C:\path\bpmind.pfx"
$env:WINDOWS_SIGN_PFX_PASSWORD = "..."
.\packaging\build_release.ps1 -Version 1.8.0-beta.1 -Sign
```

## Цифровая подпись и SmartScreen

Без подписи Windows покажет **«Неизвестный издатель»** / SmartScreen — для beta это нормально. Тестировщикам:

1. «Подробнее» → «Выполнить в любом случае», или  
2. ПКМ → Свойства → Разблокировать (для zip), или  
3. Portable zip вместо setup.

### Как получить подпись (продакшен)

1. **Код-подписывающий сертификат** (OV или EV) у DigiCert, Sectigo, SSL.com и т.д.  
   - OV: дешевле, SmartScreen доверие набирается после многих загрузок.  
   - EV: сразу лучше для SmartScreen, нужен USB-токен.

2. Экспорт `.pfx` + пароль → секреты репозитория:
   - `WINDOWS_SIGN_PFX_B64` — base64 файла pfx  
   - `WINDOWS_SIGN_PFX_PASSWORD`

3. CI на push тега вызывает `packaging/sign_windows.ps1` (нужен Windows SDK / signtool в runner).

Локально: Windows SDK → `signtool sign /fd SHA256 /tr http://timestamp.digicert.com /td SHA256 /f cert.pfx /p pass file.exe`

## CI (GitHub Actions)

Workflow `.github/workflows/release.yml` на тег `v*`:

1. pytest  
2. PyInstaller  
3. Inno Setup → `setup.exe` (без `portable.flag`)  
4. `portable.flag` → zip  
5. Опциональная подпись, если заданы secrets  
6. Публикация обоих артефактов в Release  

## Чеклист перед beta для людей

- [ ] Тег `v1.8.0-beta.1` (или следующий)  
- [ ] Оба артефакта в Release  
- [ ] Краткая инструкция в описании релиза (папка с музыкой → скан → микс)  
- [ ] Упомянуть SmartScreen / portable  
- [ ] Собрать feedback (Issues / Discord / форма)  

## Удаление

**Установщик:** Параметры → Приложения → BPMind Auto Mixer. При удалении можно согласиться удалить данные из AppData.

**Portable:** Удалить папку с программой.
