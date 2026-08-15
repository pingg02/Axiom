import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3
  static instances: MockWebSocket[] = []

  readonly url: string
  readyState = MockWebSocket.CONNECTING
  sent: string[] = []
  onopen: ((event: Event) => void) | null = null
  onmessage: ((event: MessageEvent<string>) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor(url: string | URL) {
    this.url = String(url)
    MockWebSocket.instances.push(this)
  }

  open() {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.(new Event('open'))
  }

  receive(payload: unknown) {
    this.onmessage?.(new MessageEvent('message', { data: JSON.stringify(payload) }))
  }

  send(data: string) {
    this.sent.push(String(data))
  }

  close() {
    this.readyState = MockWebSocket.CLOSED
  }
}

function socket() {
  const instance = MockWebSocket.instances.at(-1)
  if (!instance) throw new Error('Axiom did not create its desktop WebSocket')
  return instance
}

function messages(instance: MockWebSocket) {
  return instance.sent.map(item => JSON.parse(item))
}

beforeEach(() => {
  MockWebSocket.instances = []
  vi.stubGlobal('WebSocket', MockWebSocket)
  Reflect.deleteProperty(window, 'reasonix')
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('Axiom desktop interaction contracts', () => {
  it('shows first-run provider setup and sends the API key only through desktop IPC', async () => {
    const user = userEvent.setup()
    const saveProviderSetup = vi.fn().mockResolvedValue({
      configured: true,
      managed: true,
      encryptionAvailable: true,
      selected: {
        providerId: 'deepseek',
        label: 'DeepSeek',
        model: 'deepseek-chat',
        baseUrl: 'https://api.deepseek.com',
      },
      presets: [],
    })
    window.reasonix = {
      platform: 'win32',
      version: '0.2.0',
      getProviderSetup: vi.fn().mockResolvedValue({
        configured: false,
        managed: false,
        encryptionAvailable: true,
        selected: null,
        presets: [{
          id: 'deepseek',
          label: 'DeepSeek',
          defaultModel: 'deepseek-chat',
          defaultBaseUrl: 'https://api.deepseek.com',
        }],
      }),
      saveProviderSetup,
    }
    render(<App />)

    expect(await screen.findByRole('dialog', { name: '配置模型供应商' })).toBeVisible()
    await user.type(screen.getByLabelText('API Key'), 'test-key-not-a-real-credential')
    await user.click(screen.getByRole('button', { name: '安全保存并连接' }))

    expect(saveProviderSetup).toHaveBeenCalledWith({
      providerId: 'deepseek',
      apiKey: 'test-key-not-a-real-credential',
      model: 'deepseek-chat',
      baseUrl: 'https://api.deepseek.com',
    })
  })

  it('still opens provider setup when only external configuration is detected', async () => {
    window.reasonix = {
      platform: 'win32',
      version: '0.2.0',
      getProviderSetup: vi.fn().mockResolvedValue({
        configured: true,
        managed: false,
        needsSetup: true,
        externalConfigured: true,
        encryptionAvailable: true,
        selected: null,
        presets: [{
          id: 'deepseek',
          label: 'DeepSeek',
          defaultModel: 'deepseek-chat',
          defaultBaseUrl: 'https://api.deepseek.com',
        }],
      }),
      saveProviderSetup: vi.fn(),
    }

    render(<App />)

    expect(await screen.findByRole('dialog')).toBeVisible()
  })

  it('supports Anthropic-compatible provider presets in first-run setup', async () => {
    const user = userEvent.setup()
    const saveProviderSetup = vi.fn().mockResolvedValue({
      configured: true,
      managed: true,
      encryptionAvailable: true,
      selected: {
        providerId: 'anthropic_compatible',
        label: 'Anthropic Compatible',
        format: 'Anthropic',
        model: 'custom-claude',
        baseUrl: 'https://api.example.com/anthropic',
      },
      presets: [],
    })
    window.reasonix = {
      platform: 'win32',
      version: '0.2.0',
      getProviderSetup: vi.fn().mockResolvedValue({
        configured: false,
        managed: false,
        encryptionAvailable: true,
        selected: null,
        presets: [{
          id: 'compatible',
          label: 'OpenAI Compatible',
          format: 'OpenAI',
          defaultModel: '',
          defaultBaseUrl: '',
        }, {
          id: 'anthropic_compatible',
          label: 'Anthropic Compatible',
          format: 'Anthropic',
          defaultModel: '',
          defaultBaseUrl: '',
        }],
      }),
      saveProviderSetup,
    }
    render(<App />)

    await user.click(await screen.findByRole('button', { name: /Anthropic Compatible/ }))
    expect(screen.getByText('Anthropic')).toBeVisible()
    await user.type(screen.getByLabelText('API Key'), 'test-key-not-a-real-credential')
    await user.type(screen.getByLabelText('模型 ID'), 'custom-claude')
    await user.type(screen.getByLabelText('API 地址（可选）'), 'https://api.example.com/anthropic')
    await user.click(screen.getByRole('button', { name: '安全保存并连接' }))

    expect(saveProviderSetup).toHaveBeenCalledWith({
      providerId: 'anthropic_compatible',
      apiKey: 'test-key-not-a-real-credential',
      model: 'custom-claude',
      baseUrl: 'https://api.example.com/anthropic',
    })
  })

  it('offers provider setup when the selected provider is too busy', async () => {
    const getProviderSetup = vi.fn().mockResolvedValue({
      configured: true,
      managed: true,
      needsSetup: false,
      externalConfigured: false,
      encryptionAvailable: true,
      selected: {
        providerId: 'deepseek',
        label: 'DeepSeek',
        model: 'deepseek-chat',
        baseUrl: 'https://api.deepseek.com',
      },
      presets: [{
        id: 'deepseek',
        label: 'DeepSeek',
        defaultModel: 'deepseek-chat',
        defaultBaseUrl: 'https://api.deepseek.com',
      }],
    })
    window.reasonix = {
      platform: 'win32',
      version: '0.2.0',
      getProviderSetup,
      saveProviderSetup: vi.fn(),
    }
    render(<App />)
    act(() => socket().open())

    act(() => socket().receive({
      kind: 'error',
      error: "Error code: 503 - {'error': {'message': 'Service is too busy.', 'code': 'service_unavailable_error'}}",
    }))

    expect(await screen.findByText(/503\/service_unavailable/)).toBeVisible()
    expect(await screen.findByRole('dialog')).toBeVisible()
    expect(getProviderSetup).toHaveBeenCalledTimes(2)
  })
  it('renders an approval request and sends Allow with the exact request id', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    act(() => socket().open())
    // The bridge requires the per-launch token as the first message. In the
    // test (no Electron IPC bridge) the token is empty, which the dev-mode
    // backend accepts.
    await waitFor(() =>
      expect(messages(socket())).toContainEqual({ action: 'auth', token: '' }),
    )

    act(() => socket().receive({
      kind: 'approval_request',
      approval: {
        id: 'approval-1',
        tool_name: 'write_file',
        subject: 'E:\\workspace\\safe.txt',
        args_json: '{"path":"safe.txt"}',
      },
    }))

    expect(await screen.findByRole('region', { name: '待处理审批' })).toBeVisible()
    const allow = container.querySelector<HTMLButtonElement>('.axiom-composer .is-allow')
    expect(allow).not.toBeNull()
    expect(allow?.closest('.axiom-approval-dock')).not.toBeNull()
    await user.click(allow!)

    expect(messages(socket())).toContainEqual({
      action: 'approve',
      request_id: 'approval-1',
      allow: true,
      scope: 'once',
    })
    expect(container.querySelector('.is-allow')).toBeNull()
  })

  it('approves every pending operation with one session-scoped action', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    act(() => socket().open())
    for (const [id, path] of [['approval-1', 'one.txt'], ['approval-2', 'two.txt']]) {
      act(() => socket().receive({
        kind: 'approval_request',
        approval: {
          id,
          tool_name: 'write_file',
          subject: `E:\\workspace\\${path}`,
          args_json: JSON.stringify({ path }),
        },
      }))
    }

    const approveAll = container.querySelector<HTMLButtonElement>('.is-session-all')
    expect(approveAll).not.toBeNull()
    await user.click(approveAll!)
    expect(messages(socket())).toContainEqual({
      action: 'approve_all',
      allow: true,
      scope: 'session',
    })
    expect(screen.queryByRole('button', { name: '全部拒绝' })).not.toBeInTheDocument()
  })

  it('can approve the current request and auto-approve later tools for this session', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    act(() => socket().open())
    act(() => socket().receive({
      kind: 'approval_request',
      approval: {
        id: 'approval-auto',
        tool_name: 'bash',
        subject: 'npm run build',
        args_json: '{"command":"npm run build"}',
      },
    }))

    const autoApprove = container.querySelector<HTMLButtonElement>('.axiom-approval-actions .is-auto-all')
    expect(autoApprove).not.toBeNull()
    await user.click(autoApprove!)

    expect(messages(socket())).toContainEqual({
      action: 'approve_all',
      allow: true,
      scope: 'once',
      future_mode: 'allow',
    })
    expect(container.querySelector('.axiom-approval-actions .is-auto-all')).toBeNull()
  })

  it('keeps answers for multiple Ask questions and sends them in order', async () => {
    const user = userEvent.setup()
    const { container } = render(<App />)
    act(() => socket().open())
    act(() => socket().receive({
      kind: 'ask_request',
      ask_id: 'ask-1',
      text: 'Choose execution preferences',
      ask_questions: [
        { header: 'Mode', question: 'Choose mode', options: ['Plan', 'Act'] },
        { header: 'Safety', question: 'Choose safety', options: ['Safe', 'Fast'] },
      ],
    }))

    await user.click(await screen.findByRole('button', { name: /Plan/ }))
    await user.click(screen.getByRole('button', { name: /Safe/ }))
    const submit = container.querySelector<HTMLButtonElement>('.axiom-submit-answer')
    expect(submit).not.toBeNull()
    expect(submit).toBeEnabled()
    await user.click(submit!)

    expect(messages(socket())).toContainEqual({
      action: 'answer_ask',
      ask_id: 'ask-1',
      answers: ['Plan', 'Safe'],
    })
  })

  it('updates one tool card by id when the result arrives', async () => {
    const { container } = render(<App />)
    act(() => socket().open())
    act(() => socket().receive({
      kind: 'tool_dispatch',
      tool: { id: 'tool-1', name: 'bash', args_json: '{"command":"echo ok"}' },
    }))
    act(() => socket().receive({
      kind: 'tool_result',
      tool: {
        id: 'tool-1',
        name: 'bash',
        args_json: '{"command":"echo ok"}',
        output: 'completed-output',
      },
    }))

    await waitFor(() => {
      expect(screen.getByText('completed-output', { exact: false })).toBeVisible()
    })
    expect(container.querySelectorAll('.axiom-message.is-tool')).toHaveLength(1)
  })

  it('runs slash commands from the conversation composer', async () => {
    const user = userEvent.setup()
    render(<App />)
    act(() => socket().open())

    const composer = screen.getByRole('textbox')
    await user.type(composer, '/ask{Enter}')

    expect(messages(socket())).toContainEqual({
      action: 'set_permission_mode',
      mode: 'ask',
    })
    expect(await screen.findByText('本会话审批模式已切换为 ASK。')).toBeVisible()
  })

  it('searches and inserts workspace references after typing @', async () => {
    const user = userEvent.setup()
    render(<App />)
    act(() => socket().open())

    const composer = screen.getByRole('textbox')
    await user.type(composer, '@comp')
    await waitFor(() => {
      expect(messages(socket())).toContainEqual({
        action: 'search_workspace',
        query: 'comp',
      })
    })

    act(() => socket().receive({
      kind: 'workspace_suggestions',
      query: 'comp',
      workspace_suggestions: [{
        path: 'src/components/Composer.tsx',
        name: 'Composer.tsx',
        is_dir: false,
      }],
    }))
    await user.click(await screen.findByRole('option', { name: /Composer\.tsx/ }))

    expect(composer).toHaveValue('@[src/components/Composer.tsx](src/components/Composer.tsx) ')
  })
})
