import { useState } from 'react'
import type { WorkflowDefinition, WorkflowRun } from '../protocol'

export function WorkflowModule({
  workflows,
  run,
  onSave,
  onRun,
  onDelete,
  onCancel,
}: {
  workflows: WorkflowDefinition[]
  run?: WorkflowRun | null
  onSave: (name: string, steps: string[]) => void
  onRun: (workflowId: string) => void
  onDelete: (workflowId: string) => void
  onCancel: () => void
}) {
  const [name, setName] = useState('')
  const [steps, setSteps] = useState([''])

  const save = () => {
    const clean = steps.map(step => step.trim()).filter(Boolean)
    if (!name.trim() || !clean.length) return
    onSave(name.trim(), clean)
    setName('')
    setSteps([''])
  }

  return (
    <div className="axiom-module">
      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>WORKFLOW LITE</span><h2>编排重复任务</h2></div>
          <em>最多 20 个串行步骤</em>
        </div>
        <div className="axiom-workflow-editor">
          <label>
            <span>工作流名称</span>
            <input value={name} onChange={event => setName(event.target.value)} placeholder="例如：发布前检查" />
          </label>
          <div className="axiom-workflow-steps">
            {steps.map((step, index) => (
              <label key={index}>
                <span>步骤 {index + 1}</span>
                <textarea
                  value={step}
                  onChange={event => {
                    const next = [...steps]
                    next[index] = event.target.value
                    setSteps(next)
                  }}
                  placeholder="描述这一阶段交给 Axiom 完成的任务"
                />
                {steps.length > 1 && (
                  <button type="button" onClick={() => setSteps(steps.filter((_, item) => item !== index))}>
                    移除
                  </button>
                )}
              </label>
            ))}
          </div>
          <div className="axiom-workflow-editor-actions">
            <button type="button" onClick={() => setSteps([...steps, ''])} disabled={steps.length >= 20}>＋ 添加步骤</button>
            <button type="button" className="is-primary" onClick={save}>保存工作流</button>
          </div>
          <p>运行需要你主动点击；步骤中的写工具仍遵守 Ask / Allow / Deny 和批量审批策略。</p>
        </div>
      </section>

      {run && (
        <section className="axiom-section">
          <div className="axiom-section-heading">
            <div><span>ACTIVE RUN</span><h2>{run.name}</h2></div>
            {run.state === 'running'
              ? <button onClick={onCancel}>停止工作流</button>
              : <em>{stateLabel(run.state)}</em>}
          </div>
          <div className="axiom-workflow-run">
            {run.steps.map((step, index) => (
              <article key={index} className={`is-${step.state}`}>
                <i>{index + 1}</i>
                <div><strong>{step.prompt}</strong><span>{stateLabel(step.state)}</span>{step.error && <p>{step.error}</p>}</div>
              </article>
            ))}
          </div>
        </section>
      )}

      <section className="axiom-section">
        <div className="axiom-section-heading">
          <div><span>SAVED RECIPES</span><h2>已保存工作流</h2></div>
          <em>{workflows.length} 个</em>
        </div>
        {workflows.length ? (
          <div className="axiom-workflow-list">
            {workflows.map(workflow => (
              <article key={workflow.id}>
                <div>
                  <strong>{workflow.name}</strong>
                  <span>{workflow.steps.length} 步 · {new Date(workflow.updated_at * 1000).toLocaleString()}</span>
                </div>
                <ol>{workflow.steps.map((step, index) => <li key={index}>{step}</li>)}</ol>
                <footer>
                  <button onClick={() => onRun(workflow.id)} disabled={run?.state === 'running'}>审查后运行</button>
                  <button className="is-danger" onClick={() => onDelete(workflow.id)} disabled={run?.state === 'running'}>删除</button>
                </footer>
              </article>
            ))}
          </div>
        ) : (
          <div className="axiom-empty"><span>⇢</span><p>还没有工作流。把经常重复的检查和修复步骤保存下来。</p></div>
        )}
      </section>
    </div>
  )
}

function stateLabel(state: string) {
  return {
    pending: '等待',
    running: '执行中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  }[state] || state
}
