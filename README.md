Transmission Telegram Bot
=========================

Telegram bot for managing Transmission torrent client. Allows you to control torrents,
monitor download progress, and add new torrents directly from Telegram.

## Features

- **Torrent management** — start, stop, verify, delete torrents
- **Real-time status** — auto-updating download/upload progress
- **Add torrents** — via `.torrent` files, magnet links, or direct URLs
- **Batch adding** — send multiple magnet/URL links in one message
- **File selection** — choose which files to download from a torrent
- **User whitelist** — restrict access to authorized Telegram users only
- **Completion notifications** — push notifications when torrents finish downloading

## Configuration

The bot is configured via environment variables:

| Variable                          | Required | Default          | Description                                                      |
|-----------------------------------|----------|------------------|------------------------------------------------------------------|
| `TELEGRAM_TOKEN`                  | Yes      | —                | Telegram Bot API token from [@BotFather](https://t.me/BotFather) |
| `WHITELIST`                       | Yes      | —                | Comma-separated list of allowed Telegram user IDs                |
| `TRANSMISSION_HOST`               | No       | `127.0.0.1`      | Transmission RPC host                                            |
| `TRANSMISSION_PORT`               | No       | `9091`           | Transmission RPC port                                            |
| `TRANSMISSION_USERNAME`           | No       | —                | Transmission RPC username                                        |
| `TRANSMISSION_PASSWORD`           | No       | —                | Transmission RPC password                                        |
| `LOG_LEVEL`                       | No       | `INFO`           | Logging level (DEBUG, INFO, WARNING, ERROR)                      |
| `LOG_FORMAT`                      | No       | `console`        | Log output format: `console` (human-readable) or `json`          |
| `LOG_TIMESTAMP_FORMAT`            | No       | `iso` (ISO 8601) | Timestamp format, e.g. `%Y-%m-%d %H:%M:%S`                       |
| `NOTIFICATIONS_ENABLED`           | No       | `true`           | Enable push notifications for completed torrents                 |
| `NOTIFICATION_CHECK_INTERVAL_SEC` | No       | `10`             | Interval in seconds for checking torrent completion              |

## Deployment

### Docker Compose

1. Create `.env` file

    ```bash
    TELEGRAM_TOKEN=your_bot_token
    WHITELIST=123456789,987654321
    TRANSMISSION_HOST=transmission
    TRANSMISSION_PORT=9091
    ```

2. Create `docker-compose.yml` and run it `docker-compose up -d`

    ```yaml
    services:
      bot:
        image: ghcr.io/aleksey925/transmission-telegram-bot:latest
        restart: unless-stopped
        env_file: .env

      transmission:
        image: lscr.io/linuxserver/transmission:latest
        restart: unless-stopped
        ports:
          - "9091:9091"
          - "51413:51413"
          - "51413:51413/udp"
        environment:
          - TZ=UTC
        volumes:
          - ./downloads:/downloads
    ```
