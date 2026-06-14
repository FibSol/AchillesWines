// Dev convenience: launch the Python scraper job runner (the queue consumer).
//
// The Next.js app only ENQUEUES jobs into ops_job_queue. This worker is the
// separate process that polls the queue and actually runs scrapers. Without it
// running, manually-added scrapers sit in "queued" forever.
//
//   npm run worker      → just the worker
//   npm run dev:all     → Next.js dev server + worker together (via concurrently)
//
// Resolves the scraper/.venv interpreter automatically (Windows or POSIX) and
// falls back to whatever `python` is on PATH, with a clear error if neither works.

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const scraperDir = join(repoRoot, "scraper");

const venvWin = join(scraperDir, ".venv", "Scripts", "python.exe");
const venvPosix = join(scraperDir, ".venv", "bin", "python");

let python;
if (existsSync(venvWin)) python = venvWin;
else if (existsSync(venvPosix)) python = venvPosix;
else python = process.platform === "win32" ? "python" : "python3";

if (python === "python" || python === "python3") {
  console.warn(
    `[worker] No scraper/.venv found — falling back to '${python}' on PATH. ` +
      `If imports fail, create the venv: cd scraper && python -m venv .venv && .venv/Scripts/pip install -e .`
  );
}

console.log(`[worker] Starting job runner: ${python} -m achilles_scraper.cli run-jobs (cwd=${scraperDir})`);

const child = spawn(python, ["-m", "achilles_scraper.cli", "run-jobs"], {
  cwd: scraperDir,
  stdio: "inherit",
});

child.on("error", (err) => {
  console.error(`[worker] Failed to launch interpreter '${python}': ${err.message}`);
  process.exit(1);
});
child.on("exit", (code) => process.exit(code ?? 0));

// Forward Ctrl-C so the worker shuts down cleanly with the parent.
for (const sig of ["SIGINT", "SIGTERM"]) {
  process.on(sig, () => child.kill(sig));
}
