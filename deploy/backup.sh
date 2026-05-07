#!/usr/bin/env bash
# deploy/backup.sh — nightly SQLite backup, keep 7 dailies.
set -euo pipefail
BOT_DIR=/home/botuser/foreclosure-bot
BACKUP_DIR=/var/backups/foreclosure-bot
DATE=$(date +%Y-%m-%d)
sqlite3 "$BOT_DIR/data/bot.sqlite" ".backup '$BACKUP_DIR/bot-$DATE.sqlite'"
ls -1t "$BACKUP_DIR"/bot-*.sqlite | tail -n +8 | xargs -r rm
