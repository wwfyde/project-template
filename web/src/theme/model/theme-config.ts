export const THEME_MODES = [
  { value: 'system', labelKey: 'modes.system' },
  { value: 'light', labelKey: 'modes.light' },
  { value: 'dark', labelKey: 'modes.dark' },
] as const

export const THEME_PRESETS = [
  {
    value: 'default',
    labelKey: 'presets.default',
    swatches: ['oklch(0.67 0.18 254)', 'oklch(0.72 0.16 302)'],
  },
  {
    value: 'midnight',
    labelKey: 'presets.midnight',
    swatches: ['oklch(0.53 0.07 156)', 'oklch(0.57 0.09 337)'],
  },
  {
    value: 'rose-garden',
    labelKey: 'presets.roseGarden',
    swatches: ['oklch(0.58 0.24 12)', 'oklch(0.81 0.11 6)'],
  },
  {
    value: 'lake-view',
    labelKey: 'presets.lakeView',
    swatches: ['oklch(0.77 0.18 163)', 'oklch(0.55 0.09 201)'],
  },
  {
    value: 'sunset-glow',
    labelKey: 'presets.sunsetGlow',
    swatches: ['oklch(0.56 0.19 25)', 'oklch(0.79 0.12 42)'],
  },
  {
    value: 'forest-whisper',
    labelKey: 'presets.forestWhisper',
    swatches: ['oklch(0.53 0.11 182)', 'oklch(0.52 0.05 250)'],
  },
  {
    value: 'ocean-breeze',
    labelKey: 'presets.oceanBreeze',
    swatches: ['oklch(0.55 0.22 263)', 'oklch(0.59 0.2 277)'],
  },
  {
    value: 'lavender-dream',
    labelKey: 'presets.lavenderDream',
    swatches: ['oklch(0.57 0.18 307)', 'oklch(0.81 0.06 201)'],
  },
] as const

export const THEME_RADII = [
  { value: 'default', labelKey: 'radii.default', preview: '0.75rem' },
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
  preset: 'default',
  radius: 'default',
  density: 'default',
  contentWidth: 'full',
})

export const THEME_STORAGE_KEY = 'project-template.theme.v1'
