import { defineConfig } from 'oxlint'

export default defineConfig({
  options: {
    typeAware: true,
    typeCheck: true,
    maxWarnings: 10,
  },
  categories: {
    correctness: 'warn',
  },
  env: {
    builtin: true,
  },
  plugins: ["react", "typescript", "oxc"],
  ignorePatterns: ['dist'],
  rules: {
    "react/rules-of-hooks": "error",
    "react/only-export-components": ["warn", { "allowConstantExport": true }],
    'no-alert': 'error',
    'oxc/approx-constant': 'warn',
    'no-plusplus': 'off',
    'eslint/prefer-const': ['error', { destructuring: 'any' }],
    'eslint/no-unused-vars': 'error',
  },
})
