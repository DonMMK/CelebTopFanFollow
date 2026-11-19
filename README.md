# CelebTopFanFollow

Run this worker on your existing Oracle VM. It uses Python 3.10+, systemd, SQLite, and the Telegram Bot API. There is no paid data provider, LLM, or incoming web server. Oracle hosting charges, if any, depend on your existing OCI account.

| Platform | What the free worker checks | Setup |
|---|---|---|
| Instagram | Photos, carousels, videos and Reels from professional accounts visible to Business Discovery | A Meta app, a Facebook Page linked to your own Instagram Business or Creator account, and a Facebook user token |
| TikTok | Recent posts shown in the public creator embed, usually videos. A slideshow is labelled only when the embed exposes a photo type. | No account or token. Preview your actual handles from the VM to check accessibility. |

Neither source monitors Stories. TikTok describes the public embed as a selection of up to ten recent videos. It can omit posts or refuse requests from the VM, and the worker records that as a failed check when the source is inaccessible. No CAPTCHA solving, login cookies or proxies are used. Meta Business Discovery is limited to professional accounts and excludes age-gated profiles. Use a small list and check the results before relying on it. Alerts can arrive after the next successful poll and can be missed if an item leaves the source's result window first.

In the Telegram chat you configured, open the bot's command menu or send `/watchlist`. In a group with multiple bots, use `/watchlist@YourBotName`. The reply groups the usernames by platform and shows which checks have succeeded, failed, are overdue, or haven't run yet. You can also see which platform is paused. Watchlist changes are made on the VM in `watchlist.json` and applied by restarting the service.

## Rotate an exposed Telegram bot token

Use this if a token appeared in a README, Git, or a shared message. Removing it from the document does not invalidate older copies.

### 1. Revoke the old token in Telegram

1. Open the official [@BotFather](https://t.me/BotFather) chat in Telegram.
2. Send `/mybots`, select the **existing** bot that sent your CelebTopFanFollow test alert, then open **API Token** and choose **Revoke current token**. Confirm the revocation. If BotFather does not display a replacement, send `/token` and select the same bot to generate one.
3. Copy the replacement token. The bot username and destination chat ID stay the same. Alerts pause between revoking the old token and restarting the worker with the new one. Keep the replacement out of Git, this README, and screenshots.

### 2. Save the replacement on the Oracle Ubuntu VM

If you are already at the `ubuntu@jarvis-vnc` prompt, use that terminal. Otherwise connect **from your Mac**:

```bash
ssh -i "$HOME/GitHub/CelebTopFanFollow/ssh-key-2026-05-17.key" -o IdentitiesOnly=yes ubuntu@149.118.70.167
```

On **Ubuntu**, run:

```bash
sudoedit /etc/celebtopfanfollow/secrets.env
```

Replace the value on the existing `TELEGRAM_BOT_TOKEN=` line with the new token from BotFather. Put the whole token on one line immediately after the equals sign. Keep `TELEGRAM_CHAT_ID` and any Meta settings as they are. If the editor is Nano, press **Ctrl+O**, **Enter**, then **Ctrl+X**.

Save the file, keep it readable only by its owner, and restart the worker:

```bash
sudo chmod 600 /etc/celebtopfanfollow/secrets.env &&
sudo systemctl restart celebtopfanfollow &&
sudo systemctl is-active celebtopfanfollow
```

The service reads the replacement from `secrets.env` at startup. You do not need to upload the ZIP or look up the chat ID again. The watchlist and alert history stay on the VM.

### 3. Verify sending and receiving

On **Ubuntu**, send a test alert without printing the token:

```bash
sudo systemd-run --wait --pipe --collect \
  --property=EnvironmentFile=/etc/celebtopfanfollow/secrets.env \
  /usr/bin/python3 /opt/celebtopfanfollow/worker.py --test-telegram
```

Confirm the test alert arrives, then send a fresh `/watchlist` to the same bot. The test alert confirms outgoing messages, and the watchlist reply confirms the background service receives commands.

If Telegram returns **HTTP 401**, reopen `secrets.env`, check that you saved the complete replacement token for the right bot, and restart again. If the alert arrives but `/watchlist` does not reply, check the worker log:

```bash
sudo journalctl -u celebtopfanfollow -n 40 --no-pager
```

Keep OpenClaw stopped if CelebTopFanFollow is taking over this bot. An **HTTP 409** in the log can indicate another polling client or an active webhook. Share any error text without sharing `secrets.env` or the token.

[Telegram's BotFather guide](https://core.telegram.org/bots/features#botfather)

## 1. Upload the ZIP from your Mac

If CelebTopFanFollow is already installed and the preview works, jump to [Preview works but watchlist shows zero](#preview-works-but-watchlist-shows-zero). A watchlist edit does not require uploading or reinstalling the app.

Your Mac project folder is `/Users/don/GitHub/CelebTopFanFollow`. Put the archive in that folder before uploading. [Download CelebTopFanFollow.zip](https://chatgpt.com/library?file_id=libfile_46cf85d121d081919e0fe87508b390c8&account_id=personal) if you need a copy. Open a new Terminal tab on your Mac while keeping your SSH session open. Run this in the **Mac tab**:

```bash
PROJECT="$HOME/GitHub/CelebTopFanFollow"
KEY="$PROJECT/ssh-key-2026-05-17.key"
ZIP="$PROJECT/CelebTopFanFollow.zip"

ls -l "$KEY" "$ZIP" &&
chmod 600 "$KEY" &&
scp -i "$KEY" -o IdentitiesOnly=yes "$ZIP" 'ubuntu@149.118.70.167:~/CelebTopFanFollow.zip'
```

If `ls` says the ZIP is missing, check the project folder and Downloads for a differently named copy:

```bash
find "$HOME/GitHub/CelebTopFanFollow" "$HOME/Downloads" -type f -iname 'CelebTopFanFollow*.zip' -print
```

Set `ZIP` to the full path you found and rerun the upload. Keep the private `.key` file on your Mac and out of Git.

## 2. Install on the Ubuntu VM

Return to the tab with the `ubuntu@jarvis-vnc` prompt. If you closed it, reconnect **from your Mac**:

```bash
ssh -i "$HOME/GitHub/CelebTopFanFollow/ssh-key-2026-05-17.key" -o IdentitiesOnly=yes ubuntu@149.118.70.167
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

Fill in `TELEGRAM_BOT_TOKEN` and the numeric `TELEGRAM_CHAT_ID` shown by the lookup below. If your test alert already arrived, keep the chat ID that worked. If the token appeared in a document or was shared, use the [rotation steps above](#rotate-an-exposed-telegram-bot-token). Leave Meta credentials blank if you are testing TikTok on its own.

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

## 4. Add TikTok usernames and preview the feed

On **Ubuntu**:

```bash
sudoedit /etc/celebtopfanfollow/watchlist.json
```

Keep the handles you already saved if the preview works. To add more, put each public TikTok username in the same `tiktok` array as a separate string. Replace these example handles with yours. Instagram stays paused in this starter config:

```json
{
  "instagram": [],
  "tiktok": ["first_public_handle", "second_public_handle"],
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

In Telegram, send `/watchlist`. You should see your TikTok handles and Instagram marked **paused** if you used the TikTok-only config. A newly configured handle may show **awaiting check** until its first poll. For a full alert test, add a public account you control, start the worker, publish a new item, and wait for the next successful poll. The worker skips items published before it added the account and retries queued alerts if Telegram is temporarily unavailable.

When the new alerts work, you can remove the old OpenClaw and Jarvis-ish services. For a CLI-managed OpenClaw install, preview with `openclaw uninstall --dry-run --all` first. Keep the VM and the existing backups until you have verified the new setup.

## Preview works but watchlist shows zero

The preview is a separate process that reads the saved file each time it runs. The background service loads the watchlist at startup, so a successful preview can show the new handles while Telegram still reports the old list. The number beside each platform counts configured handles, even before their first check.

On **Ubuntu**, confirm both usernames are under the expected platform key, then restart the service:

```bash
sudo /usr/bin/python3 -m json.tool /etc/celebtopfanfollow/watchlist.json &&
sudo systemctl restart celebtopfanfollow &&
sudo systemctl is-active celebtopfanfollow
```

In the same Telegram chat that received the test alert, **send a new** `/watchlist`. If both handles are under `tiktok`, the new reply should say **TikTok (2)**. **Awaiting check** is normal while a handle waits for its first poll. If the handles are split between platforms, expect one under each.

If the **new** reply still shows zero, inspect which service and worker are running:

```bash
sudo systemctl show celebtopfanfollow   -p FragmentPath -p DropInPaths -p ExecStart -p MainPID -p ActiveEnterTimestamp
sudo journalctl -u celebtopfanfollow -n 40 --no-pager
```

The standard service runs `/usr/bin/python3 /opt/celebtopfanfollow/worker.py` and reads `/etc/celebtopfanfollow/watchlist.json`. If `ExecStart` includes `--config`, check the file it names. If the service logs Telegram HTTP 409, check for another worker or an OpenClaw process using the same bot. If you share these diagnostics, leave out the token and the contents of `secrets.env`.

## Configure Instagram when ready

1. Create or use an Instagram professional account you control and connect it to a Facebook Page you manage. Create a Meta app and configure **Instagram API with Facebook Login**.
2. In [Graph API Explorer](https://developers.facebook.com/tools/explorer/), select your Meta app and generate a **Facebook user token** with `instagram_basic`, `instagram_manage_insights` and `pages_read_engagement`. Include `pages_show_list` to discover your Page. Depending on how the Page role was granted, Meta also lists `ads_management` or `ads_read`. See the [Business Discovery reference](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/business_discovery).
3. Query `GET /me/accounts?fields=name,instagram_business_account{id,username}` in the Explorer. Copy the numeric `instagram_business_account.id` for **your own** linked account, rather than the Facebook Page ID or any celebrity's ID. If no linked account appears, check the Page connection and the grant for that Page.
4. Put that ID in `META_IG_USER_ID` and your Facebook user token in `META_ACCESS_TOKEN` in `secrets.env`. The optional `META_GRAPH_VERSION` defaults to `v27.0`. For ongoing use, follow [Meta's user-token documentation](https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived/) and replace the token when it expires.
5. Add one target professional account to the `instagram` array and set `instagram_feed` to `60` in `watchlist.json`. Run the preview from step 4 with `--preview instagram_feed`, then restart the service and check `/watchlist` again.

[Oracle SSH help](https://docs.oracle.com/en-us/iaas/Content/Compute/Tasks/connect-to-linux-instance.htm) · [OpenClaw uninstall](https://docs.openclaw.ai/install/uninstall) · [TikTok creator embeds](https://developers.tiktok.com/docs/en/embed-creator-profiles) · [Telegram Bot API](https://core.telegram.org/bots/api)
