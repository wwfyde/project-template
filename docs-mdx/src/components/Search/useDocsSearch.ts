'use client';
import * as React from 'react';
import { useStableCallback } from '@base-ui/utils/useStableCallback';
import type { SearchSitemapLoader } from './searchSitemap';
import { buildResultUrl, createDocsSearch, emptySearchResults } from './docsSearchIndex';

const showPrivatePages = process.env.SHOW_PRIVATE_PAGES === 'true';

export function useDocsSearch(sitemap: SearchSitemapLoader, searchValue: string) {
  const [engine, setEngine] = React.useState<Awaited<ReturnType<typeof createDocsSearch>>>();
  const [acceptedResults, setAcceptedResults] = React.useState(emptySearchResults);
  const [completedSearchId, setCompletedSearchId] = React.useState(0);
  const lastReadySearchValueRef = React.useRef('');
  const latestSearchIdRef = React.useRef(0);
  const hasQuery = searchValue.trim() !== '';
  const isReady = engine !== undefined;
  const defaultResults = engine?.defaultResults ?? emptySearchResults;

  React.useEffect(() => {
    let active = true;
    setEngine(undefined);
    lastReadySearchValueRef.current = '';
    void sitemap().then(async ({ sitemap: data }) => {
      if (!data) return;
      const nextEngine = await createDocsSearch(data, showPrivatePages);
      if (active) {
        setEngine(nextEngine);
        setAcceptedResults(nextEngine.defaultResults);
      }
    });
    return () => {
      active = false;
    };
  }, [sitemap]);

  const performSearch = useStableCallback(async (value: string) => {
    const searchId = latestSearchIdRef.current + 1;
    latestSearchIdRef.current = searchId;
    lastReadySearchValueRef.current = isReady && value.trim() ? value : '';
    const results = (await engine?.search(value)) ?? defaultResults;
    if (searchId === latestSearchIdRef.current) {
      setAcceptedResults(results);
      setCompletedSearchId(searchId);
    }
  });

  // The search index is built lazily, so a query typed before it is ready runs
  // against nothing. Replay the latest query once the index becomes ready.
  React.useEffect(() => {
    if (!hasQuery) {
      lastReadySearchValueRef.current = '';
      return;
    }

    if (!isReady || lastReadySearchValueRef.current === searchValue) {
      return;
    }

    lastReadySearchValueRef.current = searchValue;
    void performSearch(searchValue);
  }, [hasQuery, isReady, performSearch, searchValue]);

  // A query typed before the lazy index is ready is still pending: results have
  // collapsed to the defaults, so treat not-ready-yet the same as in-flight to
  // avoid rendering the default list under a real query.
  const isSearchPending = hasQuery && (!isReady || completedSearchId !== latestSearchIdRef.current);

  return {
    results: acceptedResults,
    defaultResults,
    buildResultUrl,
    isReady,
    hasQuery,
    isSearchPending,
    search: performSearch,
    performSearch,
  };
}
