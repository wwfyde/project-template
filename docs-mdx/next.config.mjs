// @ts-check
import * as path from 'path';
import * as url from 'url';
import { createRequire } from 'node:module';
import { withDeploymentConfig } from '@mui/internal-docs-infra/withDocsInfra';
import nextMdx from '@next/mdx';
import { ordering } from './src/utils/typeOrder.mjs';
import { siteConfig } from './src/site.config.mjs';

const baseDir = path.dirname(url.fileURLToPath(import.meta.url));

/**
 * @param {string} relativePath
 * @returns {string}
 */
const localPlugin = (relativePath) => path.join(baseDir, relativePath);

/** @type {NonNullable<import('@next/mdx').NextMDXOptions['options']>['remarkPlugins']} */
export const remarkPlugins = [
  'remark-gfm',
  [
    localPlugin('src/mdx/remarkDocumentMetadata.mjs'),
    {
      titleSuffix: ` · ${siteConfig.name}`,
      extractToIndex: {
        include: ['src/app/react'],
        baseDir,
        useVisibleDescription: true,
      },
    },
  ],
  // After metadata extraction so the index keeps `[Preview]`/`[New]` while rendered
  // headings turn those labels into badges.
  localPlugin('src/mdx/remarkHeadingTags.mjs'),
  'remark-typography',
  localPlugin('src/components/QuickNav/remarkQuickNavExcludeHeading.mjs'),
  '@mui/internal-docs-infra/pipeline/transformMarkdownRelativePaths',
  '@mui/internal-docs-infra/pipeline/transformMarkdownCode',
];

const withMdx = nextMdx({
  options: {
    remarkPlugins,
    rehypePlugins: [
      '@mui/internal-docs-infra/pipeline/transformHtmlCodeBlock',
      localPlugin('src/components/CodeBlock/rehypeEagerCodeBlocks.mjs'),
      '@mui/internal-docs-infra/pipeline/transformHtmlCodeInline',
      '@mui/internal-docs-infra/pipeline/enhanceCodeInline',
      localPlugin('src/components/QuickNav/rehypeSlug.mjs'),
      localPlugin('src/components/QuickNav/rehypeConcatHeadings.mjs'),
      '@stefanprobst/rehype-extract-toc',
      localPlugin('src/components/QuickNav/rehypeQuickNav.mjs'),
      localPlugin('src/components/Subtitle/rehypeSubtitle.mjs'),
      localPlugin('src/components/Kbd/rehypeKbd.mjs'),
    ],
  },
});

const require = createRequire(import.meta.url);
const baseUiPackage = require('@base-ui/react/package.json');

/** @type {import('@mui/internal-docs-infra/pipeline/loadPrecomputedTypes').LoaderOptions} */
const typesGenerationOptions = {
  updateParentIndex: {
    baseDir,
    onlyUpdateIndexes: true,
  },
  ordering,
  descriptionReplacements: [
    { pattern: '\\n\\nDocumentation: .*$', replacement: '', flags: 'm' },
    { pattern: 'Base UI', replacement: 'Base UI', flags: 'g' },
  ],
};

/** @type {import('next').NextConfig} */
const nextConfig = {
  trailingSlash: false,
  transpilePackages: ['@base-ui/react', '@base-ui/utils'],
  typescript: { ignoreBuildErrors: false },
  pageExtensions: ['mdx', 'tsx'],
  turbopack: {
    rules: {
      './src/app/**/types.ts': {
        as: '*.ts',
        loaders: [
          {
            loader: localPlugin('scripts/apiTypes/loadPrecomputedTypes.mjs'),
            options: typesGenerationOptions,
          },
        ],
      },
      './src/app/sitemap/index.ts': {
        as: '*.ts',
        loaders: [localPlugin('src/mdx/loadPrecomputedSitemap.mjs')],
      },
      './src/app/**/demos/*/index.ts': {
        as: '*.ts',
        loaders: [
          {
            loader: '@mui/internal-docs-infra/pipeline/loadPrecomputedCodeHighlighter',
            options: { emphasisOptions: { focusFramesMaxSize: 6 } },
          },
        ],
      },
    },
  },
  webpack: (config, { defaultLoaders }) => {
    // for production builds
    config.module.rules.push({
      test: /[/\\\\]src[/\\\\]app[/\\\\].*[/\\\\]types\.ts$/,
      use: [
        defaultLoaders.babel,
        {
          loader: localPlugin('scripts/apiTypes/loadPrecomputedTypes.mjs'),
          options: typesGenerationOptions,
        },
      ],
    });
    config.module.rules.push({
      test: /[/\\\\]sitemap[/\\\\]index\.ts$/,
      use: [defaultLoaders.babel, localPlugin('src/mdx/loadPrecomputedSitemap.mjs')],
    });
    config.module.rules.push({
      test: /[/\\\\]demos[/\\\\][^/\\\\]+[/\\\\]index\.ts$/,
      use: [
        defaultLoaders.babel,
        {
          loader: '@mui/internal-docs-infra/pipeline/loadPrecomputedCodeHighlighter',
          options: { emphasisOptions: { focusFramesMaxSize: 6 } },
        },
      ],
    });

    return config;
  },
  env: {
    // docs-infra
    LIB_VERSION: baseUiPackage.version,
    SOURCE_CODE_REPO: 'https://github.com/mui/base-ui',
    BASE_URL: process.env.BASE_URL || 'http://localhost:3005',
    SOURCE_CODE_REF: 'ddfc7a4581e0f0d75ecf01c1ba486a979527e9d4',
  },
  ...(process.env.NODE_ENV === 'production' && { output: 'export' }),
  devIndicators: false,
  agentRules: false,
  experimental: {
    globalNotFound: true,
    turbopackFileSystemCacheForBuild: true,
    // The TS7 side-by-side alias (@typescript/typescript6) ships no `tsc` bin,
    // which the Next.js >= 16.3 CLI checker requires. Use the TS6 JS API instead.
    useTypeScriptCli: false,
  },
};

const mergedConfig = withMdx(withDeploymentConfig(nextConfig));

mergedConfig.experimental = { ...mergedConfig.experimental, cpus: 4 };

export default mergedConfig;
