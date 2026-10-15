// @vitest-environment jsdom
import * as React from 'react';
import { act } from 'react';
import { createRoot } from 'react-dom/client';
import { expect, it, vi } from 'vitest';
import { useDocsSearch } from './useDocsSearch';

const loadSitemap = async () => ({
  sitemap: {
    schema: {},
    data: {
      Handbook: {
        title: '指南',
        prefix: '/react/handbook/',
        sections: [],
        pages: [
          {
            title: '编写文档',
            slug: 'writing-docs',
            path: './writing-docs/page.mdx',
            description: '项目指南',
            keywords: ['components'],
            section: null,
            // Real sitemap section keys are the rendered heading IDs.
            sections: { 代码块: { title: '代码块' } },
          },
        ],
      },
    },
  },
});

it('searches a sparse sitemap in Chinese and English without API type entries', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  let api: ReturnType<typeof useDocsSearch>;
  function Probe() {
    api = useDocsSearch(loadSitemap, '');
    return null;
  }

  try {
    await act(async () => root.render(<Probe />));
    expect(api!.isReady).toBe(true);

    await act(async () => api!.performSearch('component'));
    expect(api!.results.count).toBeGreaterThan(0);

    await act(async () => api!.performSearch('代码块'));
    const result = api!.results.results
      .flatMap((group) => group.items)
      .find((item) => item.type === 'section');
    expect(result).toBeDefined();
    expect(api!.buildResultUrl(result!)).toBe('/react/handbook/writing-docs#代码块');
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});

it('replays a query typed before the lazy sitemap is ready and resets on close', async () => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true);
  const container = document.createElement('div');
  const root = createRoot(container);
  let resolveSitemap: (sitemap: Awaited<ReturnType<typeof loadSitemap>>) => void;
  const pendingSitemap = new Promise<Awaited<ReturnType<typeof loadSitemap>>>((resolve) => {
    resolveSitemap = resolve;
  });
  const loader = () => pendingSitemap;
  let api: ReturnType<typeof useDocsSearch>;
  function Probe({ value }: { value: string }) {
    api = useDocsSearch(loader, value);
    return null;
  }

  try {
    await act(async () => root.render(<Probe value="代码块" />));
    expect(api!.isReady).toBe(false);
    expect(api!.hasQuery).toBe(true);
    expect(api!.isSearchPending).toBe(true);

    await act(async () => resolveSitemap!(await loadSitemap()));
    expect(api!.isReady).toBe(true);
    expect(api!.isSearchPending).toBe(false);
    expect(api!.results.results.flatMap((group) => group.items)).toContainEqual(
      expect.objectContaining({ type: 'section', title: '编写文档 ‣ 代码块' }),
    );

    await act(async () => {
      root.render(<Probe value="" />);
      await api!.performSearch('');
    });
    expect(api!.results).toBe(api!.defaultResults);
    expect(api!.hasQuery).toBe(false);
  } finally {
    await act(async () => root.unmount());
    container.remove();
    vi.unstubAllGlobals();
  }
});
