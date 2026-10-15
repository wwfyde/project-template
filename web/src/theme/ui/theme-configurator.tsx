import { Radio as RadioPrimitive } from '@base-ui/react/radio'
import { RadioGroup } from '@base-ui/react/radio-group'
import { Dialog } from '@base-ui/react/dialog'
import { Check, MonitorCog, Moon, Palette, RotateCcw, Sun, X } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { LanguageSwitcher } from '../../i18n/ui/language-switcher'
import {
  CONTENT_WIDTHS,
  THEME_DENSITIES,
  THEME_MODES,
  THEME_PRESETS,
  THEME_RADII,
  type ContentWidth,
  type ThemeDensity,
  type ThemeMode,
  type ThemePreset,
  type ThemeRadius,
} from '../model/theme-config'
import { useTheme } from '../use-theme'
import { DarkThemeIcon, LightThemeIcon, SystemThemeIcon } from './theme-icons'

const modeIcons = {
  system: SystemThemeIcon,
  light: LightThemeIcon,
  dark: DarkThemeIcon,
} satisfies Record<ThemeMode, typeof SystemThemeIcon>

const resolvedModeLabelKeys = {
  light: 'modes.light',
  dark: 'modes.dark',
} as const

type SectionProps = {
  title: string
  children: ReactNode
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="space-y-2.5">
      <h3 className="text-sm font-semibold text-muted-foreground">{title}</h3>
      {children}
    </section>
  )
}

function SelectionMark() {
  return (
    <span className="pointer-events-none absolute -right-2 -top-2 hidden size-5 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-md group-data-checked:flex">
      <Check className="size-3.5" strokeWidth={3} aria-hidden="true" />
    </span>
  )
}

function OptionFrame({ children }: { children: ReactNode }) {
  return (
    <div className="relative rounded-xl border border-border bg-card transition group-data-checked:border-primary group-data-checked:ring-2 group-data-checked:ring-primary/25 group-focus-visible:ring-2 group-focus-visible:ring-ring group-hover:border-primary/50">
      <SelectionMark />
      {children}
    </div>
  )
}

export function ThemeConfigurator() {
  const [open, setOpen] = useState(false)
  const { t } = useTranslation('theme')
  const { preferences, resolvedMode, setPreferences, resetPreferences } = useTheme()

  const ModeStatusIcon = resolvedMode === 'dark' ? Moon : Sun

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        className="inline-flex size-11 shrink-0 items-center justify-center rounded-xl border border-border bg-card text-foreground shadow-sm transition hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:size-9"
        aria-label={t('open')}
      >
        <Palette className="size-4.5" aria-hidden="true" />
      </Dialog.Trigger>

      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[2px] transition-opacity data-ending-style:opacity-0 data-starting-style:opacity-0" />
        <Dialog.Popup className="fixed inset-0 z-50 flex h-dvh w-full flex-col border-border bg-popover text-popover-foreground shadow-2xl outline-none transition duration-200 data-ending-style:translate-x-8 data-ending-style:opacity-0 data-starting-style:translate-x-8 data-starting-style:opacity-0 md:inset-y-0 md:left-auto md:right-0 md:max-w-md md:border-l">
          <header className="border-b border-border px-4 pb-4 pt-[max(1rem,env(safe-area-inset-top))] md:px-5 md:py-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <Dialog.Title className="text-base font-semibold">{t('title')}</Dialog.Title>
                <Dialog.Description className="mt-1 text-sm text-muted-foreground">
                  {t('description')}
                </Dialog.Description>
              </div>
              <Dialog.Close
                className="inline-flex size-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring md:size-8"
                aria-label={t('close')}
              >
                <X className="size-4" aria-hidden="true" />
              </Dialog.Close>
            </div>
          </header>

          <div className="min-h-0 flex-1 space-y-6 overflow-y-auto overscroll-contain px-4 py-5 md:space-y-7 md:px-5">
            <Section title={t('sections.language')}>
              <LanguageSwitcher />
            </Section>
            <Section title={t('sections.mode')}>
              <RadioGroup
                value={preferences.mode}
                onValueChange={(mode) => setPreferences({ mode: mode as ThemeMode })}
                className="grid grid-cols-3 gap-3"
                aria-label={t('groups.mode')}
              >
                {THEME_MODES.map((option) => {
                  const Icon = modeIcons[option.value]
                  return (
                    <RadioPrimitive.Root
                      key={option.value}
                      value={option.value}
                      className="group min-w-0 cursor-pointer outline-none"
                      aria-label={t(option.labelKey)}
                    >
                      <OptionFrame>
                        <Icon className="block w-full rounded-xl" aria-hidden="true" />
                      </OptionFrame>
                      <div className="mt-2 text-center text-xs font-medium">{t(option.labelKey)}</div>
                    </RadioPrimitive.Root>
                  )
                })}
              </RadioGroup>
            </Section>

            <Section title={t('sections.preset')}>
              <RadioGroup
                value={preferences.preset}
                onValueChange={(preset) => setPreferences({ preset: preset as ThemePreset })}
                className="grid grid-cols-2 gap-x-3 gap-y-4 md:grid-cols-4"
                aria-label={t('groups.preset')}
              >
                {THEME_PRESETS.map((preset) => (
                  <RadioPrimitive.Root
                    key={preset.value}
                    value={preset.value}
                    className="group min-w-0 cursor-pointer outline-none"
                    aria-label={t(preset.labelKey)}
                  >
                    <OptionFrame>
                      <div
                        className="h-12 rounded-xl"
                        style={{ background: `linear-gradient(135deg, ${preset.swatches.join(', ')})` }}
                      />
                    </OptionFrame>
                    <div className="mt-1.5 truncate text-center text-xs">{t(preset.labelKey)}</div>
                  </RadioPrimitive.Root>
                ))}
              </RadioGroup>
            </Section>

            <Section title={t('sections.radius')}>
              <RadioGroup
                value={preferences.radius}
                onValueChange={(radius) => setPreferences({ radius: radius as ThemeRadius })}
                className="grid grid-cols-3 gap-x-3 gap-y-4 md:grid-cols-6 md:gap-2"
                aria-label={t('groups.radius')}
              >
                {THEME_RADII.map((option) => (
                  <RadioPrimitive.Root
                    key={option.value}
                    value={option.value}
                    className="group min-w-0 cursor-pointer outline-none"
                    aria-label={t(option.labelKey)}
                  >
                    <OptionFrame>
                      <div className="relative h-12">
                        <span
                          className="absolute left-3 top-3 size-4 border-l-2 border-t-2 border-foreground/60"
                          style={{ borderTopLeftRadius: option.preview }}
                        />
                      </div>
                    </OptionFrame>
                    <div className="mt-1.5 truncate text-center text-xs">{t(option.labelKey)}</div>
                  </RadioPrimitive.Root>
                ))}
              </RadioGroup>
            </Section>

            <Section title={t('sections.density')}>
              <RadioGroup
                value={preferences.density}
                onValueChange={(density) => setPreferences({ density: density as ThemeDensity })}
                className="grid grid-cols-3 gap-3"
                aria-label={t('groups.density')}
              >
                {THEME_DENSITIES.map((option) => (
                  <RadioPrimitive.Root
                    key={option.value}
                    value={option.value}
                    className="group min-w-0 cursor-pointer outline-none"
                    aria-label={t(option.labelKey)}
                  >
                    <OptionFrame>
                      <div className="flex h-14 flex-col justify-center gap-1.5 px-4">
                        {Array.from({ length: option.rows }, (_, index) => (
                          <span
                            key={`${option.value}-${index}`}
                            className="h-0.5 rounded-full bg-foreground/50"
                            style={{ width: `${85 - index * 12}%` }}
                          />
                        ))}
                      </div>
                    </OptionFrame>
                    <div className="mt-1.5 text-center text-xs">{t(option.labelKey)}</div>
                  </RadioPrimitive.Root>
                ))}
              </RadioGroup>
            </Section>

            <Section title={t('sections.contentWidth')}>
              <RadioGroup
                value={preferences.contentWidth}
                onValueChange={(contentWidth) => setPreferences({ contentWidth: contentWidth as ContentWidth })}
                className="grid grid-cols-2 gap-3"
                aria-label={t('groups.contentWidth')}
              >
                {CONTENT_WIDTHS.map((option) => (
                  <RadioPrimitive.Root
                    key={option.value}
                    value={option.value}
                    className="group cursor-pointer outline-none"
                    aria-label={t(option.labelKey)}
                  >
                    <OptionFrame>
                      <div className="flex h-14 flex-col gap-1.5 p-3">
                        <span className="h-2 rounded bg-foreground/25" />
                        <span
                          className={`h-1.5 rounded bg-foreground/50 ${option.value === 'centered' ? 'mx-auto w-1/2' : 'w-full'}`}
                        />
                        <span
                          className={`h-1.5 rounded bg-foreground/35 ${option.value === 'centered' ? 'mx-auto w-1/3' : 'w-2/3'}`}
                        />
                      </div>
                    </OptionFrame>
                    <div className="mt-1.5 text-center text-xs">{t(option.labelKey)}</div>
                  </RadioPrimitive.Root>
                ))}
              </RadioGroup>
            </Section>
          </div>

          <footer className="border-t border-border px-4 pb-[max(1rem,env(safe-area-inset-bottom))] pt-4 md:p-4">
            <button
              type="button"
              className="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-destructive/12 px-4 py-2.5 text-sm font-medium text-destructive transition hover:bg-destructive/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-destructive/50"
              onClick={resetPreferences}
            >
              <RotateCcw className="size-4" aria-hidden="true" />
              {t('reset')}
            </button>
            <div className="mt-2 flex items-center justify-center gap-1.5 text-[11px] text-muted-foreground">
              {preferences.mode === 'system' ? (
                <MonitorCog className="size-3.5" />
              ) : (
                <ModeStatusIcon className="size-3.5" />
              )}
              {t('resolvedMode', { mode: t(resolvedModeLabelKeys[resolvedMode]) })}
            </div>
          </footer>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  )
}
