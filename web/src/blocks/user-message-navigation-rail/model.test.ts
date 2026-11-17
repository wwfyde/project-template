import { describe, expect, it } from 'vitest'

import { keyboardIndex, markerProgress, scrollBehavior } from './model'

describe('user message navigation rail', () => {
  it('expands the selected marker and three neighbors symmetrically', () => {
    expect(markerProgress(4, 4)).toBe(1)
    expect(markerProgress(3, 4)).toBe(0.7)
    expect(markerProgress(5, 4)).toBe(0.7)
    expect(markerProgress(2, 4)).toBe(0.4)
    expect(markerProgress(6, 4)).toBe(0.4)
    expect(markerProgress(1, 4)).toBe(0.2)
    expect(markerProgress(7, 4)).toBe(0.2)
    expect(markerProgress(0, 4)).toBe(0)
    expect(markerProgress(4, null)).toBe(0)
  })

  it('lets keyboard selection reach every message without wrapping', () => {
    expect(keyboardIndex('ArrowDown', 19, 1000)).toBe(20)
    expect(keyboardIndex('ArrowDown', 999, 1000)).toBe(999)
    expect(keyboardIndex('ArrowUp', 0, 1000)).toBe(0)
    expect(keyboardIndex('Home', 500, 1000)).toBe(0)
    expect(keyboardIndex('End', 500, 1000)).toBe(999)
    expect(keyboardIndex('Enter', 5, 1000)).toBeNull()
    expect(keyboardIndex(' ', 5, 1000)).toBeNull()
    expect(keyboardIndex('ArrowDown', 0, 0)).toBeNull()
  })

  it('uses instant navigation for distant messages, scrubbing and reduced motion', () => {
    expect(scrollBehavior(399, 400, false, 'click')).toBe('smooth')
    expect(scrollBehavior(-400, 400, false, 'keyboard')).toBe('smooth')
    expect(scrollBehavior(401, 400, false, 'click')).toBe('instant')
    expect(scrollBehavior(-401, 400, false, 'shortcut')).toBe('instant')
    expect(scrollBehavior(20, 400, true, 'click')).toBe('instant')
    expect(scrollBehavior(20, 400, false, 'scrub')).toBe('instant')
  })
})
