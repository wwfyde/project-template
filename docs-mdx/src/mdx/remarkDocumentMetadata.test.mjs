import { describe, expect, it } from "vitest";
import { evaluate } from "@mdx-js/mdx";
import * as runtime from "react/jsx-runtime";
import remarkDocumentMetadata from "./remarkDocumentMetadata.mjs";
import remarkHeadingTags from "./remarkHeadingTags.mjs";
import rehypeSlug from "../components/QuickNav/rehypeSlug.mjs";
import rehypeConcatHeadings from "../components/QuickNav/rehypeConcatHeadings.mjs";

describe("remarkDocumentMetadata", () => {
  it("keeps Chinese, formatted, tagged, and repeated headings aligned with rendered anchors", async () => {
    const page = await evaluate(
      `# 编写文档

<Meta name="description" content="页面介绍" />

## **代码块** [Preview]

### 使用 \`API\`

## 代码块

export const metadata = { keywords: ['中文', 'API'] };
`,
      {
        ...runtime,
        remarkPlugins: [
          [remarkDocumentMetadata, { titleSuffix: " · Example" }],
          remarkHeadingTags,
        ],
        rehypePlugins: [rehypeSlug],
      },
    );

    expect(page.metadata).toMatchObject({
      title: "编写文档 · Example",
      description: "页面介绍",
      keywords: ["中文", "API"],
      sections: {
        代码块: {
          title: "代码块 [Preview]",
          children: { "使用-api": { title: "使用 API" } },
        },
        "代码块-1": { title: "代码块" },
      },
    });
    const rendered = page.default({ components: { Meta: () => null } });
    const headings = rendered.props.children.filter((child) =>
      /^h[1-6]$/.test(child?.type),
    );
    expect(headings.map((heading) => heading.props.id)).toEqual([
      "编写文档",
      "代码块",
      "使用-api",
      "代码块-1",
    ]);
  });

  it("uses the same Forms page library prefixes as the rendered headings", async () => {
    const page = await evaluate(
      "# Forms\n\n## React Hook Form\n\n### Usage\n",
      {
        ...runtime,
        remarkPlugins: [remarkDocumentMetadata],
        rehypePlugins: [rehypeSlug, rehypeConcatHeadings],
      },
    );
    expect(
      page.metadata.sections["react-hook-form"].children[
        "react-hook-form-usage"
      ].title,
    ).toBe("Usage");
  });
});
