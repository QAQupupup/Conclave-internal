import { render, screen, fireEvent, act } from '@testing-library/react'
import { vi, describe, it, expect, afterEach } from 'vitest'
import { GuardButton } from '../components/GuardButton.tsx'

vi.mock('../components/CaptchaGuard.tsx', () => ({
  CaptchaGuard: () => <div data-testid="captcha-guard-mock">Guard</div>,
}))

describe('GuardButton', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('renders nothing on landing page', () => {
    const { container } = render(<GuardButton path="/" />)
    expect(container.firstChild).toBeNull()
  })

  it('renders a light-blue shield on the right side', () => {
    render(<GuardButton path="/board" />)

    const button = screen.getByTestId('guard-button')
    const shield = screen.getByTestId('guard-shield')

    expect(button).toBeInTheDocument()
    expect(button).toHaveClass('guard-button')
    expect(shield).toHaveStyle({
      background: '#f0f7ff',
      color: '#1677ff',
    })
  })

  it('expands on hover and collapses on mouse leave', () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })

    render(<GuardButton path="/board" />)

    const button = screen.getByTestId('guard-button')
    expect(button).toHaveStyle({ width: '32px' })
    expect(screen.getByTestId('guard-panel')).toHaveStyle({ opacity: '0' })

    fireEvent.mouseEnter(button)

    expect(button).toHaveStyle({ width: '260px' })
    expect(screen.getByTestId('guard-panel')).toHaveStyle({ opacity: '1' })

    fireEvent.mouseLeave(button)
    act(() => { vi.advanceTimersByTime(900) })

    expect(button).toHaveStyle({ width: '32px' })
    expect(screen.getByTestId('guard-panel')).toHaveStyle({ opacity: '0' })
  })
})
