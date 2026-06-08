import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

// Security headers. Deliberately HA-friendly:
//  • NO X-Frame-Options / frame-ancestors — the add-on renders inside an HA
//    ingress iframe, so framing must stay allowed.
//  • NO HSTS — TLS is terminated by HA/edge, not this app.
//  • Permissions-Policy keeps camera=(self) because the OCR label-scan needs it.
//  • CSP is permissive (allows inline/eval + https) to avoid breaking Next, Recharts,
//    next/font and the CartoDB dark map tiles — tighten with nonces later if desired.
const CSP = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https:",
  "font-src 'self' data:",
  "connect-src 'self' https: ws: wss:",
  "base-uri 'self'",
  "form-action 'self'",
  "object-src 'none'",
].join("; ");

const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: CSP },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
  { key: "X-DNS-Prefetch-Control", value: "off" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
  serverExternalPackages: ["better-sqlite3"],
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

const base = withNextIntl(nextConfig);

// PWA only in production — @ducanh2912/next-pwa modifies the webpack config in
// ways that break Turbopack dev-server navigation. Cannot use top-level await in
// next.config.ts (ERR_REQUIRE_ASYNC_MODULE), so we use a synchronous require().
function applyPWA(config: NextConfig): NextConfig {
  if (process.env.NODE_ENV !== "production") return config;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const withPWAInit = require("@ducanh2912/next-pwa").default as (
    opts: object
  ) => (c: NextConfig) => NextConfig;
  return withPWAInit({
    dest: "public",
    register: true,
    workboxOptions: { disableDevLogs: true },
  })(config);
}

export default applyPWA(base);
