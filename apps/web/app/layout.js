import "./globals.css";

const themeInitScript = `
(() => {
  const storageKey = "solus-theme";
  const storedTheme = window.localStorage.getItem(storageKey);
  const theme = storedTheme === "light" || storedTheme === "dark"
    ? storedTheme
    : "dark";

  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
`;

export const metadata = {
  title: "Solus | The Robotics Context Layer",
  description:
    "Solus connects GitHub, KiCad, Onshape, and ROS into one living graph of your robot — and catches cross-domain problems before they break hardware.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          rel="preconnect"
          href="https://fonts.gstatic.com"
          crossOrigin="anonymous"
        />
        <link
          href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap"
          rel="stylesheet"
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
