# Spotify Connect на NabuStation

NabuStation умеет появляться в официальном приложении Spotify как обычная
колонка. Звук при этом идёт не напрямую на станцию, а через Music Assistant:

```text
телефон Spotify -> Spotify Connect -> Music Assistant -> Snapcast -> Station 1
```

На станции **нет** librespot/spotifyd. Используется плагин Music Assistant
**Spotify Connect** с официальным движком **Spotify Soloist**. Требуется
Spotify Premium и API key Soloist, который создаётся один раз в Spotify for
Developers.

## Что нужно

- Music Assistant 2.10 или новее;
- Spotify provider в MA с playback backend **Soloist**;
- плагин **Spotify Connect** в MA;
- один раз принять условия Soloist и указать тот же API key, что у Spotify
  provider;
- выбрать плеер MA (например, `Station 1`), который нужно показывать в Spotify.

## Настройка

1. Music Assistant -> Settings -> Plugins -> Add plugin -> **Spotify Connect**.
2. Backend: **Spotify Soloist (official)**.
3. Принять предупреждение о Terms of Service Soloist.
4. Вставить Soloist API key. Ключ хранится в зашифрованном виде в MA.
5. В настройках плагина выбрать `Connected players` -> `Station 1`.
6. `Advertised device name`: например, `Player name only`, чтобы в Spotify
   устройство называлось просто `Station 1`.
7. Сохранить и перезагрузить плагин.

В логе MA должно появиться:

```text
Started Spotify Connect background daemon [Spotify Connect/Station 1]
```

## Использование

1. Телефон и MA должны быть в одной локальной сети.
2. Открыть Spotify -> динамик/устройство воспроизведения.
3. Выбрать `Station 1`.
4. Управлять музыкой из Spotify: play/pause, next/prev, очередь, лайки.

Громкость рекомендуется держать в режиме `Player volume only`: Spotify не
будет неожиданно менять усилитель станции. Общая громкость станции остаётся
под контролем NabuStation (5% для музыки, 5→70% для будильника).

## AI DJ

Spotify AI DJ — серверная функция Spotify. Она может работать не на всех
сторонних Spotify Connect-устройствах: Spotify иногда отвечает
`Your current speaker does not support interaction with DJ`. Это ограничение
Spotify, а не NabuStation. Если DJ через Connect не работает, есть
альтернатива — плагин **AI Radio** в Music Assistant: он добавляет голосовые
вставки между треками в очередь MA и не зависит от Spotify DJ.

Запустить Spotify DJ программно нельзя: Spotify не отдаёт DJ через Web API, а
URI `spotify:playlist:37i9dQZF1EYkqdzj48dyYq` не является обычным плейлистом.
Поэтому DJ запускается из приложения Spotify. В телефонном пульте NabuStation
есть кнопка **DJ** — она открывает DJ в Spotify. Если Station 1 выбран как
устройство Connect, звук пойдёт на станцию. Смена трека DJ работает локальной
командой «смени треки» или кнопкой NEXT.

## Если устройство не видно

- проверить, что плагин Spotify Connect загружен и daemon запущен;
- проверить, что телефон в той же подсети, без гостевого Wi-Fi/VPN;
- перезапустить приложение Spotify;
- перезагрузить плагин Spotify Connect в MA;
- проверить, что выбранный MA-плеер включён и доступен.
