import js from "@eslint/js";
import tseslint from "typescript-eslint";
import reactHooks from "eslint-plugin-react-hooks";
import prettier from "eslint-config-prettier";

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
  prettier
);
