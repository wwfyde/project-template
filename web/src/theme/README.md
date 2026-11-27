# 主题与设计系统

项目使用一套设计系统，提供七个可切换的视觉 preset。设计系统包含语义 token、共享组件、交互和可访问性规范；preset 为同一份 token 契约提供不同取值。因此没有额外的 `designSystem` 状态，也不为每种风格加载另一套组件库。

Tailwind CSS 负责把语义 token 映射为工具类，Base UI 负责按钮、菜单、弹窗等组件的交互行为。切换 preset 会改变颜色、圆角、间距、控件尺寸、阴影、材质和动效，组件行为保持一致。预设是视觉参考适配，并非对应产品或组件库的完整复刻。

## 文件职责

| 文件 | 职责 |
| --- | --- |
| `styles/theme.css` | 样式入口，依次导入 token、七个 preset、用户偏好覆盖 |
| `styles/tokens.css` | 公共语义 token、Tailwind 映射、派生值和通用状态色 |
| `styles/presets/*.css` | 每个 preset 的浅色值及深色覆盖 |
| `styles/preferences.css` | 圆角、密度、内容宽度覆盖，以及减少动效和透明度的适配 |
| `model/theme-config.ts` | 可选值、类型、默认偏好、配置面板的风格预览元数据 |
| `infrastructure/theme-document.ts` | 将偏好和解析后的明暗模式应用到 `<html>` |
| `infrastructure/theme-storage.ts` | 本地偏好读写 |
| `theme-provider.tsx`、`use-theme.ts` | React 内共享偏好、切换和系统模式订阅 |
| `bootstrap.ts` | React 挂载前恢复主题 |
| `ui/theme-configurator.tsx` | 全局主题配置面板 |

`index.css` 只导入 Tailwind 和 `styles/theme.css`，并定义应用基础样式。它不再导入任何 Agent 专属主题。

## 语义 token 契约

组件依赖 token 的用途，不依赖品牌名称或具体色值。

| 用途 | CSS 变量 | Tailwind 用法 |
| --- | --- | --- |
| 页面 | `--background`、`--foreground` | `bg-background text-foreground` |
| 卡片、浮层、侧栏 | `--card`、`--popover`、`--sidebar` 及对应 `-foreground` | `bg-card`、`bg-popover`、`bg-sidebar` |
| 操作 | `--primary`、`--primary-hover`、`--secondary`、`--accent` 及对应 `-foreground` | `bg-primary text-primary-foreground hover:bg-primary-hover` |
| 次要内容 | `--muted`、`--muted-foreground` | `bg-muted text-muted-foreground` |
| 状态 | `--success`、`--warning`、`--info`、`--destructive` 及对应 `-foreground` | `text-success`、`bg-destructive text-destructive-foreground` |
| 边界和焦点 | `--border`、`--input`、`--ring`、`--overlay` | `border-border focus-visible:ring-ring bg-overlay` |
| 圆角 | `--radius`、`--radius-control`、`--radius-panel` | `rounded-control rounded-panel` |
| 间距和控件尺寸 | `--spacing`、`--control-height`，后者映射到 `--spacing-control` | `p-4 gap-3 min-h-control size-control` |
| 阴影 | `--shadow-control`、`--shadow-panel` | `shadow-control shadow-panel` |
| 材质 | `--blur-surface` | `backdrop-blur-surface` |
| 字体与动效 | `--font-body`、`--motion-duration`、`--motion-easing` | 字体由基础样式继承；`duration-(--motion-duration) ease-(--motion-easing)` |

`@theme inline` 将颜色工具类直接连接到运行时变量；`@theme static` 保留 feature CSS 也需要直接读取的尺寸、圆角、阴影和模糊变量。`@theme` 必须位于顶层，不能放进 feature 选择器。机制见 [Tailwind Theme variables](https://tailwindcss.com/docs/theme)。

## Mode、preset 与用户覆盖

`mode` 和 `preset` 相互独立：

- `mode: 'system' | 'light' | 'dark'`：控制明暗；`system` 订阅系统偏好变化，`resolvedMode` 提供实际的 `light` 或 `dark`。
- `preset`：控制视觉风格，每一套都支持浅色和深色。
- `radius`、`density`：`default` 表示跟随 preset；显式值通过后加载的 `preferences.css` 覆盖 preset。
- `contentWidth`：`full` 或 `centered`，控制使用 `.app-content` 的页面宽度。

默认值是 `mode: 'system'`、`preset: 'chatgpt'`，圆角和密度跟随 preset。切换 preset 不会清除已设置的圆角或密度覆盖；如需完整体验某个 preset，将两项恢复为 `default`。

最终状态写在 `<html>` 上，例如：

```html
<html class="dark" data-theme-mode="system" data-theme-preset="apple-ios26">
```

所有旧 preset 已移除；存储里的不支持值由现有偏好校验归一化为默认 `chatgpt`，没有兼容别名或迁移层。

## 七种风格

| Preset | 视觉方向 |
| --- | --- |
| `apple-ios26` | 大圆角、柔和阴影、通透导航和浮层；内容表面保持实色。参考 [Apple Materials](https://developer.apple.com/design/human-interface-guidelines/materials)，Web 模糊材质不等同于原生 Liquid Glass 渲染。 |
| `chatgpt` | 中性灰阶、克制对比、轻阴影和圆润控件。 |
| `wechat` | 绿色强调、浅灰背景、简洁表面；视觉参考 [WeUI](https://github.com/Tencent/weui)。 |
| `taodesign` | 淘宝／淘系电商的橙色、暖色表面和圆润操作，不是腾讯 TDesign。 |
| `ant-design` | 蓝色强调、均衡圆角、清晰层级；参考 [Ant Design 主题定制](https://ant.design/docs/react/customize-theme/)。 |
| `arco-design` | 明快蓝色、小圆角、紧凑控件；参考 [Arco 主题源码](https://github.com/arco-design/arco-design/blob/main/components/style/theme/default.less)。 |
| `douyin-design` | 粉色主操作、青色辅助强调，同时提供浅色和深色表面。 |

语义化状态色和明暗切换的建模也参考 [Semi Design Tokens](https://semi.design/en-US/basic/tokens)。此处的 `douyin-design` 表示抖音品牌视觉方向，不表示安装了 Semi，也不表示两者是同一套官方组件规范。预设色值为当前 Web 界面适配过的值，配置面板缩略图只展示其浅色外观。

## 使用方式

应用根部已有 `ThemeProvider`，业务组件通过 `useTheme` 读写偏好。以下示例假定文件放在 `src/appearance-action.tsx`：

```tsx
import { useTheme } from './theme'

function AppearanceAction() {
  const { preferences, resolvedMode, setPreferences } = useTheme()

  return (
    <button
      type="button"
      className="min-h-control rounded-control bg-primary px-4 text-primary-foreground shadow-control"
      onClick={() => setPreferences({ preset: 'apple-ios26', mode: 'system' })}
    >
      {preferences.preset} · {resolvedMode}
    </button>
  )
}
```

只修改需要更新的字段即可。`setPreferences({ radius: 'default', density: 'default' })` 恢复 preset 的形状与密度，`resetPreferences()` 重置全部外观偏好。界面中通过主题面板切换，在 `/examples/base-ui/theme` 可检查卡片、输入框、按钮、状态色和弹窗的实际效果。

## Feature 与 Portal

Agent 消费同一套全局语义 token，不再定义或使用 `--agent-*`。`features/agent/ui/agent.css` 只管理 Agent 局部布局和交互外观，选择器限定在 `.agent-workspace` 或 `[data-agent-scope]` 内，避免影响其他页面。

共享组件不依赖 Agent。Dialog、Menu、Sheet 等 Portal 即使挂到 `body`，仍能从 `<html>` 继承全局主题，不需要复制 feature 的配色。需要 Agent 局部布局的内容仍应显式添加对应 scope；scope 不承担全局主题切换职责。

新增组件优先组合现有 Base UI 组件并使用上述语义工具类。修改某种视觉风格只编辑其 preset；新增公共语义才扩展 `tokens.css`，不要为已有语义再创建 feature 专属颜色别名。
