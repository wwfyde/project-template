import { createFileRoute } from '@tanstack/react-router'
import { useId, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Button } from '../../../../components/ui/button'
import { Dialog } from '../../../../components/ui/dialog'
import { ThemeConfigurator, useTheme } from '../../../../theme'
import { THEME_PRESETS } from '../../../../theme/model/theme-config'

export const Route = createFileRoute('/_authenticated/examples/base-ui/theme')({
  component: RouteComponent,
})

function RouteComponent() {
  const { t } = useTranslation('theme')
  const { t: pages } = useTranslation('pages')
  const { preferences } = useTheme()
  const [count, setCount] = useState(0)
  const [dialogOpen, setDialogOpen] = useState(false)
  const fieldId = useId()
  const dialogTrigger = useRef<HTMLButtonElement>(null)
  const activePreset = THEME_PRESETS.find((preset) => preset.value === preferences.preset)!

  return (
    <section className="space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold">{t('preview.title')}</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">{t('preview.description')}</p>
          <p className="text-xs text-muted-foreground">
            {t('preview.activeStyle')} · <span className="font-medium text-foreground">{t(activePreset.labelKey)}</span>
          </p>
        </div>
        <ThemeConfigurator />
      </header>
      <div className="grid gap-6 lg:grid-cols-2">
        <div className="space-y-5 rounded-panel border border-border bg-card p-6 text-card-foreground shadow-panel backdrop-blur-surface">
          <div>
            <h2 className="font-semibold">{t('preview.surface')}</h2>
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{t('preview.surfaceDescription')}</p>
          </div>
          <div className="space-y-2">
            <label htmlFor={fieldId} className="block text-sm font-medium">{t('preview.fieldLabel')}</label>
            <input
              id={fieldId}
              placeholder={t('preview.fieldPlaceholder')}
              className="min-h-[var(--control-height)] w-full rounded-control border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </div>
          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setCount((value) => value + 1)}>{t('preview.primary')}</Button>
            <Button variant="outline" disabled={count === 0} onClick={() => setCount(0)}>
              {pages('reset')}
            </Button>
          </div>
          <p className="text-sm text-muted-foreground" aria-live="polite">
            {pages('clickCount', { count })}
          </p>
        </div>
        <div className="space-y-5 rounded-panel border border-border bg-card p-6 text-card-foreground shadow-panel backdrop-blur-surface">
          <h2 className="font-semibold">{t('preview.colors')}</h2>
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-control bg-primary px-3 py-4 text-sm font-medium text-primary-foreground">{t('preview.primary')}</div>
            <div className="rounded-control bg-secondary px-3 py-4 text-sm font-medium text-secondary-foreground">{t('preview.secondary')}</div>
            <div className="rounded-control bg-success/12 px-3 py-4 text-sm font-medium text-success">{t('preview.success')}</div>
            <div className="rounded-control bg-warning/12 px-3 py-4 text-sm font-medium text-warning">{t('preview.warning')}</div>
            <div className="rounded-control bg-destructive/12 px-3 py-4 text-sm font-medium text-destructive">{t('preview.destructive')}</div>
          </div>
          <Button ref={dialogTrigger} variant="outline" onClick={() => setDialogOpen(true)}>
            {t('preview.openDialog')}
          </Button>
        </div>
      </div>
      <Dialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        title={t('preview.dialogTitle')}
        description={t('preview.dialogDescription')}
        closeLabel={t('preview.closeDialog')}
        returnFocusRef={dialogTrigger}
      >
        <p className="text-sm leading-relaxed text-muted-foreground">{t('preview.dialogBody')}</p>
        <Button className="mt-5" onClick={() => setDialogOpen(false)}>{t('preview.closeDialog')}</Button>
      </Dialog>
    </section>
  )
}
