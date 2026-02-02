import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

export default defineConfig([
  globalIgnores(['dist', '**/dist/**']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    rules: {
      // BeadHub is a multi-package workspace; Fast Refresh boundaries are not a correctness signal.
      'react-refresh/only-export-components': 'off',
      // This rule is too strict for our current UI patterns; revisit after OSS release hardening.
      'react-hooks/set-state-in-effect': 'off',
      // React Compiler is not currently enabled; keep this as a warning so it doesn't block CI.
      'react-hooks/preserve-manual-memoization': 'warn',
    },
    languageOptions: {
      ecmaVersion: 2020,
      globals: globals.browser,
    },
  },
])
