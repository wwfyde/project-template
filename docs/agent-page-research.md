# Agent 页面研究与实现需求

研究日期：2026-11-17。本文为 Agent 页面实现的需求基线，已接入 **Chat / Task 双模式、共享 ChatComposer 与统一 plus 菜单**；上下文扩展已完成本轮验收，Creative 图片／视频仅保留扩展设计。

后续在真实 Chrome 中完成的 Beautiful UI Prompt Bar 与 ChatGPT 登录态 plus 菜单核实见 [输入器动作与上下文](./agent-composer-actions.md)。该文补充本文早期公开页面访问的证据边界，并记录新增入口的实现与验收状态。

## 1. 范围、假设与证据边界

- 本期交付一个受现有登录保护、可以操作的 Agent 页面预览。聊天与任务分别拥有模式草稿、当前会话和执行状态；共享输入器与基础视觉组件。
- 当前仓库没有可核实的已注册 Agent 执行 HTTP 路由。本期通过明确标记的示例 transport 演示交互，不宣称模型、联网搜索、工具、任务队列或文件分析已在真实后端执行。
- 本期数据保留在当前页面的内存中。刷新后重置；不把用户内容自动写入 localStorage，也不把示例消息写进真实会话 API。
- 模型／工具选择是输入意图；是否能执行必须由后续服务端能力目录决定。切换一个工具 chip 不等于已经获得工具权限。
- Creative 与 Chat / Task 并列扩展，但图片／视频的比例、清晰度、时长等参数不进入通用 ChatComposer 的必填接口。

交付范围校正：以下研究保留了完整能力规划；已实现范围以 [设计与实现说明](./agent-design-system.md) 和 [输入器动作与上下文](./agent-composer-actions.md) 为准。当前Task是会话内的步骤预览，没有独立后台任务列表、状态筛选或生成失败／重试流程。实际运行覆盖进行中、完成与取消；错误提示覆盖附件／引用校验、复制失败与真实技能目录加载失败。草稿按Chat / Task两模式保存，尚未按每个历史会话独立保存。

本地源码证据来自以下版本与当时工作区；这不是对上游最新版能力的承诺：

| 来源 | 检查版本 | 检查范围 |
| --- | --- | --- |
| `project-template` | 基础 HEAD `4e14968affb5d0a05fc0d8365a82084fdd2dc915`，包含当时未提交工作区内容 | `web/src`、Python与Rust路由、会话 schema、Agent 模型及现有文档 |
| 本地 `LibreChat` | `9529c99f5ebd5469942feb2c83a785894f48522b` | Composer、Textarea、快捷键、语音、附件、导航、后台任务、聊天 transport 与状态类型 |
| [Beautiful UI](https://www.beautifului.dev/#prompt-bar) | 2026-11-17 公开页面、真实Chrome CUA与View code | 组件目录、Prompt Bar plus选择行为、完整`components/PromptBar.tsx`；没有复制组件源码 |
| [ChatGPT](https://chatgpt.com/) | 2026-11-17 公开页面文本与后续登录态Chrome CUA | 早期公开页面请求曾返回403；本轮已核实plus菜单及选择网页搜索后的token／模型按钮状态，不代表所有账号或套餐能力 |

研究遵循本地 LibreChat 的 [AGENTS.md](../../LibreChat/AGENTS.md)，仅只读查看；没有构建全仓 graphify 图谱。以下以 **PT** 表示当前项目根目录，以 **LC** 表示 `/Users/wwfyde/projects/LibreChat`；所有代码出处均给出可定位的仓库相对路径。

## 2. 参考对象提供什么

### 2.1 Beautiful UI：简洁的输入中心与可扫读的执行反馈

官网组件目录展示 Prompt Bar 的 `@sources`、`/commands`、模型选择、听写；Task Rows 覆盖 running / failed / completed；Approval Card 表达需要人工决策的执行环节；Chat 组件提供 tabbed chat、消息回复和 composer。实看的深色 Prompt Bar 使用中性暗灰容器、细描边、紧凑圆角条，左侧添加入口，右侧模型／麦克风／提交操作。[来源：Beautiful UI](https://beautifului.dev/)

本轮实际点开plus并选择示例来源后，菜单关闭，来源以`@名称`写入草稿，焦点返回输入框。View code表明它通过配置与统一分派管理来源／命令／模型；文件、听写和连接状态含本地演示逻辑，不能作为真实服务接入证据。详细观察见[plus证据记录](./agent-composer-actions.md#1-参考证据与采用范围)。

本项目吸收其信息密度和控件排列：留出主要输入空间、收敛辅助按钮、让选中工具与执行状态可见。本轮采用统一动作菜单与独立引用chip；`@source`／`/command`候选输入尚未实现。Approval Card 属于 P2；当前无审批协议，不添加一个看似可批准实际操作的伪入口。

### 2.2 ChatGPT：以开始输入和继续工作为中心

公开首页可读取 “What are you working on?” / “Where should we begin?” 等欢迎语，以及新对话、图像、插件与文件／搜索相关入口。适合借鉴的是：空态有清楚的主动作，输入器承担主要入口，已有对话后正文成为视觉主角。[来源：ChatGPT 公开首页](https://chatgpt.com/)

后续CUA已验证当时登录页面的“添加文件等内容”菜单：包含文件、资料库、图像、浏览器标签页、搜索、项目、深度研究及其他能力入口；选择网页搜索后出现工具token，模型按钮当时变为不可用。未发送消息，不能据此证明工具执行成功；菜单内容也不是当前套餐或所有账号能力的通用承诺。本项目没有通用资料库、浏览器标签页读取或图像生成能力，不添加相应伪入口。

### 2.3 LibreChat：可复用的职责分离与生命周期处理

本地版本正在把聊天状态、transport 与可复用消息／composer 组件迁入 `packages/chat`；应用侧保留配置、权限、导航和数据绑定。这个方向比直接复制庞大的 `ChatForm` 更适合当前项目。[LC：`AGENTS.md`](../../LibreChat/AGENTS.md)

| 研究项 | 源码事实 | 本项目采用的需求 |
| --- | --- | --- |
| 输入器布局 | `ComposerFrame` 接收 form submit、输入聚焦、queue、context rail、popovers、hints 插槽 | `ChatComposer` 负责可复用布局；运行与持久化属于 feature |
| 输入域 | `ComposerField` 以 `TextareaAutosize` 实现增长、长文收起、录音波形与锁定态 | P0 自动增高并限制最大高度；长内容滚动，不推走整个页面 |
| 提交按钮 | `ComposerActions` 根据文本、附件、提交中、停止能力决定 Send / Stop / during-run 操作 | P0 空白不能提交；运行时可停止；避免重复提交 |
| 应用组装 | `ChatForm` 组合配置、文件状态、草稿、语音、输入事件与执行动作 | 不把所有逻辑塞到 `AgentPage` 或通用 UI 组件 |
| 工具面板 | `usePaletteEntries` 把工具、skill、MCP 映射成统一 entry；区分 active 与 pinned | 工具菜单与已选 chip 用同一受控数据源，显示名称与状态 |
| 输入快捷键 | `useTextarea` 处理 Enter、组合输入、快捷键与粘贴；组合输入兼容 `Process` / 229 | Enter 提交，Shift+Enter 换行；中文候选确认不能误发 |
| 语音 | `useDictation` 管理原草稿、录音 take、听写结果、取消与可选自动发送 | 语音不是一个装饰图标；P0无语音能力则隐藏／清楚解释，不模拟已录音 |
| 附件 | 文件 chip 与上传状态独立；已提交附件须阻止异步上传回调重新写回 composer | 添加／移除／失败／待上传必须可理解；后续上传按稳定 ID 归属草稿 |
| 聊天运行 | `ChatStatus` 与 `ChatConnection` 分开，重连不等于生成完成 | UI运行态不等同网络状态；P1真实服务接入再启用重连语义 |
| 后台任务 | `TaskRow` 区分 tool / subagent；运行、停止中、完成、错误、取消；任务结果投递另有状态 | Task 列表以明确状态与时间反馈，不用假百分比表示未知进度 |

对应精确源码：

- LC [`packages/chat/src/components/composer/Frame.tsx`](../../LibreChat/packages/chat/src/components/composer/Frame.tsx)、[`input/Field.tsx`](../../LibreChat/packages/chat/src/components/composer/input/Field.tsx)、[`input/Actions.tsx`](../../LibreChat/packages/chat/src/components/composer/input/Actions.tsx)。
- LC [`client/src/components/Chat/Input/ChatForm.tsx`](../../LibreChat/client/src/components/Chat/Input/ChatForm.tsx)、[`Composer/Bar.tsx`](../../LibreChat/client/src/components/Chat/Input/Composer/Bar.tsx)、[`Composer/Actions.tsx`](../../LibreChat/client/src/components/Chat/Input/Composer/Actions.tsx)。后者把对文本的订阅放到 action slot，避免每次打字重绘整个工具栏；当前项目无需先引入相同表单库。
- LC [`client/src/hooks/Input/useTextarea.ts`](../../LibreChat/client/src/hooks/Input/useTextarea.ts)、[`useComposerBindings.ts`](../../LibreChat/client/src/hooks/Input/useComposerBindings.ts)、[`useDictation.ts`](../../LibreChat/client/src/hooks/Input/useDictation.ts)、[`usePaletteEntries.tsx`](../../LibreChat/client/src/hooks/Input/usePaletteEntries.tsx)。
- LC [`packages/chat/src/core/composer.ts`](../../LibreChat/packages/chat/src/core/composer.ts)、[`core/types.ts`](../../LibreChat/packages/chat/src/core/types.ts)、[`react/state.ts`](../../LibreChat/packages/chat/src/react/state.ts)。
- LC [`client/src/components/Chat/BackgroundTasks/rows.ts`](../../LibreChat/client/src/components/Chat/BackgroundTasks/rows.ts)、[`useTasks.ts`](../../LibreChat/client/src/components/Chat/BackgroundTasks/useTasks.ts)。停止回执被接受不等于执行已经结束，不能提前标记完成。

## 3. 当前项目能力盘点

### 3.1 Web 可复用基础

当前 web 使用 React 19、TypeScript、Vite、Tailwind 4、Base UI、TanStack Router / Query、i18next 与 Lucide。已有 UI Button / Tooltip、语义主题 token、中英文资源和认证壳层，适合继续使用，不需要加入 LibreChat 的 Ariakit、Jotai、Recoil 或另一套 UI 框架。[PT：`web/package.json`](../web/package.json)、[`web/src/components/ui/button.tsx`](../web/src/components/ui/button.tsx)、[`tooltip.tsx`](../web/src/components/ui/tooltip.tsx)、[`web/src/theme/styles/theme.css`](../web/src/theme/styles/theme.css)

认证路由在 `/_authenticated` 的 `beforeLoad` 确认 session，未登录跳转 `/login`；页面应置于这个分支。现有 shell 提供主导航、账户、语言和主题切换，Agent 应保留这些入口。[PT：`web/src/routes/_authenticated.tsx`](../web/src/routes/_authenticated.tsx)、[`web/src/app/layout/authenticated-shell.tsx`](../web/src/app/layout/authenticated-shell.tsx)

已有 `blocks/user-message-navigation-rail` 提供用户消息定位；对应 feature 使用显式中英文示例数据，不能当作真实会话数据接口。Agent 已复用该 block，正文滚动和书签存储仍由 feature 管理。[PT：`web/src/blocks/user-message-navigation-rail/README.md`](../web/src/blocks/user-message-navigation-rail/README.md)、[`web/src/features/user-message-navigation-rail-demo/model/conversation.ts`](../web/src/features/user-message-navigation-rail-demo/model/conversation.ts)

现有 `requestJson` 只允许同源 `/api` 路径，携带 cookie、生成 Request-ID，返回结构化请求错误。业务 client 按 feature 放置在 `infrastructure` 并使用 `auth.authenticatedRequest`；后续 Agent client 应遵循此边界。JSON helper 不能直接作为 SSE 解析器。[PT：`web/src/lib/api-client.ts`](../web/src/lib/api-client.ts)、[`web/src/features/skills/infrastructure/skill-client.ts`](../web/src/features/skills/infrastructure/skill-client.ts)

### 3.2 后端真实边界

仓库同时保留 Python `api/` 与 Rust `api-rs/`。下表首先描述 **Python服务源码注册的能力**，不代表当前运行环境已启动它或已配置模型服务。Rust当前 `api-rs/src/routes.rs` 仅合并 user / item / auth / account 路由，未注册 conversation / agent / chat / task。Rust认证采用 API key + JWT；Web既有认证使用 cookie session，两者不能因都位于 `/api` 就视为兼容。本期沿用Web已有登录边界，真实部署接入前还需确定后端与认证协议。[PT：`api-rs/src/routes.rs`](../api-rs/src/routes.rs)、[`api-rs/src/app.rs`](../api-rs/src/app.rs)、[`api-rs/README.md`](../api-rs/README.md)、[`web/README.md`](../web/README.md)

以下结论来自已注册路由与处理函数，不根据文件名或旧文档推断可用能力。

| 能力 | 当前事实 | 页面接入策略 |
| --- | --- | --- |
| 登录与账户 | 已有认证路由与前端 Auth provider | P0沿用真实认证 |
| 会话列表／详情 | `/api/conversations` GET/POST；`/{id}` GET/PATCH/DELETE | 可作为后续保存与历史入口；P0示例不混入真实记录 |
| 消息保存 | `/{id}/messages` GET/POST 只读写消息；没有模型生成调用 | 不把保存成功解释成回答生成成功 |
| 会话模式 | schema 仅允许 `agent`、`image` | UI的 `chat` / `task` 不能直接作为后端 `mode` 提交 |
| Agent 执行 | 当前注册路由中没有 `/agents`；`api/src/api/agents` 主要是空入口 | P0使用明确命名的示例 adapter；P1补协议后接真实执行 |
| Agent 数据模型 | 存在 `agent_session` / `agent_turn` 表模型与迁移 | 模型存在不等于路由、runner、取消或恢复能力存在 |
| 旧执行文档 | `api/agents.md` 描述 sessions、turns、SSE，但所述实现未出现在当前路由树 | 作为未来协议参考；不能按旧文档直接调用或声称已实现 |
| Skill 资产管理 | `/api/skills` 已注册；有独立前端 client | 资产可管理不代表已接入 Agent 的执行上下文 |
| 图片工具 | `/api/ai-tools/images/...` 已注册直接图片工具调用 | 与通用聊天／任务执行分开；Creative后续评估其参数与服务配置 |
| 图片资产 client | web 有 `/api/images/...` client；当前主 router 未见这些 endpoint 的注册 | 不把客户端定义视为完整后端可用证明 |
| 模型目录／通用附件／STT | 当前已注册路由未见对应 Agent 能力目录或处理端点 | P0仅展示能力边界；真实模型／文件／语音接入另行完成 |

证据：PT [`api/src/api/main.py`](../api/src/api/main.py)、[`api/src/api/routes/__init__.py`](../api/src/api/routes/__init__.py)、[`api/src/api/routes/conversations.py`](../api/src/api/routes/conversations.py)、[`api/src/api/schemas/conversation.py`](../api/src/api/schemas/conversation.py)、[`api/src/api/models/agent_session.py`](../api/src/api/models/agent_session.py)、[`api/agents.md`](../api/agents.md)、[`api/src/api/routes/ai_tools.py`](../api/src/api/routes/ai_tools.py)、[`web/src/features/images/infrastructure/image-client.ts`](../web/src/features/images/infrastructure/image-client.ts)。

所有新增数据库表仍遵守单数命名约定。P0不新增数据库表，不扩大后端范围。

## 4. 产品结构与核心流程

### 4.1 页面结构

页面由四个区域组成：轻量页面标题／执行模式 Tabs、会话或任务导航、主内容区、共享输入器。桌面导航在左侧，窄屏通过有名称的按钮打开；空态将欢迎语与输入器放在阅读中心，已有内容后将输入器保持在内容底部的可见位置。

- **Chat（本期）**：新建聊天、切换聊天、输入问题、查看用户与助手消息、复制回答、停止当前演示；生成失败与重试留待真实执行协议接入。
- **Task（本期）**：通过会话入口创建／选择任务预览、查看目标与步骤、停止运行；独立任务列表、状态筛选与失败／取消重试属于后续范围。
- **Creative（未来）**：图片／视频类型、参考素材与生成参数；选择 mode 的策略与参数面板可复用，执行契约独立。

在 Chat 输入未发送文本，切到 Task 输入另一段文本，再切回来，第一段文本必须保留。切换模式不应替用户提交、清空草稿或把任务状态变成聊天状态。

### 4.2 首次进入与示例边界

页面显示可理解的示例提示，例如“交互预览 · 内容仅保留在当前页面”。该提示解释产品行为，不向用户暴露 transport、SSE 或 adapter 等实现术语。

推荐卡片／示例任务必须能实际填入输入器或打开相应示例详情。不要用不可点击的装饰卡片暗示功能。选择模型和工具后，应能看到当前选择；运行结果仍明确属于交互示例，不生成虚假的“已搜索网页”“已读取附件”或真实 token／费用数值。

### 4.3 Chat 生命周期

`idle → submitting → streaming → completed`，以及从执行阶段进入 `cancelled` / `failed`。这些是本项目建议的界面状态，不是现有后端协议。

- 提交前验证 `text.trim()`；无文本、附件和有效引用时禁用发送，工具开关本身不能作为提交内容。当前附件仅展示元信息；真实上传接入后再加入就绪条件。
- 提交产生稳定 message / turn ID；一次确认操作只创建一个用户消息。
- 正在生成时可见停止入口；停止后保留已有文本并显示已停止，不把部分内容冒充完整回答。
- 错误提供可理解的原因与重试入口；重试应指向原输入，不能制造无穷重复消息。
- 用户向上阅读时不强行拉到底部；靠近底部时继续跟随新消息，可显示“回到最新”。
- 更换聊天或退出页面后，旧执行的异步事件只能更新其原属会话，不能污染当前会话。

### 4.4 Task 生命周期

推荐最小模型：`queued → running → completed | failed | cancelled`。如果取消并非立即生效，则另有 `stopping`；`waiting_for_input` 需要真实问答或审批协议后再启用。

任务行包含稳定 ID、标题、简短目标、状态、创建／更新时间；详情包含步骤列表与最终结果。任务状态用图标加文案表达，不能仅靠颜色。未知真实进度不显示具体百分比。P0可以演示确定的阶段变化，但必须处于示例上下文。

## 5. 共享 ChatComposer 契约与分层

依赖方向严格保持：**primitive → component（ui）→ block / widget → feature → page**。高层组合低层；低层不 import feature、不读路由、不发业务请求。

| 层级 | 所有权 | 本项目建议 |
| --- | --- | --- |
| primitive | 无样式的交互、DOM与可访问性行为 | Base UI Button / Tabs / Menu / Popover；原生 textarea / input |
| component / ui | 语义样式、变体、焦点、尺寸、可复用小控件 | `components/ui/button`、tooltip、textarea、tabs、menu、status badge |
| block / widget | 可独立组合的较大界面，受控输入与事件回调 | `blocks/chat-composer`、`blocks/user-message-navigation-rail`；feature专属任务列表先留 feature |
| feature | 领域模型、草稿、会话与任务状态、transport、错误恢复 | `features/agent/model`、`infrastructure`、`ui` |
| page / route | 认证分支下装配 feature，页面级入口 | `/agent` 路由只渲染 AgentPage，不实现提交逻辑 |

共享的是 **输入交互**，不是把三种业务写进一个超大组件。以下保留早期最小接口草案，不能作为当前导出类型使用；实际实现以[ChatComposer契约](../web/src/blocks/chat-composer/README.md)和[types.ts](../web/src/blocks/chat-composer/types.ts)为准。当前使用`busy`而非`status`／`disabled`，并通过`actions`、`selections`、`hasContext`与refs扩展plus及上下文：

```ts
type ComposerStatus = 'idle' | 'submitting' | 'streaming' | 'stopping'

interface ChatComposerProps {
  value: string
  onValueChange: (value: string) => void
  onSubmit: () => void
  onStop?: () => void
  status: ComposerStatus
  disabled?: boolean
  placeholder: string
  // 用受控选项或插槽承载模型、工具、附件；不绑定某家SDK。
  leadingActions?: React.ReactNode
  trailingActions?: React.ReactNode
  attachments?: React.ReactNode
  hint?: React.ReactNode
}
```

仅在确实被多个调用方使用时增加对应 prop；不为未实现的语音、MCP、图像比例提前建立一套复杂抽象。Chat / Task 只更换提示、功能配置和提交 handler，继续用同一个组件。Creative未来通过插槽加入参数，不复制一份输入器。

草稿由feature管理；本期按`mode`隔离，包含文本、附件、链接／文本／技能引用、模型和工具。未来需要历史会话独立草稿时再扩展为`mode + conversation/task ID`。通用组件只保留聚焦、弹层、textarea高度等短暂交互状态；引用校验／去重、真实技能目录读取、默认版本选择、模型选择、附件归属、运行ID、取消与未来重试属于feature。提交时同时保存用户消息和运行的引用快照，消息中可展开查看内容。

## 6. 功能优先级矩阵

P0为本次实现；P1为真实服务接入与完整工作流；P2为明确的后续扩展。

| 功能 | P0：交互预览 | P1：真实服务 | P2：扩展 |
| --- | --- | --- | --- |
| 页面与路由 | `/agent`、认证、导航入口、Chat / Task Tabs | URL恢复所选会话／任务 | 工作空间／项目组织 |
| Shared composer | 受控文本、增长、键盘、统一plus、引用chip、提交／停止、清晰禁用态 | 服务能力驱动模型／工具、附件与语音；`@source`／`/command`候选输入 | 可配置快捷键 |
| 草稿 | 两模式独立；页面内保留 | 各记录独立、明确存储介质与账户隔离 | 多端恢复与冲突处理 |
| Chat | 空态、消息列表、示例回复、复制、停止 | 真实流、持久化、失败恢复与重试 | 分支编辑、重新生成、共享／导出 |
| Task | 会话入口、步骤详情、创建与停止预览 | 独立任务列表／筛选、后台执行、任务ID、取消回执与重试 | 子代理、排队／优先级、审批与人工补充 |
| 模型选择 | 可见选中项，标识为示例选项 | 服务端目录及能力／配置校验 | 成本、上下文与推理档位 |
| 工具选择 | plus内选择与chip同步；真实技能目录选择默认版本引用，结果不虚报执行 | 服务器允许的工具和权限状态、技能执行与正文展开 | MCP、工具收藏 |
| 上下文引用 | 链接／文本／技能引用、校验／去重、模式隔离、提交快照与消息详情 | 明确授权的来源抓取、通用资料库与稳定资源ID | 多源索引与长期知识库 |
| 附件 | 本地选择／粘贴／拖放／移除及校验，只保留元信息；不声称上传或分析 | 上传限制、进度、失败、归属、文件 ID | 知识库与长期资产 |
| 语音 | 无真实实现时隐藏或解释未接入 | 能力检测、麦克风许可、录音、取消、转写 | 连续语音与TTS |
| 状态反馈 | empty / running / completed / cancelled；附件校验与复制失败提示 | 生成失败、网络状态、重连、请求ID、幂等控制 | 稳定事件序列与重放 |
| Creative | 仅文档与扩展点 | 独立图片模式评估 | 视频、首尾帧、画布、多资产工作流 |
| 适配 | 中英文、亮暗主题、移动端、键盘与减少动效 | 真实长记录及大附件性能 | 高对比、RTL等进一步覆盖 |

## 7. 复用项与不照搬项

**直接复用本项目基础**：Base UI 与 Button / Tooltip、语义 token、i18next、认证壳、feature/infrastructure 边界。长对话复用 user-message navigation rail。

**借鉴 LibreChat 的设计**：输入器 frame / field / actions 分离；宿主拥有业务状态；文本与附件的提交条件；组合输入保护；草稿归属；取消回执与最终状态分离；网络连接和执行状态分离。

**不直接照搬**：庞大 ChatForm、Jotai/Recoil双状态体系、多provider endpoint体系、助手历史兼容逻辑、MCP配置、持久队列／steering、复杂跨标签草稿恢复。这些解决的是 LibreChat 已有产品规模的问题，当前项目引入它们会增加维护面。

**不复制商业组件源码**：Beautiful UI作为公开视觉与功能参考；本项目组件自行实现。LibreChat为MIT许可，如果后续复制实质源码必须保留其版权与许可文本；本次以行为与架构研究为主。[LC：`LICENSE`](../../LibreChat/LICENSE)

## 8. P0验收条件

1. 登录后可从主导航进入 `/agent`；未登录沿用既有登录跳转与返回路径。
2. Chat / Task 使用同一个 ChatComposer实现；依赖方向无反转，route文件无业务执行逻辑。
3. Chat / Task的草稿相互独立；切换模式不丢失尚未提交内容，不自动发送；同模式共享当前草稿，新建清空文本与附件。
4. 空白输入不可提交；Enter提交、Shift+Enter换行；中文输入法确认候选时不触发提交。
5. 发送一次只增加一个用户输入；运行中可以停止，取消后的延迟事件不能继续改写结果。
6. 新建、切换、复制、标题搜索、查看任务步骤、停止等可见控件有真实可观察效果；无空handler，不展示尚未实现的重试入口。
7. 示例执行、示例模型与刷新清空的范围在界面中可理解；不出现“已上传／已联网／真实生成完成”等未经证实的结果。
8. 页面覆盖空态、运行态、完成态和取消态；附件校验与复制失败有文案，状态不只依赖颜色；真实生成失败恢复留待P1。
9. 320px移动宽度与常见桌面宽度无页面横向溢出；长文件名、长文本、英文长词可换行；弹层不被裁切。
10. 明暗主题和中英文切换保持布局与内容完整；语义颜色遵循现有token；减少动态效果偏好有效。
11. Tab可到达主要控件；模式Tabs、弹层、关闭、发送／停止具有可访问名称、可见焦点；Escape关闭浮层后焦点恢复。
12. 执行`pnpm --dir web check-types`、测试、lint和build；针对状态归属、取消后不再写入、输入法提交边界做必要的行为验证。已有全仓lint问题与本次定向lint结果分别记录，不把未通过的检查宣称为通过；实际结果见设计与实现说明。

## 9. P1接入前必须补齐的协议

以下是设计建议，不代表已经存在的endpoint：

- 能力目录：服务端返回可用 backend / model / tool、支持的输入类型、权限与不可用原因。
- 会话与任务身份：明确 Conversation、AgentSession、Turn、Task 的映射。不要直接把当前 `Conversation.mode` 当成页面Tabs枚举。
- 事件：启动、文本增量、步骤／工具状态、完成、失败、取消终态；每个事件携带目标ID与递增序列，客户端验证归属。
- 取消：说明仅断开连接还是停止服务端执行；异步停止需要 `stopping` 与最终回执。
- 重试与恢复：规定幂等键、重试范围、网络中断后是否继续执行、是否支持重放；没有保证时不盲目重发具有副作用的任务。
- 附件：上传独立完成，确认文件ID、所有权、类型与大小限制；展示预览与参与推理是两项不同能力。
- 安全错误与权限：使用现有认证请求入口；保持账户隔离；错误码映射成界面文案，避免透传内部异常。

旧 `api/agents.md` 可提供 session / turn / SSE术语参考，但必须与本次落地代码重新核对和更新后才能成为接入依据。
