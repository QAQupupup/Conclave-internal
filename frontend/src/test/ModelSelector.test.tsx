import { render, screen, waitFor } from '@testing-library/react'
import { vi, describe, it, expect, beforeEach } from 'vitest'
import { ModelSelector } from '../components/ModelSelector.tsx'

const listLLMProviders = vi.fn()
const listLLMModels = vi.fn()
const getLLMBalance = vi.fn()

vi.mock('../lib/api.ts', async () => {
  const actual = await vi.importActual<typeof import('../lib/api.ts')>('../lib/api.ts')
  return {
    ...actual,
    listLLMProviders: () => listLLMProviders(),
    listLLMModels: (params: Parameters<typeof actual.listLLMModels>[0]) => listLLMModels(params),
    getLLMBalance: (params: Parameters<typeof actual.getLLMBalance>[0]) => getLLMBalance(params),
  }
})

vi.mock('../lib/llmPreferences.ts', () => ({
  getApiKey: () => '',
  setApiKey: vi.fn(),
  getDefaultSelection: () => ({
    provider_id: 'siliconflow',
    model: 'Qwen/Qwen3-8B',
    api_key: '',
    base_url: '',
  }),
  loadPreferences: () => ({
    version: 1,
    default_provider_id: 'siliconflow',
    default_model: 'Qwen/Qwen3-8B',
    api_keys: {},
    custom_base_url: '',
    auto_save_model: false,
  }),
  setDefaultSelection: vi.fn(),
}))

describe('ModelSelector', () => {
  beforeEach(() => {
    listLLMProviders.mockReset()
    listLLMModels.mockReset()
    getLLMBalance.mockReset()
  })

  const defaultProviders = [
    {
      id: 'siliconflow',
      name: 'SiliconFlow',
      base_url: 'https://api.siliconflow.cn',
      has_key: true,
      supports_balance: true,
      supports_custom_key: true,
      supports_models_list: true,
      pricing_note: '',
    },
    {
      id: 'custom',
      name: 'Custom',
      base_url: '',
      has_key: false,
      supports_balance: false,
      supports_custom_key: true,
      supports_models_list: true,
      pricing_note: '',
    },
  ]

  it('always renders API key input when a provider is selected', async () => {
    listLLMProviders.mockResolvedValueOnce({ providers: defaultProviders })
    listLLMModels.mockResolvedValueOnce({
      models: [],
      categories: {},
      recommended: [],
      total: 0,
    })
    getLLMBalance.mockResolvedValueOnce({
      balance: null,
      currency: 'CNY',
      provider: 'siliconflow',
      supported: false,
    })

    render(<ModelSelector />)

    await waitFor(() => expect(screen.getByTestId('api-key-input')).toBeInTheDocument())
    expect(screen.getByTestId('api-key-input')).not.toBeDisabled()
  })

  it('disables API key input when disabled prop is true', async () => {
    listLLMProviders.mockResolvedValueOnce({ providers: defaultProviders })
    listLLMModels.mockResolvedValueOnce({
      models: [],
      categories: {},
      recommended: [],
      total: 0,
    })

    render(<ModelSelector disabled />)

    await waitFor(() => expect(screen.getByTestId('api-key-input')).toBeInTheDocument())
    expect(screen.getByTestId('api-key-input')).toBeDisabled()
  })

  it('disables API key input when provider does not support custom key', async () => {
    listLLMProviders.mockResolvedValueOnce({
      providers: [
        {
          id: 'system',
          name: 'System',
          base_url: '',
          has_key: true,
          supports_balance: false,
          supports_custom_key: false,
          supports_models_list: true,
          pricing_note: '',
        },
      ],
    })
    listLLMModels.mockResolvedValueOnce({
      models: [],
      categories: {},
      recommended: [],
      total: 0,
    })

    render(
      <ModelSelector
        value={{
          provider_id: 'system',
          model: '',
          api_key: '',
          base_url: '',
        }}
      />
    )

    await waitFor(() => expect(screen.getByTestId('api-key-input')).toBeInTheDocument())
    expect(screen.getByTestId('api-key-input')).toBeDisabled()
  })
})
