import { createInstance } from 'i18next'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { I18nextProvider } from 'react-i18next'
import { describe, expect, it } from 'vitest'

import { skillsEn } from '../model/translations'
import type { SkillFileData } from '../model/skill'
import { SkillFilePreview } from './skill-file-preview'
import { SkillTree } from './skill-tree'

const i18n = createInstance()
await i18n.init({ lng: 'en', resources: { en: { skills: skillsEn } }, interpolation: { escapeValue: false } })

function render(component: ReturnType<typeof createElement>): string {
  return renderToStaticMarkup(createElement(I18nextProvider, { i18n }, component))
}

const file: SkillFileData = {
  object: 'skill.file',
  skill_id: 'skill_1',
  version: '1',
  path: 'example.html',
  size: 50,
  media_type: 'text/html',
  encoding: 'utf-8',
  content: '<script>alert("private")</script>',
  truncated: false,
  reason: null,
}

describe('skill preview components', () => {
  it('renders uploaded HTML as escaped source instead of executable markup', () => {
    const html = render(createElement(SkillFilePreview, { file }))
    expect(html).toContain('&lt;script&gt;')
    expect(html).not.toContain('<script>')
    expect(html).toContain('Text preview')
  })

  it('shows binary and truncation states without trying to embed uploaded files', () => {
    const binary = render(createElement(SkillFilePreview, { file: { ...file, content: null, encoding: null } }))
    expect(binary).toContain('cannot be previewed as text')
    expect(binary).not.toContain('<iframe')
    expect(binary).not.toContain('<img')
    const truncated = render(createElement(SkillFilePreview, { file: { ...file, truncated: true } }))
    expect(truncated).toContain('Only the beginning')
  })

  it('uses native keyboard-accessible directory disclosures and identifies the selected file', () => {
    const html = render(
      createElement(SkillTree, {
        nodes: [
          {
            name: 'references',
            path: 'references',
            type: 'directory',
            size: null,
            media_type: null,
            children: [
              {
                name: '<unsafe>.md',
                path: 'references/<unsafe>.md',
                type: 'file',
                size: 1,
                media_type: 'text/markdown',
                children: [],
              },
            ],
          },
        ],
        selectedPath: 'references/<unsafe>.md',
        onSelect: () => undefined,
      }),
    )
    expect(html).toContain('<details open="">')
    expect(html).toContain('<summary')
    expect(html).toContain('aria-current="true"')
    expect(html).toContain('&lt;unsafe&gt;.md')
  })
})
