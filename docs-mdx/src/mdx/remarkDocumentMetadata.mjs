import path from "node:path";
import { valueToEstree } from "estree-util-value-to-estree";
import { visit } from "unist-util-visit";
import transformMarkdownMetadata from "@mui/internal-docs-infra/pipeline/transformMarkdownMetadata";
import {
  indexRelativePagePath,
  syncPageIndex,
} from "@mui/internal-docs-infra/pipeline/syncPageIndex";
import { stringToUrl } from "../components/QuickNav/rehypeSlug.mjs";
import { stripTrailingHeadingTag } from "./remarkHeadingTags.mjs";

function textContent(node) {
  return node.children
    ? node.children.map(textContent).join("")
    : node.value || "";
}

// Metadata is an object literal produced by the upstream remark plugin. Read only
// literal data; evaluating MDX exports here would execute documentation code.
function readLiteral(node) {
  if (!node) return undefined;
  if (node.type === "Literal") return node.value;
  if (node.type === "ArrayExpression") return node.elements.map(readLiteral);
  if (node.type === "ObjectExpression") {
    return Object.fromEntries(
      node.properties
        .filter((property) => property.type === "Property")
        .map((property) => [
          property.key.name ?? property.key.value,
          readLiteral(property.value),
        ]),
    );
  }
  return undefined;
}

function metadataObject(tree) {
  for (const node of tree.children) {
    for (const statement of node.data?.estree?.body ?? []) {
      for (const declaration of statement.declaration?.declarations ?? []) {
        if (
          declaration.id.name === "metadata" &&
          declaration.init?.type === "ObjectExpression"
        ) {
          return declaration.init;
        }
      }
    }
  }
  return undefined;
}

export function documentSections(tree) {
  const sections = {};
  const stack = [{ depth: 0, children: sections }];
  const usedIds = new Set();
  let pageTitle;
  let parentTitle;
  visit(tree, "heading", (heading) => {
    const title = textContent(heading);
    const visibleTitle =
      heading.depth === 1 ? title : stripTrailingHeadingTag(title);
    const base = stringToUrl(visibleTitle);
    const explicitId = heading.data?.hProperties?.id;
    let slug = explicitId || base;
    let suffix = 0;
    while (!explicitId && usedIds.has(slug)) slug = `${base}-${++suffix}`;
    usedIds.add(slug);
    if (heading.depth === 1) {
      pageTitle ??= title;
      return;
    }
    if (heading.depth === 2) parentTitle = visibleTitle;
    if (
      pageTitle === "Forms" &&
      heading.depth === 3 &&
      ["React Hook Form", "TanStack Form"].includes(parentTitle)
    ) {
      slug = stringToUrl(`${parentTitle} ${visibleTitle}`);
    }

    while (stack.at(-1).depth >= heading.depth) stack.pop();
    const section = {
      title,
      titleMarkdown: structuredClone(heading.children),
      children: {},
    };
    stack.at(-1).children[slug] = section;
    stack.push({ depth: heading.depth, children: section.children });
  });
  return sections;
}

function visibleDescription(tree) {
  const titleIndex = tree.children.findIndex(
    (node) => node.type === "heading" && node.depth === 1,
  );
  const next = tree.children[titleIndex + 1];
  if (
    titleIndex < 0 ||
    !next ||
    !["paragraph", "mdxJsxFlowElement"].includes(next.type)
  )
    return {};
  if (next.name === "Meta" || next.name === "meta") return {};
  const description = textContent(next)
    .replace(/[ \t\n\r]+/g, " ")
    .trim();
  const children = next.children;
  const descriptionMarkdown =
    children.length === 1 && children[0].type === "mdxJsxTextElement"
      ? children[0].children
      : children;
  return description ? { description, descriptionMarkdown } : {};
}

function shouldExtract(filePath, options) {
  const normalized = path
    .relative(options.baseDir || process.cwd(), filePath)
    .split(path.sep)
    .filter((segment) => !/^\(.*\)$/.test(segment))
    .join("/");
  const { include = [], exclude = [] } = options;
  return (
    !include.some((prefix) => normalized === `${prefix}/page.mdx`) &&
    (include.length === 0 ||
      include.some((prefix) => normalized.startsWith(`${prefix}/`))) &&
    !exclude.some((prefix) => normalized.startsWith(`${prefix}/`))
  );
}

/** Keep upstream page metadata and index merging, with local Unicode heading IDs. */
export default function remarkDocumentMetadata(options = {}) {
  const transform = transformMarkdownMetadata({
    ...options,
    extractToIndex: false,
  });
  return async (tree, file) => {
    await transform(tree, file);
    const object = metadataObject(tree);
    if (!object) return;

    const metadata = readLiteral(object);
    const pagePath = file.path
      ? indexRelativePagePath(path.dirname(file.path), path.basename(file.path))
      : "";
    const sections = documentSections(tree);
    const sectionProperty = object.properties.find(
      (property) => property.key?.name === "sections",
    );
    if (sectionProperty) sectionProperty.value = valueToEstree(sections);
    else object.properties.push(valueToEstree({ sections }).properties[0]);

    const extract = options.extractToIndex;
    if (!extract || !file.path) return;
    const indexOptions = extract === true ? {} : extract;
    if (!shouldExtract(file.path, indexOptions)) return;

    const title =
      options.titleSuffix && metadata.title?.endsWith(options.titleSuffix)
        ? metadata.title.slice(0, -options.titleSuffix.length)
        : metadata.title;
    await syncPageIndex({
      ...indexOptions,
      pagePath: file.path,
      updateParents: true,
      metadata: {
        ...metadata,
        ...(indexOptions.useVisibleDescription ? visibleDescription(tree) : {}),
        title,
        slug: stringToUrl(title || path.basename(path.dirname(file.path))),
        path: pagePath,
        sections,
        audience: metadata.other?.audience,
      },
    });
  };
}
