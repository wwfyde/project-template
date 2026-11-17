# Agent 输入器的 plus 菜单与上下文

观察日期：2026-11-17。状态：实现与本轮验收完成。本文记录 plus 菜单的浏览器证据、已落地的实现契约及能力边界；验证范围见文末记录。页面总体设计见 [Agent 设计与实现说明](./agent-design-system.md)，共享组件类型见 [ChatComposer](../web/src/blocks/chat-composer/README.md)。

## 1. 参考证据与采用范围

本轮使用 CUA 在真实 Chrome 中打开参考页面，检查 plus 菜单并实际选择一个条目。记录只覆盖当时页面可见行为，不代表所有账号、套餐、地区或后续版本都具备相同能力。没有向参考服务发送消息或提交文件。

| 来源与动作 | 可核实的观察 | 对本项目的启发 |
| --- | --- | --- |
| [Beautiful UI Prompt Bar](https://www.beautifului.dev/#prompt-bar)：打开 plus | 按钮名称为 “Add attachments and sources”；菜单混合上传、示例来源和外部服务连接入口 | plus 是添加上下文的入口；每项需要有明确动作与说明 |
| Beautiful UI：选择示例来源 “Flavor records” | 菜单关闭，输入框插入 `@Flavor records `，焦点回到输入框 | 选择应留下可见结果，并支持继续输入 |
| Beautiful UI：打开 View code，阅读完整 `components/PromptBar.tsx` | `SOURCES`、`COMMANDS`、`MODELS` 配置驱动条目；`parseToken` 识别末尾的 `@` 或 `/` 查询；`plusOpen` 复用来源菜单；`pick` 按 attachment / source / command 分派动作 | 复用数据配置与分派边界；不要求一次引入所有快捷输入行为 |
| Beautiful UI：源码中的交互 | 上下键、Enter、Tab 选择，Escape 和点击外部关闭，选后聚焦 | 键盘与焦点属于功能的一部分，不能只画一个菜单 |
| Beautiful UI：源码中的演示边界 | 文件来自 `FILES` 中轮换的示例文件名；听写通过定时器插入预置文本；连接状态是本地 boolean | 这些是演示逻辑，不能当成文件上传、语音识别或 OAuth 接入的证据 |
| [ChatGPT](https://chatgpt.com/)：登录后打开“添加文件等内容” | 可见上传照片和文件、从资料库添加、创建图像、添加浏览器标签页、网页搜索、在项目中工作、深度研究、绘图及已连接能力入口 | 单个 plus 可以聚合上下文与工具，但条目必须由实际能力决定 |
| ChatGPT：选择“网页搜索” | 菜单关闭；输入器出现带地球图标的工具 token；当时页面的模型按钮变为不可用 | 激活工具后应有持续可见的选择状态；模型与工具约束需要显式表达 |

Beautiful UI 页面公开提供 [Prompt Bar registry](https://www.beautifului.dev/r/prompt-bar.json) 与 [全局样式源码](https://github.com/slev12397/beautiful-ui/blob/main/app/globals.css) 链接。本文据实际浏览的页面与 View code 记录行为；没有复制该组件实现。用户提供的截图也支持“plus 打开多类动作菜单”这一结构，但截图本身不能证明条目后续执行成功。

本轮登录态 CUA 观察补充了 [原研究文档](./agent-page-research.md) 中“公开页面请求曾返回 403”的早期证据边界。不得从本次观察推导 ChatGPT 的通用套餐承诺，也不记录参考账号、私人插件名称或聊天内容。

## 2. 项目入口行为矩阵

本项目 plus 统一承载附件、上下文、工作模式和工具。模型选择保持独立；已删除独立工具按钮。当前菜单顺序为：上传文件 → 上下文（链接、文本、技能）→ 工作模式（切换到另一个模式）→ 工具（联网搜索、深度思考）。菜单项按语义分组，并显示简短说明；不可用项显示原因。

| 入口 | 选择后的动作 | 可见结果与删除方式 | 本期能力边界 |
| --- | --- | --- | --- |
| 上传文件 | 打开原生文件选择器，沿用粘贴／拖放校验 | 附件 chip 展示名称与大小，可移除 | 最多 5 个、单个 20MiB；只保留元信息，不读取或上传文件字节 |
| 添加网页链接 | 打开链接对话框，验证后添加引用；名称可选，留空时使用域名 | 独立引用 chip，可移除；提交后可展开查看 URL | 仅接受 `http:` / `https:` URL；不自动打开、抓取或解析远程页面 |
| 添加文本资料 | 打开文本对话框，填写名称和内容后添加引用 | 独立引用 chip，可移除；提交后可展开查看文本 | 保存用户输入的文本；不把它伪装成已解析的文件 |
| 添加技能 | 打开技能选择器，通过既有客户端读取列表，选择默认版本 | 保存技能名称、ID、默认版本与描述；显示可移除引用 chip；提交后可展开查看 | 列表是实际 API 请求；选择不等于读取技能包全文或执行技能 |
| 切换到对话／任务模式 | 切到另一个模式并聚焦输入框 | 复用顶部 Tabs 的 mode 状态；保留两种模式各自草稿 | 不发送消息、不执行任务；运行时 plus 锁定，顶部 Tabs 仍可切换 |
| 联网搜索／深度思考 | 切换当前草稿中的工具状态 | 菜单勾选与输入器工具 chip 同步，可取消 | 仍是交互预览；没有真实搜索或工具执行 |
| 通用资料库、浏览器标签页 | 当前没有可执行入口 | 不显示虚假的“已添加”结果 | 项目尚无通用资料库协议或读取浏览器标签页的权限通道 |
| 创建图像／视频 | 留在后续 Creative 能力规划 | 不把切换菜单项表现成生成成功 | 未接入图像／视频执行 |

链接、文本和技能引用合计最多 8 个。标题最多 80 个字符，URL 最多 2,048 个字符，文本最多 12,000 个字符；校验在 feature/model 层执行，表单长度限制只是输入辅助。URL 拒绝控制字符、内部空白和内嵌用户名／密码，保留合法片段标识。任何非法或超限输入应保留可修正内容并显示原因，不进入草稿。链接不会产生后台抓取；技能选择只保留明确版本的引用。当前长度限制使用 JavaScript 字符串 `length`，不是字节或模型 token 数。

## 3. 分层、所有权与能力契约

```text
@base-ui/react Menu / Dialog、原生 input / textarea
    ↓
components/ui/menu、dialog 与现有输入、按钮、焦点样式
    ↓
blocks/chat-composer
    ├─ ComposerActionMenu：渲染 action / toggle 与分组
    ├─ ChatComposer：统一 plus、附件、引用与工具 chip
    └─ types：受控动作、展示选项与回调
    ↓
features/agent
    ├─ ui：组装能力、链接／文本／技能对话框与翻译
    │      ↘ 既有 features/skills client：认证后的技能列表读取
    ├─ model：ContextReference、校验、模式草稿与提交快照
    └─ infrastructure：本地 preview transport
    ↓
routes/_authenticated/agent.tsx：装配页面
```

箭头表示组合层次由底层向页面展开；实际 import 只能由 feature 指向 block、由 block 指向 ui，不能反向。通用 block 不导入技能 client、认证、路由或 Agent 领域类型，不发送业务请求。是否展示能力、是否可选及选择后的动作由 feature 决定。

对应源码：[动作类型](../web/src/blocks/chat-composer/types.ts)、[动作菜单](../web/src/blocks/chat-composer/composer-action-menu.tsx)、[输入器](../web/src/blocks/chat-composer/chat-composer.tsx)、[引用模型](../web/src/features/agent/model/context.ts)、[工作空间状态](../web/src/features/agent/model/workspace.ts)、[上下文对话框](../web/src/features/agent/ui/agent-context-dialog.tsx)、[消息引用详情](../web/src/features/agent/ui/context-reference-list.tsx)、[技能客户端](../web/src/features/skills/infrastructure/skill-client.ts)。

### 动作注册

`ComposerAction` 用稳定 `id`、文案、说明、图标和分组定义菜单项；`kind` 区分即时动作和受控开关：

```ts
type ComposerAction = ComposerActionBase & (
  | { kind: 'action'; onSelect: () => void }
  | { kind: 'toggle'; checked: boolean; onCheckedChange: (checked: boolean) => void }
)
```

共同字段为 `id`、`label`、可选 `description`、`icon`、`group`、`disabled`、`disabledReason`。`disabledReason` 优先于普通说明展示；宿主应同时给出 `disabled: true`，不能仅用文案表达禁用。各条目 ID 需要唯一且稳定，避免语言切换改变身份。block 将上传入口、宿主 `actions` 与工具 toggle 合并到同一个菜单。

该配置是 UI 能力注册契约，不是后端权限清单。后续接入服务端目录时，应先按账号权限、运行状态与模型兼容性计算可用性，再传入 block。不能因为注册了菜单项就默认已经授权外部服务连接。

`ComposerSelection` 只包含可展示的 `id`、`label`、可选 `description` 与 `icon`。宿主通过 `selections` 和 `onRemoveSelection` 控制引用 chip，通过 `hasContext` 明确引用是否可独立提交；block 不根据文案猜测业务类型。工具开关本身不构成可提交内容。

`inputRef` 与 `actionTriggerRef` 提供输入框和 plus 按钮的焦点目标，让宿主可以显式安排焦点；block 不需要认识对话框的业务类型。当前 Agent 使用 `inputRef`，对话框成功、关闭或取消后都返回输入框；`actionTriggerRef` 为其他宿主保留，当前页面没有绑定它。

### 引用模型

`ContextReference` 是判别联合：

| 类型 | 字段与含义 |
| --- | --- |
| `link` | 稳定 ID、`title`、合法 `url` |
| `text` | 稳定 ID、`title`、用户提供的 `text` |
| `skill` | 稳定 ID、`title`、`skillId`、`version`、`description` |

附件继续使用独立元信息结构，不能混入 `File` 或文件字节。引用数据与展示 chip 分开：提交保留完整引用快照，UI 可用简短标题展示；移除依据稳定 ID，不依赖标题或数组下标。链接按规范化 URL 去重，技能按 ID 与版本组合去重；文本引用用自己的稳定 ID 区分。

## 4. 交互、键盘与焦点

- plus 使用可访问名称；打开后由 Base UI Menu 管理菜单角色、方向键导航、typeahead、选中和 Escape 关闭。点击外部关闭菜单，关闭时遵循 primitive 的焦点返回行为。
- 普通 action 激活一次后关闭菜单；工具 toggle 更新受控状态并关闭菜单。没有独立工具菜单，勾选状态和工具 chip 使用同一份 `draft.tools`。
- 链接／文本／技能对话框拥有标题、字段标签、校验提示和关闭按钮；链接／文本表单另有取消按钮。菜单关闭后下一帧打开对话框；焦点进入名称字段或技能搜索。Escape／关闭／取消不写入草稿；确认成功后关闭，均返回输入框。打开对话框期间暂停页面的新建快捷键。
- 添加或移除引用不应清空原输入内容。取消文件选择器不会清空原附件；选择文件仍经过 feature 校验。
- 输入器继续保留 Enter 发送、Shift+Enter 换行以及 IME／重复键保护。菜单的 Enter 不能冒泡触发发送。
- 忙碌期间仍可编辑下一条文本；附件、引用、plus、模型及工具修改应锁定，避免把正在提交的快照与当前 UI 混淆。停止按钮仍可访问。
- 长标题截断时保留完整可访问文本；窄屏菜单可滚动且不超出视口。多引用 chip 区有高度上限，不把输入与发送按钮推离可操作区域。

本期使用 Base UI 原生菜单交互，不实现 Beautiful UI 的 `@source`／`/command` token 查询，也不把 Tab 定义为选择建议项。文本中输入 `@` 或 `/` 仍是普通文字。

## 5. 状态生命周期与错误

Chat / Task 分别拥有文本、附件、引用、模型和工具草稿。模式切换保留各自状态；仍未实现每个历史会话独立草稿。关闭菜单和对话框属于短暂 UI 状态，不应把半填表单当成已经确认的引用。

```text
打开 plus → 选择动作 → 打开表单或更新工具
                         ↓
                 校验失败：保留输入与错误
                         ↓ 校验通过
                    更新当前模式草稿
                         ↓ 提交
             用户消息 + PreviewRun 的引用快照
                         ↓
          清空该模式文本、附件、引用；保留模型和工具
```

仅引用、仅附件或正文均可成为提交内容；只启用工具不能发送。提交时复制引用与工具数组，后续草稿的添加、移除或工具变化不能改变本轮消息或运行。新建会话清空该模式文本、附件与引用，保留模型和工具；另一模式的草稿保持不变。状态只留在当前页面内存，刷新重置，不写 localStorage。

技能列表使用既有 `createSkillClient(auth)` 与 Session Cookie 请求 `GET /api/skills`，每页 30 条，默认按 `desc` 顺序，使用 `last_id` 作为下一页 `after`。搜索只过滤已加载的名称和描述，不是服务端全目录搜索。选择器区分加载中、空列表、无搜索匹配、错误重试、已加载条目与加载更多；追加失败保留原条目，重试当前页。关闭时通过 AbortController 取消请求并忽略过期响应。已选 ID／版本和没有默认版本的条目不可再次选择；选择后保存当时 `default_version`，不会随目录默认版本变化。列表成功说明目录可读，不说明技能已执行。

用户消息使用原生 `details` / `summary` 展开本次提交的引用：文本显示已保存内容，链接显示 URL 及未抓取说明，技能显示名称、固定版本、描述及未执行说明。链接仅在用户主动点击时打开新标签页。预览回复也逐项列出“链接未抓取／文本仅供本地预览／技能未执行”。

预览结果可以说明本轮带有哪些引用和工具，但不能写“已读取链接”“已执行技能”“已搜索网页”等不实完成状态。真实模型调用、上下文抓取、技能展开和授权校验需要后续服务端协议。

## 6. P1 扩展

下列能力均未实现，不计入本轮 plus 菜单完成范围；当前没有假资料库、假连接器或生成接口。

| 扩展 | 接入前需要明确的契约 |
| --- | --- |
| `@source` 与 `/command` | 光标位置、候选过滤、token 替换、IME、方向键／Enter／Tab 与发送冲突；复用动作目录，不复制第二份能力状态 |
| 真实附件上传 | 文件 ID、上传归属、大小／类型复核、进度、失败／取消、提交前就绪条件及过期回调隔离 |
| URL 内容读取 | 明确抓取动作、服务端 URL 校验、内容大小与来源元数据、失败反馈；仅保存链接不隐式抓取 |
| 技能执行 | 版本解析、技能正文获取、授权与适用模型、执行记录、可取消状态和失败恢复 |
| 通用资料库／项目 | 统一资源类型、查询／分页、权限与稳定资源 ID；不能复用图片库冒充通用资料库 |
| 浏览器标签页 | 明确的用户授权通道与所选标签内容范围；普通页面无法因有菜单就读取浏览器所有标签 |
| 连接器与工具 | 服务端能力目录、连接／重连、权限、可用性和模型约束；不使用本地 boolean 表示真实连接成功 |
| 图像／视频／语音 | 各自的请求、参数、素材、队列、取消与结果协议；通过 feature 组合，不把所有业务塞入 ChatComposer |

## 7. 验收清单与记录

| 验收项 | 结果与证据 |
| --- | --- |
| 统一入口、文件选择与动作分派 | CUA实看菜单；DOM测试验证plus只开菜单、上传项才打开选择器，以及不可用项和运行时锁定 |
| 键盘与焦点 | CUA验证End定位最后一项、Enter选择、Escape回到plus；链接／文本弹窗初始焦点及成功后回到输入框；IME与停止防误发送由DOM回归测试覆盖 |
| 链接、文本与限制 | CUA验证拒绝javascript协议、添加合法HTTPS引用、添加文本；模型和表单测试覆盖credentials、空内容、长度／数量、规范化与去重 |
| 技能目录 | CUA观察真实请求的加载→空列表；DOM测试覆盖真实client的GET路径、失败／分页重试、搜索、默认版本选择、已添加禁用和关闭取消请求 |
| 状态与快照 | CUA验证切换模式保留引用、工具chip与勾选同步、仅上下文提交、工具单独存在仍不能发送；模型测试覆盖快照隔离、新建清空、busy保护 |
| 消息上下文 | CUA展开已提交文本，确认内容与标题保留；源码与类型保证链接、技能按相同引用快照呈现 |
| 窄屏浮层 | CUA验证390×844：菜单左右边界12–378px，列表可滚动；Escape和End导航有效。测试后恢复浏览器默认视口 |
| 执行边界 | 未接真实搜索、抓取、文件上传或技能执行；未注册假资料库、假OAuth或浏览器标签页读取 |

本轮命令结果：

```text
pnpm --filter web check-types   PASS
pnpm --filter web test          PASS: 21 files, 162 tests
pnpm --filter web lint          exit 0: 16 existing warnings; no new-file warnings
pnpm --filter web build         PASS
git diff --check                PASS
```

本轮保留了用户更新后的lint配置，因此全仓lint退出0，但仍如实记录既有16条警告。390px浮层为本轮新增的窄屏实测；320px、深色与英文组合未对新菜单逐项重新做浏览器矩阵验收，不能把早期页面截图当成新菜单的证据。

CUA截图：[桌面plus菜单](../output/playwright/agent-plus-menu.jpg)、[390px菜单](../output/playwright/agent-plus-mobile.jpg)、[已提交上下文详情](../output/playwright/agent-plus-context.jpg)。本轮截图来自实际本地登录会话；测试内容为专门输入的页面需求，未向外部模型发送。
