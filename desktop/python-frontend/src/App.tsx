import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import './App.css'
import {
  BUILTIN_COMPOSER_COMMANDS,
  Composer,
  type ComposerCommand,
} from './components/Composer'
import { ToolsModule, ToolTimeline } from './components/ToolsPanel'
import { WorkflowModule } from './components/WorkflowModule'
import type {
  ApprovalScope,
  AskQuestionView,
  DesktopStatus,
  Message,
  ModuleKey,
  PermissionMode,
  ProviderSetupStatus,
  SkillInfo,
  StreamEvent,
  ToolEvent,
  ToolRun,
  UsageInfo,
  WorkspaceSuggestion,
} from './protocol'

const params = new URLSearchParams(location.search)
const WS_HOST = location.hostname || '127.0.0.1'
const WS_PORT = params.get('wsPort') || '9092'
const WORKSPACE_HINT = params.get('workspace') || ''
const WS_URL = `ws://${WS_HOST}:${WS_PORT}`
const nowId = () => `${Date.now()}-${Math.random().toString(16).slice(2)}`

const modules: Array<{ key: ModuleKey; label: string; hint: string; icon: string }> = [
  { key: 'chat', label: '对话', hint: '执行与推理', icon: '◫' },
  { key: 'tools', label: '工具', hint: '调用与结果', icon: '⌁' },
  { key: 'workspace', label: '工作区', hint: '项目上下文', icon: '◇' },
  { key: 'sessions', label: '会话', hint: '状态与恢复', icon: '◎' },
  { key: 'settings', label: '设置', hint: '模型与权限', icon: '⊙' },
  { key: 'diagnostics', label: '诊断', hint: '连接与 MCP', icon: '⌁' },
]

modules.splice(4, 0, { key: 'workflows', label: '工作流', hint: '保存与执行', icon: '⇢' })

const quickPrompts = [
  '审查当前项目，按严重程度列出缺陷并修复高优先级问题',
  '检查打包链路，定位 exe 启动失败或白屏的原因',
  '检查前后端工具协议，修复调用工具后会话中断的问题',
]

function compactPath(path: string) {
  if (!path) return '尚未确认'
  return path.length > 52 ? `…${path.slice(-49)}` : path
}

function summarizeArgs(args: string) {
  try {
    const parsed = JSON.parse(args || '{}') as Record<string, unknown>
    const value = parsed.path || parsed.pattern || parsed.command || parsed.url || parsed.file_path
    return typeof value === 'string' && value ? value : JSON.stringify(parsed)
  } catch {
    return args
  }
}

function shouldOpenProviderSetup(status: ProviderSetupStatus) {
  return status.needsSetup ?? !status.configured
}

function isProviderServiceUnavailable(message: string) {
  const folded = message.toLowerCase()
  return folded.includes('503')
    || folded.includes('service_unavailable')
    || folded.includes('too busy')
    || folded.includes('temporarily switch')
}

function explainProviderError(message: string) {
  if (!isProviderServiceUnavailable(message)) return message
  return [
    '模型服务商当前返回 503/service_unavailable，表示对方服务太忙。',
    '可以稍后重试，也可以在弹出的服务商设置里切换到其他 API 服务商、模型或兼容接口地址。',
    '',
    `原始错误：${message}`,
  ].join('\n')
}

function App() {
  const [activeModule, setActiveModule] = useState<ModuleKey>('chat')
  const [messages, setMessages] = useState<Message[]>([{
    id: nowId(),
    role: 'assistant',
    text: '你好，我是 Axiom。审批、提问和工具执行都会留在当前对话中，你可以随时允许、拒绝或停止任务。',
  }])
  const [input, setInput] = useState('')
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(false)
  const [phase, setPhase] = useState('idle')
  const [status, setStatus] = useState<DesktopStatus | null>(null)
  const [usage, setUsage] = useState<UsageInfo | null>(null)
  const [toolRuns, setToolRuns] = useState<ToolRun[]>([])
  const [connectionError, setConnectionError] = useState('')
  const [providerSetup, setProviderSetup] = useState<ProviderSetupStatus | null>(null)
  const [providerSetupOpen, setProviderSetupOpen] = useState(false)
  const [workspaceSearch, setWorkspaceSearch] = useState<{
    query: string
    items: WorkspaceSuggestion[]
  }>({ query: '', items: [] })
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectAttemptRef = useRef(0)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const activeSessionRef = useRef('')

  const refreshProviderSetup = useCallback(async (open = false) => {
    if (!window.reasonix?.getProviderSetup) return
    try {
      const next = await window.reasonix.getProviderSetup()
      setProviderSetup(next)
      if (open || shouldOpenProviderSetup(next)) setProviderSetupOpen(true)
    } catch (error) {
      setConnectionError(`无法读取供应商配置：${String(error)}`)
    }
  }, [])

  useEffect(() => {
    void refreshProviderSetup()
  }, [refreshProviderSetup])

  useEffect(() => {
    if (status?.provider && !status.provider.configured) {
      setProviderSetupOpen(true)
    }
  }, [status?.provider?.configured])

  const workspace = status?.workspace || WORKSPACE_HINT
  const activeTools = toolRuns.filter(tool => tool.status === 'running').length
  const failedTools = toolRuns.filter(tool => tool.status === 'error').length
  const pendingApprovals = messages.filter(
    message => (message.role === 'approval' || message.role === 'ask') && !message.resolved,
  ).length
  const groupedTools = useMemo(() => {
    const tools = status?.tools || []
    return {
      read: tools.filter(tool => tool.read_only),
      write: tools.filter(tool => !tool.read_only),
      mcp: tools.filter(tool => tool.source === 'mcp'),
    }
  }, [status])

  const addMessage = useCallback((message: Omit<Message, 'id'>) => {
    setMessages(previous => [...previous, { id: nowId(), ...message }])
  }, [])

  const upsertToolRun = useCallback((tool: ToolEvent, nextStatus: ToolRun['status']) => {
    setToolRuns(previous => {
      const id = tool.id || `${tool.name}-${Date.now()}`
      const index = previous.findIndex(
        run => run.id === id || (!tool.id && run.name === tool.name && run.status === 'running'),
      )
      const run: ToolRun = {
        id,
        name: tool.name,
        args_json: tool.args_json || '',
        read_only: Boolean(tool.read_only),
        status: nextStatus,
        output: tool.output || '',
        error: tool.error || '',
        truncated: Boolean(tool.truncated),
        change: tool.change || (index >= 0 ? previous[index].change : undefined),
        startedAt: index >= 0 ? previous[index].startedAt : Date.now(),
        finishedAt: nextStatus === 'running' ? undefined : Date.now(),
      }
      if (index < 0) return [run, ...previous]
      const copy = [...previous]
      copy[index] = { ...copy[index], ...run }
      return copy
    })
  }, [])

  const updateToolMessage = useCallback((tool: ToolEvent, nextStatus: ToolRun['status']) => {
    const toolId = tool.id || `${tool.name}-${Date.now()}`
    const statusLabel = nextStatus === 'running' ? '运行中' : nextStatus === 'error' ? '失败' : '完成'
    const body = [
      summarizeArgs(tool.args_json || ''),
      tool.error ? `错误：${tool.error}` : '',
      tool.output ? tool.output.slice(0, 1600) : '',
      tool.truncated ? '（输出已截断）' : '',
    ].filter(Boolean).join('\n')
    setMessages(previous => {
      const index = previous.findIndex(
        message => message.toolId === toolId
          || (!tool.id && message.toolName === tool.name && message.role === 'tool'),
      )
      const text = `${tool.name} · ${statusLabel}${body ? `\n${body}` : ''}`
      if (index < 0) {
        return [...previous, { id: nowId(), role: 'tool', toolName: tool.name, toolId, text }]
      }
      const copy = [...previous]
      copy[index] = { ...copy[index], text, toolId, toolName: tool.name }
      return copy
    })
  }, [])

  const connect = useCallback(() => {
    const current = wsRef.current
    if (current && (
      current.readyState === WebSocket.OPEN || current.readyState === WebSocket.CONNECTING
    )) return
    const websocket = new WebSocket(WS_URL)
    wsRef.current = websocket
    setConnectionError('')

    websocket.onopen = () => {
      reconnectAttemptRef.current = 0
      setConnected(true)
      setPhase('syncing')
      setConnectionError('')
      websocket.send(JSON.stringify({ action: 'status' }))
    }
    websocket.onmessage = event => {
      try {
        const data: StreamEvent = JSON.parse(event.data)
        if (data.kind === 'workspace_suggestions') {
          setWorkspaceSearch({
            query: data.query || '',
            items: data.workspace_suggestions || [],
          })
          return
        }
        if (data.kind === 'status' && data.status) {
          setStatus(data.status)
          setPhase(data.status.session_state || 'idle')
          if (data.status.session_id !== activeSessionRef.current) {
            activeSessionRef.current = data.status.session_id
            const restored: Message[] = (data.status.session_messages || []).map(message => ({
              id: message.id,
              role: message.role,
              text: message.text,
              toolName: message.tool_name,
            }))
            if (data.status.recovery_prompt) {
              restored.push({
                id: `recovery-${data.status.session_id}`,
                role: 'notice',
                text: `检测到上次未完成的任务：${data.status.recovery_prompt}\n为避免重复执行写操作，Axiom 不会自动重放；你可以检查后重新发送。`,
              })
            }
            setMessages(restored.length ? restored : [{
              id: nowId(),
              role: 'assistant',
              text: '新会话已创建。历史会话会持久保存在本机，可以从“会话”模块恢复。',
            }])
          }
          return
        }
        if (data.kind === 'turn_started') {
          setLoading(true)
          setPhase('running')
        } else if (data.kind === 'phase') {
          setPhase(data.text || data.phase_label || 'model')
        } else if (data.kind === 'text' && data.text) {
          setMessages(previous => {
            const last = previous[previous.length - 1]
            if (last?.role === 'assistant' && !last.toolName) {
              const copy = [...previous]
              copy[copy.length - 1] = { ...last, text: last.text + data.text }
              return copy
            }
            return [...previous, { id: nowId(), role: 'assistant', text: data.text }]
          })
        } else if (data.kind === 'message' && data.text) {
          setMessages(previous => {
            const last = previous[previous.length - 1]
            if (last?.role === 'assistant' && last.text === data.text) return previous
            return [...previous, { id: nowId(), role: 'assistant', text: data.text }]
          })
        } else if (data.kind === 'reasoning') {
          setPhase('reasoning')
        } else if (data.kind === 'error') {
          const rawError = data.error || data.text || '发生未知错误'
          if (isProviderServiceUnavailable(rawError)) void refreshProviderSetup(true)
          addMessage({ role: 'error', text: explainProviderError(rawError) })
        } else if (data.kind === 'tool_dispatch' && data.tool) {
          upsertToolRun(data.tool, 'running')
          updateToolMessage(data.tool, 'running')
        } else if (data.kind === 'tool_result' && data.tool) {
          const nextStatus = data.tool.error ? 'error' : 'success'
          upsertToolRun(data.tool, nextStatus)
          updateToolMessage(data.tool, nextStatus)
        } else if (data.kind === 'usage' && data.usage) {
          setUsage(data.usage)
        } else if (data.kind === 'notice') {
          addMessage({ role: 'notice', text: data.text || data.level || '通知' })
        } else if (data.kind === 'approval_request' && data.approval) {
          addMessage({
            role: 'approval',
            text: `${data.approval.tool_name}\n${data.approval.subject}\n${data.approval.args_json}`,
            approvalId: data.approval.id,
          })
        } else if (data.kind === 'ask_request') {
          addMessage({
            role: 'ask',
            text: data.text || 'Axiom 需要你的选择才能继续。',
            askId: data.ask_id,
            askQuestions: data.ask_questions || [],
          })
        } else if (data.kind === 'turn_done') {
          setLoading(false)
          setPhase('idle')
          websocket.send(JSON.stringify({ action: 'status' }))
        }
      } catch (error) {
        addMessage({ role: 'error', text: `无法解析桌面事件：${String(error)}` })
      }
    }
    websocket.onclose = () => {
      if (wsRef.current === websocket) wsRef.current = null
      reconnectAttemptRef.current += 1
      setConnected(false)
      setLoading(false)
      setPhase('offline')
      setConnectionError(`桌面桥已断开，正在进行第 ${reconnectAttemptRef.current} 次重连。`)
    }
    websocket.onerror = () => {
      setConnectionError(`无法连接 ${WS_URL}。请查看 Axiom 桌面日志或确认后端已启动。`)
    }
  }, [addMessage, refreshProviderSetup, updateToolMessage, upsertToolRun])

  useEffect(() => {
    connect()
    const timer = window.setInterval(() => {
      if (!wsRef.current || wsRef.current.readyState === WebSocket.CLOSED) connect()
    }, 1400)
    return () => {
      window.clearInterval(timer)
      wsRef.current?.close()
    }
  }, [connect])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const sendMessage = useCallback((override?: string) => {
    const text = (override ?? input).trim()
    const websocket = wsRef.current
    if (status?.provider && !status.provider.configured) {
      setProviderSetupOpen(true)
      return
    }
    if (!text || !websocket || websocket.readyState !== WebSocket.OPEN) {
      if (!connected) setConnectionError(`尚未连接桌面桥：${WS_URL}`)
      return
    }
    websocket.send(JSON.stringify({ action: 'send', text }))
    setMessages(previous => [
      ...previous,
      { id: nowId(), role: 'user', text },
      { id: nowId(), role: 'assistant', text: '' },
    ])
    setInput('')
    setLoading(true)
    setPhase('queued')
    setActiveModule('chat')
  }, [connected, input, status?.provider])

  const cancelTurn = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: 'cancel' }))
    setPhase('cancelling')
  }, [])

  const sendApproval = useCallback((request_id: string, allow: boolean, scope: ApprovalScope = 'once') => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({ action: 'approve', request_id, allow, scope }))
    setMessages(previous => previous.map(message => (
      message.approvalId === request_id
        ? { ...message, resolved: true, resolution: allow ? '已允许' : '已拒绝' }
        : message
    )))
  }, [])

  const sendApprovalAll = useCallback((allow: boolean, scope: ApprovalScope = 'once') => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({ action: 'approve_all', allow, scope }))
    setMessages(previous => previous.map(message => (
      message.role === 'approval' && !message.resolved
        ? {
            ...message,
            resolved: true,
            resolution: allow
              ? scope === 'session' ? '已批量允许同类操作（本会话）' : '已批量允许'
              : '已批量拒绝',
          }
        : message
    )))
  }, [])

  const enableSessionAutoApprove = useCallback(() => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({
      action: 'approve_all',
      allow: true,
      scope: 'once',
      future_mode: 'allow',
    }))
    setStatus(previous => previous ? { ...previous, permission_mode: 'allow' } : previous)
    setMessages(previous => previous.map(message => (
      message.role === 'approval' && !message.resolved
        ? { ...message, resolved: true, resolution: '已允许，并启用本会话自动批准' }
        : message
    )))
  }, [])

  const setPermissionMode = useCallback((mode: PermissionMode) => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({ action: 'set_permission_mode', mode }))
    setStatus(previous => previous ? { ...previous, permission_mode: mode } : previous)
  }, [])

  const sendAskAnswer = useCallback((ask_id: string, answers: string[]) => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({ action: 'answer_ask', ask_id, answers }))
    setMessages(previous => previous.map(message => (
      message.askId === ask_id
        ? { ...message, resolved: true, resolution: `已回答：${answers.join('；')}` }
        : message
    )))
  }, [])

  const startNewSession = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: 'new_session' }))
    setMessages([{
      id: nowId(),
      role: 'assistant',
      text: '新会话已创建。工具运行记录仍保留在右侧，便于诊断。',
    }])
    setLoading(false)
    setPhase('idle')
    setActiveModule('chat')
  }, [])

  const resumeSession = useCallback((sessionId: string) => {
    wsRef.current?.send(JSON.stringify({ action: 'resume_session', session_id: sessionId }))
    setLoading(false)
    setPhase('restoring')
    setActiveModule('chat')
  }, [])

  const deleteSession = useCallback((sessionId: string) => {
    wsRef.current?.send(JSON.stringify({ action: 'delete_session', session_id: sessionId }))
  }, [])

  const undoLastTurn = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: 'undo_last_turn' }))
  }, [])

  const saveWorkflow = useCallback((name: string, steps: string[]) => {
    wsRef.current?.send(JSON.stringify({ action: 'save_workflow', name, steps }))
  }, [])

  const runWorkflow = useCallback((workflowId: string) => {
    wsRef.current?.send(JSON.stringify({ action: 'run_workflow', workflow_id: workflowId }))
  }, [])

  const deleteWorkflow = useCallback((workflowId: string) => {
    wsRef.current?.send(JSON.stringify({ action: 'delete_workflow', workflow_id: workflowId }))
  }, [])

  const cancelWorkflow = useCallback(() => {
    wsRef.current?.send(JSON.stringify({ action: 'cancel_workflow' }))
  }, [])

  const searchWorkspace = useCallback((query: string) => {
    const websocket = wsRef.current
    if (!websocket || websocket.readyState !== WebSocket.OPEN) return
    websocket.send(JSON.stringify({ action: 'search_workspace', query }))
  }, [])

  const handleComposerCommand = useCallback((
    command: ComposerCommand | null,
    args: string,
    rawName: string,
  ) => {
    setInput('')
    if (!command) {
      addMessage({
        role: 'notice',
        text: `未知命令 /${rawName}。输入 /help 或只输入 / 查看可用命令。`,
      })
      return
    }
    if (command.kind === 'skill') {
      sendMessage([
        `请使用 Skill “${command.value || command.name}”完成以下任务。`,
        args || '先读取该 Skill 的说明，再根据当前项目给出适用的执行建议。',
      ].join('\n'))
      return
    }
    if (command.name === 'review') {
      sendMessage(`审查当前项目，按严重程度列出问题并修复高优先级缺陷。${args ? `重点范围：${args}` : ''}`)
      return
    }
    if (command.name === 'fix') {
      sendMessage(`定位并修复当前问题，完成后运行相关测试验证。${args ? `问题：${args}` : ''}`)
      return
    }
    if (command.name === 'test') {
      sendMessage(`运行与当前项目匹配的测试，分析失败原因并给出修复建议。${args ? `测试范围：${args}` : ''}`)
      return
    }
    if (command.name === 'new') {
      startNewSession()
      return
    }
    if (command.name === 'undo') {
      undoLastTurn()
      return
    }
    if (command.name === 'ask' || command.name === 'allow' || command.name === 'deny') {
      setPermissionMode(command.name as PermissionMode)
      addMessage({
        role: 'notice',
        text: `本会话审批模式已切换为 ${command.name.toUpperCase()}。`,
      })
      return
    }
    const navigation: Partial<Record<string, ModuleKey>> = {
      tools: 'tools',
      sessions: 'sessions',
      workflows: 'workflows',
      settings: 'settings',
      status: 'diagnostics',
      mcp: 'diagnostics',
      skills: 'diagnostics',
    }
    const destination = navigation[command.name]
    if (destination) {
      setActiveModule(destination)
      return
    }
    if (command.name === 'help') {
      addMessage({
        role: 'notice',
        text: [
          '输入命令：',
          ...BUILTIN_COMPOSER_COMMANDS.map(item => `/${item.name}${item.argumentHint ? ` ${item.argumentHint}` : ''} — ${item.description}`),
          '',
          '@文件名 — 搜索并引用工作区文件；↑/↓ 选择，Tab 补全，Esc 关闭菜单。',
        ].join('\n'),
      })
    }
  }, [addMessage, sendMessage, setPermissionMode, startNewSession, undoLastTurn])

  const totalTokens = (usage?.input_tokens || 0) + (usage?.output_tokens || 0)
  const activeMeta = modules.find(module => module.key === activeModule)

  return (
    <div className="axiom-shell">
      <aside className="axiom-sidebar">
        <div className="axiom-brand">
          <div className="axiom-mark"><span>AX</span></div>
          <div><div className="axiom-brand-name">Axiom</div><div className="axiom-brand-sub">Agentic workbench</div></div>
        </div>
        <button className="axiom-new-task" onClick={startNewSession}><span>＋</span> 新建任务</button>
        <nav className="axiom-nav">
          {modules.map(module => (
            <button
              key={module.key}
              className={activeModule === module.key ? 'is-active' : ''}
              onClick={() => setActiveModule(module.key)}
            >
              <span className="axiom-nav-icon">{module.icon}</span>
              <span><strong>{module.label}</strong><small>{module.hint}</small></span>
              {module.key === 'tools' && activeTools > 0 && <i>{activeTools}</i>}
              {module.key === 'chat' && pendingApprovals > 0 && <i>{pendingApprovals}</i>}
            </button>
          ))}
        </nav>
        <div className="axiom-project">
          <div className="axiom-project-top"><span>当前项目</span><em>{connected ? '在线' : '离线'}</em></div>
          <strong title={workspace}>{compactPath(workspace)}</strong>
          <div className="axiom-project-stats"><span>{status?.tool_count || 0} tools</span><span>{groupedTools.mcp.length} MCP</span></div>
        </div>
      </aside>

      <main className="axiom-main">
        <header className="axiom-topbar">
          <div>
            <div className="axiom-kicker">AXIOM / {activeMeta?.label.toUpperCase()}</div>
            <h1>{activeMeta?.label}</h1>
            <p>{activeMeta?.hint} · {compactPath(workspace)}</p>
          </div>
          <div className="axiom-runtime">
            <span className={`axiom-live ${connected ? 'is-online' : ''}`} />
            <div><strong>{connected ? '桌面桥已连接' : '桌面桥离线'}</strong><small>{phase} · 端口 {WS_PORT}</small></div>
          </div>
        </header>

        {connectionError && <div className="axiom-alert"><span>{connectionError}</span><button onClick={connect}>立即重连</button></div>}

        <section className="axiom-metrics">
          <Metric label="会话状态" value={status?.session_state || 'waiting'} note={status?.session_id?.slice(0, 8) || '未建立'} />
          <Metric label="工具" value={String(status?.tool_count || 0)} note={`${groupedTools.read.length} 只读 · ${groupedTools.write.length} 需审批`} />
          <Metric label="令牌" value={totalTokens.toLocaleString()} note={`输入 ${usage?.input_tokens || 0} · 输出 ${usage?.output_tokens || 0}`} />
          <Metric label="待处理 / 失败" value={`${pendingApprovals} / ${failedTools}`} note={failedTools ? '请查看诊断面板' : '运行状态正常'} danger={failedTools > 0} />
        </section>

        <div className="axiom-workbench">
          <section className="axiom-stage">
            {activeModule === 'chat' && (
              <ChatModule
                messages={messages}
                input={input}
                loading={loading}
                connected={connected}
                permissionMode={status?.permission_mode || 'ask'}
                skills={status?.skills || []}
                workspaceSearch={workspaceSearch}
                onInput={setInput}
                onSend={() => sendMessage()}
                onCancel={cancelTurn}
                onQuickSend={sendMessage}
                onCommand={handleComposerCommand}
                onSearchWorkspace={searchWorkspace}
                onApprove={sendApproval}
                onApproveAll={sendApprovalAll}
                onAutoApprove={enableSessionAutoApprove}
                onAnswerAsk={sendAskAnswer}
                endRef={messagesEndRef}
              />
            )}
            {activeModule === 'tools' && (
              <ToolsModule
                catalog={status?.tools || []}
                runs={toolRuns}
                recentChanges={status?.recent_changes || []}
                canUndo={Boolean(status?.can_undo)}
                onUndo={undoLastTurn}
              />
            )}
            {activeModule === 'workspace' && <WorkspaceModule workspace={workspace} />}
            {activeModule === 'sessions' && (
              <SessionsModule
                status={status}
                onNewSession={startNewSession}
                onResumeSession={resumeSession}
                onDeleteSession={deleteSession}
              />
            )}
            {activeModule === 'workflows' && (
              <WorkflowModule
                workflows={status?.workflows || []}
                run={status?.workflow_run}
                onSave={saveWorkflow}
                onRun={runWorkflow}
                onDelete={deleteWorkflow}
                onCancel={cancelWorkflow}
              />
            )}
            {activeModule === 'settings' && (
              <SettingsModule
                wsUrl={WS_URL}
                workspace={workspace}
                permissionMode={status?.permission_mode || 'ask'}
                onPermissionMode={setPermissionMode}
                provider={status?.provider}
                providerSetup={providerSetup}
                onProviderSetup={() => void refreshProviderSetup(true)}
              />
            )}
            {activeModule === 'diagnostics' && <DiagnosticsModule error={connectionError} status={status} runs={toolRuns} wsUrl={WS_URL} />}
          </section>
          <aside className="axiom-rail">
            <section className="axiom-panel axiom-activity">
              <div className="axiom-panel-title"><span>实时活动</span><em>{activeTools ? `${activeTools} 运行中` : '已同步'}</em></div>
              <ToolTimeline runs={toolRuns.slice(0, 7)} />
            </section>
            <section className="axiom-panel">
              <div className="axiom-panel-title"><span>运行能力</span></div>
              <div className="axiom-capabilities">
                <Capability
                  label="审批流"
                  value={
                    status?.permission_mode === 'allow'
                      ? '本会话自动批准'
                      : status?.permission_mode === 'deny'
                        ? '拒绝写入'
                        : pendingApprovals ? `${pendingApprovals} 待处理` : 'Ask'
                  }
                />
                <Capability label="MCP" value={`${status?.mcp_servers?.length || 0} 服务`} />
                <Capability
                  label="安全执行"
                  value={
                    status?.security?.connected
                      ? 'Java 受控进程'
                      : status?.security?.required
                        ? '服务不可用'
                        : '开发模式'
                  }
                />
              </div>
            </section>
          </aside>
        </div>
      </main>
      {providerSetupOpen && providerSetup && (
        <ProviderSetupModal
          status={providerSetup}
          onClose={() => setProviderSetupOpen(false)}
          onSaved={next => {
            setProviderSetup(next)
            setProviderSetupOpen(false)
            setPhase('reconnecting')
          }}
        />
      )}
    </div>
  )
}

function Metric(props: { label: string; value: string; note: string; danger?: boolean }) {
  return <div className={`axiom-metric ${props.danger ? 'is-danger' : ''}`}><span>{props.label}</span><strong>{props.value}</strong><small>{props.note}</small></div>
}

function Capability({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong>{value}</strong></div>
}

function ChatModule(props: {
  messages: Message[]
  input: string
  loading: boolean
  connected: boolean
  permissionMode: PermissionMode
  skills: SkillInfo[]
  workspaceSearch: { query: string; items: WorkspaceSuggestion[] }
  onInput: (value: string) => void
  onSend: () => void
  onCancel: () => void
  onQuickSend: (value: string) => void
  onCommand: (command: ComposerCommand | null, args: string, rawName: string) => void
  onSearchWorkspace: (query: string) => void
  onApprove: (id: string, allow: boolean, scope?: ApprovalScope) => void
  onApproveAll: (allow: boolean, scope?: ApprovalScope) => void
  onAutoApprove: () => void
  onAnswerAsk: (id: string, answers: string[]) => void
  endRef: React.RefObject<HTMLDivElement | null>
}) {
  const [askSelections, setAskSelections] = useState<Record<string, string[]>>({})
  const pendingToolApprovals = props.messages.filter(
    message => message.role === 'approval' && !message.resolved,
  )
  const selectionKey = (askId: string, questionIndex: number) => `${askId}:${questionIndex}`
  const toggleAskSelection = (askId: string, questionIndex: number, option: string, multiSelect: boolean) => {
    const key = selectionKey(askId, questionIndex)
    setAskSelections(previous => {
      const selected = previous[key] || []
      if (!multiSelect) return { ...previous, [key]: [option] }
      const next = selected.includes(option) ? selected.filter(value => value !== option) : [...selected, option]
      return { ...previous, [key]: next }
    })
  }
  const answersFor = (message: Message) => (message.askQuestions || []).map(
    (_, index) => askSelections[selectionKey(message.askId || '', index)] || [],
  )
  const canSubmit = (message: Message) => {
    const questions = message.askQuestions || []
    return questions.length > 0 && answersFor(message).every(answer => answer.length > 0)
  }
  const submitAskAnswer = (message: Message) => {
    if (!message.askId || !canSubmit(message)) return
    props.onAnswerAsk(message.askId, answersFor(message).map(answer => answer.join('、')))
  }

  return (
    <div className="axiom-chat">
      <div className="axiom-prompts">
        {quickPrompts.map(prompt => <button key={prompt} onClick={() => props.onQuickSend(prompt)} disabled={props.loading}><span>↗</span>{prompt}</button>)}
      </div>
      <div className="axiom-messages">
        {props.messages.map(message => (
          <article key={message.id} className={`axiom-message is-${message.role}`}>
            <div className="axiom-avatar">{message.role === 'user' ? '你' : message.role === 'tool' ? 'T' : message.role === 'approval' ? '!' : 'AX'}</div>
            <div className="axiom-bubble">
              <div className="axiom-message-meta">
                <strong>{message.role === 'user' ? '你' : message.role === 'tool' ? message.toolName || '工具' : message.role === 'approval' ? '操作审批' : message.role === 'ask' ? '需要你的决定' : 'Axiom'}</strong>
                {message.resolution && <span>{message.resolution}</span>}
              </div>
              <pre>{message.text || (props.loading && message.role === 'assistant' ? '正在思考…' : '')}</pre>
              {message.role === 'approval' && message.approvalId && !message.resolved && (
                <div className="axiom-approval-anchor">审批操作已固定到下方输入区，可继续查看命令后允许或拒绝。</div>
              )}
              {message.role === 'ask' && message.askId && !message.resolved && (
                <div className="axiom-ask">
                  {(message.askQuestions || []).map((question, questionIndex) => {
                    const key = selectionKey(message.askId!, questionIndex)
                    const selected = askSelections[key] || []
                    return (
                      <section key={key}>
                        {question.header && <span className="axiom-ask-label">{question.header}</span>}
                        <strong>{question.question}</strong>
                        <div className="axiom-options">
                          {question.options.map(option => (
                            <button
                              key={option}
                              className={selected.includes(option) ? 'is-selected' : ''}
                              onClick={() => toggleAskSelection(message.askId!, questionIndex, option, question.multi_select)}
                            >
                              <span>{selected.includes(option) ? '✓' : '○'}</span>{option}
                            </button>
                          ))}
                        </div>
                      </section>
                    )
                  })}
                  <button className="axiom-submit-answer" disabled={!canSubmit(message)} onClick={() => submitAskAnswer(message)}>提交回答</button>
                </div>
              )}
            </div>
          </article>
        ))}
        <div ref={props.endRef} />
      </div>
      <Composer
        input={props.input}
        loading={props.loading}
        connected={props.connected}
        permissionMode={props.permissionMode}
        pendingApprovals={pendingToolApprovals}
        skills={props.skills}
        workspaceSearch={props.workspaceSearch}
        onInput={props.onInput}
        onSend={props.onSend}
        onCancel={props.onCancel}
        onCommand={props.onCommand}
        onSearchWorkspace={props.onSearchWorkspace}
        onApprove={props.onApprove}
        onApproveAll={props.onApproveAll}
        onAutoApprove={props.onAutoApprove}
      />
    </div>
  )
}

function WorkspaceModule({ workspace }: { workspace: string }) {
  return (
    <div className="axiom-module">
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>PROJECT CONTEXT</span><h2>工作区</h2></div></div>
        <div className="axiom-workspace-path"><span>◇</span><strong>{workspace || '等待后端返回工作区'}</strong></div>
        <div className="axiom-workspace-grid">
          <article><span>配置</span><strong>reasonix.toml</strong><p>保留兼容路径，产品界面已升级为 Axiom。</p></article>
          <article><span>前端</span><strong>Electron + React</strong><p>动态端口、断线重连和相对资源路径。</p></article>
          <article><span>执行</span><strong>Python + Java</strong><p>模型工具循环与安全策略服务。</p></article>
        </div>
      </section>
    </div>
  )
}

function SessionsModule(props: {
  status: DesktopStatus | null
  onNewSession: () => void
  onResumeSession: (sessionId: string) => void
  onDeleteSession: (sessionId: string) => void
}) {
  const sessions = props.status?.sessions || []
  return (
    <div className="axiom-module">
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>DURABLE SESSIONS</span><h2>会话历史与恢复</h2></div><button onClick={props.onNewSession}>＋ 新建会话</button></div>
        <p className="axiom-section-copy">对话上下文、工具消息与崩溃检查点保存在本机 SQLite 中。中断任务只恢复上下文，不会自动重复执行写操作。</p>
        <div className="axiom-session-list">
          {sessions.map(session => (
            <article key={session.id} className={session.active ? 'is-active' : ''}>
              <span className={`axiom-session-dot is-${session.status}`} />
              <div className="axiom-session-main">
                <strong>{session.title || '未命名会话'}</strong>
                <small>{session.workspace} · {new Date(session.updated_at * 1000).toLocaleString('zh-CN')}</small>
                {session.last_error && <p>{session.last_error}</p>}
              </div>
              <div className="axiom-session-state">
                <em>{session.active ? '当前' : session.status}</em>
                <code>{session.id.slice(0, 8)}</code>
              </div>
              <div className="axiom-session-actions">
                {!session.active && <button onClick={() => props.onResumeSession(session.id)}>继续</button>}
                {!session.active && <button className="is-delete" onClick={() => props.onDeleteSession(session.id)}>删除</button>}
              </div>
            </article>
          ))}
          {!sessions.length && <div className="axiom-empty"><p>还没有已保存的会话。</p></div>}
        </div>
      </section>
    </div>
  )
}

function SettingsModule(props: {
  wsUrl: string
  workspace: string
  permissionMode: PermissionMode
  onPermissionMode: (mode: PermissionMode) => void
  provider?: DesktopStatus['provider']
  providerSetup: ProviderSetupStatus | null
  onProviderSetup: () => void
}) {
  return (
    <div className="axiom-module axiom-two-columns">
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>CONNECTION</span><h2>桌面桥</h2></div></div>
        <dl className="axiom-details"><div><dt>WebSocket</dt><dd>{props.wsUrl}</dd></div><div><dt>Workspace</dt><dd>{props.workspace || '尚未确认'}</dd></div></dl>
      </section>
      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>MODEL PROVIDER</span><h2>模型供应商</h2></div>
          <button onClick={props.onProviderSetup}>{props.provider?.configured ? '更换配置' : '立即配置'}</button>
        </div>
        <dl className="axiom-details">
          <div><dt>状态</dt><dd>{props.provider?.configured ? '已配置' : '需要配置 API'}</dd></div>
          <div><dt>供应商 / 模型</dt><dd>{props.provider?.name || props.providerSetup?.selected?.label || '尚未选择'} · {props.provider?.model || props.providerSetup?.selected?.model || '—'}</dd></div>
          <div><dt>密钥存储</dt><dd>{props.providerSetup?.managed ? '系统加密存储（不会写入安装包）' : '环境变量或外部 reasonix.toml'}</dd></div>
        </dl>
      </section>
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>PERMISSION GATE</span><h2>审批策略</h2></div></div>
        <div className="axiom-permission-modes">
          <button className={props.permissionMode === 'ask' ? 'is-active' : ''} onClick={() => props.onPermissionMode('ask')}>
            <strong>Ask</strong><span>写操作逐项或批量确认</span>
          </button>
          <button className={props.permissionMode === 'allow' ? 'is-active is-auto' : ''} onClick={() => props.onPermissionMode('allow')}>
            <strong>自动批准</strong><span>本会话后续写操作直接执行</span>
          </button>
          <button className={props.permissionMode === 'deny' ? 'is-active is-deny' : ''} onClick={() => props.onPermissionMode('deny')}>
            <strong>拒绝写入</strong><span>只读工具仍可直接执行</span>
          </button>
        </div>
        <p className="axiom-permission-note">模式仅在当前会话有效，新建会话会恢复配置默认值；显式 Deny 规则始终优先。</p>
        <div className="axiom-policy">
          <div><span className="is-green">✓</span><p><strong>Allow</strong> 只读工具可直接执行</p></div>
          <div><span className="is-amber">?</span><p><strong>Ask</strong> 写入与危险操作显示审批卡</p></div>
          <div><span className="is-red">×</span><p><strong>Deny</strong> 拒绝后将结果返回模型继续会话</p></div>
        </div>
      </section>
    </div>
  )
}

function ProviderSetupModal(props: {
  status: ProviderSetupStatus
  onClose: () => void
  onSaved: (status: ProviderSetupStatus) => void
}) {
  const initialId = props.status.selected?.providerId || props.status.presets[0]?.id || ''
  const initialPreset = props.status.presets.find(item => item.id === initialId)
  const [providerId, setProviderId] = useState(initialId)
  const [apiKey, setApiKey] = useState('')
  const [model, setModel] = useState(props.status.selected?.model || initialPreset?.defaultModel || '')
  const [baseUrl, setBaseUrl] = useState(props.status.selected?.baseUrl || initialPreset?.defaultBaseUrl || '')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')

  const selectProvider = (id: string) => {
    const preset = props.status.presets.find(item => item.id === id)
    setProviderId(id)
    setApiKey('')
    setModel(preset?.defaultModel || '')
    setBaseUrl(preset?.defaultBaseUrl || '')
    setError('')
  }

  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!window.reasonix?.saveProviderSetup) {
      setError('供应商安全配置仅在 Axiom 桌面版中可用。')
      return
    }
    setSaving(true)
    setError('')
    try {
      const next = await window.reasonix.saveProviderSetup({ providerId, apiKey, model, baseUrl })
      setApiKey('')
      props.onSaved(next)
    } catch (saveError) {
      setError(String(saveError))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="axiom-provider-overlay" role="dialog" aria-modal="true" aria-label="配置模型供应商">
      <form className="axiom-provider-modal" onSubmit={save}>
        <div className="axiom-provider-heading">
          <div><span>FIRST-RUN SETUP</span><h2>选择模型供应商</h2><p>API Key 由当前 Windows 用户的系统加密能力保护，不会写入项目、前端资源或安装包。</p></div>
          <button type="button" onClick={props.onClose} aria-label="关闭供应商设置">×</button>
        </div>
        <div className="axiom-provider-presets">
          {props.status.presets.map(preset => (
            <button
              type="button"
              key={preset.id}
              className={providerId === preset.id ? 'is-selected' : ''}
              onClick={() => selectProvider(preset.id)}
            >
              <strong>{preset.label}</strong>
              {preset.format && <em>{preset.format}</em>}
              <span>{preset.defaultModel || '自定义模型与地址'}</span>
            </button>
          ))}
        </div>
        <label className="axiom-provider-field">
          <span>API Key</span>
          <input
            type="password"
            value={apiKey}
            onChange={event => setApiKey(event.target.value)}
            placeholder="仅发送给所选供应商"
            autoComplete="new-password"
            required
          />
        </label>
        <div className="axiom-provider-row">
          <label className="axiom-provider-field">
            <span>模型 ID</span>
            <input value={model} onChange={event => setModel(event.target.value)} placeholder="例如 deepseek-chat" required />
          </label>
          <label className="axiom-provider-field">
            <span>API 地址（可选）</span>
            <input value={baseUrl} onChange={event => setBaseUrl(event.target.value)} placeholder="https://api.example.com/v1" />
          </label>
        </div>
        {!props.status.encryptionAvailable && <div className="axiom-provider-error">系统加密存储不可用，因此已禁止保存明文 API Key。</div>}
        {error && <div className="axiom-provider-error">{error}</div>}
        <div className="axiom-provider-footer">
          <p>也可以取消并继续使用环境变量或外部 reasonix.toml。Axiom 只保存环境变量名称，密钥单独加密。</p>
          <button type="submit" disabled={saving || !props.status.encryptionAvailable || !apiKey.trim() || !model.trim()}>
            {saving ? '正在安全保存并重启…' : '安全保存并连接'}
          </button>
        </div>
      </form>
    </div>
  )
}

function DiagnosticsModule(props: { error: string; status: DesktopStatus | null; runs: ToolRun[]; wsUrl: string }) {
  const lastError = props.runs.find(run => run.status === 'error')
  const servers = props.status?.mcp_servers || []
  return (
    <div className="axiom-module axiom-two-columns">
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>TRANSPORT</span><h2>连接诊断</h2></div></div>
        <dl className="axiom-details"><div><dt>目标</dt><dd>{props.wsUrl}</dd></div><div><dt>状态</dt><dd>{props.error || '连接正常'}</dd></div><div><dt>工具数</dt><dd>{props.status?.tool_count || 0}</dd></div><div><dt>Java 安全服务</dt><dd>{props.status?.security?.connected ? '已连接 · 受控进程执行' : props.status?.security?.error || '开发模式未启用'}</dd></div></dl>
      </section>
      <section className="axiom-section">
        <div className="axiom-section-heading"><div><span>MCP SERVERS</span><h2>MCP 状态</h2></div></div>
        <div className="axiom-server-list">
          {servers.length ? servers.map(server => (
            <div key={server.name}>
              <span className={server.state === 'connected' ? 'is-online' : ''} />
              <div><strong>{server.name}</strong><small>{server.transport} · {server.tool_count} tools</small></div>
              <em>{server.error || server.state}</em>
            </div>
          )) : <p>尚未配置 MCP 服务。可在 reasonix.toml 的 [mcp_servers] 中添加。</p>}
        </div>
      </section>
      <section className="axiom-section axiom-full-width">
        <div className="axiom-section-heading">
          <div><span>PROGRESSIVE SKILLS</span><h2>Skills 能力目录</h2></div>
          <em>{props.status?.skills?.length || 0} 个已发现</em>
        </div>
        <div className="axiom-skill-list">
          {props.status?.skills?.length ? props.status.skills.map(skill => (
            <article key={`${skill.scope}-${skill.name}`}>
              <div><strong>{skill.name}</strong><i>{skill.scope === 'project' ? 'PROJECT' : 'USER'}</i></div>
              <p>{skill.description || '暂无描述'}</p>
              <code>{skill.path}</code>
            </article>
          )) : <div className="axiom-empty"><span>◇</span><p>未发现 SKILL.md。可放在项目 .axiom/skills 或用户 skills 目录。</p></div>}
        </div>
      </section>
      <section className="axiom-section axiom-full-width">
        <div className="axiom-section-heading"><div><span>LAST FAILURE</span><h2>最近工具错误</h2></div></div>
        <pre className="axiom-error-log">{lastError ? `${lastError.name}\n${lastError.args_json}\n${lastError.error}` : '暂无工具错误。'}</pre>
      </section>
    </div>
  )
}

export default App
