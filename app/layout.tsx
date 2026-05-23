import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Achilles's Wines",
  description: "Vinothèque familiale, multi-source, multi-langue.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Achilles",
  },
};

export const viewport: Viewport = {
  themeColor: "#1A0B2E",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
