import { readFile, readdir } from 'node:fs/promises';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const outputDirectory = path.resolve(import.meta.dirname, '../out');
const siteOrigin = 'http://docs-mdx.local';

interface HtmlPage {
  file: string;
  url: URL;
  anchors: Set<string>;
  links: { href: string; typeRef: string | null }[];
}

async function listFiles(directory: string, prefix = ''): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map(async (entry) => {
      const relativePath = path.posix.join(prefix, entry.name);
      return entry.isDirectory()
        ? listFiles(path.join(directory, entry.name), relativePath)
        : [relativePath];
    }),
  );
  return files.flat();
}

async function main() {
  let files: string[];
  try {
    files = await listFiles(outputDirectory);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      throw new Error('Static export not found. Run pnpm --filter docs-mdx build first.');
    }
    throw error;
  }

  const allFiles = new Set(files);
  const pages = new Map<string, HtmlPage>();

  // Close each document after extracting links so a full-site check stays small in memory.
  for (const file of files.filter((name) => name.endsWith('.html'))) {
    const route = `/${file}`.replace(/\/index\.html$/, '/').replace(/\.html$/, '');
    const url = new URL(route, siteOrigin);
    const dom = new JSDOM(await readFile(path.join(outputDirectory, file), 'utf8'), {
      url: url.href,
    });
    const document = dom.window.document;
    const anchors = new Set<string>();
    for (const element of document.querySelectorAll('[id], a[name]')) {
      const anchor = element.getAttribute('id') || element.getAttribute('name');
      if (anchor) {
        anchors.add(anchor);
      }
    }
    const links = new Map<string, HtmlPage['links'][number]>();
    for (const element of document.querySelectorAll('a[href], area[href], link[href]')) {
      const href = element.getAttribute('href')!;
      const typeRef = element.getAttribute('data-type-ref');
      // Keep ordinary and deferred references separate, even when their href matches.
      links.set(JSON.stringify([href, typeRef]), { href, typeRef });
    }
    pages.set(file, { file, url, anchors, links: Array.from(links.values()) });
    dom.window.close();
  }

  if (pages.size === 0) {
    throw new Error(
      'Static export contains no HTML pages. Run pnpm --filter docs-mdx build first.',
    );
  }

  const issues: string[] = [];
  const deferredTypeRefs: string[] = [];
  let checkedLinks = 0;

  for (const page of pages.values()) {
    for (const { href, typeRef } of page.links) {
      if (!href.trim()) {
        continue;
      }
      let target: URL;
      try {
        target = new URL(href, page.url);
      } catch {
        issues.push(`${page.file}: invalid URL ${href}`);
        continue;
      }
      if (target.origin !== siteOrigin) {
        continue;
      }

      let pathname: string;
      let anchor: string;
      try {
        pathname = decodeURIComponent(target.pathname);
        // Text fragments do not require a matching element ID.
        anchor = decodeURIComponent(target.hash.slice(1).split(':~:text=')[0]);
      } catch {
        issues.push(`${page.file}: invalid URL encoding ${href}`);
        continue;
      }
      checkedLinks += 1;
      const relativePath = pathname.replace(/^\/+|\/+$/g, '');
      const candidates = [
        relativePath,
        `${relativePath}.html`,
        relativePath ? `${relativePath}/index.html` : 'index.html',
      ];
      const targetFile = candidates.find((candidate) => allFiles.has(candidate));
      if (!targetFile) {
        issues.push(`${page.file}: missing target ${href}`);
        continue;
      }
      const targetPage = pages.get(targetFile);
      if (anchor && targetPage && !targetPage.anchors.has(anchor)) {
        if (typeRef) {
          deferredTypeRefs.push(`${page.file}: ${typeRef} (${href})`);
        } else {
          issues.push(`${page.file}: missing anchor ${href}`);
        }
      }
    }
  }

  console.log(`Checked ${pages.size} HTML pages and ${checkedLinks} local links.`);
  if (deferredTypeRefs.length > 0) {
    console.log(
      `Deferred ${deferredTypeRefs.length} dynamic type references for browser hydration verification:`,
    );
    for (const reference of deferredTypeRefs) {
      console.log(`- ${reference}`);
    }
  }
  if (issues.length > 0) {
    for (const issue of issues.slice(0, 50)) {
      console.error(`- ${issue}`);
    }
    if (issues.length > 50) {
      console.error(`- ... ${issues.length - 50} more issues`);
    }
    console.error(`Found ${issues.length} broken links.`);
    process.exitCode = 1;
  } else {
    console.log(
      deferredTypeRefs.length > 0
        ? 'No broken static links found; dynamic type references require browser hydration verification.'
        : 'No broken static links found.',
    );
  }
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : error);
  process.exitCode = 1;
});
