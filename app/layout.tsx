import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Achilles's Wines",
  description: "Vinothèque familiale, multi-source, multi-langue.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return children;
}
