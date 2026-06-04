import "./globals.css";

const themeInitScript = `
(() => {
  const storageKey = "solus-theme";
  const storedTheme = window.localStorage.getItem(storageKey);
  const preferredTheme = window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
  const theme = storedTheme === "light" || storedTheme === "dark"
    ? storedTheme
    : preferredTheme;

  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
})();
`;

export const metadata = {
  title: "Solus Forge | Robotics Development Environment",
  description:
    "The robotics development environment built for real-world complexity. Forge unifies mechanical, electrical, software, and simulation context so your team ships faster.",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link
          href="https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;1,300&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
