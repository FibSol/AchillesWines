import type { NextConfig } from "next";
import createNextIntlPlugin from "next-intl/plugin";

const withNextIntl = createNextIntlPlugin("./i18n/request.ts");

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  experimental: {
    serverActions: { bodySizeLimit: "2mb" },
  },
  serverExternalPackages: ["better-sqlite3"],
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
