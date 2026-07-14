import { render, screen, waitFor, act } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach, afterEach } from 'vitest'
import userEvent from '@testing-library/user-event'
import { ThemeProvider, useTheme } from '../store/ThemeContext.tsx'

function TestConsumer() {
  const { mode, toggleMode, syncStatus } = useTheme()
  return (
    <div>
      <span data-testid="mode">{mode}</span>
      <span data-testid="sync">{syncStatus}</span>
      <button data-testid="toggle" onClick={toggleMode}>toggle</button>
    </div>
  )
}

describe('ThemeContext', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.useFakeTimers({ shouldAdvanceTime: true })
    vi.stubGlobal('fetch', vi.fn())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('fetches preferences on mount and applies remote theme mode', async () => {
    ;(window.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ 'theme-mode': 'dark', 'token-overrides': JSON.stringify({ accent: '#ff0000' }) }),
    })

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>
    )

    expect(screen.getByTestId('sync').textContent).toBe('syncing')
    await waitFor(() => expect(screen.getByTestId('mode').textContent).toBe('dark'))
    await waitFor(() => expect(screen.getByTestId('sync').textContent).toBe('synced'))

    expect(window.fetch).toHaveBeenCalledWith('/preferences', expect.any(Object))
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(getComputedStyle(document.documentElement).getPropertyValue('--accent').trim()).toBe('#ff0000')
  })

  it('persists local default when remote has no theme-mode', async () => {
    ;(window.fetch as ReturnType<typeof vi.fn>).mockResolvedValueOnce({
      ok: true,
      json: async () => ({ 'token-overrides': JSON.stringify({}) }),
    })

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>
    )

    await waitFor(() => expect(screen.getByTestId('sync').textContent).toBe('synced'))
    expect(screen.getByTestId('mode').textContent).toBe('light')
  })

  it('toggles theme and saves to backend', async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTimeAsync.bind(vi) })
    ;(window.fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      json: async () => ({}),
    })

    render(
      <ThemeProvider>
        <TestConsumer />
      </ThemeProvider>
    )

    await waitFor(() => expect(screen.getByTestId('sync').textContent).toBe('synced'))
    expect(screen.getByTestId('mode').textContent).toBe('light')

    await user.click(screen.getByTestId('toggle'))

    expect(screen.getByTestId('mode').textContent).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')

    await act(async () => { await vi.advanceTimersByTimeAsync(600) })

    expect(window.fetch).toHaveBeenCalledWith(
      '/preferences/theme-mode',
      expect.objectContaining({
        method: 'PUT',
        body: JSON.stringify({ value: 'dark' }),
      }),
    )
  })
})