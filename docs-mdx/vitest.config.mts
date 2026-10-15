import { defineConfig } from 'vitest/config';

export default defineConfig({
  // Next.js preserves JSX for its compiler; component tests need Vite to transform it.
  oxc: {
    jsx: { runtime: 'automatic' },
  },
  resolve: {
    dedupe: ['react', 'react-dom'],
    alias: {
      'docs-mdx': import.meta.dirname,
    },
  },
  test: {
    name: 'docs-mdx',
    root: import.meta.dirname,
    include: ['src/**/*.test.{ts,tsx,mjs}', 'scripts/**/*.test.mjs'],
    environment: 'node',
    server: {
      deps: {
        inline: [/@base-ui\/utils/],
      },
    },
    environmentOptions: {
      jsdom: {
        pretendToBeVisual: true,
        url: 'http://localhost',
      },
    },
    env: {
      VITEST_ENV: 'node',
    },
  },
});
