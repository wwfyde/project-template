# Web 项目

React + TypeScript + Vite，使用 TanStack Router、Tailwind CSS 和 Radix Themes。主题及国际化模块从 `fs-agent/web/src/theme`、`fs-agent/web/src/i18n` 复用，再适配本项目的页面、组件和存储命名。

## 启动与检查

在仓库根目录执行：

```sh
pnpm install
pnpm --filter web dev
pnpm --filter web check-types
pnpm --filter web lint
pnpm --filter web test
pnpm --filter web build
```

也可以通过根目录的 just recipes 启动：

```sh
just web                        # 读取 WEB_PORT，未设置时为 5173
just web --port 6173             # 也支持 just web -p 6173
WEB_PORT=6173 just web
just run                        # 同时启动前端与后端
just run --web-port 6173 --api-port 9036
```

`just` 加载根目录 `.env`，recipe flags 优先于终端环境和 `.env`。直接通过 pnpm 启动 Vite 时，同样读取根目录和 `web/` 下当前 mode 的 `.env` 文件；优先级为终端环境、`web/` 配置、根目录配置、默认值。变量 `WEB_PORT` 和 `API_PORT` 仅用于开发服务器，不会注入浏览器代码。指定端口不可用时会报错，不会自动改用下一个端口。

## API 代理与部署

前端统一使用相对 API 地址：

```ts
import { requestJson } from './src/lib/api-client'

const data = await requestJson<{ message: string }>('/api/hello')
```

开发服务器将 `/api` 和 `/api/...` 请求转发到 `http://127.0.0.1:<API_PORT>`（默认 `8000`），保留路径、查询参数和请求体，并支持 WebSocket。运行 `just run --api-port ...` 时，代理目标会自动跟随后端端口。认证与后续业务接口统一使用 `requestJson`：携带 Session Cookie，每次生成 `Request-ID`，保留调用方注入的 OpenTelemetry `traceparent`；不自行构造用户、租户身份或追踪上下文。错误对象保留服务端响应的 Request-ID，便于关联日志。

Vite 的代理用于开发，`pnpm --filter web build` 生成的 `web/dist/` 不包含代理服务器。生产部署时，将静态文件与 API 放在同一域名下，例如 Nginx：

```nginx
server {
    listen 80;
    server_name example.com;
    root /srv/project-template/web/dist;

    location /api/ {
        # 不在端口后添加 /，保留后端路由所需的 /api 前缀。
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

部署时只需调整服务器的 upstream 地址，无需将后端域名或端口写入前端构建产物。

## 用户与认证

认证从 `fs-agent` 迁移，集中在 `src/features/auth/`：`model` 定义用户、身份提供方和安全跳转地址，`infrastructure` 管理服务端会话，React Provider 向路由与页面提供状态。浏览器不保存身份令牌，不通过 localStorage 模拟登录。

- 用户及渠道信息以服务端会话响应为准。进入受保护页面、重新聚焦窗口或回到标签页时通过 `GET /api/auth/session` 重新验证会话。
- 所有既有页面位于 `src/routes/_authenticated/`，URL 保持不变；匿名访问跳转到 `/login?redirect=...`，登录后仅允许返回本应用的页面。
- 登录页根据后端返回的 `providers` 渲染已启用渠道。Google 与钉钉通过 `/api/auth/oauth/{provider}/start` 发起 OAuth；手机号只预留类型和不可用状态的 UI 分支，后端当前禁止启用，不发送验证码、不提供伪登录接口。新增 OAuth 身份提供方不需要更改路由或认证客户端；可补充对应显示文案和图标。
- 启用 `password` 渠道时展示用户名与密码表单，通过 `POST /api/auth/password/login` 提交 JSON，并发送 `X-Requested-With: XMLHttpRequest`。登录沿用 Session Cookie 与安全返回地址，密码不会写入认证状态或浏览器存储，提交完成后清空密码输入；账号由后端管理，不提供公开注册入口。
- `POST /api/auth/logout` 携带会话接口返回的 `X-CSRF-Token`。只有服务端确认退出成功后才清除客户端用户状态；失败时保留状态并显示重试提示。
- OAuth 客户端 ID、密钥、回调地址与渠道开关在后端配置，禁止使用 `VITE_*` 将密钥打包给浏览器。简单 Header 认证所用的共享密钥也只由可信服务或脚本持有，不加入前端请求配置。

## 主题与语言

页面上的主题设置按钮打开配置面板，可切换系统 / 浅色 / 深色、8 种颜色预设、圆角、密度、内容宽度，以及简体中文 / 英文。外观与语言分别保存，重置外观不会重置语言。

- `src/main.tsx` 在 React 挂载前执行 `initializeTheme()` 并等待 `initializeI18n()`。
- `src/app/app-providers.tsx` 注册 `I18nProvider`、`ThemeProvider`、`AuthProvider` 和全局 Radix Theme。Radix 共享明暗模式、基础文字、背景、圆角与密度；按钮颜色通过下述适配类接入。
- 主题类名、`data-theme-*` 属性和 `color-scheme` 都挂在 `<html>`，与基础和派生 CSS 变量保持在同一节点。默认预设、圆角、密度会移除对应属性，使默认样式恢复生效。
- 语言按本地偏好、浏览器语言检测；中文地区变体统一为 `zh-CN`，其他语言回退为 `en`。切换时同步 `<html lang>`。

| 偏好 | localStorage key               | 格式                                       |
| ---- | ------------------------------ | ------------------------------------------ |
| 主题 | `project-template.theme.v1`    | `{ "version": 1, "preferences": { ... } }` |
| 语言 | `project-template.language.v1` | `zh-CN` 或 `en`                            |

存储不可用时仍可在当前页面切换。默认外观不写入存储；主题解析会忽略损坏或不支持的存储版本，并为不合法的字段恢复默认值。

## 使用语义 Token

`src/theme/styles/theme.css` 定义设计系统变量，并通过 Tailwind `@theme inline` 注册对应工具类。页面优先使用语义名称，让所有预设自动生效：

```tsx
<section className="rounded-lg border border-border bg-card p-6 text-card-foreground">
  <p className="text-muted-foreground">辅助说明</p>
  <button className="rounded-md bg-primary px-4 py-2 text-primary-foreground focus-visible:outline-ring">确认</button>
</section>
```

普通 CSS 可直接使用 `var(--background)`、`var(--foreground)`、`var(--primary)`、`var(--border)`、`var(--radius)` 等变量。背景与文字使用配套 Token，例如 `card` / `card-foreground`。避免在业务页面写死颜色或圆角；主内容容器使用 `app-content` 以响应内容宽度设置。

通过 `useTheme()` 读取 `preferences`、`resolvedMode`，使用 `setPreferences({ preset: 'ocean-breeze' })` 修改部分偏好，或调用 `resetPreferences()` 重置外观。

Radix `Button` 添加 `className="theme-radix-button"` 使用语义颜色；描边按钮同时添加 `theme-radix-button-outline`。新增其他 Radix 组件时应按其视觉语义添加适配，不要假设所有组件的品牌色已自动映射。

## 扩展预设与翻译

新增颜色预设时，在 `src/theme/model/theme-config.ts` 的 `THEME_PRESETS` 添加值、翻译键和色样，再在 `src/theme/styles/theme.css` 添加对应的 `:root[data-theme-preset='...']` 变量覆盖；如需要，为 `:root.dark[data-theme-preset='...']` 补充深色覆盖。预设应覆盖语义 Token，而不是单个页面的样式。

翻译位于 `src/i18n/resources/en.ts`、`zh-cn.ts`，分为 `common`、`navigation`、`theme`、`pages`、`auth` 命名空间。新增文案需同步维护两种语言的键；资源测试会检查键结构一致性。

```tsx
import { useTranslation } from 'react-i18next'

function PageTitle() {
  const { t } = useTranslation('pages')
  return <h1>{t('aboutTitle')}</h1>
}
```

计数文案使用 `t('clickCount', { count })`，在资源中维护 `_one`、`_other` 复数键。模块导出的 `i18n.changeLanguage('zh-CN')` 可切换语言；现有 `LanguageSwitcher` 已封装相应交互。
