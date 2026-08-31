// ESLint flat config (v9+). Q8 of docs/specs/engineering-governance-optimization.
//
// This is the FIRST eslint enablement for web/ — previously package.json had a
// `lint` script but eslint was never installed and no config existed, so
// `npm run lint` always failed. This config is intentionally permissive
// (non-blocking baseline): it wires up vue + ts parsing and surfaces issues
// without a large upfront fix. Tightening path: add stricter rule sets
// (eslint:recommended, plugin:vue/vue3-recommended, ts recommended) gradually.
import js from "@eslint/js";
import tseslint from "typescript-eslint";
import pluginVue from "eslint-plugin-vue";

export default [
  // Ignore build output + deps (flat config does not inherit .gitignore).
  { ignores: ["dist/**", "node_modules/**", "test-results/**"] },

  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/essential"],

  // Vue parser 负责 SFC 外壳，TypeScript parser 负责 <script setup lang="ts">。
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
        extraFileExtensions: [".vue"],
      },
    },
  },

  // Project-specific relaxations for the baseline pass.
  {
    rules: {
      // Vue SFC <script> is TS; let vue parser + ts-eslint handle it.
      "vue/multi-word-component-names": "off",
      // Allow console in dev tooling (frontend logs are intentional).
      "no-console": "off",
      // ts-eslint `no-explicit-any` fires on many existing signatures; warn
      // only for the baseline so the config is adoptable.
      "@typescript-eslint/no-explicit-any": "warn",
      // Unused vars are common in refactors; warn rather than error.
      "@typescript-eslint/no-unused-vars": ["warn", { argsIgnorePattern: "^_" }],
    },
  },

  // Vite 的标准 Vue shim 必须使用 DefineComponent 的开放泛型。
  {
    files: ["**/*.d.ts"],
    rules: {
      "@typescript-eslint/no-empty-object-type": "off",
      "@typescript-eslint/no-explicit-any": "off",
    },
  },
];
