import type { Metadata } from "next";
import { Space_Grotesk, DM_Sans } from "next/font/google";
import "../globals.css";

const spaceGrotesk = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-heading",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MaluDb — Your team, connected",
  description: "MaluDb Agent View: your organisation's people and AI agents, in orbit.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${spaceGrotesk.variable} ${dmSans.variable}`}>
      <body>{children}</body>
    </html>
  );
}
