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

// PWA is only applied in production builds — @ducanh2912/next-pwa modifies
// the webpack config in ways that break Turbopack's dev server even when
// disable:true is set. The manifest.json + icons are served statically anyway.
async function buildConfig() {
  if (process.env.NODE_ENV === "production") {
    const withPWAInit = (await import("@ducanh2912/next-pwa")).default;
    const withPWA = withPWAInit({
      dest: "public",
      register: true,
      workboxOptions: { disableDevLogs: true },
    });
    return withPWA(withNextIntl(nextConfig));
  }
  return withNextIntl(nextConfig);
}

export default await buildConfig();
