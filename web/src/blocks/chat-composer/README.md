# ChatComposer

受控的共享输入器block，用于Chat、Task及后续需要同类输入体验的界面。当前接入页面为登录后的 `/agent`。组件依赖 `components/ui`，不依赖feature、路由、认证或业务API。

## 契约

完整类型由 [types.ts](./types.ts) 导出，入口为 [index.ts](./index.ts)。

| Props | 职责 |
| --- | --- |
| `value` / `onValueChange` | 宿主拥有文本草稿；输入器不自动清空或持久化 |
| `attachments` / `onFilesAdded` / `onRemoveAttachment` | 展示稳定ID、名称、大小；转交新选File或待移除ID |
| `modelId` / `models` / `onModelChange` | 受控模型单选；label与description由宿主提供 |
| `tools` / `onToolToggle` | 受控工具多选；`enabled`决定统一 plus 菜单的勾选状态，支持可选说明和图标 |
| `actions` | 可选 `ComposerAction[]`；由宿主注册分组动作或受控 toggle，和上传／工具合并到 plus 菜单 |
| `selections` / `onRemoveSelection` | 可选的受控 chip；只接收展示元信息和移除ID，实际引用及工具归属由宿主管理 |
| `hasContext` | 默认为false；宿主明确是否存在可独立提交的上下文，不能用工具选择或chip数量代替 |
| `inputRef` / `actionTriggerRef` | 可选输入框与plus按钮refs，供宿主安排对话框关闭、模式切换等焦点行为 |
| `busy` / `onSubmit` / `onStop` | 宿主拥有执行状态；组件只发送提交或停止意图 |
| `labels` | 文案与可访问名称；新增可选`addContext`、`actionsHint`、`removeSelection`、`uploadDescription` |
| `context` | 可选ReactNode，位于附件与输入区域上方；Task使用它展示模式说明 |
| `accept` | 原生文件选择过滤，默认 `image/*,.pdf,.txt,.md,.csv,.json` |
| `error` | 可选校验文案；以`role="alert"`展示并关联textarea的`aria-describedby`、`aria-invalid` |
| `className` | 外层容器样式扩展 |

宿主传入完整状态和handlers。例如将业务层准备好的模型、工具与翻译绑定到输入器：

```tsx
import { ChatComposer } from '../../blocks/chat-composer'

;<ChatComposer
  value={draft.text}
  onValueChange={updateText}
  attachments={draft.attachments}
  onFilesAdded={validateAndAddFiles}
  onRemoveAttachment={removeAttachment}
  modelId={draft.modelId}
  models={modelOptions}
  onModelChange={selectModel}
  tools={toolOptions}
  onToolToggle={toggleTool}
  actions={contextActions}
  selections={selectionChips}
  onRemoveSelection={removeSelection}
  hasContext={draft.contexts.length > 0}
  inputRef={composerInputRef}
  busy={isRunning}
  onSubmit={submitDraft}
  onStop={stopRun}
  labels={composerLabels}
  error={attachmentError}
/>
```

其中`contextActions`、`selectionChips`和handlers由宿主准备，block不会从`draft.contexts`推导业务行为。Agent宿主将引用和工具都映射为`selections`；只启用工具时`hasContext`仍为false。

## Plus 菜单与动作注册

[ComposerActionMenu](./composer-action-menu.tsx)也通过[index.ts](./index.ts)独立导出。它基于现有Base UI Menu封装渲染`actions`，不包含文件选择、业务请求或对话框。`ChatComposer`按以下来源合并菜单：

1. 内置上传动作`composer-files`，打开保留在菜单外的原生文件input。
2. 宿主传入的`actions`，例如添加链接、文本、技能或切换模式。
3. `tools`映射的受控toggle，ID为`composer-tool-${tool.id}`，分组标题使用`labels.tools`。

分组按第一次出现的顺序展示；同组条目保留传入顺序。宿主ID需唯一且避开内置ID。页面没有独立工具按钮，模型选择仍使用单独菜单。

`ComposerAction`公共字段为`id`、`label`和可选的`description`、`icon`、`group`、`disabled`、`disabledReason`，再按`kind`区分：

| kind | 事件与状态 |
| --- | --- |
| `action` | `onSelect()`，用于打开宿主对话框或执行即时UI动作 |
| `toggle` | `checked`与`onCheckedChange(checked)`，用于受控开关 |

`disabledReason`优先于`description`显示，但不会自动禁用动作，宿主仍需传`disabled: true`。普通项和toggle选择后都会关闭菜单。方向键、typeahead、Escape、外部关闭和焦点返回由Base UI处理；未实现`@source`或`/command`候选查询。

`ComposerSelection`只含`id`、`label`及可选`description`／`icon`。`selections`不自动取自`tools`或`actions`，宿主需维护菜单勾选与chip的一致性；没有`onRemoveSelection`时chip只读。条目描述作为悬停说明，移除按钮有完整可访问名称。

## 交互与边界

- 输入域自动增长到200px，至少64px；更长内容内部滚动。Enter提交，Shift+Enter换行，IME组合输入及229兼容事件不提交，长按重复Enter不重复提交。
- `!busy && Boolean(value.trim() || attachments.length || hasContext)`允许提交。附件或宿主确认的上下文可单独提交；工具／chip数量本身不允许提交。宿主仍必须在业务状态层防重复执行。
- `busy`时文本保持可编辑；plus及所有菜单项、附件添加／移除、selection移除、模型和工具锁定，停止替换发送。组件不实现排队发送，也没有独立`disabled`属性。
- 文件选择、粘贴、拖放只调用`onFilesAdded(File[])`；`accept`不是类型验证。宿主负责类型、数量、大小、去重、上传和归属。Agent页面目前最多5个、单个20MiB，接受图片及PDF/TXT/MD/CSV/JSON，仅保存元信息，不上传或读取内容。
- 提交、停止、草稿清空、模型／工具能力校验和执行结果都由宿主决定。`error`只负责呈现，不包含网络请求或重试逻辑。
- `context`可以扩展模式说明；Creative比例／时长等专用业务参数应在宿主组装，避免把模式分支塞进block。
- selections与附件分别使用有高度上限的滚动区。`inputRef`只提供原生textarea目标，不自行触发聚焦；`actionTriggerRef`传给plus触发器。宿主负责选择与关闭对话框后的焦点安排。
- 使用`agent-*`语义token，与当前Agent中性明暗主题一致；输入器不会修改主题或语言偏好。

当前feature按Chat / Task两模式保留草稿，包含文本、附件、上下文、模型与工具。链接／文本校验、真实技能列表读取、引用快照、停止／切换／新建的异步归属都由feature处理，不由block识别会话。完整边界见[输入器动作与上下文](../../../../docs/agent-composer-actions.md)。

## 验证

[chat-composer.test.ts](./chat-composer.test.ts)覆盖提交／空白／附件或上下文单独提交、IME、忙碌态、选择／拖放／粘贴、移除／错误关联、统一动作／工具菜单、不可用项、selection移除、模型选择及Tabs方向键。运行：

```bash
pnpm --dir web exec vitest run src/blocks/chat-composer/chat-composer.test.ts
```

本轮整合验收结果见[输入器动作与上下文](../../../../docs/agent-composer-actions.md#7-验收清单与记录)。DOM测试不证明真实模型、文件上传或传输恢复可用；相关能力需要在feature与服务端接入时单独验证。
