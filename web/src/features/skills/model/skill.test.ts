import { describe, expect, it } from 'vitest'

import { findManifest, mergeSkillPage, validateSkillUpload, type SkillTreeNode } from './skill'

describe('skill browsing', () => {
  it('finds case-insensitive manifests beneath a bundle root', () => {
    const nodes: SkillTreeNode[] = [
      {
        name: 'review',
        path: 'review',
        type: 'directory',
        size: null,
        media_type: null,
        children: [
          {
            name: 'skill.MD',
            path: 'review/skill.MD',
            type: 'file',
            size: 1,
            media_type: 'text/markdown',
            children: [],
          },
        ],
      },
    ]
    expect(findManifest(nodes)).toBe('review/skill.MD')
    expect(findManifest([])).toBeNull()
  })

  it('merges overlapping pages by ID without losing updated default pointers or mutating old data', () => {
    const current = [
      { id: 'a', default_version: '1' },
      { id: 'b', default_version: '1' },
    ]
    const merged = mergeSkillPage(current, [
      { id: 'b', default_version: '3' },
      { id: 'c', default_version: '1' },
    ])
    expect(merged.map((item) => item.id)).toEqual(['a', 'b', 'c'])
    expect(merged[1].default_version).toBe('3')
    expect(current[1].default_version).toBe('1')
  })

  it('checks count and per-file limits while keeping ZIP and folder formats distinct', () => {
    const file = new File(['text'], 'SKILL.md')
    expect(validateSkillUpload({ kind: 'zip', file })).toBe('invalidZip')
    expect(validateSkillUpload({ kind: 'directory', files: [] })).toBe('emptyUpload')
    expect(validateSkillUpload({ kind: 'directory', files: Array.from({ length: 501 }, () => file) })).toBe(
      'tooManyFiles',
    )
    Object.defineProperty(file, 'size', { value: 25 * 1024 * 1024 + 1 })
    expect(validateSkillUpload({ kind: 'directory', files: [file] })).toBe('fileTooLarge')
    expect(validateSkillUpload({ kind: 'zip', file: new File(['zip'], 'SKILL.ZIP') })).toBeNull()
  })
})
