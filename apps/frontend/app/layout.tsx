import type { Metadata } from "next";
import "./globals.css";
import { StoreProvider } from "@/components/providers/store-provider";

export const metadata: Metadata = {
  title: "Ithute Pay",
  description: "Centralized payment infrastructure for Ithute and external projects by Ithute Solutions",
  icons: { icon: "/brand/ithute-pay-bridge-icon.svg" },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body><StoreProvider>{children}</StoreProvider></body></html>;
}
