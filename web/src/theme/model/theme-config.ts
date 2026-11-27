export const THEME_MODES = [
  { value: 'system', labelKey: 'modes.system' },
  { value: 'light', labelKey: 'modes.light' },
  { value: 'dark', labelKey: 'modes.dark' },
] as const

export const THEME_PRESETS = [
  {
    value: 'apple-ios26',
    labelKey: 'presets.appleIos26',
    descriptionKey: 'presetDescriptions.appleIos26',
    preview: { surface: '#f2f2f7', primary: '#0065d9', radius: '1.25rem', shadow: '0 16px 48px #2635561a, inset 0 1px 0 #ffffffe6' },
  },
  {
    value: 'chatgpt',
    labelKey: 'presets.chatgpt',
    descriptionKey: 'presetDescriptions.chatgpt',
    preview: { surface: '#fff', primary: '#242424', radius: '1rem', shadow: '0 4px 24px #0000000a, 0 1px 5px #00000008' },
  },
  {
    value: 'wechat',
    labelKey: 'presets.wechat',
    descriptionKey: 'presetDescriptions.wechat',
    preview: { surface: '#ededed', primary: '#078445', radius: '0.5rem', shadow: '0 4px 16px #0000000d' },
  },
  {
    value: 'taodesign',
    labelKey: 'presets.taodesign',
    descriptionKey: 'presetDescriptions.taodesign',
    preview: { surface: '#fff8f3', primary: '#c84400', radius: '1rem', shadow: '0 8px 28px #b94d0012' },
  },
  {
    value: 'ant-design',
    labelKey: 'presets.antDesign',
    descriptionKey: 'presetDescriptions.antDesign',
    preview: { surface: '#f5f5f5', primary: '#1668dc', radius: '0.375rem', shadow: '0 6px 16px #00000014, 0 3px 6px #0000000a' },
  },
  {
    value: 'arco-design',
    labelKey: 'presets.arcoDesign',
    descriptionKey: 'presetDescriptions.arcoDesign',
    preview: { surface: '#f2f3f5', primary: '#165dff', radius: '0.25rem', shadow: '0 4px 10px #0000001a' },
  },
  {
    value: 'douyin-design',
    labelKey: 'presets.douyinDesign',
    descriptionKey: 'presetDescriptions.douyinDesign',
    preview: { surface: '#faf8fc', primary: '#d5164b', radius: '0.75rem', shadow: '0 8px 28px #39133b12' },
  },
] as const

export const THEME_RADII = [
  { value: 'default', labelKey: 'radii.default', preview: 'var(--radius)' },
  { value: 'none', labelKey: 'radii.none', preview: '0' },
  { value: 'sm', labelKey: 'radii.sm', preview: '0.3rem' },
  { value: 'md', labelKey: 'radii.md', preview: '0.5rem' },
  { value: 'lg', labelKey: 'radii.lg', preview: '0.75rem' },
  { value: 'xl', labelKey: 'radii.xl', preview: '1rem' },
] as const

export const THEME_DENSITIES = [
  { value: 'compact', labelKey: 'densities.compact', rows: 4 },
  { value: 'default', labelKey: 'densities.default', rows: 3 },
  { value: 'comfortable', labelKey: 'densities.comfortable', rows: 2 },
] as const

export const CONTENT_WIDTHS = [
  { value: 'full', labelKey: 'contentWidths.full' },
  { value: 'centered', labelKey: 'contentWidths.centered' },
] as const

export type ThemeMode = (typeof THEME_MODES)[number]['value']
export type ResolvedThemeMode = Exclude<ThemeMode, 'system'>
export type ThemePreset = (typeof THEME_PRESETS)[number]['value']
export type ThemeRadius = (typeof THEME_RADII)[number]['value']
export type ThemeDensity = (typeof THEME_DENSITIES)[number]['value']
export type ContentWidth = (typeof CONTENT_WIDTHS)[number]['value']

export type ThemePreferences = {
  mode: ThemeMode
  preset: ThemePreset
  radius: ThemeRadius
  density: ThemeDensity
  contentWidth: ContentWidth
}

export const DEFAULT_THEME_PREFERENCES: Readonly<ThemePreferences> = Object.freeze({
  mode: 'system',
  preset: 'chatgpt',
  radius: 'default',
  density: 'default',
  contentWidth: 'full',
})

export const THEME_STORAGE_KEY = 'project-template.theme.v1'
