import {defineConfig} from 'oxfmt'

export default defineConfig({
  semi: false,
  printWidth: 100,
  singleQuote: true,
  trailingComma: 'all',
  proseWrap: 'never',
  importOrder: ['^@core/(.*)$', '^@server/(.*)$', '^@ui/(.*)$', '^[./]'],
  importOrderSeparation: true,
  importOrderSortSpecifiers: true,
})
