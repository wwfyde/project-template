---
description: 安装、启动、构建和部署文档站点。
---

# 快速开始

本站基于 VitePress 2，`docs/` 同时是 VitePress 项目目录与 Markdown 源目录。

## 启动开发服务

使用 Node.js 22 或更高版本，以及仓库指定的 pnpm。在仓库根目录执行：

```sh
pnpm install
pnpm docs:dev
```

默认访问 `http://localhost:5174`。也可以进入 `docs/` 后运行 `pnpm dev`。

::: info 版本
当前锁定 `vitepress@2.0.0-alpha.20`。VitePress 2 仍为预发布版本，升级前请查看[官方更新记录](https://github.com/vuejs/vitepress/releases)。
:::

## 目录结构

```text
docs/
├── .vitepress/
│   └── config.mts       # 站点、导航、侧边栏与搜索配置
├── guide/
│   ├── index.md         # /guide/
│   ├── routing.md       # /guide/routing.html
│   └── markdown.md      # /guide/markdown.html
├── index.md             # /
└── package.json         # 文档引擎依赖与运行命令
```

直接在 `docs/` 下添加 `.md` 文件即可生成页面，无需注册路由。站点不设置额外的 `srcDir`，也不使用路由重写。参见[文件路由](./routing.md)。

## 构建与预览

在仓库根目录执行：

```sh
pnpm docs:build
pnpm docs:preview
```

预览默认使用 `http://localhost:4174`。`pnpm docs:start` 是相同预览命令的别名。构建产物位于 `docs/.vitepress/dist/`，可以发布到静态文件服务器；缓存和构建产物已加入忽略规则。

本站保留 VitePress 默认的 `.html` 链接，静态服务器只需支持目录首页 `index.html`。若部署到子路径（例如 `/project-template/`），在 `.vitepress/config.mts` 中设置对应的 `base`，然后重新构建。

## 修改站点配置

在 `.vitepress/config.mts` 中调整站点标题、描述、导航、侧边栏和搜索选项。侧边栏控制展示顺序，不决定页面是否存在；新增页面可以直接访问，需要出现在菜单时再添加侧边栏链接。

仓库中的 `docs-mdx/` 是独立的 MDX 文档站。它使用根目录的 `pnpm docs-mdx:dev`、`pnpm docs-mdx:build` 和 `pnpm docs-mdx:start` 命令。
