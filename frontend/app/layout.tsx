import type { Metadata } from "next";
import "./globals.css";
import "./chat-scroll.css";
import "./chat-history.css";

export const metadata: Metadata = {
  title: "Olladex — Local AI Development Agent",
  description: "Codex-style development workspace powered by Ollama",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}

