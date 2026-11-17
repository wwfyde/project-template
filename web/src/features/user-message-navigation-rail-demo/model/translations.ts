export const railDemoEn = {
  title: 'User message navigation rail',
  description:
    'Preview a question and its response, bookmark it, or drag along the rail to revisit earlier messages.',
  conversationTitle: 'Designing a shared knowledge workspace',
  conversationLabel: 'Sample conversation',
  demo: 'Local demo',
  user: 'You',
  assistant: 'Assistant',
  addTurn: 'Append a message',
  latest: 'Go to latest',
  openHistory: 'Reveal earlier example',
  loadingHistory: 'Revealing local history fixture…',
  fixtureDescription:
    'History loading and output labels use local fixtures. This demo sends no network requests.',
  fixtureOutputs:
    'This response includes three demo output labels in its navigation preview; they are not real files.',
  hiddenHistory: (count: number) =>
    `${count} earlier user messages are not mounted. Preview one before loading it; dragging skips unloaded messages.`,
  hint: 'The rail appears with at least four user messages and 48 px of left space. Hover to preview; drag to scrub; Alt + ↑ / ↓ navigates inside this conversation.',
  turns: (count: number) => `${count} user messages`,
  turn: (index: number) => `User message ${index}`,
  appended: (count: number) =>
    `${count} example messages appended. Your reading position is preserved.`,
  extraQuestion: (index: number) =>
    `Follow-up ${index}: what should we review before the next release?`,
  extraAnswer:
    'Walk through the core reading flow with a long conversation, then verify keyboard navigation, narrow screens and both themes. Keep the current message in view when new content arrives.',
  rail: {
    navigation: 'User message navigation',
    loading: 'Loading preview…',
    unavailable: 'Preview unavailable in this fixture',
    bookmark: 'Bookmark message',
    removeBookmark: 'Remove bookmark',
    navigationError: 'Could not reveal this example. Try again.',
    bookmarkError: 'Could not update this bookmark. Try again.',
    position: (index: number, total: number) => `Message ${index} of ${total}`,
  },
} as const

export const railDemoZhCN = {
  title: '用户消息导航条',
  description: '预览问题和回复、收藏消息，或沿导航条拖动，快速回到之前的上下文。',
  conversationTitle: '设计一个共享知识工作台',
  conversationLabel: '示例对话',
  demo: '本地演示',
  user: '你',
  assistant: '助手',
  addTurn: '追加一条消息',
  latest: '跳到最新',
  openHistory: '显示较早的示例',
  loadingHistory: '正在展开本地历史示例…',
  fixtureDescription: '历史加载与产物标签均使用本地演示数据，不会发起网络请求。',
  fixtureOutputs: '这条回复的导航预览包含三个示例产物标签，并非真实文件。',
  hiddenHistory: (count: number) =>
    `有 ${count} 条较早的用户消息尚未挂载，可先预览再加载；拖动会跳过未加载消息。`,
  hint: '至少四条用户消息且正文左侧留白达到 48 px 时显示导航。悬停预览，拖动快速定位；Alt + ↑ / ↓ 在当前对话中前后跳转。',
  turns: (count: number) => `${count} 条用户消息`,
  turn: (index: number) => `用户消息 ${index}`,
  appended: (count: number) => `已追加 ${count} 条示例消息，当前阅读位置保持不变。`,
  extraQuestion: (index: number) => `补充问题 ${index}：下次发布前还需要检查什么？`,
  extraAnswer:
    '用一段长对话走完核心阅读流程，再检查键盘导航、窄屏和两种主题。新增内容时保留当前消息的阅读位置，让读者决定何时跳到最新。',
  rail: {
    navigation: '用户消息导航',
    loading: '正在加载预览…',
    unavailable: '这条示例暂时没有预览',
    bookmark: '收藏消息',
    removeBookmark: '取消收藏',
    navigationError: '未能展开这条示例，请重试。',
    bookmarkError: '未能更新收藏，请重试。',
    position: (index: number, total: number) => `第 ${index} / ${total} 条消息`,
  },
} as const
