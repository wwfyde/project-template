import { createSitemap } from '@mui/internal-docs-infra/createSitemap';
import Overview from '../(docs)/react/overview/page.mdx';
import Handbook from '../(docs)/react/handbook/page.mdx';
import Components from '../(docs)/react/components/page.mdx';

export const sitemap = createSitemap(import.meta.url, {
  开始使用: Overview,
  写作指南: Handbook,
  示例组件: Components,
});
