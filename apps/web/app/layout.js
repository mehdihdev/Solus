export const metadata = {
  title: "Solus | The Greatest Robotics Tool You Could Ever Have",
  description:
    "Solus links your repos, CAD files, schematics, and live telemetry into a single multimodal context — so that you, your team, and your agents get to work on what's actually important.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
