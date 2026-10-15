import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { expect, it } from "vitest";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkMdx from "remark-mdx";
import { syncPageIndex } from "@mui/internal-docs-infra/pipeline/syncPageIndex";
import remarkDocumentMetadata from "../../mdx/remarkDocumentMetadata.mjs";
import { loadDocumentIndex } from "../../mdx/loadDocumentIndex.mjs";
import loadPrecomputedSitemap from "../../mdx/loadPrecomputedSitemap.mjs";

it("round-trips Chinese sections and API entries through unmodified docs-infra", async () => {
  const rootContext = await fs.mkdtemp(path.join(os.tmpdir(), "docs-index-"));
  try {
    const indexPath = path.join(
      rootContext,
      "src/app/(docs)/react/handbook/page.mdx",
    );
    await fs.mkdir(path.dirname(indexPath), { recursive: true });
    const pagePath = path.join(
      path.dirname(indexPath),
      "writing-docs/page.mdx",
    );
    const processor = unified()
      .use(remarkParse)
      .use(remarkMdx)
      .use(remarkDocumentMetadata, {
        titleSuffix: " · Example",
        extractToIndex: { baseDir: rootContext, include: ["src/app/react"] },
      });
    const file = {
      path: pagePath,
      value:
        "# 编写文档\n\n项目文档写作指南。\n\n## 代码块\n\n## 生成 API 表\n\n### 代码块\n",
    };
    await fs.mkdir(path.dirname(pagePath), { recursive: true });
    await fs.writeFile(pagePath, file.value);
    await processor.run(processor.parse(file), file);

    // API extraction merges another producer's data into the same index. This
    // must preserve source-derived Unicode IDs when rebuilding the sitemap.
    await syncPageIndex({
      pagePath,
      baseDir: rootContext,
      metadata: {
        path: "./writing-docs/page.mdx",
        slug: "writing-docs",
        parts: { Root: { props: ["value", "onValueChange"] } },
      },
      preserveExistingTitleAndSlug: true,
    });
    const dependencies = [];
    const index = await loadDocumentIndex(pathToFileURL(indexPath).href, {
      rootContext,
      addDependency: (dependency) => dependencies.push(dependency),
    });

    expect(index.pages).toHaveLength(1);
    expect(index.pages[0].title).toBe("编写文档");
    expect(index.pages[0].slug).toBe("编写文档");
    expect(
      Object.values(index.pages[0].sections).map((section) => section.title),
    ).toEqual(["代码块", "生成 API 表"]);
    expect(
      index.pages[0].sections["生成-api-表"].children["代码块-1"].title,
    ).toBe("代码块");
    expect(index.pages[0].parts.Root.props).toEqual(["value", "onValueChange"]);
    expect(dependencies).toEqual([indexPath, pagePath]);

    // Exercise the actual webpack/Turbopack loader, including removing MDX
    // imports so the source scanner does not enter the browser bundle.
    const sitemapPath = path.join(rootContext, "src/app/sitemap/index.ts");
    await fs.mkdir(path.dirname(sitemapPath), { recursive: true });
    const source = `import { createSitemap } from '@mui/internal-docs-infra/createSitemap';
import Handbook from '../(docs)/react/handbook/page.mdx';
export const sitemap = createSitemap(import.meta.url, { 写作指南: Handbook });`;
    const transformed = await new Promise((resolve, reject) => {
      loadPrecomputedSitemap.call(
        {
          resourcePath: sitemapPath,
          rootContext,
          cacheable() {},
          addDependency() {},
          async: () => (error, result) =>
            error ? reject(error) : resolve(result),
        },
        source,
      );
    });
    expect(transformed).not.toContain(
      "from '../(docs)/react/handbook/page.mdx'",
    );
    const { createSitemap } =
      await import("@mui/internal-docs-infra/createSitemap");
    const evaluate = new Function(
      "createSitemap",
      transformed
        .replace(/^import .*;\n/, "")
        .replace(
          "import.meta.url",
          JSON.stringify(pathToFileURL(sitemapPath).href),
        )
        .replace("export const sitemap =", "return"),
    );
    expect(evaluate(createSitemap).data.写作指南.pages[0].sections).toEqual(
      index.pages[0].sections,
    );

    // Heading edits are read immediately even before an index sync; the loader
    // tracks this source dependency so development builds invalidate correctly.
    await fs.appendFile(pagePath, "\n## 新章节\n");
    const updated = await loadDocumentIndex(indexPath, { rootContext });
    expect(updated.pages[0].sections.新章节.title).toBe("新章节");
  } finally {
    await fs.rm(rootContext, { recursive: true, force: true });
  }
});
