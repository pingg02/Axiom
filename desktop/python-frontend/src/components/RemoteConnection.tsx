import { useState } from 'react'
import type { DesktopStatus } from '../protocol'

export function RemoteConnection(props: {
  remote: DesktopStatus['remote']
  onAction: (action: Record<string, unknown>) => void
}) {
  const [url, setUrl] = useState('http://127.0.0.1:4096')
  const [directory, setDirectory] = useState('/root/autodl-tmp/projects/cv-project')
  const [username, setUsername] = useState('opencode')
  const [password, setPassword] = useState('')
  const [sessionId, setSessionId] = useState('')

  return (
    <section className="axiom-section">
      <div className="axiom-section-heading"><div><span>REMOTE EXECUTION</span><h2>远程 OpenCode / AutoDL</h2></div></div>
      {props.remote ? <>
        <dl className="axiom-details">
          <div><dt>服务器</dt><dd>{props.remote.url} · {props.remote.version}</dd></div>
          <div><dt>远程项目</dt><dd>{props.remote.directory}</dd></div>
        </dl>
        <p>对话、文件修改和命令在远程执行；远程审批由 OpenCode 管理。</p>
        <button onClick={() => props.onAction({ action: 'disconnect_remote' })}>返回本地（远程任务继续）</button>
      </> : <form onSubmit={event => {
        event.preventDefault()
        props.onAction({ action: 'connect_remote', url, directory, username, password, session_id: sessionId })
        setPassword('')
      }} className="axiom-remote-form">
        <p>先建立 SSH 隧道，再填写本机隧道地址。密码仅保存在当前后台进程内。</p>
        <label>服务器 URL<input required value={url} onChange={event => setUrl(event.target.value)} /></label>
        <label>远程 Linux 项目目录<input required value={directory} onChange={event => setDirectory(event.target.value)} /></label>
        <label>用户名<input value={username} onChange={event => setUsername(event.target.value)} /></label>
        <label>服务器密码<input type="password" autoComplete="off" value={password} onChange={event => setPassword(event.target.value)} /></label>
        <label>已有 Session ID（可选）<input value={sessionId} onChange={event => setSessionId(event.target.value)} /></label>
        <button type="submit">连接远程 OpenCode</button>
      </form>}
    </section>
  )
}
