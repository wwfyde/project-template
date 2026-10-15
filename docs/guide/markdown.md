---
description: 常用 Markdown 格式与 VitePress 扩展示例。
---

# Markdown 写作

文档直接使用 `.md` 文件。二、三级标题会自动出现在右侧的本页目录中。

## 页面信息

文件开头可以使用 frontmatter 设置标题和描述：

```yaml
---
title: 页面标题
description: 用一句话概括页面内容。
---
```

## 代码高亮

代码块支持语言标记、行号和重点行：

```ts {2} line-numbers
const docsRoot = 'docs'
const page = `${docsRoot}/guide/index.md`
console.log(page)
```

## 提示容器

::: tip 写作建议
每篇文档集中回答一个问题，通过相对链接关联其他页面。
:::

::: warning 路径变更
移动 Markdown 文件也会改变路由，请同步检查指向它的链接。
:::

## 多组代码

::: code-group

```sh [仓库根目录]
pnpm docs:dev
```

```sh [docs 目录]
pnpm dev
```

:::

## 表格与链接

| 操作 | 仓库根目录命令 |
| --- | --- |
| 开发 | `pnpm docs:dev` |
| 构建 | `pnpm docs:build` |
| 预览 | `pnpm docs:preview` |

继续阅读[文件路由](./routing.md)，或查看 [VitePress Markdown 扩展](https://vitepress.dev/guide/markdown)。
