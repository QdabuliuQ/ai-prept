import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config([
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "out/**",
      "next-env.d.ts",
      // Third-party / generated / vendored (not app source)
      "ppt-master/**",
      "agent/.venv/**",
      "public/slide-editor/**",
      "public/slide-vendor/**",
      "scripts/build-slide-editor.js",
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
