import type { PreviewEvent, PreviewRun } from '../model/workspace'

// This transport produces local UI examples. It never uploads files or calls a model.
export function startPreviewRun(run: PreviewRun, onEvent: (event: PreviewEvent) => void, signal: AbortSignal): void {
  if (signal.aborted) return
  const timers = new Set<ReturnType<typeof setTimeout>>()
  const cleanup = () => {
    timers.forEach(clearTimeout)
    timers.clear()
    signal.removeEventListener('abort', cleanup)
  }
  signal.addEventListener('abort', cleanup, { once: true })
  const schedule = (delay: number, event: PreviewEvent) => {
    const timer = setTimeout(() => {
      timers.delete(timer)
      if (signal.aborted) return
      onEvent(event)
      if (event.type === 'complete') cleanup()
    }, delay)
    timers.add(timer)
  }

  const prompt = Array.from(run.prompt).slice(0, 160).join('')
  let answer =
    run.language === 'zh-CN'
      ? run.mode === 'task'
        ? `这是任务模式的交互示例。围绕「${prompt}」，可以按以下步骤组织工作：\n\n1. 明确目标：补充期望的交付物、使用场景和完成标准。\n2. 拆分任务：列出需要的资料、关键步骤和依赖条件。\n3. 检查结果：逐项核对要求，记录待确认的问题。\n\n上方步骤展示的是界面状态变化，没有执行真实任务、读取附件或调用工具。你可以继续补充要求，或切换到对话模式。`
        : `这是对话模式的交互示例。你希望讨论的是：\n\n「${prompt}」\n\n可以先明确希望得到的结果，再补充背景、限制和偏好的呈现方式。例如：一份简洁的说明、一组可比较的选项，或可以逐步执行的计划。\n\n当前回复由本地预览生成，未调用 AI 模型，也没有读取附件或搜索外部资料。`
      : run.mode === 'task'
        ? `This is an interactive task preview. For “${prompt}”, a useful plan could be:\n\n1. Define the outcome, audience and success criteria.\n2. Break the work into steps and identify the information each step needs.\n3. Review the result against the requirements and note open questions.\n\nThe steps above demonstrate UI states. No real tasks, file reading or tool calls took place. Add more context, or switch to Chat to explore the idea.`
        : `This is an interactive chat preview. You would like to discuss:\n\n“${prompt}”\n\nStart with the outcome you want, then add context, constraints and your preferred format. This could be a short explanation, a comparison of options or a practical plan.\n\nThis response is generated locally for the preview. No AI model, file reading or external search was used.`

  if (run.modelId === 'fast') {
    answer =
      run.language === 'zh-CN'
        ? `简洁示例：围绕「${prompt}」，先明确目标，再补充限制，最后确定下一步。\n\n这是本地交互预览，没有调用 AI、读取附件、搜索资料或执行任务。`
        : `Quick example: for “${prompt}”, define the goal, add constraints, then choose a next step.\n\nThis is a local UI preview. No AI, file reading, search or real task execution took place.`
  } else if (run.modelId === 'thoughtful') {
    answer +=
      run.language === 'zh-CN'
        ? '\n\n进一步考虑：\n• 谁会使用最终结果，他们最关心什么？\n• 哪些信息已经确定，哪些仍需验证？\n• 如果时间有限，最小但有价值的交付是什么？\n\n可以用这些问题补充需求，让下一步更具体。以上仍是预设示例，并非实际模型推理。'
        : '\n\nA few more points to consider:\n• Who will use the result, and what matters most to them?\n• Which information is known, and what still needs validation?\n• If time is limited, what is the smallest useful deliverable?\n\nUse these questions to make the next step more concrete. These are preset examples, not actual model reasoning.'
  }
  if (run.tools.length > 0) {
    const toolLabels: Record<string, string> =
      run.language === 'zh-CN'
        ? { web: '联网搜索', reasoning: '深度思考' }
        : { web: 'Web search', reasoning: 'Extended thinking' }
    const selected = run.tools.map((tool) => toolLabels[tool] ?? tool).join(run.language === 'zh-CN' ? '、' : ', ')
    answer +=
      run.language === 'zh-CN'
        ? `\n\n已选择工具：${selected}（仅预览，未实际执行）。`
        : `\n\nSelected tools: ${selected} (preview only; not executed).`
  }

  if (run.contexts.length > 0) {
    const labels =
      run.language === 'zh-CN'
        ? { link: '链接未抓取', text: '文本仅供本地预览', skill: '技能未执行' }
        : { link: 'link not fetched', text: 'text is local preview only', skill: 'skill not executed' }
    const selected = run.contexts.map((context) => `• ${context.title}（${labels[context.kind]}）`).join('\n')
    answer +=
      run.language === 'zh-CN'
        ? `\n\n已选择上下文：\n${selected}\n\n以上是资料引用，未将资料内容作为指令执行。`
        : `\n\nSelected context:\n${selected}\n\nThese are source references. Their contents were not executed as instructions.`
  }

  if (run.mode === 'task') {
    schedule(650, { type: 'step', index: 0, status: 'completed' })
    schedule(650, { type: 'step', index: 1, status: 'running' })
    schedule(1400, { type: 'step', index: 1, status: 'completed' })
    schedule(1400, { type: 'step', index: 2, status: 'running' })
    schedule(2350, { type: 'step', index: 2, status: 'completed' })
  }
  const characters = Array.from(answer)
  const startDelay = run.mode === 'task' ? 800 : 280
  let finalDelay = startDelay
  for (let offset = 0; offset < characters.length; offset += 12) {
    finalDelay = startDelay + (offset / 12) * 65
    schedule(finalDelay, { type: 'chunk', text: characters.slice(offset, offset + 12).join('') })
  }
  schedule(Math.max(finalDelay + 100, run.mode === 'task' ? 2450 : 0), { type: 'complete' })
}
