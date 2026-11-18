#!/bin/sh
set -eu

src=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd)
config=/etc/celebtopfanfollow
app=/opt/celebtopfanfollow

if [ "$(id -u)" -ne 0 ]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

/usr/bin/python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'
install -d -m 0755 "$app" "$config"
install -m 0644 "$src/worker.py" "$app/worker.py"
install -m 0644 "$src/celebtopfanfollow.service" /etc/systemd/system/celebtopfanfollow.service
if [ ! -e "$config/watchlist.json" ]; then
    install -m 0644 "$src/watchlist.example.json" "$config/watchlist.json"
fi
if [ ! -e "$config/secrets.env" ]; then
    (
        umask 077
        cat > "$config/secrets.env" <<'EOF'
META_IG_USER_ID=
META_ACCESS_TOKEN=
META_GRAPH_VERSION=v27.0
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOF
    )
fi
systemctl daemon-reload
echo "Installed. Set the watchlist and Telegram secrets, and add Meta credentials for Instagram."
