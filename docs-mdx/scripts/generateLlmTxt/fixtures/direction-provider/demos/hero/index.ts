import { createDemoWithVariants } from 'docs-mdx/src/utils/createDemo';
import CssModules from './css-modules';
import Tailwind from './tailwind';

export const DemoDirectionProviderHero = createDemoWithVariants(
  import.meta.url,
  { CssModules, Tailwind },
  { highlightAfter: 'init', enhanceAfter: 'init' },
);
