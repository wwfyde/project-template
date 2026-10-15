import { redirect } from 'next/navigation';
import { siteConfig } from 'docs-mdx/src/site.config.mjs';

export default function IndexPage() {
  redirect(siteConfig.entryPath);
}
