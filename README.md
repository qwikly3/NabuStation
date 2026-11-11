# NabuStation 1.0

Голосовой ассистент для **root-станции Яндекс Станция 1**: Debian-режим
(микрофонный массив, wake word «Окей Набу», AEC, Home Assistant Assist,
Music Assistant, Spotify, громкость) и Android TV-режим (TV Launcher,
Now Playing, SmartTube, Snapcast, телефонный пульт).

Проект модульный. Можно поставить только голосового ассистента в HA, без
Spotify и даже без музыки. Можно добавить музыку, громкость, LED-кольцо,
физический диск, кнопку, Android TV/визуализатор и пульт.

> Версия: **1.0.0**
>
> Статус: первый публичный релиз. Проверено на Station 1 с Debian,
> Home Assistant 2026.7, Music Assistant server и Spotify Premium/Soloist.

---

## Содержание

- [Что умеет](#что-умеет)
- [Архитектура](#архитектура)
- [Модули](#модули)
- [Требования](#требования)
- [Быстрый старт: полная установка](#быстрый-старт-полная-установка)
- [Установка по шагам](#установка-по-шагам)
  - [1. Станция: Debian, SSH, ALSA](#1-станция-debian-ssh-alsa)
  - [2. Station-модуль](#2-station-модуль)
  - [3. Silero TTS](#3-silero-tts)
  - [4. Voice server](#4-voice-server)
  - [5. Home Assistant](#5-home-assistant)
  - [6. Music Assistant и Snapcast](#6-music-assistant-и-snapcast)
  - [7. Spotify и like/unlike](#7-spotify-и-likeunlike)
- [Android TV-режим](#android-tv-режим)
- [Только ассистент, без Spotify](#только-ассистент-без-spotify)
- [Конфигурация](#конфигурация)
- [Голосовые команды](#голосовые-команды)
- [Как это работает](#как-это-работает)
- [Диагностика](#диагностика)
- [Безопасность](#безопасность)
- [Обновление и удаление](#обновление-и-удаление)
- [Ограничения версии 1.0](#ограничения-версии-10)
- [Благодарности](#благодарности)
- [Лицензия](#лицензия)

---

## Что умеет

- Wake word **«Окей Набу»** на самой станции (openWakeWord, модель
  `okay_nabu`), без облака для детекции.
- 5-канальный TDM-захват микрофонов Station 1.
- AEC: **SpeexDSP** с адаптивным фильтром, high-pass 100 Гц и подавлением
  остаточного эха. Reference — `ch4` (оба тапа усилителя), микрофоны —
  `ch1-3`.
- Отправка фразы в **Home Assistant Assist** (STT + intent + TTS).
- Локальный TTS **Silero** (Docker, русские голоса).
- Музыка через **Music Assistant + Snapcast**; станция — обычный
  Snapcast-клиент.
- Голосом: пауза, продолжить, дальше, назад, перемешать, что за трек.
- Spotify: поставить/убрать лайк, включить Liked Songs.
- Громкость: HTTP-сервис на станции, физический диск, голосовые команды.
- LED-кольцо и кнопка Алисы (опционально).
- **Android TV-режим:** TV Launcher (Projectivy опционально), Now Playing, SmartTube 32.68,
  Snapcast, RemoteDaemon, телефонный пульт и веб-пульт.
- Всё ставится модулями: можно отказаться от Spotify, музыки, громкости
  или Android-режима.

---

## Архитектура

```
┌──────────────────────────────┐
│ Station 1 (Debian, root)     │
│                              │
│  arecord 5ch ──TCP 8091──┐   │
│  aplay     ◄──TCP 8092───┤   │
│  LED ring  ◄──TCP 8093───┤   │
│  button    ◄──TCP 8095───┤   │
│  volume    ◄──HTTP 8098──┤   │
│  snapclient ──TCP 1704───┼───┼──► Music Assistant / Snapserver
└──────────────────────────────┘   │
                                   │
┌──────────────────────────────┐   │
│ Voice server (Linux, systemd)│   │
│  wake word + AEC + pipeline  │◄──┘
│  Silero TTS :10400           │
└──────────────┬───────────────┘
               │ WebSocket/HTTP
┌──────────────▼───────────────┐
│ Home Assistant               │
│  Assist pipeline             │
│  custom intents / scripts    │
│  Music Assistant integration │
└──────────────────────────────┘
```

Важно: **voice server** — это отдельный процесс на Linux-хосте, а не
аддон HA. Он подключается к HA по WebSocket и к станции по TCP. На HA OS
удобнее поставить его на отдельный Linux-сервер (или на хост Supervised,
где есть systemd и Docker).

В **Android TV-режиме** станция загружается в Android: те же порты
8091-8093/8095 для mic/TTS/LED/кнопки, плюс visualizer `:8099`,
RemoteDaemon `:8096`, touchpad `:8097` и веб-пульт `:8080`. Голосовой
сервер и HA остаются на HA-хосте.

---

## Модули

| Модуль | Что даёт | Можно не ставить |
|---|---|---|
| `station/` | mic/play/LED/button/dial/volume + runit | если станция в Android-режиме |
| `voice-server/` | wake word, AEC, Assist, TTS-плеер | если не нужен голос |
| `silero-tts/` | локальный русский TTS | если используете другой TTS |
| `home-assistant/packages/nabustation_helpers.yaml` | helper-сущности | только если не нужен now playing/музыка |
| `home-assistant/packages/nabustation_core.yaml` | pause/resume/next/prev/shuffle/now playing | если не нужна музыка |
| `home-assistant/packages/nabustation_volume.yaml` | громкость через HTTP станции | если нет Debian-громкости |
| `home-assistant/packages/nabustation_spotify.yaml` | «включи музыку», like/unlike | если нет Spotify |
| `home-assistant/custom_sentences/ru/*` | русские фразы | если другой язык |
| `music-assistant/` | MA/Snapcast + Spotify + patch | если нет музыки/Spotify |
| `android/` | Android TV: launcher, Now Playing, SmartTube, Snapcast, RemoteDaemon, phone remote | если станция в Debian-режиме |

Минимальный набор для «только ассистент»:

```
station/ + voice-server/ + silero-tts/ + HA Assist pipeline
```

Минимальный набор для «ассистент + музыка без Spotify»:

```
station/ + voice-server/ + silero-tts/ + helpers + core + MA/Snapcast
```

Полный набор:

```
всё + volume + spotify + music-assistant patch + android/ (если нужен TV-режим)
```

---

## Требования

### Станция

- Root-доступ и **Debian rootfs** на Station 1 (не Android).
- SSH root (ключ или пароль; в репозитории секретов нет).
- Ядро/DTS с TDM-захватом 5 каналов (Station 1: `plughw:2,0`).
- `alsa-utils`, `python3`, `netcat`, `runit`, `snapclient` (ставит
  `station/install.sh`).
- Звуковая карта усилителя — card 1 (`Subwoofer Master`,
  `Tweeters Master`), микрофоны — card 2. Проверьте `aplay -l` и
  `arecord -l`; при других номерах задайте `AMP_CARD`/`MIC_CARD`/
  `MIC_DEVICE` в `/etc/nabustation/station.env`.

### Android TV-режим (опционально)

- Станция, загруженная в **Android 6**, с root и ADB.
- `adb` на ПК, `busybox-smp` на станции.
- HA-хост с visualizer (`android/visualizer/`), если нужен Now Playing
  и медиа-панель пульта.
- Телефон на той же LAN для Station Remote.

### Хост voice server

- Linux с systemd (Supervised/Core или отдельный сервер).
- Python 3.11+ и `python3-venv`.
- `libspeexdsp1` (Debian/Ubuntu: `sudo apt install libspeexdsp1`).
- Docker + Compose (для Silero TTS) — либо свой HTTP TTS с интерфейсом
  `GET /tts?text=...&speaker=...&sr=...`.
  Официальный `silero-tts` образ рассчитан на x86_64; на ARM нужен другой
  TTS-сервер с тем же интерфейсом.
- Сеть до станции (порты 8091-8093, 8095, 8098) и до HA (8123).

### Home Assistant

- HA 2024.8+ (проверено на 2026.7; используется современный ключ `action:`).
- Пайплайн Assist с русским STT/TTS.
- Music Assistant integration (для музыки).
- `music_assistant_client` в окружении HA (обычно уже есть с интеграцией
  MA; для Core venv — `pip install music-assistant-client aiohttp`).

### Music Assistant / Spotify

- MA server (аддон или контейнер) + Snapcast provider.
- Spotify Premium и провайдер Spotify с playback backend **Soloist**.
- Никаких librespot/spotifyd/локальных Spotify-клиентов на станции.

---

## Быстрый старт: полная установка

Все примеры используют `<STATION_IP>` и `<HA_IP>`. Замените их на свои.

```bash
# 1. На station (root)
scp -r NabuStation root@<STATION_IP>:/root/
ssh root@<STATION_IP>
cd /root/NabuStation
SNAPCAST_HOST=<HA_IP> ./station/install.sh

# 2. На HA-хосте (обычный пользователь)
cd NabuStation
STATION_HOST=<STATION_IP> HA_HOST=127.0.0.1 ./voice-server/install.sh

# 3. Silero TTS (на HA-хосте, Docker)
cd NabuStation/silero-tts
docker compose up -d --build

# 4. HA packages
#    скопируйте нужные файлы в /config/packages и custom_sentences/ru
#    см. home-assistant/install.md

# 5. Music Assistant
#    добавьте Snapcast + Spotify (Soloist), см. music-assistant/README.md

# 6. Проверка
STATION_HOST=<STATION_IP> HA_HOST=<HA_IP> ./tools/doctor.sh
```

---

## Установка по шагам

### 1. Станция: Debian, SSH, ALSA

Этот репозиторий **не содержит rootfs**. Предполагается, что станция уже
загружается в Debian и вы можете войти по SSH как root. Если это не так,
сначала установите Debian rootfs и ядро с поддержкой TDM-микрофонов.

Проверьте звук:

```bash
aplay -l
arecord -l
```

Ожидаемая картина Station 1:

- card 1 — усилитель TAS5751M (`Subwoofer Master`, `Tweeters Master`);
- card 2 — 5 x TLV320ADC3101, TDM capture.

Проверьте микрофон (5 каналов, 16 кГц):

```bash
arecord -D plughw:2,0 -f S16_LE -r 16000 -c 5 -t raw /tmp/test.raw
ls -l /tmp/test.raw
```

Если card 2/устройство другое, задайте `MIC_CARD`/`MIC_DEVICE` при
установке.

Поставьте SSH-ключ и **смените root-пароль** — станция не должна висеть
в сети с дефолтным паролем.

### 2. Station-модуль

На станции:

```bash
cd /root/NabuStation
SNAPCAST_HOST=<HA_IP> ./station/install.sh
```

Что делает скрипт:

- ставит `alsa-utils`, `python3`, `netcat-openbsd`, `runit`, `snapclient`;
- копирует `mic.sh`, `play.sh`, `led.sh`, `start.sh`, `watch.sh`,
  `button.py`, `dial.py`, `volume_server.py` в `/root/voice`;
- ставит `/etc/asound.conf` с dmix `default` для микса музыки и TTS
  (если файла нет; перезапись — `--force-asound`);
- создаёт `/etc/nabustation/station.env`;
- ставит runit-сервисы `voice`, `voice-watch`, `volume`, `snapclient`;
- запускает их.

Опции:

```bash
./station/install.sh --no-snapclient   # без музыки/Snapcast
./station/install.sh --force-env       # перезаписать station.env
./station/install.sh --force-asound    # перезаписать /etc/asound.conf
```

Проверка:

```bash
sv status voice volume voice-watch snapclient
curl http://127.0.0.1:8098/health
# {"ok": true, "mode": "debian", "level": 5, "amp": 375}
```

Порты станции:

| Порт | Назначение |
|---|---|
| 8091 | микрофонный поток (станция слушает) |
| 8092 | приём WAV для TTS |
| 8093 | LED-команды |
| 8095 | кнопка Алисы |
| 8098 | HTTP-громкость |

Если порт 8098 не отвечает:

```bash
tail -n 50 /root/voice/health.log
sv restart volume
```

### 3. Silero TTS

На HA-хосте с Docker:

```bash
cd NabuStation/silero-tts
docker compose up -d --build
```

Первый запуск скачивает модель Silero (интернет нужен один раз) и
занимает несколько минут. Проверка:

```bash
curl http://127.0.0.1:10400/health
# {"ready":true}

curl 'http://127.0.0.1:10400/tts?text=привет&speaker=eugene&sr=48000' \
  -o /tmp/tts.wav
file /tmp/tts.wav
```

Голоса: `aidar`, `baya`, `kseniya`, `xenia`, `eugene`. Voice server по
умолчанию использует `eugene`; можно поменять `SILERO_VOICE` в
`voice.env`.

Если Docker недоступен, поставьте любой TTS с HTTP-интерфейсом
`GET /tts?text=...&speaker=...&sr=...` и укажите `SILERO_URL`.

### 4. Voice server

На HA-хосте (не root, от пользователя, который будет владельцем сервиса):

```bash
cd NabuStation
STATION_HOST=<STATION_IP> HA_HOST=127.0.0.1 ./voice-server/install.sh
```

Скрипт:

- создаёт `~/nabustation/voice` и venv;
- ставит Python-зависимости;
- копирует `station_voice.py`, `speex_aec.py`, `aec.py`;
- спрашивает HA long-lived token; пишет `ha_token.txt` с `chmod 600`;
- создаёт `voice.env`;
- ставит и запускает `systemd --user` сервис
  `station-voice.service`.

Токен: HA -> профиль -> Security -> Long-lived access tokens.

Проверка:

```bash
systemctl --user status station-voice.service
journalctl --user -u station-voice.service -f
```

В логе должно быть:

```
AEC: SpeexDSP (adaptive, double-talk)
pipeline: <id>
mic format: 5 channel(s)
station volume set to 5%
mic connected to <STATION_IP>:8091
```

Если сервис останавливается после выхода из SSH:

```bash
sudo loginctl enable-linger $USER
```

Если `libspeexdsp1` не установлен, будет предупреждение и fallback на FIR
AEC (хуже). Установите:

```bash
sudo apt install libspeexdsp1
```

### 5. Home Assistant

Подробно: [`home-assistant/install.md`](home-assistant/install.md).

Кратко:

1. В `/config/configuration.yaml` добавьте:

   ```yaml
   homeassistant:
     packages: !include_dir_named packages
   ```

2. Скопируйте нужные пакеты:

   ```bash
   mkdir -p /config/packages
   cp home-assistant/packages/nabustation_helpers.yaml /config/packages/
   cp home-assistant/packages/nabustation_core.yaml /config/packages/
   # опционально:
   cp home-assistant/packages/nabustation_volume.yaml /config/packages/
   cp home-assistant/packages/nabustation_spotify.yaml /config/packages/
   ```

3. Скопируйте фразы:

   ```bash
   mkdir -p /config/custom_sentences/ru
   cp home-assistant/custom_sentences/ru/music_core.yaml /config/custom_sentences/ru/
   # опционально:
   cp home-assistant/custom_sentences/ru/volume.yaml /config/custom_sentences/ru/
   cp home-assistant/custom_sentences/ru/music_spotify.yaml /config/custom_sentences/ru/
   ```

4. Для Spotify:

   ```bash
   mkdir -p /config/scripts
   cp home-assistant/scripts/music_like.py /config/scripts/
   cp home-assistant/nabustation.json.example /config/nabustation.json
   ```

5. Перезапустите HA:

   ```bash
   ha core restart
   ```

6. Заполните helpers (Settings -> Devices & services -> Helpers):

   - `input_text.nabustation_media_player` — ваш MA media_player;
   - `input_text.nabustation_station_host` — IP станции;
   - `input_text.nabustation_liked_playlist` — URI Liked Songs (Spotify).

7. Включите `prefer_local_intents` в пайплайне Assist, чтобы фразы
   обрабатывались локально, без LLM.

Проверка без голоса: Developer Tools -> Actions -> `conversation.process`:

```yaml
text: "что за трек"
language: ru
agent_id: conversation.home_assistant
```

Ожидаемый ответ: `Исполнитель: ... Песня: ...`.

### 6. Music Assistant и Snapcast

Подробно: [`music-assistant/README.md`](music-assistant/README.md).

1. Установите MA (аддон/контейнер), добавьте Snapcast player provider.
2. На станции уже стоит `snapclient` (если не отключали).
3. В MA появится плеер станции. Поставьте:
   - MA volume = 100%;
   - Snapcast client volume = 100%;
   - громкость — только на станции (8098).
4. Если хотите сохранить тот же MA-плеер, что был в Android, задайте
   `STATION_HOST_ID` (Android hostID) в `/etc/nabustation/station.env` и
   перезапустите `snapclient`.
5. Проверьте: `media_player.play_media` в HA -> станция играет;
   `media_pause` -> пауза.

Почему 100% в MA: иначе громкость применяется дважды (MA и усилитель), и
станция играет тише, чем ожидается. Усилитель — единственный регулятор.

### 7. Spotify и like/unlike

1. В MA добавьте Spotify provider, войдите в аккаунт, выберите playback
   backend **Soloist**. Spotify Premium обязателен.
2. Найдите URI Liked Songs:

   ```bash
   docker exec homeassistant mkdir -p /config/scripts
   docker cp tools/discover_ma.py homeassistant:/config/scripts/
   docker exec -it homeassistant python /config/scripts/discover_ma.py
   ```

   Ищите плейлист `Liked Songs ...` с provider
   `liked_songs-spotify--...`. Скопируйте `uri` в
   `input_text.nabustation_liked_playlist`.

3. Поставьте пакет `nabustation_spotify.yaml`, фразы
   `music_spotify.yaml`, скрипт `music_like.py`.

4. Примените patch в контейнере MA:

   ```bash
   docker cp music-assistant/patch_spotify_like.py \
     music-assistant:/data/patch_spotify_like.py
   docker exec -i music-assistant python /data/patch_spotify_like.py
   docker restart music-assistant
   ```

5. Проверьте голосом: «поставь лайк», «убери лайк».

Если MA обновился, patch нужно применить заново. Скрипт идемпотентный и
делает backup `/data/provider.py.bak-spotify-like`.

---

## Android TV-режим

Android-модуль — это второй режим станции: TV Launcher, Now Playing,
SmartTube 32.68, Snapcast, RemoteDaemon, телефонный пульт и веб-пульт.
Он не заменяет Debian-голос, а дополняет его, если станция умеет
загружаться в Android.

Полная инструкция: [`android/README.md`](android/README.md).

APK лежат в GitHub Releases, не в git. Скачать их:

```bash
./android/scripts/fetch_apks.sh
```

Release: **https://github.com/qwikly3/NabuStation/releases/tag/v1.0.0**

Кратко, на станции в Android с root/ADB:

```bash
SNAPCAST_HOST=<HA_IP> HA_HOST=<HA_IP> \
  ./android/scripts/install.sh
```

На HA-хосте:

```bash
cd android/visualizer
HA_TOKEN_FILE=$HOME/nabustation/voice/ha_token.txt \
PLAYER_ENTITY=media_player.station_1 \
  ./install.sh
```

Телефонный пульт: `http://<STATION_IP>:8080/station-remote-modes.apk`.
В приложении **SET** задайте IP станции и IP visualizer/HA.

Если HA-хост не `192.168.1.20`, пропатчьте Now Playing APK:

```bash
cd android/nowplaying
ANDROID_HOME=/path/to/sdk python patch_host.py --host <13-char-ha-ip>
```

## Только ассистент, без Spotify

Не копируйте `nabustation_spotify.yaml` и `music_spotify.yaml`.
Не применяйте MA patch. Всё остальное работает.

Если не нужна и музыка:

- не ставьте `snapclient` (`./station/install.sh --no-snapclient`);
- не копируйте `nabustation_core.yaml`, `music_core.yaml` и helpers;
- voice server всё равно работает: он просто не будет pause/resume
  музыки (проверяет доступность `MUSIC_ENTITY`).

Если нужна музыка, но не Spotify:

- MA + Snapcast + любой провайдер (локальная библиотека, радио и т.п.);
- `nabustation_core.yaml` + `music_core.yaml`;
- «включи музыку»/like/unlike не будут работать, это нормально.

Если нужна только громкость:

- `station/install.sh` (volume service);
- `nabustation_helpers.yaml` + `nabustation_volume.yaml` + `volume.yaml`;
- голосовой сервер не обязателен, громкость можно дергать из HA.

---

## Конфигурация

### `/etc/nabustation/station.env` (станция)

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `SNAPCAST_HOST` | — | IP MA/Snapserver |
| `SNAPCAST_PORT` | `1704` | порт Snapserver |
| `STATION_HOST_ID` | пусто | hostID для совместимости с Android-плеером |
| `AMP_CARD` | `1` | ALSA-карта усилителя |
| `MIC_CARD` | `2` | ALSA-карта ADC |
| `MIC_DEVICE` | `plughw:2,0` | устройство захвата |
| `MIC_CHANNELS` | `5` | TDM-каналы |
| `MIC_RATE` | `16000` | частота |
| `MIC_PERIOD` | `1024` | ALSA period |
| `MIC_BUFFER` | `8192` | ALSA buffer (512 мс) |
| `PLAY_DEVICE` | `default` | ALSA playback (dmix) |
| `DEFAULT_LEVEL` | `5` | стартовая громкость 0..100 |
| `AMP_MIN` / `AMP_MAX` | `350` / `850` | шкала усилителя |

### `~/nabustation/voice/voice.env` (voice server)

| Переменная | Пример | Смысл |
|---|---|---|
| `STATION_HOST` | `192.168.1.10` | IP станции |
| `HA_HOST` | `127.0.0.1` | HA host |
| `HA_TOKEN_FILE` | `.../ha_token.txt` | long-lived token |
| `PIPELINE_NAME` | пусто | имя пайплайна; пусто = preferred |
| `MUSIC_ENTITY` | `media_player.station_1` | MA-плеер |
| `SILERO_URL` | `http://127.0.0.1:10400/tts` | TTS |
| `SILERO_VOICE` | `eugene` | голос |
| `STATION_VOLUME_DEFAULT` | `5` | громкость, если файла ещё нет |
| `MIC_ORDER` | `debian` | карта каналов |
| `WAKE_THRESHOLD` | `0.15` | порог wake |
| `WAKE_HITS_MIN` | `1` | подтверждений |
| `WAKE_HIGH` | `0.75` | сильный score |
| `SILENCE_MS` | `600` | тишина для конца фразы |
| `MAX_UTTERANCE_MS` | `6000` | аварийный лимит |

Полный пример: [`voice-server/voice.env.example`](voice-server/voice.env.example).

### Helpers HA

| Helper | Пример |
|---|---|
| `input_text.nabustation_media_player` | `media_player.station_1` |
| `input_text.nabustation_station_host` | `192.168.1.10` |
| `input_text.nabustation_liked_playlist` | `library://playlist/12` |

---

## Голосовые команды

После wake word «Окей Набу»:

| Фраза | Действие |
|---|---|
| «пауза» | пауза |
| «продолжи» / «продолжай» | продолжить с того же места |
| «дальше» / «следующий трек» | следующий |
| «назад» / «предыдущий трек» | предыдущий |
| «перемешай» | shuffle текущей очереди |
| «что за трек» / «что за песня» | «Исполнитель: … Песня: …» |
| «поставь лайк» | Spotify Liked Songs + |
| «убери лайк» | Spotify Liked Songs − |
| «включи музыку» | Liked Songs (Spotify-модуль) |
| «громкость 5» | 5% на станции |
| «громче» / «тише» | ±10% |
| «стоп» / «выключи музыку» | стоп |

Команды работают локально в HA (`prefer_local_intents: true`), без LLM.
Голосовой сервер также умеет локально обрабатывать «громкость N»,
«громче», «тише» до HA.

---

## Как это работает

### Микрофоны и AEC

Station 1 отдаёт 5 каналов TDM:

- `ch1-3` — микрофоны;
- `ch4` — оба reference-тапа усилителя;
- `ch0` — тихий/нераспаянный канал, не использовать.

`station_voice.py` берёт `ch1-3` как микрофонный микс, `ch4` как
reference. SpeexDSP адаптивно вычитает эхо музыки/TTS. Дополнительно:

- high-pass 100 Гц — убирает бас/пики;
- residual echo suppression — добивает остатки эха;
- 4096 taps;
- `MUSIC_REF_RMS=10` — порог активности reference.

Пороги wake подобраны под громкую музыку: `0.15`/1 hit, сильные score
срабатывают сразу.

### Конец фразы

VAD адаптивный: noise floor берётся из последних ~3 с wake-кадров,
порог `max(200, noise × 1.35)`, после начала речи — ещё и
`speech_peak × 0.25`. Тишина 600 мс завершает фразу; аварийный лимит
6 с. Это убирает старую задержку 12 с.

### TTS

Silero не любит латиницу: одиночные буквы и английские слова могут
пропадать. Voice server перед TTS:

- раскрывает `C418 → Си 418`;
- транслитерирует английские слова (`Mutation → мьютейшн`,
  `Slam → слэм`);
- нормализует числа (`418 → четыреста восемнадцать`);
- разбивает now playing на два предложения:
  `Исполнитель: … Песня: …`, чтобы название не обрезалось возвратом
  музыки.

### Громкость

`volume_server.py` (8098) пишет уровень в `position`/`volume_set` и
меняет `Subwoofer Master`/`Tweeters Master` на card 1. `dial.py` читает
тот же файл и синхронизирует физический диск. `station_voice.py` сначала
пробует 8098, потом Android 8096.

---

## Диагностика

### Wake word не срабатывает

1. Проверьте микрофонный поток:

   ```bash
   journalctl --user -u station-voice.service -n 100 --no-pager
   ```

   Должно быть `mic connected`, `mic format: 5 channel(s)`.

2. Проверьте, что `arecord` жив:

   ```bash
   ssh root@<STATION_IP> 'pgrep -a arecord; tail -20 /root/voice/mic.log'
   ```

3. Проверьте карту каналов: `MIC_ORDER=debian`, reference `ch4`.
   Если используете другой rootfs/ядро, снимите 5 каналов и посмотрите
   уровни:

   ```bash
   arecord -D plughw:2,0 -f S16_LE -r 16000 -c 5 -t raw /tmp/mic.raw
   ```

4. `libspeexdsp1` установлен? Если нет — fallback FIR, качество хуже.

5. Пороги: начните с `WAKE_THRESHOLD=0.15`, `WAKE_HITS_MIN=1`.
   Если много ложных срабатываний от ТВ — поднимите до `0.2`/`2`,
   но не выше без проверки.

### Большая задержка после речи

Смотрите лог:

```bash
journalctl --user -u station-voice.service -f | grep -E 'first speech|utterance|heard'
```

`utterance 12.0s` означал, что VAD не видел тишину. В 1.0 порог
адаптивный, тишина 600 мс. Если utterance всё ещё длинный, проверьте
`noise`/`threshold` в строке `first speech`:

- `noise` высокий (музыка/ТВ) — порог тоже высокий;
- `rms` речи ниже порога — уменьшите `VAD_NOISE_FACTOR` до `1.2`.

### TTS молчит или глотает слова

- Проверьте Silero:

  ```bash
  curl 'http://127.0.0.1:10400/tts?text=привет&speaker=eugene&sr=48000' -o /tmp/t.wav
  aplay /tmp/t.wav
  ```

- Английские названия транслитерируются в voice server. Если конкретное
  слово звучит плохо, добавьте его в `_TTS_WORDS` в
  `station_voice.py` и перезапустите сервис.

- Если TTS обрезается, проверьте `play.log` на станции и увеличьте
  `tail` в `_send_wav` (по умолчанию 0.55 с для ответов).

### Like/unlike не работает

- MA patch применён? `docker exec music-assistant ...` и
  `docker restart music-assistant`.
- Проверьте, что `spotify/set_liked` зарегистрирован (лог MA).
- `music_like.py` запускается в контейнере HA; там есть
  `music_assistant_client`?
- `input_text.nabustation_liked_playlist` заполнен?
- Плеер в `nabustation.json` совпадает с MA.

### Громкость не работает

```bash
curl http://<STATION_IP>:8098/health
curl 'http://<STATION_IP>:8098/volume?level=5'
```

- `sv status volume` на станции;
- `AMP_CARD` правильный? `amixer -c 1 sset 'Subwoofer Master' 375`;
- `binary_sensor.nabustation_debian` в HA = on?
- Если нет — HA использует fallback `media_player.volume_*` (MA volume).

### Snapcast/музыка

- `snapclient` запущен? `sv status snapclient`;
- `SNAPCAST_HOST` правильный?
- MA player volume 100%, Snapcast client volume 100%;
- buffer 1000 мс в MA/Snapcast; 500 мс может вызывать рестарты.

### HA intents не срабатывают

- `conversation.reload` и `intent_script.reload` после правок;
- `prefer_local_intents: true` в пайплайне;
- язык custom sentences — `ru`;
- проверьте `conversation.process` в Developer Tools.

---

## Безопасность

- В репозитории **нет** токенов, паролей, ключей, IP и имён.
- `ha_token.txt`, `voice.env`, `station.env`, `nabustation.json` — не
  коммитить; они в `.gitignore`.
- HA long-lived token: минимальные права, отзывайте при утечке.
- Станция: смените root-пароль, используйте SSH-ключ, закройте порты
  8091-8098 от интернета (только LAN).
- Spotify/MA credentials хранятся в MA; не дублируйте их в репозитории.
- Патч MA меняет `provider.py`; backup лежит в
  `/data/provider.py.bak-spotify-like`.

---

## Обновление и удаление

### Обновление

```bash
git pull
# station
sudo ./station/install.sh
# voice server
./voice-server/install.sh --force
# HA packages/custom sentences — скопировать заново, перезапустить HA
# MA patch — применить заново после обновления образа MA
```

Скрипты делают backup старых файлов с timestamp.

### Удаление

```bash
# station
sv stop voice voice-watch volume snapclient
rm -rf /etc/service/voice /etc/service/voice-watch /etc/service/volume /etc/service/snapclient
rm -rf /root/voice /etc/nabustation

# voice server
systemctl --user disable --now station-voice.service
rm -rf ~/nabustation/voice
rm ~/.config/systemd/user/station-voice.service

# HA: удалить пакеты, фразы, helper-сущности, /config/scripts/music_like.py
# Silero: docker compose down; удалить папку/образ по желанию
```

---

## Ограничения версии 1.0

- Нет автоматической установки Debian rootfs/ядра и Android ROM/root.
- Исходников оригинального Now Playing APK нет; в репозитории лежит
  рабочий APK с обезличенным host-плейсхолдером и скрипт патча.
- Android-режим проверен на конкретной прошивке Station 1 (Android 6,
  vendor `busybox-smp`); на другой прошивке пути/пакеты могут отличаться.
- Spotify patch привязан к внутренностям MA; после обновления MA его
  нужно применять заново.
- Русские custom sentences; для другого языка нужен перевод.
- Один voice server на одну станцию (можно запустить несколько
  экземпляров с разными `voice.env` и портами).

---

## Благодарности

NabuStation — во многом «клей» между чужими проектами. Основная заслуга —
у авторов этих проектов:

- [yandex-station-linux](https://github.com/MyszkinPL/yandex-station-linux) —
  Debian rootfs, ядро и DTS для Station 1;
- [Home Assistant](https://github.com/home-assistant/core) — Assist, интенты,
  API;
- [Music Assistant](https://github.com/music-assistant/server) — музыка,
  очередь, Spotify-провайдер;
- [Snapcast](https://github.com/snapcast/snapcast) — синхронное аудио;
- [Spotify Soloist](https://github.com/spotify/soloist) — Spotify Connect
  backend;
- [openWakeWord](https://github.com/dscripka/openWakeWord) и
  [pyopen-wakeword](https://github.com/rhasspy/pyopen-wakeword) — wake word;
- [SpeexDSP](https://github.com/xiph/speexdsp) — AEC;
- [Silero models](https://github.com/snakers4/silero-models) — русский TTS;
- [SmartTube](https://github.com/yuliskov/SmartTube) — YouTube на TV;
- [TV Launcher](https://github.com/wiiguy/lightweight_androidtv_launcher),
  [Lite Launcher](https://github.com/anujmv/lite-tv-launcher) и
  [Projectivy](https://github.com/spocky/miproja1) — лаунчеры;
- [LRCLIB](https://lrclib.net/) — тексты песен;
- [Groq](https://groq.com/) — STT/LLM в HA-пайплайне.

Полный список, лицензии и заметки об APK/моделях: [`CREDITS.md`](CREDITS.md).

NabuStation **не аффилирован** с Yandex, Spotify, Home Assistant, Music
Assistant, Snapcast и авторами Android-приложений. Yandex Station, Quasar,
Alice, Spotify, SmartTube, Projectivy и другие названия — товарные знаки их
владельцев.

## Лицензия

MIT. См. [`LICENSE`](LICENSE).

MIT покрывает только код и документацию NabuStation. Сторонние проекты, APK
и модели Silero остаются под их собственными лицензиями (см.
[`CREDITS.md`](CREDITS.md)).

История версий: [`CHANGELOG.md`](CHANGELOG.md).
