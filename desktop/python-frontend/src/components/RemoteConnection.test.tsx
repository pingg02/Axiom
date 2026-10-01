import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RemoteConnection } from './RemoteConnection'
import { Experiments } from './Experiments'

describe('remote execution controls', () => {
  it('clears the password after sending connection details', () => {
    const onAction = vi.fn()
    render(<RemoteConnection remote={null} onAction={onAction} />)
    const password = screen.getByLabelText('服务器密码')
    fireEvent.change(password, { target: { value: 'test-only' } })
    fireEvent.click(screen.getByRole('button', { name: '连接远程 OpenCode' }))
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: 'connect_remote', password: 'test-only', url: 'http://127.0.0.1:4096',
    }))
    expect(password).toHaveValue('')
  })

  it('requires explicit user confirmation before submitting a command', () => {
    const onAction = vi.fn()
    render(<Experiments records={[]} remote onAction={onAction} />)
    const submit = screen.getByRole('button', { name: '启动实验' })
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox'))
    fireEvent.click(submit)
    expect(onAction).toHaveBeenCalledWith(expect.objectContaining({
      action: 'submit_experiment', confirmed: true,
    }))
    expect(submit).toBeDisabled()
  })

  it('reuses the durable ID when refreshing and stopping a job', () => {
    const onAction = vi.fn()
    render(<Experiments remote onAction={onAction} records={[{
      id: 'exp_test', name: 'baseline', state: 'running', command: 'train', directory: '/project',
    }]} />)
    fireEvent.click(screen.getByRole('button', { name: '刷新状态和日志' }))
    fireEvent.click(screen.getByRole('button', { name: '停止' }))
    expect(onAction.mock.calls.map(call => call[0])).toEqual([
      { action: 'refresh_experiment', experiment_id: 'exp_test' },
      { action: 'stop_experiment', experiment_id: 'exp_test' },
    ])
  })
})
