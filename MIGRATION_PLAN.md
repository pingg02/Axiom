# Reasonix 迁移计划：Go → Python + LangChain/LangGraph

> 生成时间：2026-07-17
> 状态：规划阶段 — AI agent 自动生成

---

## 1. 背景

Reasonix 原为 Go 编写的 AI 编程代理（1084 个 `.go` 源文件，~8.7MB 代码）。本计划描述将其完全迁移到 Python + LangChain/LangGraph 生态的策略。

### 关键决策

| 决策 | 选择 |
|------|------|
| 框架 | LangChain + LangGraph + 自定义前缀缓存 |
| 桌面前端 | 保留 React (241 个 TSX/TS 文件)，Python 后端通过 WebSocket 桥接 |
| 跨平台代码 | ctypes/pywin32/pyobjc 精确翻译，保持功能等价 |

---

## 2. 依赖图谱（Go 内部包依赖关系）

```
Provider 层（叶子）
├── provider/openai
├── provider/anthropic

Tool 层（叶子）
├── tool/builtin（50+ 工具）
├── tool/sessiontool

基础设施层（被依赖，无内部依赖）
├── event          ← 所有模块依赖
├── config         ← boot 依赖
├── secrets        ← agent/sandbox 依赖
├── i18n           ← cli/control 依赖
├── diff           ← tool 依赖
├── fileutil       ← skill/memory 依赖
└── nilutil        ← 被大量使用

中间层（部分依赖内部包）
├── tool/base + tool/registry
├── memory
├── skill
├── permission
├── sandbox / proc / winsandbox / sysproxy  ← 平台特定
├── store / history / checkpoint
├── shellparse / shellsafe
└── retrieval（BM25）

核心层（依赖以上所有）
├── agent           ← provider + tool + memory + sandbox + secrets
├── control         ← agent + permission + guardian + skill + memory + tool
├── boot            ← 所有包的装配工厂
├── guardian        ← agent + provider + tool

前端层（依赖 control）
├── cli             ← boot + control + event
├── serve           ← boot + control + event
├── desktop(Go)     ← boot + control + event
└── bot             ← control + event
```

---

## 3. Go → Python 映射策略

### 3.1 可直接复用 LangChain 生态的部分

| Go 概念 | Python 映射 | 策略 |
|---------|------------|------|
| `provider/openai` | `langchain_openai.ChatOpenAI` | 直接复用 |
| `provider/anthropic` | `langchain_anthropic.ChatAnthropic` | 直接复用 |
| `tool.Tool` | `langchain_core.tools.BaseTool` | `@tool` 装饰器或子类 |
| `tool/Registry` | `langchain.agents.AgentExecutor` 的 tool list | 原生支持 |
| `event.Sink` | `asyncio.Queue` + `CallbackSink` | 适配层 |
| `serve/Server` | `FastAPI` + SSE | FastAPI 替代 |
| `cli/chat_tui` | `textual` / `rich` | Textual 替代 bubbletea |
| 并发 | `asyncio` | 协程替代 goroutine |
| 互斥锁 | `asyncio.Lock` | 标准替代 |
| 配置解析 | `pydantic-settings` + `tomllib` | 标准方案 |
| BM25 检索 | `rank_bm25` | Python 库直接替代 |

### 3.2 需要自定义实现的部分

| Go 概念 | Python 实现 | 说明 |
|---------|------------|------|
| `control.Controller` | `langgraph.StateGraph` 状态机 | 会话状态机编排 |
| `agent.Runner` | 自定义 AgentExecutor + LangGraph | LLM 调用循环 |
| `agent.Compose` | **自定义前缀缓存** | 核心差异化，自己处理字节稳定性 |
| `guardian.Guardian` | LangGraph 并行节点 | 安全审查子代理 |
| `memory.MemorySet` | 自定义文件发现 | 层次化文档是业务逻辑 |
| `skill.Skill` | 自定义文件发现 + prompt 加载 | 业务逻辑为主 |

### 3.3 需要平台特定代码的部分

| Go 概念 | Python 实现 | 涉及 OS |
|---------|------------|---------|
| `sandbox/seatbelt_windows.go` | `ctypes` + `pywin32` | Windows |
| `sandbox/seatbelt_darwin.go` | `pyobjc` (SandboxInit) | macOS |
| `proc/kill_windows.go` | `ctypes` (TerminateProcess, Job Object) | Windows |
| `proc/tree_windows.go` | `ctypes` (Toolhelp32Snapshot) | Windows |
| `proc/hide_windows.go` | `ctypes` (ShowWindow) | Windows |
| `sysproxy/system_windows.go` | `winreg` (WinHTTP) | Windows |
| `winsandbox/sandbox_windows.go` | `ctypes` + `pywin32` (AppContainer) | Windows |
| `winsandbox/coordination_windows.go` | `ctypes` (IPC) | Windows |
| 桌面 app.go (278KB) | `FastAPI` WebSocket 桥接 | 跨平台 |

---

## 4. 架构数据流（Python 版）

```
用户输入
    │
    ▼
Controller.send(text)
    │
    ▼
agent.Runner.run(messages)
    │
    ├── agent.compose.cached_compose()
    │       │
    │       ├── [缓存命中] → 复用前缀
    │       └── [缓存未命中] → 重建前缀并缓存
    │
    ├── langchain_chat_model.generate()
    │       │
    │       ▼
    │   StreamEvent（推理 + 文本流）
    │       │
    │       ▼
    │   event.Sink.emit()  ← 推送给前端
    │
    ├── 解析 tool calls
    │       │
    │       ▼
    │   tool.Registry.execute(name, args)
    │       │
    │       ├── Guardian 并行审查（LangGraph 节点）
    │       ├── Permission 门
    │       └── 工具执行 → 结果回送
    │
    └── 循环直到完成
```

### 前缀缓存机制

```
┌─────────────────────────────────────┐  ← 缓存边界（跨轮次稳定）
│  BASE_PROMPT（冻结文本）              │
│  TOOLS（工具定义）                    │
│  MEMORY（REASONIX.md + 记忆）        │
├─────────────────────────────────────┤  ← 轮次尾（每轮变化）
│  Instructions / 当前日期等            │
│  对话历史                            │
└─────────────────────────────────────┘
```

**实现方式**：`cached_compose()` 将前缀部分缓存，仅当 tools 或 memory 发生变化时重建。轮次间只追加变动的 tail 部分，保证 DeepSeek 自动前缀缓存命中。

---

## 5. 包结构设计

```
reasonix-py/
├── pyproject.toml
├── reasonix/
│   ├── __init__.py
│   ├── __main__.py              # 入口 python -m reasonix
│   │
│   ├── event/                   # 类型化事件系统
│   │   ├── __init__.py          # Event, Kind, Sink
│   │   └── types.py             # 详细事件类型
│   │
│   ├── config/                  # 配置系统
│   │   └── __init__.py          # 多级 TOML 加载
│   │
│   ├── agent/                   # 代理引擎（核心）
│   │   ├── runner.py            # LLM 调用循环 + LangGraph 状态机
│   │   ├── compose.py           # 系统提示词 + 前缀缓存
│   │   └── context.py           # 上下文窗口管理
│   │
│   ├── tool/                    # 工具系统
│   │   ├── base.py              # Tool 抽象 + Registry
│   │   └── builtin/             # 内置工具
│   │       ├── bash.py
│   │       ├── readfile.py
│   │       ├── writefile.py
│   │       ├── grep.py
│   │       ├── glob.py
│   │       ├── web_fetch.py
│   │       ├── edit_file.py
│   │       ├── task.py          # 子代理
│   │       ├── ask.py
│   │       ├── todo.py
│   │       ├── remember.py
│   │       └── ...
│   │
│   ├── provider/                # 模型后端
│   │   ├── __init__.py          # Provider 抽象
│   │   ├── openai.py            # 复用 langchain-openai
│   │   └── anthropic.py         # 复用 langchain-anthropic
│   │
│   ├── control/                 # 核心控制器
│   │   ├── controller.py        # 会话生命周期 + 轮次编排
│   │   ├── session.py           # 会话状态
│   │   └── commands.py          # 命令类型
│   │
│   ├── boot/                    # 装配工厂
│   │   └── __init__.py          # Build Controller from config
│   │
│   ├── memory/                  # 记忆系统
│   │   ├── loader.py            # 层次化文档发现
│   │   ├── store.py             # 自动记忆存储
│   │   └── compiler.py          # 记忆编译器
│   │
│   ├── skill/                   # 技能系统
│   │   ├── loader.py            # 文件发现
│   │   ├── skill.py             # 技能模型
│   │   └── executor.py          # inline/subagent 执行
│   │
│   ├── permission/              # 权限门
│   │   └── gate.py              # allow/deny/ask 三级
│   │
│   ├── guardian/                # 安全审查
│   │   └── guardian.py          # LLM 子代理审查
│   │
│   ├── sandbox/                 # 沙箱（平台特定）
│   │   ├── base.py
│   │   ├── windows.py           # ctypes + pywin32
│   │   ├── darwin.py            # pyobjc
│   │   └── linux.py             # stubs
│   │
│   ├── proc/                    # 进程管理（平台特定）
│   │   ├── base.py
│   │   ├── windows.py           # Job Object, 进程树
│   │   ├── darwin.py
│   │   └── linux.py
│   │
│   ├── serve/                   # HTTP/SSE 服务
│   │   ├── server.py            # FastAPI
│   │   ├── broadcaster.py       # SSE 广播
│   │   └── auth.py              # OAuth
│   │
│   ├── cli/                     # CLI 前端
│   │   ├── cli.py               # 命令行路由
│   │   └── chat_tui.py          # Textual TUI
│   │
│   ├── secrets/                 # 秘密清理
│   │   └── redact.py
│   │
│   ├── i18n/                    # 国际化
│   │   └── __init__.py
│   │
│   ├── diff/                    # Diff 工具
│   ├── evidence/                # 证据管理
│   ├── store/                   # 会话持久化
│   ├── history/                 # 历史会话
│   ├── checkpoint/              # Checkpoint
│   ├── retrieval/               # BM25 检索
│   ├── autoresearch/            # 自动研究
│   ├── shellparse/              # Shell 解析
│   ├── shellsafe/               # Shell 安全
│   ├── outputstyle/             # 输出风格
│   ├── notify/                  # 系统通知
│   ├── sysproxy/                # 系统代理
│   ├── billing/                 # 计费/用量
│   ├── hook/                    # 事件钩子
│   └── util/                    # 工具函数
│
├── desktop/                     # 桌面桥接
│   ├── bridge.py                # FastAPI WebSocket 服务器
│   └── frontend/                # 保留现有 React 代码
│
├── tests/
│   ├── unit/
│   └── integration/
│
└── README.md
```

---

## 6. 分阶段迁移路线图

### Phase 1：核心框架 + 最小可行产品（~200 文件）

**目标**：能用 `python -m reasonix "写个文件"` 完成一个完整轮次。

| 步骤 | 内容 | 产出 |
|------|------|------|
| 1.1 | 项目结构 + pyproject.toml + 依赖 | ✅ 已完成 |
| 1.2 | 事件系统 (`event/`) | ✅ 已完成 |
| 1.3 | 工具抽象层 (`tool/base`, `tool/builtin`: 核心 5-8 个工具) | ✅ 基础完成 |
| 1.4 | Provider 抽象 + OpenAI 集成 (复用 langchain-openai) | ✅ 基础完成 |
| 1.5 | Config 加载 (`pydantic-settings` + `tomllib`) | ✅ 基础完成 |
| 1.6 | 系统提示词 + 前缀缓存 (`agent/compose`) | ✅ 基础完成 |
| 1.7 | Agent 运行器 (`agent/runner`: LangGraph 状态机) | ⬜ |
| 1.8 | Controller (`control/`: 会话生命周期) | ⬜ |
| 1.9 | CLI 客户端 (最小化的 `rich`/`textual` TUI) | ⬜ |
| 1.10 | 预览验证 | ⬜ |

### Phase 2：完整工具集 + 安全层（~250 文件）

**目标**：安全审批流 + 技能调用可用。

| 步骤 | 内容 |
|------|------|
| 2.1 | 所有剩余内置工具 (bash, web_fetch, task/子代理, ask 等) |
| 2.2 | Permission 门 (`allow`/`deny`/`ask` 三级) |
| 2.3 | Guardian (LLM 并行审查 + 熔断器) |
| 2.4 | 技能系统 (`skill/` 发现 + 执行) |
| 2.5 | 记忆系统 (`memory/` 层次化文档) |
| 2.6 | 秘密清理 (`secrets/` redact) |

### Phase 3：平台特定代码（~100 文件）

**目标**：所有跨平台功能在各自 OS 上可用。

| 步骤 | 内容 | 平台 |
|------|------|------|
| 3.1 | Windows 沙箱 (`winsandbox/`) — ctypes + pywin32 | Windows |
| 3.2 | 进程管理 (`proc/`) — psutil + ctypes | 全平台 |
| 3.3 | macOS 沙箱 (`sandbox/seatbelt`) — pyobjc | macOS |
| 3.4 | 系统代理 (`sysproxy/`) — winreg / 环境变量 | 全平台 |

### Phase 4：前端 + 服务层（~150 文件）

**目标**：三种前端 + 桌面都可用。

| 步骤 | 内容 |
|------|------|
| 4.1 | HTTP/SSE 服务端 (`serve/`) — FastAPI |
| 4.2 | 桌面桥接 (`desktop/bridge.py`) — WebSocket |
| 4.3 | 完整的 CLI/TUI (`cli/`) — Textual |
| 4.4 | Bot 协议 (`bot/`) — 飞书/QQ/微信 |

### Phase 5：磨合并迁移剩余模块（~200 文件）

**目标**：功能等价于原始 Go 版本。

| 步骤 | 内容 |
|------|------|
| 5.1 | 所有剩余模块 (autoresearch, retrieval, billing, checkpoint 等) |
| 5.2 | 测试覆盖 (移植关键 Go 测试) |
| 5.3 | CI/CD (GitHub Actions → pytest) |
| 5.4 | 文档 |

---

## 7. 技术选型清单

| 类别 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | >= 3.12 |
| LLM 框架 | LangChain | >= 0.3 |
| 状态机 | LangGraph | >= 0.3 |
| 数据模型 | Pydantic | >= 2.0 |
| 配置 | pydantic-settings + tomllib | — |
| CLI/TUI | Textual / Rich | latest |
| HTTP 服务 | FastAPI + uvicorn | latest |
| SSE | sse-starlette | latest |
| 桌面桥接 | WebSocket (websockets) | >= 12.0 |
| 异步 HTTP | httpx | >= 0.27 |
| Windows API | pywin32 | >= 306 |
| macOS API | pyobjc | >= 10 |
| 进程管理 | psutil | latest |
| 测试 | pytest + pytest-asyncio | latest |
| 格式化 | ruff | latest |
| 类型检查 | mypy | latest |
| BM25 | rank_bm25 | latest |

---

## 8. 关键风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| 前缀缓存字节稳定性破坏 | 缓存命中率下降→成本增加 | 严格单元测试验证每次 compose 的输出字节一致性 |
| ctypes 翻译 Windows API 出错 | 沙箱安全弱化 | 逐步迁移 + 与原版 Go 行为对比测试 |
| 并发性能下降 (GIL) | 多工具并行执行变慢 | 关键路径用 `asyncio.to_thread` + `concurrent.futures` |
| 桌面桥接延迟 | 用户体验下降 | WebSocket 本地通信，延迟 < 1ms |
| LangGraph 版本更新破坏兼容性 | 工作流中断 | 锁定版本，隔离 LangGraph 层 |
| 原版 Go 持续演进 | 迁移目标移动 | 锁定原版版本为迁移基线，完成后同步更新 |
