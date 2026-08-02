import { describe, it, expect } from 'vitest';
import { cn } from '@/lib/utils';

describe('cn utility', () => {
  it('merges class names correctly', () => {
    expect(cn('a', 'b')).toBe('a b');
    expect(cn('a', { b: true, c: false })).toBe('a b');
    // tailwind-merge dedupes conflicting tailwind classes (not arbitrary strings)
    expect(cn('px-2 px-4')).toBe('px-4');
  });
});

describe('constants', () => {
  it('has STAGE_LABELS for all 6 stages', async () => {
    const { STAGE_LABELS } = await import('@/lib/constants');
    expect(Object.keys(STAGE_LABELS)).toHaveLength(6);
    expect(STAGE_LABELS.clarification).toBe('问题澄清');
    expect(STAGE_LABELS.produce).toBe('成果产出');
  });
});
