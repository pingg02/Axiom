import type { FileChange, ToolCatalogItem, ToolRun } from '../protocol'

function summarizeArgs(args: string) {
  try {
    const parsed = JSON.parse(args || '{}') as Record<string, unknown>
    const value = parsed.path || parsed.pattern || parsed.command || parsed.url || parsed.file_path
    return typeof value === 'string' && value ? value : JSON.stringify(parsed)
  } catch {
    return args
  }
}

function formatDuration(run: ToolRun) {
  const elapsed = Math.max(0, (run.finishedAt || Date.now()) - run.startedAt)
  return elapsed < 1000 ? `${elapsed}ms` : `${(elapsed / 1000).toFixed(1)}s`
}

export function ToolsModule({
  catalog,
  runs,
  recentChanges,
  canUndo,
  onUndo,
}: {
  catalog: ToolCatalogItem[]
  runs: ToolRun[]
  recentChanges: FileChange[]
  canUndo: boolean
  onUndo: () => void
}) {
  return (
    <div className="axiom-module">
      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>CHANGE REVIEW</span><h2>最近一轮文件变更</h2></div>
          <button onClick={onUndo} disabled={!canUndo}>撤销最近一轮</button>
        </div>
        {recentChanges.length ? (
          <div className="axiom-change-list">
            {recentChanges.map((change, index) => (
              <DiffView key={`${change.path}-${index}`} change={change} />
            ))}
          </div>
        ) : (
          <div className="axiom-empty"><span>±</span><p>还没有可审查的文件变更。</p></div>
        )}
      </section>
      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>CAPABILITY CATALOG</span><h2>工具目录</h2></div>
          <em>{catalog.length} 项能力</em>
        </div>
        <div className="axiom-tool-grid">
          {catalog.map(tool => (
            <article key={tool.name}>
              <div>
                <strong>{tool.name}</strong>
                <i>{tool.source === 'mcp' ? 'MCP' : 'LOCAL'}</i>
              </div>
              <p>{tool.description || '暂无描述'}</p>
              <span className={tool.read_only ? 'is-read' : 'is-write'}>
                {tool.read_only ? '只读 · 自动执行' : '写入 · 需要审批'}
              </span>
            </article>
          ))}
        </div>
      </section>
      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>EXECUTION TRACE</span><h2>最近调用</h2></div>
        </div>
        <ToolTimeline runs={runs} expanded />
      </section>
    </div>
  )
}

export function ToolTimeline({
  runs,
  expanded = false,
}: {
  runs: ToolRun[]
  expanded?: boolean
}) {
  if (!runs.length) {
    return (
      <div className="axiom-empty">
        <span>⌁</span>
        <p>还没有工具调用。发送一个需要读取或修改项目的任务试试。</p>
      </div>
    )
  }
  return (
    <div className="axiom-tool-timeline">
      {runs.map(run => (
        <article key={run.id} className={`is-${run.status}`}>
          <span className="axiom-tool-status" />
          <div>
            <div className="axiom-tool-head">
              <strong>{run.name}</strong>
              <em>
                {run.status === 'running'
                  ? '运行中'
                  : run.status === 'error'
                    ? '失败'
                    : formatDuration(run)}
              </em>
            </div>
            <p>{summarizeArgs(run.args_json)}</p>
            {expanded && (
              <>
                <pre>{run.error || run.output || run.args_json}</pre>
                {run.change && <DiffView change={run.change} compact />}
              </>
            )}
          </div>
        </article>
      ))}
    </div>
  )
}

function DiffView({
  change,
  compact = false,
}: {
  change: FileChange
  compact?: boolean
}) {
  return (
    <article className={`axiom-diff ${compact ? 'is-compact' : ''}`}>
      <header>
        <div>
          <strong>{change.path}</strong>
          <span>{change.description || '文件变更'}</span>
        </div>
        <em><b>+{change.added}</b><i>-{change.removed}</i></em>
      </header>
      {change.unified_diff
        ? <pre>{change.unified_diff}</pre>
        : <p>文件内容已改变，但没有可显示的文本差异。</p>}
    </article>
  )
}
