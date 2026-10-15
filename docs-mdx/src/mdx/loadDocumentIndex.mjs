import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { unified } from "unified";
import remarkParse from "remark-parse";
import remarkMdx from "remark-mdx";
import remarkGfm from "remark-gfm";
import {
  createLoadServerPageIndex,
  stripTitleMarkdown,
} from "@mui/internal-docs-infra/pipeline/loadServerPageIndex";
import { documentSections } from "./remarkDocumentMetadata.mjs";
import { stringToUrl } from "../components/QuickNav/rehypeSlug.mjs";

/**
 * Keep upstream navigation order, labels, audience and API metadata. Read heading
 * IDs from the source MDX because docs-infra's plain-text index uses ASCII slugs.
 * Reading source also preserves duplicate headings that an index round-trip loses.
 */
export async function loadDocumentIndex(
  filePath,
  { rootContext, addDependency = () => {} } = {},
) {
  const absolutePath = filePath.startsWith("file:")
    ? fileURLToPath(filePath)
    : filePath;
  addDependency(absolutePath);
  const index = await createLoadServerPageIndex({ rootContext })(absolutePath);
  if (!index) return null;

  const parser = unified().use(remarkParse).use(remarkMdx).use(remarkGfm);
  index.pages = await Promise.all(
    index.pages.map(async (page) => {
      if (!page.path.startsWith("./") || !page.path.endsWith(".mdx"))
        return page;
      const sourcePath = path.resolve(path.dirname(absolutePath), page.path);
      addDependency(sourcePath);
      const tree = parser.parse(await fs.readFile(sourcePath, "utf8"));
      return {
        ...page,
        slug: page.slug || stringToUrl(page.title),
        sections: stripTitleMarkdown(documentSections(tree)),
      };
    }),
  );
  return index;
}
