import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Athar AI — أثر",
  description: "Organizational decision intelligence for Arabic-English teams.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
