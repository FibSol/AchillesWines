import { NextRequest, NextResponse } from "next/server";
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { audit } from "@/lib/audit";

// child_process is only available in the Node.js runtime, not Edge.
export const runtime = "nodejs";

// "Process queue now" button (HA add-on). The web server and the Python worker
// share one container there, so we can spawn a bounded one-shot drain:
//   python -m achilles_scraper.cli run-jobs --once
// The argv is fixed (no request input is interpolated), so there is no command
// injection surface. In docker-compose the worker is a separate container and
// runs continuously — this endpoint is for the single-container HA topology.

// Debounce rapid double-clicks: ignore a second spawn within this window.
const SPAWN_DEBOUNCE_MS = 10_000;
let lastSpawnAt = 0;

function resolvePython(): string {
  const override = process.env.ACHILLES_WORKER_PYTHON?.trim();
  if (override) return override;
  // Dev convenience: prefer the scraper/.venv interpreter if present.
  const scraperDir = path.resolve(process.cwd(), "scraper");
  const venvWin = path.join(scraperDir, ".venv", "Scripts", "python.exe");
  const venvPosix = path.join(scraperDir, ".venv", "bin", "python");
  if (existsSync(venvWin)) return venvWin;
  if (existsSync(venvPosix)) return venvPosix;
  // HA add-on / docker image: the package is pip-installed, python is on PATH.
  return "python";
}

export async function POST(req: NextRequest) {
  const now = Date.now();
  if (now - lastSpawnAt < SPAWN_DEBOUNCE_MS) {
    return NextResponse.json(
      { started: false, reason: "A drain was just started — give it a moment." },
      { status: 429 }
    );
  }

  const python = resolvePython();
  // Run from scraper/ when present so `-m achilles_scraper.cli` resolves even if
  // the package isn't pip-installed (dev); in the container cwd doesn't matter.
  const scraperDir = path.resolve(process.cwd(), "scraper");
  const cwd = existsSync(scraperDir) ? scraperDir : process.cwd();

  try {
    const child = spawn(python, ["-m", "achilles_scraper.cli", "run-jobs", "--once"], {
      cwd,
      detached: true,
      stdio: "ignore",
    });

    // Let the drain outlive this request.
    child.unref();

    if (typeof child.pid !== "number") {
      throw new Error("spawn returned no pid");
    }

    lastSpawnAt = now;
    await audit("worker.run", { pid: child.pid, python }, req);
    return NextResponse.json({ started: true, pid: child.pid });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Failed to start worker";
    return NextResponse.json(
      {
        started: false,
        error: `Could not launch the worker (${python}): ${message}. ` +
          `Set ACHILLES_WORKER_PYTHON to a Python with achilles-scraper installed.`,
      },
      { status: 500 }
    );
  }
}
