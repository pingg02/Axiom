# Axiom 远程 OpenCode 与 CV 实验

本地 Axiom 是操作台，AutoDL 上的 OpenCode 是执行器。远程不需要安装 Axiom、Hermes
或 Daytona，只需要 Linux、Python 3、Git 和 OpenCode。协议基线是 OpenCode 1.18.34，
上游提交 `0112a92c416f5ad833d96e7a8308441f0a875d94`。

## AutoDL 端准备

先安装 OpenCode、配置模型供应商，把 API Key 留在远程，不要写进 Git。
在你自己的 CV 项目目录执行；建议用 tmux 保持服务运行：

```bash
cd /root/autodl-tmp/projects/cv-project
git switch -c baseline-study
# 按项目说明安装依赖，先确认 nvidia-smi 和训练命令正常。
read -s -p 'OpenCode server password: ' OPENCODE_SERVER_PASSWORD
echo
export OPENCODE_SERVER_PASSWORD
opencode serve --hostname 127.0.0.1 --port 4096
```

服务器仅监听远程本机，不要把 4096 直接暴露到公网。

## Windows 端连接

使用 AutoDL 控制台提供的 SSH 账号、地址和端口建立隧道：

```powershell
ssh -N -L 4096:127.0.0.1:4096 -p <SSH端口> <账号>@<服务器地址>
```

保持隧道运行，在 Axiom 设置页填写：URL `http://127.0.0.1:4096`，项目目录
`/root/autodl-tmp/projects/cv-project`（不是本地 E 盘路径），用户名默认 `opencode`，
密码为远程服务密码。首次 Session ID 留空，重启后台后可填原 ID 重新接入。
密码仅保存在后台内存；本地 SQLite 不保存密码。支持 HTTPS 直连，未加密 HTTP
仅接受 loopback/localhost 隧道地址。

远程对话通过 HTTP 提交，输出通过 SSE 返回；审批发给远程 OpenCode。
本地 Java 安全层不会保护 AutoDL：远程模型工具由 OpenCode 审批，显式实验命令由
你的 Linux 账号运行。此实现没有额外容器或 OS 沙箱。

## 创新点与消融实验

先要求远程 Agent 检查代码、数据路径和环境，再在新的 Git 分支实现创新模块。
检查 diff 和测试，确认后提交代码。每个消融配置使用独立 YAML/JSON 文件。
设置页“远程实验作业”可运行长时间训练，例如：

```bash
source /root/miniconda3/etc/profile.d/conda.sh && conda activate cv && \
python train.py --config configs/baseline.yaml --output "$AXIOM_OUTPUT_DIR"
```

换成自己的环境和脚本参数。勾选确认后启动：这是**用户直接提交的命令**，不会再
经过模型审批，不要提交不可信命令。后台使用 OpenCode `/session/{id}/shell` 发送
短启动请求；远程 Python 监督进程启动独立进程组，HTTP 不会阻塞数小时。

记录包括实验 ID、会话、服务器地址、目录、命令、配置路径、Git 分支/commit/dirty
状态、PID/启动标识、退出码、输出目录和日志尾部。日志在
`.axiom/experiments/<实验ID>/train.log`。权重保存在输出目录时，刷新列出
`.pt/.pth/.ckpt/.safetensors`。不自动解析任意框架的训练指标，也不复制整个 Git diff
或配置内容；未提交修改不能仅靠 commit 复现，建议先提交代码。

“刷新”查询状态和日志，“停止”核对 PID/启动标识后向该进程组发送 SIGTERM。
`stopping` 表示可能还没退出，没有自动强杀或重启。训练命令不应二次 daemonize
或逃离进程组。提交响应丢失时标为 `unknown`，先查询原 ID，不能直接重提。
远程关机、磁盘清空或容器重建仍可能丢失作业；独立进程不是任务集群。

## 从代码学习实现

```text
React 界面 → 桌面 WebSocket（启动令牌认证）→ DesktopRuntime
    ├─ 本地 Controller / Runner
    ├─ RemoteController → OpenCode HTTP + SSE
    └─ ExperimentService → OpenCode 用户 shell API
        → 远程 worker.py → 独立训练进程组 + 日志 / job.json
```

- `reasonix/remote/client.py`：HTTP 认证、请求与 SSE 解码；写请求不自动重试。
- `reasonix/remote/controller.py`：把 OpenCode 会话、工具、审批和问题变成 Axiom 事件。
- `reasonix/desktop/__init__.py`：界面是订阅者，后台拥有执行权；一个后台共享一个
  当前会话，多窗口不是不同会话并发调度器。断开窗口不取消任务。退出 Electron
  仍会停止本地后台，但已独立启动的远程实验训练不会因此被取消。
- `reasonix/experiments/service.py`：发送无第三方依赖的 worker 源码给远程 Python
  执行，不需要远程装 Axiom。只有明确用户确认才能提交命令。
- `reasonix/experiments/store.py`：本机 SQLite 索引，按服务器 URL 和目录隔离。
  隧道地址变化需恢复原地址；尚无服务器指纹/地址迁移。
- `reasonix/history/store.py`：消息、checkpoint、工具审计、父子会话关系。
  仅后台启动时将遗留 running 标记 interrupted；新数据库连接不做此操作。
- `reasonix/agent/runner.py`：模型返回后保存消息；工具执行前记录 planned/running，
  执行后保存结果与历史。HISTORY_COMMITTED 区分已保存历史与瞬时输出。
  崩溃恢复补齐未知结果的警告，不自动运行工具，也不保证 exactly-once。
- `reasonix/control/controller.py`：真实子 Agent 使用独立持久化会话/历史，继承父模型、
  工作目录、审批 Gate、Java 安全配置。默认最大嵌套深度 2，单个子 Agent 最多 10 个
  模型轮，父子合计受父会话 max_steps 限制。顺序调用、共享目录，不是并行 Fleet
  或独立文件沙箱；不支持随意指定子 Agent 模型。

## 验证

```powershell
cd E:\Axiom\reasonix-py
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check reasonix tests
.venv\Scripts\mypy.exe reasonix
cd E:\Axiom\desktop\python-frontend
npx tsc --noEmit
npm run test:run -- --pool=threads --maxWorkers=1
npm run build
```

真实 Linux 进程测试在 `tests/integration/test_experiment_worker_linux.py`，Windows 跳过，
CI 新增 Ubuntu job。真实 OpenCode API 测试设置 `AXIOM_TEST_OPENCODE_URL`、
`AXIOM_TEST_OPENCODE_DIRECTORY`、`AXIOM_TEST_OPENCODE_PASSWORD` 后运行
`tests/integration/test_remote_opencode_live.py`，不调用付费模型。
实际 AutoDL/GPU 训练仍需要你的服务器和 CV 项目进行端到端验收。
