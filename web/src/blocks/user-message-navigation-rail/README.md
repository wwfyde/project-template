# UserMessageNavigationRail

用户消息导航条（Prompt Rail），依据用户提供的静态分析调整：每条用户消息一个索引，悬停预览、点击定位、按住拖动浏览。应用自己的消息、历史 API 和书签存储不进入 block。

## 分层与入口

- **primitive**：已有 `@base-ui/react` 的 Button、Popover。
- **component/ui**：共享 `Button`、`AnchoredPopover` 提供主题、非模态定位与边界避让。
- **block**：`src/blocks/user-message-navigation-rail` 管理索引、预览、键盘、scrubbing 和可取消导航请求。
- **feature**：生成用户消息索引、关联回复与产物、测量正文留白、加载历史、滚动与高亮、持久化书签。

`/examples/user-message-navigation-rail` 展示本地示例；旧 `/examples/conversation-navigator` 仅保留跳转兼容。Agent 页也已迁移到新组件。

## 接口

```tsx
import { UserMessageNavigationRail } from '../../blocks/user-message-navigation-rail'

;<UserMessageNavigationRail
  items={userMessages.map((message) => ({
    id: message.id,
    turnKey: message.turnKey,
    bookmarkId: message.id,
    getLabel: () => message.content,
    getPreview: () => ({ response: message.response, outputs: message.outputs }),
    isLoaded: message.isLoaded,
    isBookmarked: bookmarkedIds.has(message.id),
  }))}
  activeId={readingMessageId}
  activeIds={visibleMessageIds}
  availableSpace={leftGutterWidth}
  shortcutScopeRef={transcriptContainerRef}
  onNavigate={navigateToMessage}
  onPreviewItem={loadMessagePreview}
  onRevealItem={revealHistoricalMessage}
  onBookmarkChange={saveBookmark}
/>
```

`id` 必须唯一且稳定，不用数组下标。会话切换应以会话 ID 作为 React `key`，避免历史预览缓存跨会话共享。`turnKey` 与 `bookmarkId` 保留业务映射；回调接收完整 item（`onNavigate` 接收 ID）。所有文本通过 React 文本节点渲染，不执行消息中的 HTML。

`getPreview()` 返回 `{ response?, outputs? }`；每个产物含 `id`、`label` 和可选 `type`。getters 在渲染时读取，支持正文增量更新。`onPreviewItem(item, { signal })` 返回预览或 `null`；`previewState` 可由调用方声明 loading / loaded / unavailable。已加载的实时数据优先，历史结果按 ID 缓存。

`onNavigate(id, { source, behavior, signal })` 的 source 为 click / keyboard / shortcut / scrub。普通历史点击先等待 `onRevealItem(item, { signal })` 加载并挂载目标，再调用 onNavigate；返回 `false` 或抛错显示定位失败。新导航取消前一请求，回调必须遵守 signal，并在完成自身异步工作后再次检查取消状态。feature 负责目标离视口超过一屏时使用 instant，其余近距离跳转用 smooth；reduced-motion 和 scrub 始终 instant。

`onBookmarkChange(item, boolean)` 受控更新 `isBookmarked`；持久化按会话隔离，block 不写 localStorage。省略该回调时预览为 tooltip；提供后使用非模态 dialog，支持书签按钮。

## 样式与行为

- 至少 4 项且 `availableSpace >= 48` 才显示；默认位于正文左侧，预览向右打开。`side="right"` 可用于右侧布局。
- 36×10px 导航按钮、30px marker 容器、2px 横线；横线从 6px 伸到 26px，邻近三项进度分别为 0.7 / 0.4 / 0.2，过渡 160ms。书签附加圆点。触摸设备扩大点击区。
- 完整索引置于独立滚动列表，上限 `min(70vh, 40rem)`，隐藏滚动条；取消原来的20项分页、上下翻页按钮和底部计数。正文阅读变化使对应 marker 保持可见，不打断悬停或键盘预览。
- 用户提示一行截断，回复最多三行，产物显示前两项与 `+N`。悬停立即显示卡片，历史加载延迟150ms；键盘聚焦立即加载。过期响应不能覆盖新选择。
- 上下方向键及 Home / End 仅选择；Enter / Space 定位。ArrowRight 进入书签按钮，Escape 关闭预览并将焦点归还 marker。
- Alt+↑/↓ 仅在 `shortcutScopeRef` 内生效，不拦截输入框或可编辑文本的原生快捷键。
- 按住跨 marker 拖动即进入 scrubbing，逐项 instant 定位；跳过未加载历史，不触发历史加载。释放后的 click 不会重复定位，pointer cancel / capture 丢失会结束拖动。
- `activeIds` 支持同时高亮多个可见用户消息；省略时仅使用 activeId。预览目标和当前阅读状态互不覆盖。

## 接入边界

参考分析中的 OpenAI 私有历史接口、埋点和可选话题导航不作为本项目依赖。示例历史与产物明确为本地 fixture；真正的分页、虚拟列表与远程书签由 feature 的回调接入。本组件不承诺模拟任何未接入的后端服务。
