import { promises as fs } from "node:fs";
import path from "node:path";

// Best-effort append-only audit log for sensitive mutations (job triggers, DLQ
// resolutions, data promotion, etc.). NEVER throws — auditing must not break the
// request path. Single-instance / local file under logs/audit.log.
const AUDIT_FILE = path.resolve(process.cwd(), "logs", "audit.log");

type HeaderBag = { get(name: string): string | null };

export async function audit(
  action: string,
  details: Record<string, unknown> = {},
  req?: { headers: HeaderBag }
): Promise<void> {
  try {
    const ip =
      (req?.headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim() || "local";
    const line =
      JSON.stringify({ ts: new Date().toISOString(), action, ip, ...details }) + "\n";
    await fs.mkdir(path.dirname(AUDIT_FILE), { recursive: true });
    await fs.appendFile(AUDIT_FILE, line, "utf8");
  } catch {
    // swallow — auditing is best-effort and must never fail a request
  }
}
