# Agent 页面与 GPT 风格设计系统

状态：已实现的交互预览及后续接入边界，2026-11-17；plus 与上下文扩展已完成本轮验收。需求与源码依据见 [研究文档](./agent-page-research.md)，输入器接口见 [ChatComposer](../web/src/blocks/chat-composer/README.md)。

plus 菜单的后续浏览器核实、上下文引用与能力契约见 [输入器动作与上下文](./agent-composer-actions.md)；该文单独记录本轮验收状态。

## 目标与范围

登录后访问 `/agent`，打开经现有会话认证保护的全屏工作空间。以 ChatGPT 的中性表面、留白、阅读宽度和圆角输入框为视觉方向，结合 Beautiful UI 的任务步骤与紧凑状态信息。Chat / Task 共用一个 `ChatComposer`，支持桌面、窄屏、浅色和深色界面。

当前没有实装的聊天推理或任务运行接口，因此本期明确标注“交互预览”，提交使用示例响应；不上传附件、不调用外部模型、不执行工具。附件用于展示已选择的本地文件。真实登录保持现有 Session Cookie 流程。会话与草稿保留在当前页面内存，刷新重置。

已落地的交互包括模式切换、分别保留两种模式的草稿、新建与选择会话、按标题搜索、填入建议、逐段显示本地示例回复、停止、任务步骤、复制以及多轮对话定位。Task 当前以会话中的步骤卡片表达任务，没有独立后台任务队列、状态筛选或失败重试入口。已处理附件校验和复制失败提示；预览 transport 没有失败事件，不能据此宣称已验证真实生成错误恢复。

plus 现统一包含文件、网页链接、文本资料、技能、模式切换与工具；已选引用和工具显示为可移除 chip。技能选择读取既有认证 API 的真实目录，支持已加载条目搜索、分页和失败重试，并保存默认版本引用；不执行技能。提交后的引用可展开查看文本、URL 或技能版本与描述。

Creative 是后续模式，当前不增加不可工作的第三个 Tab。预留 image/video 参数、参考图、生成队列、取消及结果网格；详见需求文档。页面中的资产和技能入口连接现有页面。

## 信息架构与视觉

- 桌面：约 252px 侧栏 + 自适应主区域；侧栏包含新建、搜索、资产/技能、当前页面会话、账号入口。
- 顶栏：Agent 名称、预览标识、明暗模式和语言切换。Agent 使用独立全屏布局，不叠加管理页面的横向导航。
- 初始态：中心标题、Chat / Task Tabs、模式说明、共享 Composer、四个可填入草稿的建议。Task 额外展示执行方式的简短说明。
- 会话态：内容宽度最多 760px；用户消息右对齐浅灰气泡、助手正文无大面积卡片；任务步骤使用细边框分组。Composer 固定在内容区下沿，消息区独立滚动。
- 窄屏：侧栏改为可关闭的抽屉，键盘焦点受控；composer 不超过视口宽度，主控件触摸目标至少 40px，手机输入字体不小于 16px。
- 长内容：所有 flex 文本容器设置 min-width:0，文件名截断但保留完整可访问名称，正文允许长链接换行。

## Theme → Tailwind

在 `src/theme/styles/agent.css` 定义专用语义变量，通过 `@theme inline` 注册 Tailwind 名称。全局定义 token，避免挂在 body 的浮层丢失主题；颜色不依赖用户的品牌色预设。明暗跟随已有 `ThemeProvider`，不在挂载时修改偏好。

| Token / Tailwind | 浅色 | 深色 | 用途 |
| --- | --- | --- | --- |
| `--agent-canvas` / `bg-agent-canvas` | #ffffff | #212121 | 主背景 |
| `--agent-sidebar` | #f9f9f9 | #181818 | 侧栏 |
| `--agent-surface` | #ffffff | #303030 | 输入框、菜单 |
| `--agent-subtle` | #f4f4f4 | #2c2c2c | 用户消息、hover |
| `--agent-text` | #252525 | #ececec | 主文案 |
| `--agent-muted` | #737373 | #a3a3a3 | 辅助说明 |
| `--agent-border` | #e8e8e8 | #404040 | 弱分隔线 |
| `--agent-strong` | #242424 | #ececec | 主要提交动作 |
| `--agent-on-strong` | #ffffff | #212121 | 主按钮文字 |
| `--agent-success` | #34745c | #86c8aa | 完成状态 |

圆角：composer 26px、卡片 16px、菜单 14px、按钮 10px、tab pill 999px。字号：大标题 clamp(26px, 3vw, 36px)，正文 15/16px、辅助 12/13px；行高正文 1.7。图标统一 lucide，16–20px，strokeWidth 1.7–2。阴影只用于 composer 与浮层。动效 150–200ms，尊重 prefers-reduced-motion。

## 分层与依赖方向

```text
primitive  @base-ui/react + 原生 textarea/input
    ↓
component  components/ui/{button,tooltip,icon-button,segmented-tabs,menu,dialog,auto-textarea}
    ↓
block      blocks/chat-composer（输入、统一动作菜单、附件、selection、提交/停止）
           blocks/user-message-navigation-rail（用户消息索引、预览与导航）
    ↓
feature    features/agent/{model,infrastructure,ui}
    ↓
page       routes/_authenticated/agent.tsx
```

UI 不知道聊天、路由或后端；block 不导入 feature。Feature 负责语言文案、mode、草稿、会话、运行状态和示例 transport。Page 仅装配 feature。避免复制 LibreChat 的 Recoil、React Hook Form 与 endpoint 分支到本项目。

## ChatComposer 契约

受控 block 接收 `value/onValueChange`、`attachments/onFilesAdded/onRemoveAttachment`、`modelId/models/onModelChange`、`tools/onToolToggle`、`busy/onSubmit/onStop` 与 `labels`。新增 `actions` 注册菜单动作，`selections/onRemoveSelection` 展示引用与工具 chip，`hasContext` 表达上下文是否可独立提交；`inputRef/actionTriggerRef` 供宿主安排焦点。`onSubmit` 不直接进行网络请求，父级负责校验与状态切换。组件不包含业务模式判断；Task 所需额外说明通过 `context` 插槽注入。

共同行为：textarea 高度在64–200px之间增长、超长内容内部滚动；短视口进一步按22dvh限制输入高度，会话中的输入区和底部容器提供有界滚动，避免发送按钮落在不可访问区域。Enter发送、Shift+Enter换行、中文IME合成及长按重复键不提交。空白且无附件／引用时禁用发送，附件或引用可单独提交，工具开关本身不能提交。支持附件选择／粘贴／拖放／删除、模型单选、plus内工具多选、发送／停止互斥。没有接入语音服务时不显示录音入口。

`busy` 时保留可编辑文本，锁定plus、附件、引用、模型和工具，发送按钮替换为停止按钮；当前接口没有独立 `disabled` prop。`error` 是宿主传入的可访问校验提示，不代表block实现了传输错误或重试。文件类型、最多5个及单个20MiB的限制由 feature 中的 `validateAttachments` 执行；block只转交File并展示元信息，不读取内容、不存储File、不上传。链接／文本／技能合计最多8条，引用校验与去重由feature负责；不自动抓取URL或执行技能。

Chat/Task 使用各自的草稿（文字、附件、引用、模型、工具）与当前会话。草稿按模式保存，尚未实现每个历史会话独立的草稿。运行中可通过顶部Tabs切到另一模式，返回仍能停止原运行；同模式新建或改选另一会话会结束原预览，离开页面会清理所有计时器。新建清空该模式的文本、附件与引用，并保留模型／工具选择。每次运行有独立身份，过期异步回调不能覆盖新会话。示例回复标记为预览，不宣称已完成真实搜索、文件读取、技能或代码执行。

提交时把 `modelId`、复制后的 `tools` 与独立引用快照记录到 `PreviewRun`；用户消息也保存引用快照，后续草稿变化不改变当前运行或消息详情。Fast显示更简短的预设示例，Auto显示适中示例，Thoughtful在适中示例后增加三个进一步考虑的问题；这些是本地呈现差异，不是真实模型推理。已选工具与引用会在回复末尾列出，并明确注明未实际执行／抓取。

## 无障碍与验证

- Tabs 提供 tablist/tab/tabpanel 和方向键导航；弹出菜单/抽屉支持 Escape、焦点返回。
- 图标按钮有可访问名称；状态使用文本配合图标，不只依赖颜色。
- 发送与停止状态通过 live region 提示，避免逐字符播报整个回答。
- 自动化覆盖模式草稿隔离、IME、重复提交保护、停止／新建取消、附件限制、独立模式运行、模型／工具菜单与Tabs键盘行为。
- 浏览器QA检查桌面／手机、浅色／深色、菜单、搜索、新会话、发送、停止与Tab。测试浏览器中的session fixture只用于UI验证，不是产品认证功能；产品未添加绕过开关。
- plus扩展前的历史验证：`pnpm --filter web check-types`、`pnpm --filter web build`及142项测试通过；当时相关文件定向lint通过。全仓`pnpm --filter web lint`因已有16条警告退出1，不能标为全仓lint通过。这些历史数量不代表本轮扩展验收结果。
- 早期Playwright实测：移动抽屉焦点返回、初次发送焦点、Chat/Task 草稿隔离、停止后保留下一条草稿且不误发送、模型/工具选择、任务完成、搜索、新建；390×390 视口下5个附件与15行草稿可操作，320px无横向溢出。该次生产构建浏览器控制台0 errors/0 warnings。
- 历史截图：[桌面浅色](../output/playwright/agent-desktop-light.png)、[桌面深色](../output/playwright/agent-desktop-dark.png)、[任务状态](../output/playwright/agent-task-dark.png)、[移动端](../output/playwright/agent-mobile-light.png)。截图中的用户是测试fixture；plus扩展的新验证与截图见[本轮验收记录](./agent-composer-actions.md#7-验收清单与记录)。

## 后端接入阶段

替换示例 transport，使用服务端模型能力清单、文件上传 ID、run ID、SSE/流式事件、取消接口及规范化错误。新增失败事件、用户可理解的错误与重试／恢复策略，并验证幂等和取消回执；这些尚未由当前本地预览实现。服务端是执行状态与完成结果的权威来源。`chat/task` 属于页面交互模式，不直接写入Python会话API目前仅支持的`agent/image` mode；Rust也尚未注册对应执行路由。数据库新增表沿用本项目单数命名规则。
