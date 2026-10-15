---
description: Markdown 文件与页面 URL 的对应关系。
---

# 文件路由

VitePress 根据 Markdown 文件相对于 `docs/` 的路径生成页面。创建、移动或删除文件，就会相应地新增、移动或删除路由。

## 文件与 URL

下表展示路由规则，其中未创建的文件仅作示例：

| 文档文件 | 页面 URL |
| --- | --- |
| `docs/index.md` | `/` |
| `docs/guide/index.md` | `/guide/` |
| `docs/guide/routing.md` | `/guide/routing.html` |
| `docs/api/client.md` | `/api/client.html` |
| `docs/api/examples/basic.md` | `/api/examples/basic.html` |

目录中的 `index.md` 是该目录的首页。不要同时创建 `guide.md` 和 `guide/index.md` 来表达同一个目录首页，避免链接含义混淆。

## 新增页面

例如创建 `docs/api/client.md`：

```md
---
title: 客户端 API
description: 客户端初始化与使用说明。
---

# 客户端 API

在这里编写文档。
```

保存后即可访问 `/api/client.html`，不需要修改路由表或配置文件。开发服务会自动发现新的 Markdown 页面。

如果要把页面加入侧边栏，再向 `.vitepress/config.mts` 的 `themeConfig.sidebar` 添加 `{ text: '客户端 API', link: '/api/client' }`。

## 页面链接

Markdown 中推荐直接链接到已有的 `.md` 文件，VitePress 会将它们转换为页面 URL：

```md
[快速开始](./index.md)
[Markdown 写作](./markdown.md)
[首页](../index.md)
```

例如：[快速开始](./index.md)、[Markdown 写作](./markdown.md)和[首页](../index.md)。构建时会检查失效的内部链接。

## 静态资源

与文章一起管理的图片可以放在文章附近，通过相对路径引用。需要原样复制的资源可以放在 `docs/public/`，例如 `docs/public/logo.svg` 对应 `/logo.svg`。

## 无扩展名 URL

本站默认保留 `.html`。若希望使用 `/guide/routing` 这样的 URL，可以设置 `cleanUrls: true`，并确保部署平台能把无扩展名请求映射到对应的 `.html` 文件。只有客户端导航可用、刷新页面却返回 404，通常就是服务器没有配置这一映射。

更多规则见 [VitePress 官方路由文档](https://vitepress.dev/guide/routing)。
