#!/usr/bin/env bash
# Career Autopilot: one-time setup on an always-on Ubuntu server (22.04 or newer).
#
#   bash setup_server.sh
#
# What it does: installs Python and git, downloads the bot, connects to your private notes repo with a
# read-only key, asks you for your Telegram and Gemini details (typed here, hidden, never shown to anyone),
# and starts the bot as a service that restarts itself and starts again after a reboot.
set -euo pipefail

ROOT="$HOME/career-autopilot-host"
APP="$ROOT/app"
NOTES="$ROOT/notes"
DATA="$ROOT/data"
KEY="$HOME/.ssh/notes_deploy"
NOTES_REPO="git@github.com:Ashritha-Abbabathula/resume-projects-notes.git"
CODE_REPO="https://github.com/Ashritha-Abbabathula/career-autopilot.git"

echo "== 1/5 Installing Python and git"
sudo apt-get update -y
sudo apt-get install -y git python3 python3-venv openssh-client
mkdir -p "$ROOT" "$DATA/out"

echo "== 2/5 Downloading the bot"
if [ -d "$APP/.git" ]; then git -C "$APP" pull --ff-only; else git clone "$CODE_REPO" "$APP"; fi

echo "== 3/5 Connecting to your private notes repo (read-only key)"
mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"
[ -f "$KEY" ] || ssh-keygen -t ed25519 -N "" -f "$KEY" -C "career-autopilot-server"
echo
echo "Add this key on GitHub so the server can READ your notes (it can never change them):"
echo "  github.com/Ashritha-Abbabathula/resume-projects-notes -> Settings -> Deploy keys -> Add deploy key"
echo "  Title: career-autopilot-server    Key: (the line below)    leave 'Allow write access' UNTICKED"
echo
cat "$KEY.pub"
echo
read -rp "Press Enter once you have added the key... " _
export GIT_SSH_COMMAND="ssh -i $KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"
if [ -d "$NOTES/.git" ]; then git -C "$NOTES" pull --ff-only; else git clone "$NOTES_REPO" "$NOTES"; fi
git -C "$NOTES" config core.sshCommand "ssh -i $KEY -o IdentitiesOnly=yes"

echo "== 4/5 Your settings (typed text is hidden and saved only on this server, readable only by you)"
ENVFILE="$APP/.env"
if [ ! -f "$ENVFILE" ]; then
  read -rsp "Telegram bot token (from BotFather): " TG_TOKEN; echo
  read -rp  "Your Telegram chat id (from @userinfobot): " TG_CHAT
  read -rsp "Gemini API key: " GEM_KEY; echo
  read -rp  "LeetCode username: " LC_USER
  read -rp  "GitHub username [Ashritha-Abbabathula]: " GH_USER
  GH_USER="${GH_USER:-Ashritha-Abbabathula}"
  umask 077
  {
    printf 'TELEGRAM_BOT_TOKEN=%s\n' "$TG_TOKEN"
    printf 'TELEGRAM_OWNER_CHAT_ID=%s\n' "$TG_CHAT"
    printf 'GEMINI_API_KEY=%s\n' "$GEM_KEY"
    printf 'LEETCODE_USER=%s\n' "$LC_USER"
    printf 'GITHUB_USER=%s\n' "$GH_USER"
    printf 'TIMEZONE=Asia/Kolkata\n'
  } > "$ENVFILE"
  chmod 600 "$ENVFILE"
  unset TG_TOKEN GEM_KEY
else
  echo "(.env already exists; keeping it)"
fi

echo "== 5/5 Starting the bot as a service"
UNIT=/etc/systemd/system/career-autopilot.service
sudo tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=Career Autopilot (Telegram assistant)
After=network-online.target
Wants=network-online.target

[Service]
User=$USER
WorkingDirectory=$APP
Environment=PYTHONIOENCODING=utf-8
Environment=CA_PRIVATE_DIR=$NOTES/notebooks/09-career-autopilot
Environment=CA_OUTPUT_DIR=$DATA/out
Environment=CA_DB_PATH=$DATA/ca.sqlite
Environment=NOTES_AUTOPULL=1
Environment=CALENDAR_PORT=0
ExecStart=/usr/bin/python3 -u -m ca.run
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable --now career-autopilot
sleep 5
sudo systemctl --no-pager --lines=8 status career-autopilot || true
echo
echo "Done. Useful commands:"
echo "  sudo journalctl -u career-autopilot -f      watch the bot's log"
echo "  sudo systemctl restart career-autopilot     restart it"
echo "  git -C $APP pull && sudo systemctl restart career-autopilot     update to the newest code"
echo
echo "IMPORTANT: stop the bot on your laptop now (two copies fight over Telegram)."
