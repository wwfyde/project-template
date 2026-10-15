import { create, insertMultiple, search } from '@orama/orama';
import { tokenizer } from '@orama/orama/components';
import { language, stemmer } from '@orama/stemmers/english';
import { resolvePageUrl } from '@mui/internal-docs-infra/resolvePageUrl';
import type {
  SearchResult,
  SearchResults,
  Sitemap,
  SitemapPage,
  SitemapSection,
  SitemapSectionData,
} from '@mui/internal-docs-infra/useSearch/types';

export interface DocsSearchResults {
  results: SearchResults;
  count: number;
  elapsed: { raw: number; formatted: string };
}

export const emptySearchResults: DocsSearchResults = {
  results: [],
  count: 0,
  elapsed: { raw: 0, formatted: '0ms' },
};

// Keep field names aligned with the sitemap's page, heading and API entries.
const boost = {
  type: 100,
  group: 100,
  slug: 2,
  path: 2,
  title: 2,
  page: 10,
  description: 1.5,
  part: 1.5,
  export: 1.3,
  types: 2,
  sectionTitle: 50,
  section: 3,
  subsection: 2.5,
  props: 1.5,
  dataAttributes: 1.5,
  cssVariables: 1.5,
  keywords: 1.5,
};
const schema = {
  ...(Object.fromEntries(Object.keys(boost).map((key) => [key, 'string'])) as {
    [Property in keyof typeof boost]: 'string';
  }),
  prefix: 'string' as const,
};

function createTokenizer() {
  const base = tokenizer.createTokenizer({
    stemming: true,
    language,
    stemmer,
    stemmerSkipProperties: [
      'type',
      'group',
      'slug',
      'sectionTitle',
      'page',
      'part',
      'export',
      'dataAttributes',
      'cssVariables',
      'props',
    ],
  });
  const segmenter = new Intl.Segmenter('zh-CN', { granularity: 'word' });

  return {
    ...base,
    tokenize(input: string, locale?: string, property?: string) {
      const chineseWords = Array.from(segmenter.segment(input))
        .filter((word) => word.isWordLike && /\p{Script=Han}/u.test(word.segment))
        .map((word) => word.segment);
      return [...new Set([...base.tokenize(input, locale, property), ...chineseWords])];
    },
  };
}

function pageEntries(page: SitemapPage, category: SitemapSectionData): SearchResult[] {
  const common = {
    path: page.path,
    prefix: category.prefix,
    sectionTitle: category.title,
    description: page.description,
    keywords: page.keywords?.join(' '),
  };
  const entries: SearchResult[] = [
    {
      ...common,
      type: 'page',
      group: `${category.title} Pages`,
      title: page.title,
      page: page.title,
      slug: page.slug,
      types: page.types?.join(' '),
    },
  ];

  for (const [name, part] of Object.entries(page.parts ?? {})) {
    entries.push({
      ...common,
      type: 'part',
      group: 'API Reference',
      title: [page.title, name].filter(Boolean).join(' ‣ '),
      slug: name.toLowerCase(),
      part: name,
      export: `${page.slug}.${name}`,
      props: part.props?.join(' '),
      dataAttributes: part.dataAttributes?.join(' '),
      cssVariables: part.cssVariables?.join(' '),
    });
  }
  for (const [name, item] of Object.entries(page.exports ?? {})) {
    entries.push({
      ...common,
      type: 'export',
      group: 'API Reference',
      title: name,
      slug: page.slug,
      export: name.toLowerCase() === page.slug.toLowerCase() ? 'api-reference' : name.toLowerCase(),
      props: item.props?.join(' '),
      dataAttributes: item.dataAttributes?.join(' '),
      cssVariables: item.cssVariables?.join(' '),
    });
  }

  function addHeadings(sections: Record<string, SitemapSection>, parents: string[] = []) {
    for (const [id, section] of Object.entries(sections)) {
      const titles = [...parents, section.title];
      const heading = {
        ...common,
        group: 'Sections',
        title: [page.title, ...titles].filter(Boolean).join(' ‣ '),
        // The index stores the rendered ID, including explicit IDs and duplicates.
        slug: `${page.slug}#${id}`,
      };
      entries.push(
        parents.length
          ? { ...heading, type: 'subsection', subsection: titles.join(' ‣ ') }
          : { ...heading, type: 'section', section: section.title },
      );
      addHeadings(section.children ?? {}, titles);
    }
  }
  addHeadings(page.sections ?? {});
  return entries;
}

export function buildResultUrl(result: SearchResult) {
  const url = resolvePageUrl(result.path, result.prefix);
  let hash = '';
  if (result.type === 'section' || result.type === 'subsection') {
    hash = result.slug.split('#')[1] ?? '';
  } else if (result.type === 'part') {
    hash = result.part.toLowerCase();
  } else if (result.type === 'export') {
    hash = result.export;
  }
  return hash ? `${url}#${hash}` : url;
}

export async function createDocsSearch(sitemap: Sitemap, showPrivatePages = false) {
  const entries: SearchResult[] = [];
  const groups = new Map<string, SearchResult[]>();
  for (const category of Object.values(sitemap.data)) {
    for (const page of category.pages) {
      if (!showPrivatePages && page.audience === 'private') {
        continue;
      }
      const flattened = pageEntries(page, category);
      const first = flattened[0];
      const group = first.group!;
      groups.set(group, [...(groups.get(group) ?? []), first]);
      entries.push(...flattened);
    }
  }

  const index = create({
    schema,
    components: { tokenizer: createTokenizer() },
  });
  // BM25 handles optional sitemap fields directly; no QPS dummy documents needed.
  await insertMultiple(index, entries);
  const defaultResults: DocsSearchResults = {
    ...emptySearchResults,
    results: Array.from(groups, ([group, items]) => ({ group, items })),
    count: Array.from(groups.values()).reduce((count, items) => count + items.length, 0),
  };

  return {
    defaultResults,
    async search(value: string): Promise<DocsSearchResults> {
      const term = value.trim();
      if (!term) {
        return defaultResults;
      }
      const normalized = term.toLowerCase().replace(/[-\s]+/g, ' ');
      function matchRank(document: { title?: string; slug: string }) {
        const fields = [document.title ?? '', document.slug].map((field) =>
          field.toLowerCase().replace(/[-\s]+/g, ' '),
        );
        if (fields.some((field) => field === normalized)) return 3;
        if (fields.some((field) => field.startsWith(normalized))) return 2;
        return fields.some((field) => field.includes(normalized)) ? 1 : 0;
      }
      const matches = await search(index, {
        term,
        boost,
        tolerance: 0,
        limit: 20,
        groupBy: { properties: ['group'], maxResult: 5 },
        sortBy:
          term.length <= 20
            ? ([, leftScore, left], [, rightScore, right]) =>
                matchRank(right) - matchRank(left) || rightScore - leftScore
            : undefined,
      });
      return {
        count: matches.count,
        elapsed: matches.elapsed,
        results: (matches.groups ?? []).map((group) => ({
          group: group.values.join(' '),
          items: group.result.map(
            (hit) =>
              ({
                ...hit.document,
                id: hit.id,
                score: hit.score,
              }) as SearchResult,
          ),
        })),
      };
    },
  };
}
