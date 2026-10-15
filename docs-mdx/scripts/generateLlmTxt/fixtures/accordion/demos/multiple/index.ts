import { createDemoWithVariants } from 'docs-mdx/src/utils/createDemo';
import CssModules from './css-modules';
import Tailwind from './tailwind';

export const DemoAccordionMultiple = createDemoWithVariants(import.meta.url, {
  CssModules,
  Tailwind,
});
