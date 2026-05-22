import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Achilles's Wines",
  description: "Vinothèque familiale, multi-source, multi-langue.",
  manifest: "/manifest.json",
  themeColor: "#1A0B2E",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Achilles",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
