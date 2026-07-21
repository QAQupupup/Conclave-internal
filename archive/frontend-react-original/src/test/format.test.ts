import { describe, it, expect } from 'vitest'
import { formatTime, formatDateTime, tryFormatJson, truncate } from '../lib/format'

describe('format', () => {
  describe('formatTime', () => {
    it('formats ISO string to HH:MM:SS', () => {
      const result = formatTime('2026-01-15T14:30:45Z')
      expect(result).toMatch(/^\d{2}:\d{2}:\d{2}$/)
    })

    it('returns empty string for invalid date', () => {
      expect(formatTime('not-a-date')).toBe('')
    })
  })

  describe('formatDateTime', () => {
    it('formats ISO string to localized string', () => {
      const result = formatDateTime('2026-01-15T14:30:45Z')
      expect(result).toBeTruthy()
      expect(result).not.toBe('2026-01-15T14:30:45Z')
    })

    it('returns empty string for empty input', () => {
      expect(formatDateTime('')).toBe('')
    })
  })

  describe('tryFormatJson', () => {
    it('formats valid JSON object', () => {
      const result = tryFormatJson('{"b":2,"a":1}')
      expect(result).toContain('"a": 1')
      expect(result).toContain('"b": 2')
    })

    it('formats valid JSON array', () => {
      const result = tryFormatJson('[1,2,3]')
      expect(result).toBe('[\n  1,\n  2,\n  3\n]')
    })

    it('returns original for non-JSON', () => {
      expect(tryFormatJson('hello world')).toBe('hello world')
    })

    it('returns original for invalid JSON', () => {
      expect(tryFormatJson('{invalid}')).toBe('{invalid}')
    })
  })

  describe('truncate', () => {
    it('returns original when shorter than maxLen', () => {
      expect(truncate('short', 10)).toBe('short')
    })

    it('truncates and adds ellipsis when longer', () => {
      expect(truncate('a very long string', 10)).toBe('a very lon…')
    })

    it('returns original when exactly maxLen', () => {
      expect(truncate('exact', 5)).toBe('exact')
    })
  })
})
