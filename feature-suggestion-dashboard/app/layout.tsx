import "./globals.css";
export const metadata = {
  title: "Matiks · Feature requests",
  description: "Feature requests and module summaries",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
