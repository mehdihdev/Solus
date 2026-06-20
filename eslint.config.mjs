import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import prettier from "eslint-config-prettier";
import globals from "globals";

export default tseslint.config(
  {
    ignores: [
      "**/dist/**",
      "**/out/**",
      "**/.next/**",
      "**/node_modules/**",
      "**/.venv/**",
      "**/coverage/**",
      "**/release/**"
    ]
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/explicit-module-boundary-types": "warn",
      complexity: ["error", 10],
      "max-lines-per-function": ["warn", 80],
      "no-console": ["warn", { allow: ["warn", "error"] }]
    }
  },
  {
    files: ["**/*.js", "**/*.mjs", ".claude/hooks/**/*.js", "apps/web/**/*.js"],
    languageOptions: {
      globals: {
        ...globals.node,      // process, console, etc.
      },
    },
  },
  {
    files: ["apps/web/**/*.{js,jsx,ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,   // Response, fetch, etc. for Next.js
        ...globals.node,
      },
    },
  },
  { ignores: ["**/dist/**", "**/.next/**", "**/node_modules/**", ".claude/**"] },
  prettier
);
