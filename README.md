# CelebTopFanFollow

Run this worker on your existing Oracle VM. It uses Python 3.10+, systemd, SQLite, and the Telegram Bot API. There is no paid data provider, LLM, or incoming web server. Oracle hosting charges, if any, depend on your existing OCI account.

| Platform | What the free worker checks | Setup |
|---|---|---|
| Instagram | Photos, carousels, videos and Reels from professional accounts visible to Business Discovery | A Meta app, a Facebook Page linked to your own Instagram Business or Creator account, and a Facebook user token |
| TikTok | Recent posts shown in the public creator embed, usually videos. A slideshow is labelled only when the embed exposes a photo type. | No account or token. Preview your actual handles from the VM to check accessibility. |

Neither source monitors Stories. TikTok describes the public embed as a selection of up to ten recent videos. It can omit posts or refuse requests from the VM, and the worker records that as a failed check when the source is inaccessible. No CAPTCHA solving, login cookies or proxies are used. Meta Business Discovery is limited to professional accounts and excludes age-gated profiles. Use a small list and check the results before relying on it. Alerts can arrive after the next successful poll and can be missed if an item leaves the source's result window first.

In the Telegram chat you configured, open the bot's command menu or send `/watchlist`. In a group with multiple bots, use `/watchlist@YourBotName`. The reply groups the usernames by platform and shows which checks have succeeded, failed, are overdue, or haven't run yet. You can also see which platform is paused. Watchlist changes are made on the VM in `watchlist.json` and applied by restarting the service.

## 1. Upload the ZIP from your Mac

You are already connected to the Oracle VM as `ubuntu@jarvis-vnc`. The `scp: stat local ... No such file or directory` error came from your Mac before uploading. Your key worked, and the server's home directory listing shows that the ZIP did not arrive.

[Download the latest CelebTopFanFollow.zip](https://chatgpt.com/library?file_id=libfile_46cf85d121d081919e0fe87508b390c8&account_id=personal) to your Mac's **Downloads** folder. Open a new Mac Terminal tab with **Command–T** and keep your existing SSH session open. Run the following in the **Mac tab**:

the paths below need to get updtaed because eveyrhting was oved to 
/Users/don/GitHub/CelebTopFanFollow

```bash
KEY="$HOME/Downloads/openclaw-jarvis/ssh-key-2026-05-17.key"
ZIP="$HOME/Downloads/CelebTopFanFollow.zip"

ls -l "$KEY" "$ZIP" &&
chmod 600 "$KEY" &&
scp -i "$KEY" -o IdentitiesOnly=yes "$ZIP" 'ubuntu@149.118.70.167:~/CelebTopFanFollow.zip'
```

If the ZIP has a different name, find it on your Mac:

```bash
find "$HOME/Downloads" -type f -iname 'CelebTopFanFollow*.zip' -print
```

Set `ZIP` to the full path that command prints, then rerun the `ls`, `chmod`, and `scp` commands. The remote filename is always `CelebTopFanFollow.zip`. Leave the private `.key` file on your Mac.

## 2. Install on the Ubuntu VM

Return to the tab with the `ubuntu@jarvis-vnc` prompt. If you closed it, reconnect **from your Mac**:

```bash
ssh -i "$HOME/Downloads/openclaw-jarvis/ssh-key-2026-05-17.key" -o IdentitiesOnly=yes ubuntu@149.118.70.167
```

If a previous CelebTopFanFollow worker is running, stop it first with `sudo systemctl stop celebtopfanfollow`. On **Ubuntu**, check that the upload landed and that the archive is readable, then install:

```bash
ls -lh "$HOME/CelebTopFanFollow.zip" &&
python3 -m zipfile -t "$HOME/CelebTopFanFollow.zip" &&
python3 -m zipfile -e "$HOME/CelebTopFanFollow.zip" "$HOME" &&
cd "$HOME/CelebTopFanFollow" &&
sudo sh ./install.sh
```

The installer preserves existing bot settings, watchlist, and SQLite history. It stages the new service for you to configure and start below.

## 3. Reuse your Telegram bot

Your VM already has `~/openclaw_config_backup.json` and `~/openclaw_workspace_backup`. Keep both while setting the new service up. If you need the bot token, open the config backup privately on the VM with `less ~/openclaw_config_backup.json` and search for `telegram`. The token may be under `channels.telegram.botToken`, inside a Telegram account entry, or stored separately if the config points to a token file or the `TELEGRAM_BOT_TOKEN` environment variable. Keep the token out of pasted terminal logs.

On **Ubuntu**, open the service settings:

```bash
sudoedit /etc/celebtopfanfollow/secrets.env
```

Fill in `TELEGRAM_BOT_TOKEN`(8595092744:AAEiTi_vgJJ76y76fMjEyvH5k34uLXZyIhY) and, if you know it, the numeric `TELEGRAM_CHAT_ID`(2CKCWXQ6). Leave Meta credentials blank for now. TikTok can be set up on its own.

If the old OpenClaw gateway is still running for this bot, stop it before looking up the chat ID or starting the new worker. For a CLI install, run `openclaw gateway stop` as the account that owns it. If it runs as a container or a separate service, stop that specific container or service.

**If you need the chat ID**, send a fresh `/start` in your bot DM. For a group, send a command that mentions your bot in that group. Then run the lookup on Ubuntu:

```bash
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/celebtopfanfollow/secrets.env \
  /usr/bin/python3 /opt/celebtopfanfollow/worker.py --chat-id
```

Copy the ID for your intended DM or group into `TELEGRAM_CHAT_ID` in `secrets.env`. Keep a leading minus sign if the group ID has one. If the lookup returns HTTP 409, check for an old polling process first. If this bot used a webhook and you are moving it to CelebTopFanFollow, rerun the same command with `--clear-telegram-webhook`, send a fresh message to the bot, then retry `--chat-id`.

Send yourself one test message from Ubuntu:

```bash
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/celebtopfanfollow/secrets.env \
  /usr/bin/python3 /opt/celebtopfanfollow/worker.py --test-telegram
```

Continue when the test alert arrives in the right chat.

## 4. Add a TikTok username and preview the feed

On **Ubuntu**:

```bash
sudoedit /etc/celebtopfanfollow/watchlist.json
```

Use a public TikTok handle you want to follow in place of `tiktok`. Instagram stays paused in this starter config:

```json
{
  "instagram": [],
  "tiktok": ["tiktok"],
  "poll_minutes": {
    "instagram_feed": 0,
    "tiktok_feed": 60
  },
  "feed_results_per_profile": 10
}
```

Run a live preview from the VM. It prints detected posts without sending Telegram alerts:

```bash
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/celebtopfanfollow/secrets.env \
  /usr/bin/python3 /opt/celebtopfanfollow/worker.py --preview tiktok_feed
```

A working preview prints rows with the username, post type, and link. If the VM gets an HTTP 403 or the worker says the public feed is unavailable, try another public handle. Telegram can still answer `/watchlist`, but alerts for that handle depend on TikTok returning a usable feed.

## 5. Start the service and check Telegram

On **Ubuntu**:

```bash
sudo systemctl enable celebtopfanfollow
sudo systemctl restart celebtopfanfollow
sudo systemctl status celebtopfanfollow --no-pager
sudo journalctl -u celebtopfanfollow -n 30 --no-pager
```

In Telegram, send `/watchlist`. You should see your TikTok handle and Instagram marked **paused**. A newly configured handle may show **awaiting check** until its first poll. For a full alert test, add a public account you control, start the worker, publish a new item, and wait for the next successful poll. The worker skips items published before it added the account and retries queued alerts if Telegram is temporarily unavailable.

When the new alerts work, you can remove the old OpenClaw and Jarvis-ish services. For a CLI-managed OpenClaw install, preview with `openclaw uninstall --dry-run --all` first. Keep the VM and the existing backups until you have verified the new setup.

## Configure Instagram when ready

1. Create or use an Instagram professional account you control and connect it to a Facebook Page you manage. Create a Meta app and configure **Instagram API with Facebook Login**.
2. In [Graph API Explorer](https://developers.facebook.com/tools/explorer/), select your Meta app and generate a **Facebook user token** with `instagram_basic`, `instagram_manage_insights` and `pages_read_engagement`. Include `pages_show_list` to discover your Page. Depending on how the Page role was granted, Meta also lists `ads_management` or `ads_read`. See the [Business Discovery reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery).
3. Query `GET /me/accounts?fields=name,instagram_business_account{id,username}` in the Explorer. Copy the numeric `instagram_business_account.id` for **your own** linked account, rather than the Facebook Page ID or any celebrity's ID. If no linked account appears, check the Page connection and the grant for that Page.
4. Put that ID in `META_IG_USER_ID` and your Facebook user token in `META_ACCESS_TOKEN` in `secrets.env`. The optional `META_GRAPH_VERSION` defaults to `v27.0`. For ongoing use, follow [Meta's user-token documentation](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/) and replace the token when it expires.
5. Add one target professional account to the `instagram` array and set `instagram_feed` to `60` in `watchlist.json`. Run the preview from step 4 with `--preview instagram_feed`, then restart the service and check `/watchlist` again.

[Oracle SSH help](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/connect-to-linux-instance.htm) · [OpenClaw uninstall](https://docs.openclaw.ai/install/uninstall) · [TikTok creator embeds](https://developers.tiktok.com/docs/en/embed-creator-profiles) · [Telegram Bot API](https://core.telegram.org/bots/api)
