# Copying the dev database to the Home Assistant production Pi

This is the **proven** procedure for replacing the production database with the full
dev database. It was validated end-to-end on 2026-05-31.

> **Why not `scripts/migrate-dev-to-prod.ps1`?**
> That script assumes it can `ssh`/`scp` directly to `/data/achilles.db` on the Pi.
> That is **not** how this deployment works. Achilles runs as a **Home Assistant
> add-on**, and every add-on has an isolated `/data` that the SSH add-on container
> **cannot see**. External SSH auth to the box was also unreliable (see below).
> The script is still useful for the *snapshot-building* part; the *apply* part below
> replaces its SSH logic.

## Topology

- **Prod:** RPi 5 running Home Assistant, add-on slug **`59d464f5_achilles_wines`**,
  container **`addon_59d464f5_achilles_wines`**.
- **DB host path:** `/mnt/data/supervisor/addons/data/59d464f5_achilles_wines/achilles.db`
  (this is the add-on's `/data`).
- **Pi:** `192.168.0.251` · **Dev machine:** `192.168.0.6`.
- **Access:** frenck's **Advanced SSH & Web Terminal** add-on. The **web Terminal tab**
  (runs as root) is the reliable entry point. Docker/host access requires
  **Protection mode OFF** (toggle in the add-on's *Info* tab — turn it back ON when done).

### SSH gotchas (why we don't rely on external SSH)

- The configured SSH username is not a real `/etc/passwd` account; external key/password
  auth did not work from dev.
- The add-on **regenerates `authorized_keys` from its config on every restart**, so keys
  appended manually to `/root/.ssh/authorized_keys` or `/etc/ssh/authorized_keys` do not
  persist. (If you want persistent key auth, add the key in the add-on's *Configuration*.)

## Procedure

### 1. Build a clean snapshot (dev, PowerShell)

The live DB is in WAL mode and heavily fragmented (~1.5 GB). `VACUUM INTO` produces a
consistent, defragmented single file (~178 MB), which gzips to ~57 MB.

```powershell
$py = @'
import sqlite3, os, gzip, shutil, hashlib
dev  = r"C:/Claude/achilles-wines/data/achilles.db"
snap = r"C:/Claude/achilles-wines/data/_prodsnap_tmp.db"
gz   = r"C:/Claude/achilles-wines/data/achilles-prod-snapshot.db.gz"
for p in (snap, gz):
    if os.path.exists(p): os.remove(p)
src = sqlite3.connect(dev); src.execute("VACUUM INTO '" + snap.replace("'", "''") + "'"); src.close()
chk = sqlite3.connect(snap); res = chk.execute("PRAGMA integrity_check").fetchone()[0]; chk.close()
assert res == "ok", "integrity failed: " + res
with open(snap, "rb") as fi, gzip.open(gz, "wb", compresslevel=6) as fo:
    shutil.copyfileobj(fi, fo, 8*1024*1024)
os.remove(snap)
h = hashlib.sha256()
with open(gz, "rb") as f:
    for blk in iter(lambda: f.read(8*1024*1024), b""): h.update(blk)
print("integrity:", res, "| size_MB:", round(os.path.getsize(gz)/1048576,1), "| sha256:", h.hexdigest())
'@
$tmp = "$env:TEMP\build_snap.py"; [System.IO.File]::WriteAllText($tmp, $py, (New-Object System.Text.UTF8Encoding($false)))
& "C:\Claude\achilles-wines\scraper\.venv\Scripts\python.exe" $tmp; Remove-Item $tmp
```

Note the printed **sha256** — you verify it on the Pi in step 3.

### 2. Serve it on the LAN (dev, a second PowerShell window — leave it open)

External SSH doesn't work, so the Pi pulls the file over HTTP. Click **Allow** on the
Windows firewall prompt the first time.

```powershell
mkdir C:\Claude\_serve -Force | Out-Null
Copy-Item C:\Claude\achilles-wines\data\achilles-prod-snapshot.db.gz C:\Claude\_serve\
C:\Claude\achilles-wines\scraper\.venv\Scripts\python.exe -m http.server 8099 --directory C:\Claude\_serve
```

### 3. Pull + verify (Pi web Terminal)

```sh
wget -O /tmp/achilles-prod-snapshot.db.gz http://192.168.0.6:8099/achilles-prod-snapshot.db.gz
sha256sum /tmp/achilles-prod-snapshot.db.gz   # must equal the sha256 from step 1
```

### 4. Apply (Pi web Terminal — Protection mode OFF)

Stops the add-on, uses a throwaway `alpine` helper to mount the add-on's data dir,
backs up the current DB, swaps in the snapshot, clears the stale WAL/SHM, integrity-checks,
then restarts. **Full overwrite** — including `dim_source` and all `ops_*` (dev is the
single source of truth).

```sh
set -e
SLUG=59d464f5_achilles_wines
DATADIR=/mnt/data/supervisor/addons/data/$SLUG
GZ=/tmp/achilles-prod-snapshot.db.gz
TS=$(date +%Y%m%d-%H%M%S)

ls -la "$GZ"
ha addons stop "$SLUG"

docker rm -f achilles_xfer 2>/dev/null || true
docker run -d --name achilles_xfer -v "$DATADIR":/d alpine sleep 600 >/dev/null
docker cp "$GZ" achilles_xfer:/d/_snap.db.gz
docker exec -e TS="$TS" achilles_xfer sh -c '
  set -e; cd /d
  if [ -f achilles.db ]; then cp -a achilles.db "achilles.db.bak-$TS"; fi
  gunzip -c _snap.db.gz > achilles.db.new
  rm -f achilles.db-wal achilles.db-shm
  mv achilles.db.new achilles.db
  rm -f _snap.db.gz
  ls -la achilles.db
'
docker exec achilles_xfer sh -c 'apk add --no-cache sqlite >/dev/null 2>&1 && sqlite3 /d/achilles.db "PRAGMA integrity_check;" || echo "(integrity skipped)"'
docker rm -f achilles_xfer >/dev/null
ha addons start "$SLUG"
echo "APPLY DONE"
```

### 5. Verify + clean up

- Open the **Achilles** panel in HA and confirm data loads. Optional row-count check:
  ```sh
  docker run --rm -v /mnt/data/supervisor/addons/data/59d464f5_achilles_wines:/d:ro alpine \
    sh -c 'apk add --no-cache sqlite >/dev/null 2>&1; sqlite3 /d/achilles.db "SELECT COUNT(*) FROM dim_producer; SELECT COUNT(*) FROM dim_wine; SELECT COUNT(*) FROM fact_price;"'
  ```
- **Ctrl+C** the dev web-server window (closes the LAN exposure).
- Turn **Protection mode back ON** for the SSH add-on.
- Keep the rollback backup (`achilles.db.bak-<TS>` in the data dir) a few days, then delete.

### Rollback

```sh
ha addons stop 59d464f5_achilles_wines
docker run --rm -v /mnt/data/supervisor/addons/data/59d464f5_achilles_wines:/d alpine \
  sh -c 'cd /d && cp -a achilles.db.bak-<TS> achilles.db && rm -f achilles.db-wal achilles.db-shm'
ha addons start 59d464f5_achilles_wines
```
