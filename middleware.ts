import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

// ─── Optional shared-secret access gate ──────────────────────────────────────
// DISABLED unless ACHILLES_ACCESS_TOKEN is set. On Home Assistant the add-on is
// fronted by HA ingress (which already enforces HA login), so this stays a
// no-op there — leave the env var unset. Set it ONLY for direct LAN / standalone
// (docker-compose) deployments that are not already behind HA or a VPN.
const ACCESS_TOKEN = process.env.ACHILLES_ACCESS_TOKEN;
const ACCESS_COOKIE = "achilles_access";

function isTrusted(req: NextRequest): boolean {
  if (!ACCESS_TOKEN) return true; // gate disabled
  // Trust Home Assistant ingress — it authenticates upstream.
  if (req.headers.get("x-ingress-path") || req.headers.get("x-hassio-ingress")) return true;
  if (req.cookies.get(ACCESS_COOKIE)?.value === ACCESS_TOKEN) return true;
  if (req.headers.get("authorization") === `Bearer ${ACCESS_TOKEN}`) return true;
  return false;
}

const LOGIN_HTML = `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Achilles's Wines — locked</title><style>body{font-family:system-ui,sans-serif;background:#0f0e17;color:#f7f4ea;display:grid;place-items:center;height:100vh;margin:0}form{display:flex;gap:.5rem}input{padding:.6rem .8rem;border-radius:8px;border:1px solid #a53860;background:#1a1825;color:#f7f4ea}button{padding:.6rem 1rem;border-radius:8px;border:0;background:#a53860;color:#0f0e17;font-weight:600;cursor:pointer}</style></head><body><form method="GET" action=""><input type="password" name="token" placeholder="Access token" autofocus /><button type="submit">Unlock</button></form></body></html>`;

export default function middleware(req: NextRequest) {
  const { pathname, searchParams } = req.nextUrl;

  if (ACCESS_TOKEN) {
    // Token login: ?token=… sets an httpOnly cookie, then redirects clean.
    const provided = searchParams.get("token");
    if (provided !== null) {
      const url = req.nextUrl.clone();
      url.searchParams.delete("token");
      const res = NextResponse.redirect(url);
      if (provided === ACCESS_TOKEN) {
        res.cookies.set(ACCESS_COOKIE, ACCESS_TOKEN, {
          httpOnly: true,
          sameSite: "lax",
          path: "/",
          maxAge: 60 * 60 * 24 * 30,
        });
      }
      return res;
    }
    if (!isTrusted(req)) {
      if (pathname.startsWith("/api")) {
        return NextResponse.json({ error: "unauthorized" }, { status: 401 });
      }
      return new NextResponse(LOGIN_HTML, {
        status: 401,
        headers: { "content-type": "text/html; charset=utf-8" },
      });
    }
  }

  // API routes are not locale-rewritten.
  if (pathname.startsWith("/api")) return NextResponse.next();
  return intlMiddleware(req);
}

export const config = {
  // Run on everything except Next internals and static files. NOTE: unlike the
  // previous matcher, `/api` is now included so the access gate can cover it.
  matcher: ["/((?!_next|_vercel|.*\\..*).*)"],
};
