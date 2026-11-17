import { railDemoEn, railDemoZhCN } from './translations'

export type ConversationDemoLanguage = 'en' | 'zh-CN'

export interface ConversationDemoTurn {
  id: string
  question: string
  answer: string
}

// Each tuple describes the same turn in both languages, so changing language keeps its ID.
const turns: readonly (readonly [string, string, string, string])[] = [
  [
    '我们先明确这个知识工作台要解决什么问题。',
    '让团队能找到讨论过的问题、确认过的决定和可继续使用的资料。首页优先呈现最近使用的内容，搜索与对话导航帮助用户回到具体上下文。',
    'What problem should this knowledge workspace solve?',
    'Help the team find previous questions, agreed decisions and reusable material. Start with recently used content, then make search and conversation navigation lead back to the relevant context.',
  ],
  [
    '哪些用户会最频繁地使用它？',
    '先围绕项目成员设计：他们需要补上错过的讨论、核对一项决定，或继续已有工作。把阅读与查找做顺畅，再逐步加入管理功能。',
    'Who will use it most often?',
    'Start with project members who need to catch up on a discussion, verify a decision or continue existing work. Make reading and finding information straightforward before adding administrative tools.',
  ],
  [
    '首页应该保留哪些主要入口？',
    '保留最近对话、已收藏资料和搜索三个入口。按实际任务组织内容，让用户能快速继续上次的工作，避免在首页放入过多互相竞争的模块。',
    'Which entry points belong on the home page?',
    'Keep recent conversations, saved resources and search. Organize the page around real tasks so people can resume their work without choosing between too many competing sections.',
  ],
  [
    '如何区分工作空间和项目？',
    '工作空间承担成员和权限边界，项目聚合某个目标下的对话与资料。导航中先显示当前工作空间，再显示项目，保持用户的当前位置清晰。',
    'How should workspaces and projects differ?',
    'A workspace defines membership and access. A project groups conversations and resources around one objective. Show the current workspace before its projects so the location stays clear.',
  ],
  [
    '左侧导航应该一直展开吗？',
    '宽屏保留项目列表，窄屏通过明确的按钮打开。收起时保留当前项目名称；切换项目后，页面标题和导航状态同步变化。',
    'Should the sidebar always stay expanded?',
    'Keep the project list visible on wide screens and open it with a labeled button on narrow screens. Retain the current project name when collapsed and update it together with the page title.',
  ],
  [
    '搜索框放在哪里比较合适？',
    '把全局搜索放在稳定的位置，项目内搜索则明确显示范围。结果同时提供标题、摘要与来源，让用户在打开内容前判断是否相关。',
    'Where should the search field go?',
    'Give global search a consistent position and make the scope of project search explicit. Show a title, excerpt and source in results so people can judge relevance before opening them.',
  ],
  [
    '搜索结果如何展示上下文？',
    '标题下保留命中关键词附近的短摘要，再显示所属项目与对话。点击结果时定位到具体消息，避免只打开对话顶部后要求用户再次查找。',
    'How should search results show context?',
    'Place a short excerpt around the matching words below the title, followed by the project and conversation. Open the exact message so the user does not have to repeat the search inside the chat.',
  ],
  [
    '没有搜索结果时显示什么？',
    '保留输入内容与当前筛选条件，解释本次没有匹配项。提供清除筛选的入口，用户可以调整关键词后继续，而不会丢失已经输入的查询。',
    'What should an empty search result show?',
    'Keep the query and current filters visible and explain that nothing matched. Offer a way to clear filters so users can adjust their search without losing what they typed.',
  ],
  [
    '对话标题应该如何生成？',
    '优先使用能说明任务的短标题，允许用户修改。标题用于识别整个对话；具体问题仍然保留在轮次导航和搜索结果里。',
    'How should conversation titles work?',
    'Use a short title that describes the task and let the user edit it. The title identifies the whole conversation, while individual questions remain available in navigation and search results.',
  ],
  [
    '长对话里怎样快速返回之前的问题？',
    '在正文旁提供紧凑的轮次导航，每个标记对应一个用户问题。悬停时预览摘要，点击时跳转，滚动正文时同步显示当前轮次。',
    'How can someone return to an earlier question in a long chat?',
    'Place a compact turn navigator beside the transcript, with one mark per user question. Preview the question on hover, jump on activation and track the current turn as the reader scrolls.',
  ],
  [
    '导航刻度应该按内容长度分配高度吗？',
    '按轮次等距排列更利于逐个查找，也能保持短问题可选。正文中的段落长度由阅读区处理，导航主要表达顺序和当前的位置。',
    'Should the marks be sized by message length?',
    'Even spacing makes individual turns easier to find and keeps short questions selectable. Let the transcript express content length while the navigator communicates order and current position.',
  ],
  [
    '当前轮次和悬停轮次需要怎样区分？',
    '当前轮次使用稳定的强调状态，悬停轮次只提供临时预览。移动鼠标不应改变正文位置，只有点击或键盘确认才执行跳转。',
    'How should the active and hovered turns differ?',
    'Use a stable emphasis for the current turn and a temporary preview for the hovered turn. Moving the pointer should leave the transcript in place; clicking or confirming with the keyboard performs the jump.',
  ],
  [
    '预览卡片里应该放多少内容？',
    '展示轮次编号、问题标题和一小段原文。预览帮助识别目标，完整阅读仍在正文中完成；过长的内容截断，卡片保持可快速扫读。',
    'How much text belongs in a preview?',
    'Show the turn number, question title and a short excerpt. The preview helps identify a destination, while the transcript remains the place for full reading. Truncate long content to keep it scannable.',
  ],
  [
    '超过二十轮后导航会不会变得太密？',
    '为全部用户消息保留固定间距的刻度，让导航列表独立滚动。当前阅读项或键盘焦点移出可见区域时，将对应刻度滚动到可见位置，保持完整索引可达。',
    'Will the navigator become crowded after twenty turns?',
    'Keep a fixed spacing for every user-message mark and let the navigation list scroll independently. When the current reading item or keyboard focus moves out of view, bring its mark into view while keeping the complete index reachable.',
  ],
  [
    '键盘用户如何操作这个导航器？',
    '让导航器拥有明确名称和可见焦点。方向键用于选择，确认键用于跳转，关闭键用于退出预览；操作后焦点位置应保持可预测。',
    'How should keyboard users operate the navigator?',
    'Give the navigator an accessible name and a visible focus indicator. Use arrow keys for selection, confirmation for jumping and Escape to dismiss a preview. Keep focus predictable after each action.',
  ],
  [
    '手机上也保留同样的交互吗？',
    '窄屏保留基本定位能力，并为触摸提供足够的点击区域。消息内容应正常换行，预览卡片不能超出窗口，也不能依赖悬停才能执行跳转。',
    'Should mobile use the same interaction?',
    'Preserve the essential navigation with sufficiently large touch targets. Messages should wrap naturally, previews must fit the screen and jumping must remain available without hover.',
  ],
  [
    '滚动到旧消息时，新回复要怎样出现？',
    '让新回复追加在对话尾部，保留用户当前的阅读位置。提供明确的跳到最新入口，避免持续输出打断对旧内容的阅读。',
    'What happens when a reply arrives while reading older messages?',
    'Append it at the end and preserve the reading position. Provide a clear way to return to the latest content so a new reply does not interrupt the reader.',
  ],
  [
    '能否给某条消息加收藏？',
    '可以用独立的消息操作保存重要内容，并让收藏指向原始消息。收藏列表保留来源信息，避免脱离对话后失去含义。',
    'Can an individual message be saved?',
    'Use a separate message action to save useful content and keep a link to the original message. Include its source in the saved list so it remains understandable outside the conversation.',
  ],
  [
    '附件在对话里如何展示？',
    '图片使用适合阅读宽度的预览，文件展示名称和类型。附件属于对应消息，导航跳转时仍定位到该轮次的起点。',
    'How should attachments appear in the conversation?',
    'Show images at a readable size and files with a name and type. Keep attachments attached to their message and navigate to the beginning of the relevant turn.',
  ],
  [
    '代码块太长会不会影响导航？',
    '导航使用消息的稳定标识，不依赖代码块的行数。代码内容可以独立横向滚动；正文高度改变后重新计算当前可见轮次。',
    'Can long code blocks interfere with navigation?',
    'Use stable message identifiers rather than code line counts. Code may scroll horizontally on its own, and the current visible turn can be recalculated when the transcript height changes.',
  ],
  [
    '阅读位置应该在返回页面后恢复吗？',
    '同一对话可以记录消息标识与相对偏移。返回时先找到消息，再恢复附近的位置；如果原消息已不存在，则选择合理的相邻位置。',
    'Should reading position be restored when returning?',
    'A conversation can remember a message identifier and relative offset. Find that message first and restore the nearby position; if it no longer exists, select a reasonable neighboring location.',
  ],
  [
    '对话被删除或移动后如何处理收藏？',
    '用消息的可访问状态决定展示。保留可理解的说明，不把用户带到空白页面；移动内容后继续使用稳定标识维护链接关系。',
    'What happens to saved links when a conversation moves?',
    'Base the display on whether the message is still accessible. Explain unavailable content instead of opening a blank page, and preserve links with stable identifiers when conversations move.',
  ],
  [
    '主题切换时哪些颜色需要跟随？',
    '背景、正文、次要文字、分隔线和强调状态都使用语义颜色。预览卡片与主界面共享主题，当前轮次也通过长度或文字表达状态。',
    'Which colors should follow theme changes?',
    'Use semantic colors for backgrounds, text, secondary labels, borders and emphasis. Keep previews consistent with the main interface and use shape or text as well as color for the current turn.',
  ],
  [
    '高对比度下还能看清当前标记吗？',
    '检查背景和标记之间的对比，并保留明确的焦点轮廓。状态应有尺寸或文字差异，使读者不必仅靠颜色判断当前位置。',
    'How can the current mark stay visible in high contrast?',
    'Check the contrast between marks and their background and retain a clear focus outline. Add a size or text difference so the current position does not depend on color alone.',
  ],
  [
    '动效应该保持多长时间？',
    '动效用于连接操作与结果，时间应短且稳定。尊重减少动态效果的系统设置，必要时直接定位，避免长距离动画让用户失去方向。',
    'How should motion behave?',
    'Use brief, consistent motion to connect an action with its result. Respect reduced-motion preferences and allow immediate positioning so long animations do not make people lose their place.',
  ],
  [
    '如何让英文和中文界面共享布局？',
    '让按钮和文本容器根据内容自然伸展，为较长的英文标签留出空间。切换语言时保持消息标识与阅读位置，不重新创建整段对话。',
    'How can English and Chinese share the same layout?',
    'Allow controls and text containers to grow with their content and leave room for longer labels. Preserve message identifiers and reading position when switching languages.',
  ],
  [
    '哪些信息需要保存在本地？',
    '可以保存主题、语言和阅读偏好。具体对话内容及权限应由对应的数据层管理，让界面组件只负责显示和传递用户操作。',
    'Which preferences should be stored locally?',
    'Theme, language and reading preferences can be local. Let the appropriate data layer manage conversation content and access, while interface components display information and report actions.',
  ],
  [
    '团队权限要在哪里体现？',
    '在内容入口和操作处展示当前可用能力。只读成员仍可搜索和导航，编辑相关操作根据真实权限显示，并给不可用操作清晰的说明。',
    'Where should team permissions appear?',
    'Represent available capabilities where users open content or perform actions. Readers can still search and navigate; editing actions follow actual permissions with clear explanations when unavailable.',
  ],
  [
    '载入较早历史时怎样避免页面跳动？',
    '在追加前记录可见消息及其位置，加载完成后恢复它的相对偏移。导航可以显示加载状态，但不要把未完成的定位表现为已经成功。',
    'How can older history load without moving the reader?',
    'Record the visible message and its position before adding earlier content, then restore the relative offset. Navigation can show progress, but should only signal success when the target is available.',
  ],
  [
    '一次对话有几百轮时应该如何处理？',
    '先保证每一轮都有稳定标识，再按实际需要加载内容。导航与正文可以采用不同的渲染策略，让定位能力不局限于当前屏幕上的消息。',
    'How should a conversation with hundreds of turns work?',
    'Give each turn a stable identifier and load content as needed. Navigation and the transcript may use different rendering strategies so destinations are not limited to messages currently on screen.',
  ],
  [
    '可以为团队提供导出功能吗？',
    '导出应保留消息顺序、来源和可用附件说明。让用户选择具体范围，生成结果中明确标识缺失的内容，避免把截断结果当成完整记录。',
    'Could the team export a conversation?',
    'Preserve message order, sources and attachment details. Let the user choose a range and identify unavailable content so a partial export is not mistaken for the complete record.',
  ],
  [
    '怎样验证这个导航器真的更好用？',
    '让参与者寻找一条较早的问题，记录是否能正确识别并到达目标。再检查鼠标、键盘和触摸流程，关注误跳转与返回阅读位置的成本。',
    'How can we evaluate the navigator?',
    'Ask participants to find an earlier question and observe whether they identify and reach it correctly. Check pointer, keyboard and touch flows, paying attention to wrong destinations and the effort of returning.',
  ],
  [
    '第一版应该先交付哪些能力？',
    '先交付轮次刻度、问题预览、点击跳转和阅读位置同步。把长列表与键盘访问一起完成，让核心流程在真实长度的对话中可以使用。',
    'What should the first version include?',
    'Ship turn marks, question previews, jump navigation and reading-position tracking. Include long-list behavior and keyboard access so the core flow works with realistically long conversations.',
  ],
  [
    '暂时不做的功能怎么记录？',
    '把全文搜索、话题分组或自动摘要等后续方向记录为独立需求，并说明解决的问题。当前导航组件已支持消息收藏，后续能力通过明确接口接入，保持组件边界清晰。',
    'How should deferred features be recorded?',
    'Record later ideas such as full-text search, topic grouping or automatic summaries as separate needs with a clear problem statement. Message bookmarks are already supported; introduce further capabilities through explicit interfaces to keep the navigator focused.',
  ],
  [
    '发布前的最后一次检查有哪些？',
    '用长短不同的对话检查首尾跳转、当前轮次和预览位置。再切换语言、主题与窗口宽度，确认追加消息后已有标记仍对应同一条消息。',
    'What should we check before release?',
    'Use short and long conversations to verify first and last turns, active state and preview placement. Switch language, theme and width, then append a message and verify that existing marks still point to the same content.',
  ],
  [
    '请汇总这次讨论的最终方案。',
    '以对话内容为中心，用紧凑导航帮助用户定位。保留稳定标识、清晰的预览和阅读位置同步，并让窄屏、键盘与主题支持成为基础体验的一部分。',
    'Summarize the final direction from this discussion.',
    'Keep the conversation at the center and use compact navigation to help people find their place. Build around stable identifiers, clear previews and reading-position tracking, with narrow screens, keyboard access and themes included from the start.',
  ],
]

export function createDemoConversation(
  language: ConversationDemoLanguage,
  additionalTurns: number,
): ConversationDemoTurn[] {
  const chinese = language === 'zh-CN'
  const copy = chinese ? railDemoZhCN : railDemoEn

  return [
    ...turns.map(([zhQuestion, zhAnswer, enQuestion, enAnswer], index) => ({
      id: `demo-turn-${index + 1}`,
      question: chinese ? zhQuestion : enQuestion,
      answer: chinese ? zhAnswer : enAnswer,
    })),
    ...Array.from({ length: additionalTurns }, (_, index) => ({
      id: `demo-appended-turn-${index + 1}`,
      question: copy.extraQuestion(index + 1),
      answer: copy.extraAnswer,
    })),
  ]
}
