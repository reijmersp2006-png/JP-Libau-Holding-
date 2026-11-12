import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import { Shell } from "@/components/Shell";
import "./globals.css";

export const metadata: Metadata = {
  title: "NEXUS AI · Command Center",
  description: "Multi-asset research- en handelsplatform van JP-libau Holding. Live handelen staat uit.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="nl" className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}>
      <body className="min-h-full font-sans">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
