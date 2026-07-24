import { useEffect, useMemo, useRef, useState } from 'react'
import type {
  ApprovalScope,
  Message,
  PermissionMode,
  SkillInfo,
  WorkspaceSuggestion,
} from '../protocol'

export type ComposerCommand = {
  name: string
  description: string
  group: 'actions' | 'session' | 'permissions' | 'navigation' | 'integrations' | 'skills'
  argumentHint?: string
  kind?: 'builtin' | 'skill'
  value?: string
}

export const BUILTIN_COMPOSER_COMMANDS: ComposerCommand[] = [
  { name: 'review', description: '审查当前项目并按严重程度处理缺陷', group: 'actions', argumentHint: '可选范围' },
  { name: 'fix', description: '定位并修复当前问题，然后运行相关验证', group: 'actions', argumentHint: '问题描述' },
  { name: 'test', description: '运行与当前项目匹配的测试并总结失败', group: 'actions', argumentHint: '可选测试范围' },
  { name: 'new', description: '创建一个新会话', group: 'session' },
  { name: 'undo', description: '安全撤销最近一轮文件变更', group: 'session' },
  { name: 'ask', description: '写操作执行前询问', group: 'permissions' },
  { name: 'allow', description: '本会话自动允许写操作', group: 'permissions' },
  { name: 'deny', description: '本会话拒绝写操作', group: 'permissions' },
  { name: 'tools', description: '打开工具调用与 Diff 面板', group: 'navigation' },
  { name: 'sessions', description: '打开历史会话', group: 'navigation' },
  { name: 'workflows', description: '打开工作流', group: 'navigation' },
  { name: 'status', description: '打开连接、MCP 与 Skills 诊断', group: 'navigation' },
  { name: 'settings', description: '打开模型和权限设置', group: 'navigation' },
  { name: 'mcp', description: '查看 MCP 服务和 MCP 工具', group: 'integrations' },
  { name: 'skills', description: '查看当前发现的 Skills', group: 'integrations' },
  { name: 'help', description: '显示所有输入命令和快捷键', group: 'integrations' },
]

const GROUP_LABELS: Record<ComposerCommand['group'], string> = {
  actions: '常用动作',
  session: '会话',
  permissions: '审批模式',
  navigation: '工作台',
  integrations: '集成',
  skills: 'Skills',
}

const GROUP_ORDER: ComposerCommand['group'][] = [
  'actions',
  'session',
  'permissions',
  'navigation',
  'integrations',
  'skills',
]

type ComposerTrigger =
  | { kind: 'slash'; query: string; start: number; token: string }
  | { kind: 'mention'; query: string; start: number; token: string }

export function activeComposerTrigger(text: string): ComposerTrigger | null {
  const slash = /^(\s*)\/([^\s/]*)$/u.exec(text)
  if (slash) {
    return {
      kind: 'slash',
      query: slash[2] || '',
      start: slash[1].length,
      token: text,
    }
  }
  const mention = /(^|\s)@([^\s@]*)$/u.exec(text)
  if (!mention) return null
  return {
    kind: 'mention',
    query: mention[2] || '',
    start: mention.index + mention[1].length,
    token: text.slice(mention.index + mention[1].length),
  }
}

export function parseSlashCommand(text: string): { name: string; args: string } | null {
  const match = /^\s*\/([^\s/]+)(?:\s+([\s\S]*))?\s*$/u.exec(text)
  if (!match) return null
  return { name: match[1].toLocaleLowerCase(), args: (match[2] || '').trim() }
}

export function applyWorkspaceMention(
  text: string,
  trigger: ComposerTrigger,
  item: WorkspaceSuggestion,
): string {
  const label = item.path.replace(/[\[\]\r\n]/gu, ' ')
  const reference = `@[${label}](${item.path})`
  return `${text.slice(0, trigger.start)}${reference} `
}

function skillCommands(skills: SkillInfo[]): ComposerCommand[] {
  return skills.map((skill): ComposerCommand => ({
    name: skill.name.trim().replace(/^\/+/u, '').replace(/\s+/gu, '-'),
    description: skill.description || `使用 ${skill.name} Skill`,
    group: 'skills',
    argumentHint: '可选任务',
    kind: 'skill',
    value: skill.name,
  })).filter(command => Boolean(command.name))
}

function ApprovalDock(props: {
  pending: Message[]
  permissionMode: PermissionMode
  onApprove: (id: string, allow: boolean, scope?: ApprovalScope) => void
  onApproveAll: (allow: boolean, scope?: ApprovalScope) => void
  onAutoApprove: () => void
}) {
  const current = props.pending[0]
  if (!current?.approvalId) return null
  const [toolName = '工具', subject = '', args = ''] = current.text.split('\n')
  const multiple = props.pending.length > 1

  return (
    <section className="axiom-approval-dock" aria-label="待处理审批">
      <div className="axiom-approval-dock-main">
        <span className="axiom-approval-dock-icon">!</span>
        <div>
          <strong>{toolName}</strong>
          <span>{subject || args || '该操作需要你的批准'}</span>
        </div>
        <small>{multiple ? `1 / ${props.pending.length}` : '等待审批'} · {props.permissionMode.toUpperCase()}</small>
      </div>
      <div className="axiom-approval-actions">
        <button
          className="is-allow"
          onClick={() => props.onApprove(current.approvalId!, true, 'once')}
        >
          允许一次 <kbd>Ctrl↵</kbd>
        </button>
        <button
          className="is-session"
          onClick={() => props.onApprove(current.approvalId!, true, 'session')}
        >
          本会话允许同类
        </button>
        <button className="is-auto-all" onClick={props.onAutoApprove}>自动批准后续</button>
        <button
          className="is-deny"
          onClick={() => props.onApprove(current.approvalId!, false, 'once')}
        >
          拒绝 <kbd>Esc</kbd>
        </button>
      </div>
      {multiple && (
        <div className="axiom-approval-batch-actions">
          <span>{props.pending.length} 项待处理</span>
          <button className="is-allow-all" onClick={() => props.onApproveAll(true, 'once')}>全部允许一次</button>
          <button className="is-session-all" onClick={() => props.onApproveAll(true, 'session')}>全部允许同类</button>
          <button className="is-deny-all" onClick={() => props.onApproveAll(false, 'once')}>全部拒绝</button>
        </div>
      )}
    </section>
  )
}

export function Composer(props: {
  input: string
  loading: boolean
  connected: boolean
  permissionMode: PermissionMode
  pendingApprovals: Message[]
  skills: SkillInfo[]
  workspaceSearch: { query: string; items: WorkspaceSuggestion[] }
  onInput: (value: string) => void
  onSend: () => void
  onCancel: () => void
  onCommand: (command: ComposerCommand | null, args: string, rawName: string) => void
  onSearchWorkspace: (query: string) => void
  onApprove: (id: string, allow: boolean, scope?: ApprovalScope) => void
  onApproveAll: (allow: boolean, scope?: ApprovalScope) => void
  onAutoApprove: () => void
}) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [activeIndex, setActiveIndex] = useState(0)
  const [dismissedToken, setDismissedToken] = useState('')
  const trigger = activeComposerTrigger(props.input)
  const commands = useMemo(
    () => [...BUILTIN_COMPOSER_COMMANDS, ...skillCommands(props.skills)],
    [props.skills],
  )
  const slashItems = useMemo(() => {
    if (trigger?.kind !== 'slash') return []
    const query = trigger.query.toLocaleLowerCase()
    return commands.filter(command => (
      !query
      || command.name.toLocaleLowerCase().includes(query)
      || command.description.toLocaleLowerCase().includes(query)
    )).slice(0, 30)
  }, [commands, trigger])
  const mentionItems = trigger?.kind === 'mention'
    && props.workspaceSearch.query === trigger.query
    ? props.workspaceSearch.items
    : []
  const visibleItems = trigger?.kind === 'slash' ? slashItems : mentionItems
  const menuVisible = Boolean(
    trigger
    && trigger.token !== dismissedToken
    && (visibleItems.length > 0 || trigger.kind === 'mention'),
  )

  useEffect(() => {
    setActiveIndex(0)
  }, [props.input])

  const triggerKind = trigger?.kind
  const triggerQuery = trigger?.query || ''
  const triggerToken = trigger?.token || ''

  useEffect(() => {
    if (triggerKind !== 'mention' || triggerToken === dismissedToken) return
    const timer = window.setTimeout(() => props.onSearchWorkspace(triggerQuery), 120)
    return () => window.clearTimeout(timer)
  }, [dismissedToken, props.onSearchWorkspace, triggerKind, triggerQuery, triggerToken])

  const focusInput = () => window.setTimeout(() => textareaRef.current?.focus(), 0)
  const pickCommand = (command: ComposerCommand) => {
    props.onInput(`/${command.name}${command.argumentHint ? ' ' : ''}`)
    setDismissedToken('')
    focusInput()
  }
  const pickMention = (item: WorkspaceSuggestion) => {
    if (!trigger || trigger.kind !== 'mention') return
    props.onInput(applyWorkspaceMention(props.input, trigger, item))
    setDismissedToken('')
    focusInput()
  }
  const executeTypedCommand = () => {
    const parsed = parseSlashCommand(props.input)
    if (!parsed) return false
    const command = commands.find(item => item.name.toLocaleLowerCase() === parsed.name) || null
    props.onCommand(command, parsed.args, parsed.name)
    return true
  }

  const handleKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (menuVisible && ['ArrowDown', 'ArrowUp'].includes(event.key)) {
      event.preventDefault()
      const direction = event.key === 'ArrowDown' ? 1 : -1
      setActiveIndex(index => (index + direction + visibleItems.length) % visibleItems.length)
      return
    }
    if (menuVisible && event.key === 'Tab' && visibleItems.length) {
      event.preventDefault()
      const selected = visibleItems[Math.min(activeIndex, visibleItems.length - 1)]
      if (trigger?.kind === 'slash') pickCommand(selected as ComposerCommand)
      else pickMention(selected as WorkspaceSuggestion)
      return
    }
    if (menuVisible && event.key === 'Enter' && !event.shiftKey && visibleItems.length) {
      const parsed = trigger?.kind === 'slash' ? parseSlashCommand(props.input) : null
      const exact = parsed && commands.find(command => command.name.toLocaleLowerCase() === parsed.name)
      event.preventDefault()
      if (exact) props.onCommand(exact, parsed.args, parsed.name)
      else if (trigger?.kind === 'slash') pickCommand(visibleItems[activeIndex] as ComposerCommand)
      else pickMention(visibleItems[activeIndex] as WorkspaceSuggestion)
      return
    }
    if (event.key === 'Escape') {
      if (menuVisible && trigger) {
        event.preventDefault()
        setDismissedToken(trigger.token)
        return
      }
      const approval = props.pendingApprovals[0]
      if (approval?.approvalId) {
        event.preventDefault()
        props.onApprove(approval.approvalId, false, 'once')
      }
      return
    }
    if (
      event.key === 'Enter'
      && (event.ctrlKey || event.metaKey)
      && props.pendingApprovals[0]?.approvalId
    ) {
      event.preventDefault()
      props.onApprove(props.pendingApprovals[0].approvalId!, true, 'once')
      return
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault()
      if (!executeTypedCommand()) props.onSend()
    }
  }

  const groups = trigger?.kind === 'slash'
    ? GROUP_ORDER.map(group => ({
        group,
        items: slashItems
          .map((item, index) => ({ item, index }))
          .filter(entry => entry.item.group === group),
      })).filter(group => group.items.length)
    : []

  return (
    <div className="axiom-composer">
      <ApprovalDock
        pending={props.pendingApprovals}
        permissionMode={props.permissionMode}
        onApprove={props.onApprove}
        onApproveAll={props.onApproveAll}
        onAutoApprove={props.onAutoApprove}
      />
      {menuVisible && (
        <div className="axiom-completion-menu" role="listbox" aria-label={trigger?.kind === 'slash' ? '命令' : '工作区引用'}>
          {trigger?.kind === 'slash' && groups.map(group => (
            <section key={group.group}>
              <span>{GROUP_LABELS[group.group]}</span>
              {group.items.map(({ item, index }) => (
                <button
                  key={`${item.kind || 'builtin'}:${item.name}`}
                  className={index === activeIndex ? 'is-active' : ''}
                  onMouseDown={event => event.preventDefault()}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => pickCommand(item)}
                  role="option"
                  aria-selected={index === activeIndex}
                >
                  <strong>/{item.name}</strong>
                  {item.argumentHint && <code>{item.argumentHint}</code>}
                  <small>{item.description}</small>
                  {item.kind === 'skill' && <i>Skill</i>}
                </button>
              ))}
            </section>
          ))}
          {trigger?.kind === 'mention' && mentionItems.map((item, index) => (
            <button
              key={`${item.is_dir ? 'dir' : 'file'}:${item.path}`}
              className={index === activeIndex ? 'is-active' : ''}
              onMouseDown={event => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(index)}
              onClick={() => pickMention(item)}
              role="option"
              aria-selected={index === activeIndex}
            >
              <strong>{item.is_dir ? '◇' : '·'} {item.name}</strong>
              <small>{item.path}</small>
              <i>{item.is_dir ? '目录' : '文件'}</i>
            </button>
          ))}
          {trigger?.kind === 'mention' && mentionItems.length === 0 && (
            <div className="axiom-completion-empty">
              {props.workspaceSearch.query === trigger.query ? '没有匹配的工作区文件' : '正在搜索工作区…'}
            </div>
          )}
        </div>
      )}
      <div className="axiom-composer-input">
        <textarea
          ref={textareaRef}
          value={props.input}
          onChange={event => {
            setDismissedToken('')
            props.onInput(event.target.value)
          }}
          onKeyDown={handleKeyDown}
          placeholder={props.connected ? '描述任务；输入 / 执行命令，输入 @ 引用文件…' : '正在连接桌面桥…'}
          disabled={!props.connected}
        />
      </div>
      <div className="axiom-composer-footer">
        <div className="axiom-composer-tools">
          <button onClick={() => { props.onInput('/'); focusInput() }} disabled={!props.connected} title="命令">/</button>
          <button onClick={() => { props.onInput(`${props.input}${props.input && !/\s$/u.test(props.input) ? ' ' : ''}@`); focusInput() }} disabled={!props.connected} title="引用文件">@</button>
          <span>Enter 发送 · Shift + Enter 换行</span>
        </div>
        {props.loading
          ? <button className="axiom-stop" onClick={props.onCancel}>■ 停止</button>
          : <button className="axiom-send" onClick={() => executeTypedCommand() || props.onSend()} disabled={!props.connected || !props.input.trim()}>发送 <span>↗</span></button>}
      </div>
    </div>
  )
}
