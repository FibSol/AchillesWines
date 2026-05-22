# Installing Achilles's Wines on a Raspberry Pi 5 — Home Assistant OS

> **Who is this guide for?**  
> Someone who has a Raspberry Pi 5 running Home Assistant OS (HAOS), knows how to open a browser,
> but has little or no Linux experience. No prior Docker knowledge required.
>
> **Need help?** See the last section — you can ask Claude to do the installation for you via SSH.

---

## What you'll end up with

Achilles's Wines running at **`http://<your-rpi-ip>:8080`** on your local network —
accessible from any phone, tablet, or laptop on your Wi-Fi without any cloud account.

---

## Before you start — checklist

- [ ] Your Raspberry Pi 5 is powered on and connected to your router via cable or Wi-Fi
- [ ] Home Assistant is working normally (you can open its UI in a browser)
- [ ] You know your RPi's local IP address (e.g. `192.168.1.42`) — find it in your router's device list or in **Settings → System → Network** inside HA
- [ ] Your Raspberry Pi's storage has at least **4 GB free** (check in **Settings → System → Storage**)
- [ ] You have a GitHub account (free) — needed to download the code

---

## Part 1 — Install the SSH terminal add-on

This gives you a text window inside Home Assistant where you can type commands.
You only need to do this once.

1. In the Home Assistant sidebar, click **Settings**
2. Click **Add-ons**
3. Click **Add-on store** (bottom-right corner)
4. In the search box, type `Advanced SSH`
5. Click **Advanced SSH & Web Terminal** (by *hassio-addons*)
6. Click **Install** — wait a minute for it to download
7. Once installed, click the **Configuration** tab
8. Set a password — replace the placeholder with something you'll remember:
   ```yaml
   password: "YourChosenPassword"
   ```
9. Click **Save**
10. Click the **Info** tab, then click **Start**
11. Toggle **Show in sidebar** to ON — this adds a terminal icon to your HA sidebar

> You now have a terminal. Every time you need to type commands, click that sidebar icon.

---

## Part 2 — Open the terminal and check Docker is available

1. Click the **Terminal** icon in the HA sidebar
2. You'll see a black screen with a `#` prompt — this is the command line
3. Type this and press Enter:
   ```
   docker --version
   ```
4. You should see something like `Docker version 26.x.x` — that's good.
5. Type this and press Enter:
   ```
   docker compose version
   ```
   You should see `Docker Compose version v2.x.x` — also good.

If either command says "not found", stop here and ask for help — it means your HAOS
version is very old. Update Home Assistant first.

---

## Part 3 — Download the Achilles's Wines code

Type these commands one by one, pressing Enter after each.
Copy-paste is fine — right-click in the terminal window to paste.

```bash
mkdir -p /share/achilles-wines
cd /share/achilles-wines
git clone https://github.com/FibSol/AchillesWines.git .
```

You should see lines scrolling by ending with `done`. The code is now on your RPi.

---

## Part 4 — Create your configuration file

The app needs a `.env` file with your personal settings.

```bash
cp .env.example .env
```

Now open the file in the built-in text editor:

```bash
nano .env
```

A simple text editor opens. Use the arrow keys to navigate.

Find the lines below and fill them in (the others can stay as-is for now):

```dotenv
# Leave this as-is — it's where the database will live inside Docker
DATABASE_URL=/data/achilles.db

# The port you'll use to open the app in your browser (8080 is fine)
ACHILLES_HTTP_PORT=8080

# A passphrase to encrypt your daily database backups
# Choose anything — write it down somewhere safe
ACHILLES_GPG_PASSPHRASE=MySecretBackupPassphrase

# Cron schedules — when scrapers run automatically
# This example runs the Millesima scraper every night at 3:00 AM
ACHILLES_SCHEDULE_MILLESIMA=0 3 * * *
```

When done: press **Ctrl+X**, then **Y**, then **Enter** to save and exit.

---

## Part 5 — Build the Docker images

This compiles the app for your Raspberry Pi. It takes **10–15 minutes** the first time
because it compiles code for the ARM processor. You only do this once.

```bash
docker compose build
```

You'll see lots of text scrolling. Wait until you're back at the `#` prompt.
If you see `ERROR` in red, something went wrong — see the Troubleshooting section below.

---

## Part 6 — Set up the database

```bash
docker compose up web --wait
```

This starts the web container, which creates and prepares the database automatically.
Wait until you see a line containing `✓` or `ready` (about 20 seconds), then press **Ctrl+C**.

---

## Part 7 — Import your wine data from burgundy-manager

> **Skip this step** if you don't have an existing burgundy-manager database.

This imports your ~8 700 producers and wine list from the old app. You need to copy
the old database file to the RPi first.

**On your Windows PC**, open PowerShell and run:
```powershell
scp "C:\Users\Nicolas\Bourgogne\burgundy-manager\data\burgundy.db" root@192.168.1.42:/share/burgundy.db
```
*(Replace `192.168.1.42` with your RPi's actual IP address)*

Then back in the RPi terminal:
```bash
docker compose run --rm web \
  npx tsx scripts/import-from-burgundy-manager.ts \
  --source /share/burgundy.db
```

You should see a summary: `8 701 producers imported, 201 appellations imported`.

---

## Part 8 — Start everything

```bash
docker compose up -d
```

The `-d` means it runs in the background — you can close the terminal and it keeps running.

Check that everything started correctly:
```bash
docker compose ps
```

You should see three lines all showing **Up (healthy)**:
```
achilles-nginx    running (healthy)
achilles-scraper  running (healthy)
achilles-web      running (healthy)
```

---

## Part 9 — Open the app

Open a browser on any device on your home network and go to:

```
http://192.168.1.42:8080
```

*(Replace with your RPi's IP address)*

You should see the Achilles's Wines dashboard. 🎉

---

## Part 10 — Add it to the Home Assistant sidebar (optional)

If you want a shortcut in HA:

1. In HA, go to **Settings → Dashboards**
2. Click **Add dashboard** (the `+` button)
3. Choose **Webpage** (iframe)
4. Fill in:
   - **Title:** Achilles's Wines
   - **URL:** `http://192.168.1.42:8080`  *(your RPi IP)*
   - **Icon:** `mdi:glass-wine`
5. Click **Create**

The app now appears as an icon in your HA sidebar.

---

## Part 11 — Set up automatic daily backups

```bash
crontab -e
```

If it asks which editor, type `1` (nano) and press Enter.

Add this line at the bottom of the file:
```
0 2 * * * docker compose -f /share/achilles-wines/docker-compose.yml exec -T scraper bash scripts/backup.sh >> /share/achilles-wines/logs/backup.log 2>&1
```

Save and exit: **Ctrl+X**, **Y**, **Enter**.

This runs an encrypted backup every day at 2:00 AM.

---

## Auto-start after reboot

The `restart: unless-stopped` setting in `docker-compose.yml` means the containers
start automatically after a reboot. No extra configuration needed.

---

## Useful commands to know

Open the terminal (HA sidebar) and use these whenever needed:

| What you want to do | Command |
|---|---|
| Check if everything is running | `docker compose -f /share/achilles-wines/docker-compose.yml ps` |
| See recent log messages | `docker compose -f /share/achilles-wines/docker-compose.yml logs --tail=50` |
| Stop the app | `docker compose -f /share/achilles-wines/docker-compose.yml down` |
| Start the app again | `docker compose -f /share/achilles-wines/docker-compose.yml up -d` |
| Update to the latest version | `cd /share/achilles-wines && git pull && docker compose build && docker compose up -d` |
| Run a manual backup | `docker compose -f /share/achilles-wines/docker-compose.yml exec scraper bash scripts/backup.sh` |

---

## Troubleshooting

### "port is already allocated"
Port 8080 is used by something else. Edit `.env` and change `ACHILLES_HTTP_PORT=8080`
to `8081` or another number, then `docker compose up -d` again.

### "no space left on device"
Your SD card / SSD is full. Free up space or use a larger drive.

### The app opens but shows no wine data
The database is empty — you need to run the import (Part 7) or trigger a scraper run
from the **Admin → Jobs** page inside the app.

### The scraper shows errors in the log
This is often a temporary website issue. The retry + backoff system will try again
automatically up to 3 times. Check `/admin/jobs` in the app for details.

---

## Let Claude do it for you via SSH

If any of the steps above feel intimidating, you can ask Claude Code to do the
entire installation for you directly on your Raspberry Pi.

**What you need to provide:**

1. Your RPi's local IP address (e.g. `192.168.1.42`)
2. SSH credentials — either:
   - The root password you set in the Advanced SSH add-on, or
   - An SSH key pair (the add-on supports `authorized_keys`)

**How to enable SSH access from outside HA:**

In the Advanced SSH add-on configuration, make sure:
```yaml
ssh:
  username: root
  password: "YourChosenPassword"
  authorized_keys: []
  sftp: false
network:
  default: null
```
And in the **Network** tab of the add-on, set the port to `22` (or another port of your choice).

**Then just tell Claude:**
> "Here is my RPi IP: 192.168.1.42, SSH port 22, user root, password: [yourpassword].
> Please install Achilles's Wines for me."

Claude will connect, run every step in this guide, and confirm when the app is accessible.

> ⚠️ Only share SSH credentials in a private, trusted session.
> After the installation is complete, consider changing your SSH password.
