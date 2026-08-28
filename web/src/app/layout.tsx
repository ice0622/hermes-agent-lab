import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "筋トレ",
  description: "記録から次のメニューを組み、積み上がっているかを見る",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="ja">
      <body>{children}</body>
    </html>
  );
}
