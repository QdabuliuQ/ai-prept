import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config([
  {
    ignores: [
      "node_modules/**",
      "frontend/dist/**",
      "frontend/postcss.config.js",
      "frontend/tailwind.config.js",
      "ppt-master/**",
      "backend/**",
      "agent-output/**",
      ".agent-output/**",
      "frontend/public/slide-editor/**",
      "frontend/public/slide-vendor/**",
      "scripts/build-slide-editor.js",
      "scripts/slide-vendor.tailwind.config.js",
    ],
  },
  {
    files: ["**/*.{js,jsx,ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    plugins: {
      "react-hooks": reactHooks,
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "@typescript-eslint/no-unused-vars": [
        "error",
        {
          argsIgnorePattern: "^_",
          varsIgnorePattern: "^_",
        },
      ],
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
]);
