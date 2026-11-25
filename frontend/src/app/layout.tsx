import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "VibeBench",
  description: "Same prompt. Different models. Real applications.",
  referrer: "no-referrer",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
