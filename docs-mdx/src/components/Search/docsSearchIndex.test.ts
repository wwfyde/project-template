import { expect, it } from 'vitest';
import type { Sitemap } from '@mui/internal-docs-infra/useSearch/types';
import { buildResultUrl, createDocsSearch } from './docsSearchIndex';

const sitemap: Sitemap = {
  schema: {},
  data: {
    Components: {
      title: 'React Components',
      prefix: '/react/',
      sections: [],
      pages: [
        {
          title: 'Checkbox',
          slug: 'checkbox',
          path: './(components)/checkbox/page.mdx',
          section: null,
          types: ['CheckboxChangeEventDetails'],
          parts: {
            Root: {
              props: ['onCheckedChange', 'checked'],
              dataAttributes: ['data-indeterminate'],
              cssVariables: ['--checkbox-size'],
            },
          },
          exports: { Checkbox: { props: ['defaultChecked'] } },
          sections: {
            中文示例: {
              title: '中文示例',
              children: { 受控复选框: { title: '受控复选框' } },
            },
          },
        },
        {
          title: 'Internal',
          slug: 'internal',
          path: './internal/page.mdx',
          section: null,
          audience: 'private',
        },
      ],
    },
    Resources: {
      title: 'Resources',
      prefix: '/',
      sections: [],
      pages: [{ title: 'LLM Guide', slug: 'llms', path: '/llms.txt', section: null }],
    },
  },
};

it('keeps default category order, hides private pages and resets an empty query', async () => {
  const engine = await createDocsSearch(sitemap);
  expect(engine.defaultResults.count).toBe(2);
  expect(engine.defaultResults.results.map((group) => group.group)).toEqual([
    'React Components Pages',
    'Resources Pages',
  ]);
  expect(await engine.search('  ')).toBe(engine.defaultResults);
  expect((await engine.search('internal')).count).toBe(0);
  expect(buildResultUrl(engine.defaultResults.results[1].items[0])).toBe('/llms.txt');

  const internalEngine = await createDocsSearch(sitemap, true);
  expect(internalEngine.defaultResults.count).toBe(3);
  expect((await internalEngine.search('internal')).count).toBe(1);
});

it('finds API type names, props, data attributes and CSS variables with working anchors', async () => {
  const engine = await createDocsSearch(sitemap);
  const types = await engine.search('CheckboxChangeEventDetails');
  expect(types.results.flatMap((group) => group.items)).toContainEqual(
    expect.objectContaining({ type: 'page', title: 'Checkbox' }),
  );
  for (const term of ['onCheckedChange', 'data-indeterminate', '--checkbox-size']) {
    const matches = await engine.search(term);
    const part = matches.results
      .flatMap((group) => group.items)
      .find((item) => item.type === 'part');
    expect(part, term).toBeDefined();
    expect(buildResultUrl(part!)).toBe('/react/checkbox#root');
  }
  const exports = await engine.search('defaultChecked');
  const result = exports.results
    .flatMap((group) => group.items)
    .find((item) => item.type === 'export');
  expect(result).toBeDefined();
  expect(buildResultUrl(result!)).toBe('/react/checkbox#api-reference');
});

it('finds Chinese words inside nested headings and preserves indexed heading IDs', async () => {
  const engine = await createDocsSearch(sitemap);
  const matches = await engine.search('复选框');
  const heading = matches.results
    .flatMap((group) => group.items)
    .find((item) => item.type === 'subsection');
  expect(heading?.title).toBe('Checkbox ‣ 中文示例 ‣ 受控复选框');
  expect(buildResultUrl(heading!)).toBe('/react/checkbox#受控复选框');

  const releaseSitemap = structuredClone(sitemap);
  releaseSitemap.data.Components.pages[0].sections = {
    'v1-0-0': {
      title: 'v1.0.0',
      children: {
        'custom-id': { title: '中文更新' },
        '中文更新-1': { title: '中文更新' },
      },
    },
  };
  const releases = await createDocsSearch(releaseSitemap);
  const results = (await releases.search('中文更新')).results
    .flatMap((group) => group.items)
    .filter((item) => item.type === 'subsection');
  expect(results.map(buildResultUrl)).toEqual(
    expect.arrayContaining(['/react/checkbox#custom-id', '/react/checkbox#中文更新-1']),
  );
});

it('limits each search group while retaining every page in the default results', async () => {
  const manyPages: Sitemap = {
    schema: {},
    data: {
      Guides: {
        title: 'Guides',
        prefix: '/',
        sections: [],
        pages: Array.from({ length: 8 }, (_, index) => ({
          title: index === 7 ? 'Guide' : `Guide ${index}`,
          slug: index === 7 ? 'guide' : `guide-${index}`,
          path: `./guide-${index}/page.mdx`,
          section: null,
        })),
      },
    },
  };
  const engine = await createDocsSearch(manyPages);
  expect(engine.defaultResults.results[0].items).toHaveLength(8);
  const matches = await engine.search('guide');
  expect(matches.count).toBe(8);
  expect(matches.results[0].items).toHaveLength(5);
  expect(matches.results[0].items[0].title).toBe('Guide');
});
