# docs-mdx

供项目维护自有内容的 MDX 文档模板，沿用 Base UI 文档引擎与视觉样式。访问 `/` 会进入 `/react/overview/quick-start`，不再包含品牌官网、招聘、发布历史和实验站。

## 运行

在仓库根目录执行：

```sh
pnpm install
pnpm docs-mdx:dev
```

打开 <http://localhost:3005/react/overview/quick-start>。

```sh
pnpm docs-mdx:check-types
pnpm docs-mdx:test
pnpm docs-mdx:build
pnpm docs-mdx:link-check
pnpm docs-mdx:start
```

`pnpm --filter docs-mdx validate` 会构建文档并检查链接，使用与开发、生产一致的中文索引及 API 提取流程。

开发模式和生产预览都使用 3005 端口，请择一启动。生产文件位于 `docs-mdx/out/`，可以交给静态文件服务器部署。使用仓库指定的 Node.js 24 与 pnpm 版本。

## 保留的内容

仅保留四篇正文，作为后续替换和扩展的示范：

| 页面 | 路径 | 用途 |
| --- | --- | --- |
| 快速开始 | `react/overview/quick-start` | 启动文档、目录结构和维护入口 |
| 文档写作 | `react/handbook/writing-docs` | Markdown、表格、代码块、中文目录、MDX 和扩展方式 |
| Accordion | `react/components/accordion` | 可交互示例、两种样式版本和自动 API 表 |
| Popover | `react/components/popover` | 弹层示例、定位和完整组件 API |

各分组的 `page.mdx` 和 `react/page.mdx` 是引擎索引，不是额外的正文示例。解析测试的 `scripts/generateLlmTxt/fixtures/` 不会发布为页面。

## 常用修改位置

- `src/site.config.mjs`：站点名称、描述、默认入口与地址。
- `src/app/(docs)/react/`：MDX 正文及分组索引。
- `src/app/sitemap/index.ts`：导航和搜索使用的分组。
- `src/app/(docs)/layout.tsx`：文档布局。
- `src/mdx-components.tsx`：Markdown 元素和自定义 MDX 组件映射。
- `src/css/`：主题、字体与视觉样式。
- `public/favicon.svg`：站点图标。

### 添加页面

1. 在已有分组下创建 `my-page/page.mdx`，写入标题、`Subtitle` 和正文。
2. 在同分组的 `page.mdx` 列表中维护入口及顺序，例如 `- 新页面 - ([Outline](#新页面), [Contents](./my-page/page.mdx))`。
3. 新增分组时，在 `src/app/sitemap/index.ts` 引入分组索引，并维护 `react/page.mdx` 总索引。
4. 运行构建和链接检查。

保留索引条目中的 `Outline` 和 `Contents`，前者让搜索保留页面章节。索引注释标记下的元数据由引擎生成。修改正文标题和描述后，构建会更新相关索引。中文标题支持页内目录和搜索结果定位。

### 添加交互示例和 API 表

参考保留的两个组件目录：`demos/hero/index.ts` 使用 `createDemoWithVariants` 注册 CSS Modules / Tailwind 版本；`types.ts` 使用 `createTypes` 或 `createMultipleTypes` 注册组件。

引擎保留语法高亮、复制、源码选项卡、交互预览、在线沙盒导出、API 参数表和类型弹层。常见写法也收录在「文档写作」页面。

## 搜索与 Markdown 导出

保留桌面搜索、移动导航、页内目录、明暗主题、页面元数据和本地字体。`generate-llms` 会自动发现当前文档分组，生成 `llms.txt`、`llms-full.txt` 和每篇文档的 Markdown，并清理已删除文章的旧 Markdown。

开发启动前导出到 `public/`；开发中修改内容后，可用 `pnpm --filter docs-mdx generate-llms` 刷新 Markdown；生产构建完成 API 提取后导出到 `out/`。`link-check` 检查静态页面、文件和锚点，依赖客户端类型弹层的引用会单独列出以供浏览器验证。

`BASE_URL` 设置部署地址，默认 `http://localhost:3005`。Google Analytics 默认关闭，配置自己的 `NEXT_PUBLIC_GOOGLE_ANALYTICS_ID` 后才启用。示例的源码链接保留指向 Base UI；改为自有组件时可调整 `next.config.mjs` 的源码仓库配置与链接映射。

## 引擎依赖

组件直接使用 `@base-ui/react@1.9.0` 和 `@base-ui/utils@0.5.0`，无需组件源码副本。API 表从已安装包的声明提取。

依赖使用官方发布包，不需要 pnpm 补丁或安装后修改 `node_modules`。根 workspace 中的 TypeScript override 统一类型提取器使用的编译器版本；构建时自动准备 Base UI 声明缓存，让提取器保留组件 Props 和 State，同时继续排除 React、DOM 等外部属性。缓存由已安装包生成，不需要维护组件源码副本。

基础代码来自 [Base UI docs](https://github.com/mui/base-ui/tree/ddfc7a4581e0f0d75ecf01c1ba486a979527e9d4/docs)，保留其 MIT `LICENSE`。

中文索引规则由本地 MDX 插件与站点地图加载器维护，直接从正文读取章节并保持 Unicode 锚点一致。搜索直接使用 Orama，通过 `Intl.Segmenter` 补充中文分词，并保留英文词干匹配；适用于仅有少量页面的模板。
