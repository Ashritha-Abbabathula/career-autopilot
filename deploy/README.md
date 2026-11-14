# Run the bot on an always-on server (so your laptop can be off)

The assistant talks to Telegram and reads public websites, so it needs a computer that is on and online all
day. Your laptop can be asleep, off, or offline once the bot lives on a small cloud server. (Nothing can work
without an internet connection somewhere; the point is that the connection is the server's, not yours.)

## What you need (about 20 minutes, once)
1. **A small Ubuntu server.** Any one of these works; the bot needs very little (1 CPU, 1 GB):
   - **Oracle Cloud "Always Free"** VM: free forever, but sign-up asks for a card for identity checks and some
     Indian cards are refused.
   - **Google Cloud** free `e2-micro` VM (a US region): free, card needed.
   - **Any cheap VPS** (about Rs 300 to 500 a month): Hetzner, DigitalOcean, Contabo, and so on. Easiest and most reliable.
   Choose Ubuntu 22.04 or 24.04. Create it, and note its address. Only you can create the account and pay;
   I cannot and should not.
2. **Connect to it** (the provider shows a "Connect" or "SSH" button; or `ssh ubuntu@ADDRESS` in PowerShell).
3. **Run the setup** (copy and paste; it asks for your details and keeps them on the server only):

   ```bash
   sudo apt-get update && sudo apt-get install -y git
   git clone https://github.com/Ashritha-Abbabathula/career-autopilot.git ~/ca-setup
   bash ~/ca-setup/deploy/setup_server.sh
   ```
   It will show you a key to paste into GitHub (a read-only "deploy key" for your private notes repo), then ask
   for your Telegram token, chat id, Gemini key and usernames. Typing is hidden.
4. **Stop the bot on your laptop** (two copies fight over Telegram). In PowerShell:
   ```powershell
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "ca\.run" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   ```
5. **Optional: keep what you already ticked.** The server starts fresh from your plan. To bring over today's ticks
   and the tracker, stop the laptop bot first, then copy the file (replace ADDRESS and the user name):
   ```powershell
   scp C:\Users\jayag\OneDrive\Desktop\resume-projects\09-career-autopilot\data\ca.sqlite ubuntu@ADDRESS:~/career-autopilot-host/data/ca.sqlite
   ```
   and on the server: `sudo systemctl restart career-autopilot`.

Then send `help` in Telegram. The morning card, reminders, digest, mentor note and weekly drafts keep coming with
your laptop shut.

## How it works there
- The bot code runs as a service that restarts itself if it crashes and starts again after the server reboots.
- Your private notes (plan, facts, tracker, the scout's digest) are pulled from your notes repo every hour,
  read-only. The bot's own files (tracker copy, LinkedIn drafts, ready emails, calendar) are saved on the server
  in `~/career-autopilot-host/data/out`, so nothing it does can touch your notes repo or its history.
- The calendar: send `calendar` in Telegram and it sends you the page as a file. Ticks inside that file stay on
  your phone or laptop; tell the bot `done <task>` so it knows too.
- Your keys live only in `~/career-autopilot-host/app/.env` on the server, readable only by you.

## Two honest limits
1. **The scout, the startup radar and the daily project build are Claude tasks that run in the Claude desktop app
   on your laptop.** They only run while that app is open on a computer that is awake. The bot on the server does
   not depend on them (without a fresh scout file, the digest is simply skipped), but they need their own cloud
   home to run with the laptop off. See "Next: the scout" below.
2. **Updating:** when I change the bot, run on the server
   `git -C ~/career-autopilot-host/app pull && sudo systemctl restart career-autopilot`.

## Next: the scout and the project builds
Those need the Claude side moved to a cloud schedule (a "routine"). It needs your GitHub connection and your Gmail
connector turned on for it, which only you can switch on. Until then, leave the Claude app open on a charging laptop
for the 7 am scout and the 7:30 pm build.
