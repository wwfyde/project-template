import { FolderUp, Upload } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import type { ChangeEvent } from 'react'

import type { SkillUpload } from '../model/skill'

export function SkillUploadButtons({
  disabled,
  onUpload,
}: {
  disabled: boolean
  onUpload: (upload: SkillUpload) => void
}) {
  const { t } = useTranslation('skills')
  const upload = (event: ChangeEvent<HTMLInputElement>, kind: SkillUpload['kind']) => {
    const files = Array.from(event.currentTarget.files ?? [])
    event.currentTarget.value = ''
    if (!files.length) return
    onUpload(kind === 'zip' ? { kind, file: files[0] } : { kind, files })
  }

  return (
    <div className="flex flex-wrap gap-2">
      <label className={`skill-button relative ${disabled ? 'opacity-40' : ''}`}>
        <Upload size={16} aria-hidden="true" />
        {t('uploadZip')}
        <input
          type="file"
          accept=".zip,application/zip"
          disabled={disabled}
          aria-label={t('uploadZip')}
          className="absolute inset-0 w-full cursor-pointer opacity-0"
          onChange={(event) => upload(event, 'zip')}
        />
      </label>
      <label className={`skill-button relative ${disabled ? 'opacity-40' : ''}`}>
        <FolderUp size={16} aria-hidden="true" />
        {t('uploadDirectory')}
        <input
          type="file"
          multiple
          {...{ webkitdirectory: '' }}
          disabled={disabled}
          aria-label={t('uploadDirectory')}
          className="absolute inset-0 w-full cursor-pointer opacity-0"
          onChange={(event) => upload(event, 'directory')}
        />
      </label>
    </div>
  )
}
