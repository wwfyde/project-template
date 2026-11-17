# Agent UI 验收记录

## Plus 菜单扩展（2026-11-17）

本轮通过 Computer Use / CUA 在真实 Chrome 中核实两个参考站点，并在独立的本地登录标签页验收。`agent-plus-menu.jpg`、`agent-plus-mobile.jpg`、`agent-plus-context.jpg`分别记录统一菜单、390px滚动浮层及已提交文本资料详情。浏览器临时视口已恢复。

本轮21个测试文件／162项测试、类型检查、构建、lint命令和diff检查通过；全仓lint退出0但有16条既有警告。完整功能与验证范围见[plus菜单说明](../../docs/agent-composer-actions.md)。下面的PNG和脚本是扩展前的历史验收记录，不能证明当前plus行为；旧脚本中的“工具”按钮应在复用时迁移为统一plus菜单。

## 初版页面历史记录

2026-11-17，使用独立 Playwright 浏览器上下文测试。生产构建截图使用虚构账号 Alex Chen 的 `/api/auth/session` 响应 fixture；产品代码保留真实认证，不存在假登录开关。没有读取用户 Cookie，也没有真实上传附件或调用模型。

- `agent-desktop-light.png` / `agent-desktop-dark.png`：1440×1000，新对话。
- `agent-task-dark.png`：1440×1000，任务示例。
- `agent-mobile-light.png`：390×844，新对话。
- `agent-smoke.js`：模式草稿、初次发送焦点、停止防误提交、模型/工具、搜索和移动抽屉验收脚本。
- `agent-short-viewport.js`：五附件、15行草稿、390×390低高度与320px宽度；附件是 `fixtures/` 中的纯测试文本。

脚本供 `playwright-cli run-code --filename=...` 执行，需要先打开已登录的 `/agent` 并切换为中文。fixture只在独立QA上下文拦截session接口；不要将其加入应用源码或部署环境。脚本文件中的断言失败会直接抛出错误，CLI输出的 `### Error` 也应视为失败。

最终结果：19个测试文件、142项测试通过；类型检查、生产构建、变更范围lint通过。生产页控制台没有错误或警告。全仓lint仍有16条既有警告，详见设计文档。
