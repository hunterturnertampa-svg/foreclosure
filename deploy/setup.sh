#!/usr/bin/env bash
# deploy/setup.sh — one-shot provisioning for a fresh Ubuntu 24.04 VPS.
# Run as root. Assumes /home/botuser/foreclosure-bot already cloned.
set -euo pipefail

apt-get update
apt-get install -y python3.12 python3.12-venv git curl wget ca-certificates \
    libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64 \
    xvfb sqlite3

# Real Google Chrome — required to bypass publicindex.sccourts.org bot detection.
# Patchright + headless-shell still gets HTTP 406 on AJAX postbacks; only headed
# real Chrome under Xvfb makes it through.
if ! command -v google-chrome >/dev/null 2>&1; then
    wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
    apt-get install -y /tmp/chrome.deb
    rm -f /tmp/chrome.deb
fi

id -u botuser >/dev/null 2>&1 || useradd -m -s /bin/bash botuser

BOT_DIR=/home/botuser/foreclosure-bot
sudo -u botuser bash <<EOF
cd "$BOT_DIR"
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="\$HOME/.cargo/bin:\$HOME/.local/bin:\$PATH"
uv venv
uv pip install -e ".[dev]"
uv run patchright install chromium
EOF

mkdir -p /var/backups/foreclosure-bot
chown botuser:botuser /var/backups/foreclosure-bot
chmod 750 /var/backups/foreclosure-bot

cp "$BOT_DIR/deploy/foreclosure-bot.service" /etc/systemd/system/
cp "$BOT_DIR/deploy/foreclosure-bot.timer" /etc/systemd/system/
systemctl daemon-reload

# Nightly backup at 03:17
cat >/etc/cron.d/foreclosure-bot-backup <<EOF
17 3 * * * botuser $BOT_DIR/deploy/backup.sh
EOF

echo "Setup complete. Next steps:"
echo "  1. Edit /home/botuser/foreclosure-bot/.env (chmod 600)"
echo "  2. Run smoke tests (see README)"
echo "  3. systemctl enable --now foreclosure-bot.timer"
