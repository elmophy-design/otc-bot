import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "OTC Intelligence",
  description: "Premium OTC trading intelligence dashboard"
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}