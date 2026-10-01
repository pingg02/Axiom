import { useState } from 'react'
import type { ExperimentRecord } from '../protocol'

export function Experiments(props: {
  records: ExperimentRecord[]
  remote: boolean
  onAction: (action: Record<string, unknown>) => void
}) {
  const [name, setName] = useState('baseline')
  const [command, setCommand] = useState('python train.py --config configs/baseline.yaml')
  const [configPath, setConfigPath] = useState('configs/baseline.yaml')
  const [confirmed, setConfirmed] = useState(false)
  return <section className="axiom-section">
    <div className="axiom-section-heading"><div><span>EXPERIMENTS</span><h2>远程实验作业</h2></div></div>
    <p>训练在远程独立进程中运行。断开界面不会停止训练；点击“停止”发送终止信号。</p>
    {props.remote && <form className="axiom-remote-form" onSubmit={event => {
      event.preventDefault()
      props.onAction({ action: 'submit_experiment', name, command, config_path: configPath, confirmed })
      setConfirmed(false)
    }}>
      <label>实验名称<input required value={name} onChange={e => setName(e.target.value)} /></label>
      <label>配置文件记录<input value={configPath} onChange={e => setConfigPath(e.target.value)} /></label>
      <label>训练命令<input required value={command} onChange={e => setCommand(e.target.value)} /></label>
      <label><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />
        我确认在远程执行这条命令（直接用户命令，不经过模型审批）</label>
      <p>命令可用 $AXIOM_OUTPUT_DIR 保存权重，用 $AXIOM_EXPERIMENT_ID 标记运行。</p>
      <button disabled={!confirmed}>启动实验</button>
    </form>}
    {props.records.map(record => <article className="axiom-section" key={record.id}>
      <h3>{record.name} · {record.state}</h3>
      <code>{record.id}</code>
      <p>{record.command}</p>
      <p>Git：{record.branch || '—'} / {record.commit?.slice(0, 12) || '—'}
        {record.dirty ? '（有未提交修改）' : ''} · PID：{record.pid || '待确认'}</p>
      <p>输出：{record.output_dir || '等待服务器确认'}</p>
      <button onClick={() => props.onAction({ action: 'refresh_experiment', experiment_id: record.id })}>
        刷新状态和日志</button>
      {['submitted', 'running', 'unknown', 'stopping'].includes(record.state) && <button
        onClick={() => props.onAction({ action: 'stop_experiment', experiment_id: record.id })}>停止</button>}
      {record.log_tail && <pre>{record.log_tail}</pre>}
      {record.checkpoints?.length ? <p>权重：{record.checkpoints.join(', ')}</p> : null}
    </article>)}
    {!props.remote && <p>连接远程服务器后，可以查看该项目的持久化实验记录。</p>}
  </section>
}
