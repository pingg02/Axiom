export interface FileChange {
  path: string
  description: string
  unified_diff: string
  added: number
  removed: number
}

export interface ToolEvent {
  id: string
  name: string
  args_json: string
  output?: string
  error?: string
  read_only?: boolean
  truncated?: boolean
  change?: FileChange
}

export interface ToolCatalogItem {
  name: string
  description: string
  read_only: boolean
  source?: 'builtin' | 'mcp'
}

export interface McpServerStatus {
  name: string
  transport: string
  state: string
  tool_count: number
  error?: string
}

export interface SessionSummary {
  id: string
  title: string
  workspace: string
  created_at: number
  updated_at: number
  status: string
  last_error?: string
  active: boolean
}

export type PermissionMode = 'ask' | 'allow' | 'deny'

export interface DesktopStatus {
  workspace: string
  session_id: string
  session_state: string
  permission_mode?: PermissionMode
  provider?: {
    configured: boolean
    name: string
    model: string
    error: string
  }
  tool_count: number
  tools: ToolCatalogItem[]
  mcp_servers?: McpServerStatus[]
  skills?: SkillInfo[]
  sessions?: SessionSummary[]
  session_messages?: Array<{
    id: string
    role: 'user' | 'assistant' | 'tool'
    text: string
    tool_name?: string
  }>
  recovery_prompt?: string
  can_undo?: boolean
  recent_changes?: FileChange[]
  workflows?: WorkflowDefinition[]
  workflow_run?: WorkflowRun | null
}

export interface SkillInfo {
  name: string
  description: string
  path: string
  scope: 'project' | 'user'
}

export interface WorkspaceSuggestion {
  path: string
  name: string
  is_dir: boolean
}

export interface WorkflowDefinition {
  id: string
  name: string
  steps: string[]
  updated_at: number
}

export interface WorkflowRun {
  workflow_id: string
  name: string
  state: 'running' | 'completed' | 'failed' | 'cancelled'
  current_step: number
  steps: Array<{
    prompt: string
    state: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
    error: string
  }>
}

export interface UsageInfo {
  input_tokens?: number
  output_tokens?: number
  cache_read_tokens?: number
  cache_write_tokens?: number
}

export type AskQuestionView = {
  header: string
  question: string
  options: string[]
  multi_select: boolean
}

export interface StreamEvent {
  kind: string
  text?: string
  reasoning?: string
  error?: string
  query?: string
  level?: string
  phase_label?: string
  tool?: ToolEvent
  usage?: UsageInfo
  status?: DesktopStatus
  workspace_suggestions?: WorkspaceSuggestion[]
  approval?: {
    id: string
    tool_name: string
    subject: string
    args_json: string
  }
  ask_id?: string
  ask_questions?: AskQuestionView[]
}

export type ModuleKey =
  | 'chat'
  | 'tools'
  | 'workspace'
  | 'sessions'
  | 'workflows'
  | 'settings'
  | 'diagnostics'
export type MessageRole =
  | 'user'
  | 'assistant'
  | 'error'
  | 'tool'
  | 'approval'
  | 'ask'
  | 'notice'
export type ApprovalScope = 'once' | 'session'

export type ProviderPreset = {
  id: string
  label: string
  format?: string
  defaultModel: string
  defaultBaseUrl: string
}

export type ProviderSetupStatus = {
  configured: boolean
  managed: boolean
  needsSetup?: boolean
  externalConfigured?: boolean
  encryptionAvailable: boolean
  selected: {
    providerId: string
    label: string
    format?: string
    model: string
    baseUrl: string
  } | null
  presets: ProviderPreset[]
}

declare global {
  interface Window {
    reasonix?: {
      platform: string
      version: string
      getProviderSetup: () => Promise<ProviderSetupStatus>
      saveProviderSetup: (setup: {
        providerId: string
        apiKey: string
        model: string
        baseUrl: string
      }) => Promise<ProviderSetupStatus>
    }
  }
}

export type Message = {
  id: string
  role: MessageRole
  text: string
  toolName?: string
  toolId?: string
  approvalId?: string
  askId?: string
  askQuestions?: AskQuestionView[]
  resolved?: boolean
  resolution?: string
}

export type ToolRun = {
  id: string
  name: string
  args_json: string
  read_only: boolean
  status: 'running' | 'success' | 'error'
  output: string
  error: string
  truncated: boolean
  change?: FileChange
  startedAt: number
  finishedAt?: number
}
