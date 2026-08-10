# Axiom（Reasonix）项目问题、难点与解决方案总结

> 文档日期：2026-07-24  
> 项目目录：`E:\reasonix`  
> 项目名称：对外名称统一为 **Axiom**，Python 核心仍保留 Reasonix 兼容命名。  
> 总结范围：本会话中对 `reasonix`、`deepseek-reasonix`、`hermes-agent`、`CodeWhale` 的对比审查，以及对 Python 核心、Electron 桌面端、React 前端、Java 安全服务、MCP、审批、工作流和打包链路的修复。

## 1. 项目目标

Axiom 是一个面向本地项目的 AI 编程工作台，核心目标包括：

- 提供可持续多轮对话，而不是一次性问答。
- 允许模型读取、分析和修改工作区文件。
- 对有副作用的工具调用提供 Ask / Allow / Deny 审批。
- 保存会话、检查点、工具变更和工作流。
- 支持 MCP、Skills 和多模型供应商。
- 通过 Electron 打包成 Windows 桌面应用。
- 使用 Java 安全服务提供额外的权限、沙箱和 Guardian 防护。

本轮优化并非直接复制其他项目代码，而是提取三个参考项目中适合 Axiom 的产品和架构思路，再按照当前代码结构重新实现。

---

## 2. 总体结论

本轮集中解决了以下核心问题：

1. Electron EXE 启动白屏或无法运行。
2. 桌面前端功能模块不足、页面结构单一。
3. 工具获取失败，并出现 `Expecting value`、`Unknown tool: None`。
4. 调用工具后对话无法继续。
5. Ask / Allow / Deny 审批入口缺失。
6. 审批必须逐项点击，缺少批量批准和会话级策略。
7. 会话、检查点和崩溃恢复能力不足。
8. 文件修改没有统一 Diff 和安全撤销。
9. 缺少可保存、可运行、可取消的工作流。
10. Skills 和 MCP 的发现、展示与诊断不足。
11. API Key 是否会被打进安装包缺少明确边界。
12. 打包缓存和临时数据曾写入 C 盘。
13. Java Windows 沙箱存在能力边界，严格模式不够明确。
14. Guardian 日志可能暴露不必要的模型原始内容。
15. Maven Wrapper 和多语言打包链路不稳定。

完成修复后：

- Python 测试：100 个通过。
- React 前端测试：6 个通过。
- Java 安全模块测试：66 个通过。
- Ruff：通过。
- Mypy 严格检查：通过。
- Vite 生产构建：通过。
- Electron NSIS 安装包：构建成功。
- `reasonix.exe --version`：运行成功。
- Electron 解包版：实际启动成功。
- 渲染器 DOM：实际检查成功，不再白屏。
- Python 桌面桥：实际连接成功。
- 无供应商环境变量时：实际显示首次 API 配置窗口。

---

## 3. 参考项目带来的可迁移思路

对 `deepseek-reasonix`、`hermes-agent`、`CodeWhale` 的对比，主要得到以下启发：

### 3.1 任务不应只有聊天窗口

成熟 Agent 产品通常把一次任务拆分成多个可观察模块：

- 对话与推理
- 工具调用
- 文件变更
- 权限审批
- 会话恢复
- 工作流
- MCP / Skills
- 运行诊断

Axiom 原前端过于集中，因此本轮把功能拆分成独立模块，并让侧边导航能够直接查看任务状态。

### 3.2 工具执行必须可观察、可恢复

只展示最终回答会导致用户无法知道：

- 模型调用了什么工具。
- 工具参数是什么。
- 工具是否成功。
- 哪些文件被修改。
- 为什么对话停止。

因此增加了工具时间线、错误状态、Diff、审批状态、撤销入口和诊断信息。

### 3.3 会话与工作流是两种不同资产

- 会话用于保存上下文、消息和工具执行记录。
- 工作流用于保存可重复运行的任务步骤。

本轮将两者分别持久化，避免把工作流简单实现成一段聊天记录。

### 3.4 Skills 应采用渐进式披露

启动时把所有 Skill 全文注入 Prompt 会浪费上下文并降低模型判断质量。当前实现只注入 Skill 名称、描述和路径；模型判断适用后再读取具体 `SKILL.md`。

### 3.5 审批必须同时兼顾安全和效率

逐个批准安全但低效，完全自动批准又风险过高。因此采用：

- 单次批准或拒绝。
- 批量批准或拒绝当前待处理项。
- 本会话允许同类操作。
- Ask / Allow / Deny 三种模式。
- 写操作仍保留 Diff 和撤销记录。

---

## 4. 问题一：EXE 启动白屏

### 现象

- `Reasonix.exe` 或 `Axiom.exe` 能打开窗口，但内容全白。
- 有时只显示 Electron 默认菜单栏。
- 用户无法判断是前端未加载、后端未启动，还是 WebSocket 未连接。

### 排查难点

Electron 白屏可能发生在多个阶段：

1. `BrowserWindow` 未创建。
2. `app.asar` 内没有正确包含前端文件。
3. Vite 资源路径在 `file://` 协议下无效。
4. Python 后端未启动。
5. WebSocket 端口冲突或尚未就绪。
6. 渲染进程崩溃。
7. 开发环境路径和打包环境路径不一致。

只看到白色窗口无法区分这些情况。

### 根因

- Electron 打包资源路径、前端静态资源和后端启动目录之间缺少稳定约定。
- 缺少 `did-finish-load`、`did-fail-load`、`render-process-gone` 等日志。
- 构建完成不等于安装版真正可以运行，原流程缺少运行时验证。

### 解决方案

- Electron 使用打包后的本地前端入口，并显式传入桌面桥端口和工作区。
- Python 桌面服务作为 `extraResources` 随安装包部署。
- Electron 启动 Python 后端时显式指定：
  - `127.0.0.1`
  - 桌面端口
  - 工作区
  - 父进程 PID
  - 供应商配置文件
- 增加渲染器加载成功、加载失败和渲染进程退出日志。
- 使用 Chrome DevTools Protocol 对安装版实际页面执行 DOM 检查，而不是只看进程是否存在。
- 删除 Electron 默认应用菜单：

```js
Menu.setApplicationMenu(null)
```

### 验证

真实运行解包版后确认：

- 页面标题为 `Axiom`。
- 根节点已渲染。
- 页面包含对话、工具、工作区、会话、工作流、设置和诊断模块。
- 页面显示“桌面桥已连接”。
- 后端显示 16 个工具。
- 不再出现白屏。

---

## 5. 问题二：安装包可以生成，但程序不能运行

### 现象

- 构建脚本显示成功，但安装后程序无法正常使用。
- 单独复制 `Axiom.exe` 后无法运行。
- Python、Java、React、Electron 的产物版本可能不一致。

### 排查难点

该项目不是单一程序，而是四条构建链的组合：

1. Python 核心与 PyInstaller。
2. React / TypeScript 与 Vite。
3. Java / Maven / Spring Boot。
4. Electron / electron-builder / NSIS。

任意一条链使用旧产物，都可能造成“打包成功但运行失败”。

### 根因

- 便携版 Electron EXE 依赖同目录的 `resources`、DLL、语言包等文件。
- 最终交付目录可能残留上一次构建结果。
- 过去更偏重编译成功，缺少完整安装版启动检查。
- Maven Wrapper 曾存在脚本格式和下载目录问题。

### 解决方案

- 统一 `build_all.ps1` 构建顺序。
- 将最新 Python EXE、Java JAR、前端资源和 Electron 包同步到最终交付目录。
- 修复 `mvnw.cmd`，使用 Maven 3.9.16。
- Maven 本地仓库改到项目 E 盘目录。
- 对最终 Electron 解包版执行真实启动验证。
- 交付时同时保留安装包和完整免安装目录。

### 使用要求

- 推荐使用 NSIS 安装包。
- 免安装版必须保留整个 `desktop` 目录。
- 不能只复制 `desktop\Axiom.exe` 到其他位置运行。

---

## 6. 问题三：默认菜单栏仍显示 File / Edit / View / Window

### 现象

窗口顶部仍显示 Electron 默认英文菜单，影响产品完整度，也容易让用户误以为仍是开发版。

### 根因

Electron 未主动清除默认应用菜单。

### 解决方案

在 Electron ready 阶段调用：

```js
Menu.setApplicationMenu(null)
```

最终窗口只保留 Axiom 自己的页面与标题栏。

---

## 7. 问题四：前端功能模块不足、页面不够完整

### 现象

- 功能主要集中在单一页面。
- 工具、会话、审批、工作流、MCP 等能力缺少清晰入口。
- 与参考项目相比，缺少工作台感和任务可观察性。

### 根因

- `App.tsx` 承担过多职责。
- 协议类型、业务模块和展示组件耦合。
- 后端已有能力没有完整映射到前端。

### 解决方案

当前前端划分为：

- **对话**：消息、流式输出、审批卡片和任务建议。
- **工具**：工具调用时间线、状态、错误、参数和 Diff。
- **工作区**：项目路径和工作区上下文。
- **会话**：历史会话、恢复和删除。
- **工作流**：新建、保存、运行和取消。
- **设置**：模型供应商和权限模式。
- **诊断**：桌面桥、工具、MCP、Skills 和运行状态。

同时完成以下代码拆分：

- `src/protocol.ts`：前后端协议与类型。
- `src/components/ToolsPanel.tsx`：工具和 Diff 展示。
- `src/components/WorkflowModule.tsx`：工作流界面。
- `src/App.tsx`：保留全局状态、路由和组合逻辑。

### 效果

- 页面职责更清楚。
- 新增功能不必继续堆积到一个组件。
- 工具失败和审批待处理能在导航和指标中直接看到。

---

## 8. 问题五：工具获取失败

### 典型错误

```text
Expecting value: line 1 column 1 (char 0)
Unknown tool: None
```

### 现象解释

- `Expecting value` 表示系统尝试把空内容或非 JSON 内容解析为 JSON。
- `Unknown tool: None` 表示模型输出的工具名为空、字段不符合协议，或者工具调用没有成功映射到注册表。

### 排查难点

工具调用横跨：

1. 模型响应。
2. LangChain 工具调用结构。
3. Runner 循环。
4. 权限控制。
5. 工具注册表。
6. WebSocket 事件。
7. React 状态。

错误如果只在前端显示为“工具失败”，无法定位发生在哪一层。

### 解决方案

- 工具执行统一通过注册表和结构化参数。
- 对未知工具、无效参数和执行异常生成明确的失败事件。
- 工具事件包含调用 ID、工具名、参数、状态、结果和错误。
- 前端工具时间线展示成功、失败和待审批状态。
- 诊断模块展示已注册工具数量和 MCP 服务数量。
- 写操作在执行前生成预览，执行后记录变更。
- 工具失败不会直接破坏整个会话状态。

### 后续诊断建议

再次出现工具失败时，应依次检查：

1. 诊断页中的桌面桥是否在线。
2. 工具是否出现在注册表。
3. MCP 服务是否已连接。
4. 工具时间线中的实际工具名和参数。
5. 是否存在尚未处理的 Ask 或审批。
6. Electron 日志中的后端或渲染器错误。

---

## 9. 问题六：调用工具后不能继续会话

### 现象

- 工具调用后消息流停止。
- 工具成功或失败后没有下一轮模型响应。
- 审批完成后任务没有恢复。

### 根因

- Runner 没有完整保留工具消息并继续 Agent 循环。
- 工具结果、审批结果和聊天消息之间缺少统一状态。
- 前端容易把工具调用结束误判为整轮任务结束。

### 解决方案

- `Runner` 接收并保留历史消息。
- 工具结果作为后续模型输入的一部分。
- `TurnResult` 返回完整消息状态。
- 审批结果通过 WebSocket 回到控制器后恢复原任务。
- 工具失败写入事件和会话，但不使整个会话失效。
- 控制器将每轮状态保存到 SQLite。

### 效果

- 工具执行完成后模型可以继续回答。
- 审批后可以恢复任务。
- 即使工具失败，用户也能继续发送下一条消息。

---

## 10. 问题七：Ask / Allow / Deny 审批功能缺失

### 现象

- 后端有权限概念，但前端看不到审批入口。
- 用户无法明确允许或拒绝写文件、执行命令等操作。

### 根因

- 审批事件没有完整映射为前端交互组件。
- 前端消息类型未覆盖审批请求。
- 权限模式和单次审批混在一起。

### 解决方案

前端现在支持：

- **Ask**：危险或有副作用的工具需要询问。
- **Allow**：当前会话自动批准。
- **Deny**：拒绝有副作用的工具。
- 单个允许。
- 单个拒绝。
- 批量允许当前待处理项。
- 批量拒绝当前待处理项。
- 本会话允许同类操作。

后端 WebSocket 协议支持：

- `approve`
- `approve_all`
- `scope: once`
- `scope: session`
- `future_mode`

### 安全原则

- 只读工具可以根据策略直接执行。
- 写文件、删除内容、命令执行等仍受审批策略控制。
- Workflow 中的写步骤不会绕过审批系统。

---

## 11. 问题八：审批必须一个一个点击

### 现象

长任务会产生多个工具审批，用户需要反复点击。

### 难点

批量批准不能简单等同于永久关闭安全控制，否则会扩大权限范围。

### 解决方案

采用两层批量机制：

1. **当前批次**：批准或拒绝目前等待中的项目。
2. **本会话策略**：后续同类操作自动批准，结束会话后失效。

这样既减少重复操作，又不把权限永久扩展到所有项目和未来会话。

---

## 12. 问题九：会话没有可靠持久化和恢复

### 现象

- 关闭应用后历史消息难以恢复。
- 崩溃时无法知道上次任务停在哪一步。
- 会话列表可能只是前端临时数据。

### 解决方案

新增 SQLite 会话存储：

- `sessions`
- `messages`
- `checkpoints`
- `changes`
- `workflows`

主要能力：

- 创建和更新会话。
- 保存用户、助手、工具和审批消息。
- 保存检查点。
- 标记运行中、完成和异常中断状态。
- 恢复历史会话。
- 删除指定会话。
- 启动时识别异常退出的任务。
- 使用 WAL 模式提高桌面进程读写稳定性。

默认状态库位置：

```text
%APPDATA%\axiom-desktop\state\axiom.db
```

测试或隔离运行时可通过 `AXIOM_STATE_DIR` 改写位置。

---

## 13. 问题十：文件修改没有 Diff，也无法安全撤销

### 现象

- 用户只知道工具写了文件，不知道具体修改内容。
- 修改错误后没有统一撤销入口。
- 简单恢复旧内容可能覆盖用户后续手动修改。

### 难点

撤销不能无条件覆盖当前文件。工具执行后，如果用户或其他任务又修改了文件，直接回滚会造成二次数据丢失。

### 解决方案

- `write_file`、`edit_file`、`delete_range` 在执行前生成变更预览。
- 记录统一 Diff、增加行数和删除行数。
- 工具成功后把变更写入 change journal。
- 前端工具面板显示 Diff。
- 提供“撤销上一轮变更”。
- 撤销前比较当前内容与工具执行后的内容。
- 如果文件已被后续修改，拒绝自动覆盖并报告冲突。

### 安全收益

- 用户可以在批准前理解影响。
- 工具修改有审计记录。
- 撤销不会覆盖后来产生的人工修改。

---

## 14. 问题十一：缺少可重复运行的工作流

### 目标

把多个常用任务步骤保存下来，例如：

1. 审查项目。
2. 运行测试。
3. 修复高优先级问题。
4. 重新验证。

### 解决方案

实现 Workflow Lite：

- 新建工作流。
- 设置名称。
- 最多保存 20 个步骤。
- 按工作区持久化。
- 串行执行步骤。
- 显示当前运行状态。
- 取消运行。
- 删除工作流。
- 每个步骤继续使用原有审批机制。

### 设计边界

当前是轻量串行工作流，不包含：

- 可视化 DAG。
- 条件分支。
- 循环节点。
- 并行节点。
- 分布式调度。

这些可以作为后续版本扩展，不应在基础稳定性尚未验证前一次性引入。

---

## 15. 问题十二：Skills 发现和使用不足

### 现象

- 项目中的 `SKILL.md` 可能无法被自动发现。
- 把所有 Skill 全文注入 Prompt 会造成上下文浪费。
- 前端无法看到当前发现了哪些 Skill。

### 解决方案

新增 Skill 发现器，扫描：

- 项目级 `.axiom`
- 项目级 `.reasonix`
- 项目级 `.agents`
- 项目级 `.codex`
- 用户级 Skill 目录

启动时只向模型提供：

- Skill 名称。
- Skill 描述。
- 文件路径。
- 来源是项目级还是用户级。

模型判断适用后再读取完整 `SKILL.md`，实现渐进式披露。诊断页同时展示发现结果。

---

## 16. 问题十三：MCP 状态不透明与 LangChain 版本核对

### 现象

- 用户只能看到“工具获取失败”，无法确认 MCP 是否连接。
- 担心 LangChain MCP 接入方式或版本过旧。

### 解决方案

- MCP 工具统一加载到工具注册表。
- 前端诊断页显示 MCP 服务数量和工具数量。
- MCP 加载失败不会让所有内置工具失效。
- 使用官方推荐的 `langchain-mcp-adapters` 和 `MultiServerMCPClient`。

### 版本核对结果

在 2026-07-23 通过本地 `pip index versions` 核对：

| 包 | 版本 |
|---|---:|
| `langchain` | 1.3.14 |
| `langchain-core` | 1.5.0 |
| `langchain-openai` | 1.4.0 |
| `langchain-mcp-adapters` | 0.3.0 |

项目约束位于：

```text
E:\reasonix\reasonix-py\pyproject.toml
```

官方参考：

- [LangChain MCP 文档](https://docs.langchain.com/oss/python/langchain/mcp)
- [LangChain 安装文档](https://docs.langchain.com/oss/python/langchain/install)

---

## 17. 问题十四：API Key 是否被打入 EXE

### 风险

如果在打包阶段把开发机环境变量、`.env` 或配置中的密钥写进前端或安装包，任何拿到安装包的人都可能提取密钥。

### 解决方案

最终实现不把 API Key 写入：

- React 前端资源。
- 项目源码。
- `provider.toml`。
- Electron 安装包固定配置。

首次启动且未检测到外部配置时，显示供应商向导：

- DeepSeek
- OpenAI
- Anthropic
- OpenAI Compatible

保存策略：

- `provider.toml` 只保存供应商、模型、地址和环境变量名称。
- API Key 使用 Electron `safeStorage` 加密。
- 加密不可用时拒绝明文保存。
- 密钥只在启动 Python 子进程时注入该子进程环境。

### 验证

使用全新的 E 盘用户数据目录，并清除当前进程中的供应商环境变量后启动安装版，实际确认页面显示：

- `FIRST-RUN SETUP`
- 供应商选项
- API Key 输入框
- 模型 ID
- 可选 API 地址

这说明安装包没有依赖开发机内置密钥。

---

## 18. 问题十五：打包临时数据写入 C 盘

### 现象

Python、npm、Electron、Maven 等工具默认会使用用户目录和系统临时目录，容易在 C 盘产生大量缓存。

### 解决方案

最终构建脚本将主要缓存和临时目录重定向到：

```text
E:\reasonix\.build-cache
```

包括：

- `PIP_CACHE_DIR`
- npm cache
- Electron cache
- electron-builder cache
- `TEMP`
- `TMP`

Maven 本地仓库改为：

```text
E:\reasonix\reasonix-java\.mvn\repository
```

真实运行验证使用的隔离用户目录和状态目录也位于 E 盘，并在验证完成后删除。

### 注意

系统中原本已经存在的用户级缓存不应在不确认归属时直接递归删除，以免影响其他项目。当前方案重点是确保 Axiom 后续构建不再依赖或继续扩大这些 C 盘缓存。

---

## 19. 问题十六：Java Windows 安全沙箱边界

### 现象

- 需要审查 Java 安全沙箱是否真正限制命令、进程、网络和资源。
- Windows 下部分安全能力依赖 Job Object 和本地 API。

### 难点

普通 Java 进程无法仅靠标准库实现完整的：

- 文件系统命名空间隔离。
- 网络命名空间隔离。
- AppContainer 权限边界。
- Linux seccomp 等系统调用过滤。

因此必须明确“策略守卫”和“操作系统强隔离”的区别。

### 已完成的修复

- Java HTTP 和 gRPC 服务只监听 `127.0.0.1`。
- Spring 配置默认启用严格沙箱：

```yaml
axiom.sandbox.strict: ${AXIOM_SANDBOX_STRICT:true}
```

- 当请求要求当前平台无法落实的隔离时，严格模式失败关闭。
- 命令执行继续使用：
  - 命令策略。
  - 网络能力检测。
  - 超时。
  - 进程树终止。
  - Job Object（可用时）。
  - 内存和输出限制。
- stdout / stderr 持续排空，但只保留限定大小，避免子进程因管道写满死锁。
- Job Object 不可用时明确记录降级到进程树守卫。

### 当前边界

Windows 后端目前不是 AppContainer 级沙箱。它是“策略校验 + 进程与资源守卫”。对于必须具备强文件系统或强网络隔离的任务，严格模式应拒绝执行，而不是假装已经安全隔离。

### 后续增强方向

- Windows AppContainer。
- 低完整性令牌。
- Windows Defender Application Control。
- Hyper-V / Windows Sandbox。
- 容器或专用虚拟机执行不可信代码。

---

## 20. 问题十七：Guardian 可能泄漏模型原始内容

### 风险

当 Guardian 返回无效 JSON 或异常时，如果日志直接记录完整模型响应，可能包含：

- 用户输入。
- 文件内容。
- 推理内容。
- 潜在密钥。

### 解决方案

- 不再记录原始无效 JSON。
- 不再把 Guardian rationale 原样写入错误日志。
- 对外返回通用错误：
  - `Guardian model unavailable`
  - `Guardian returned an invalid verdict`
- 保留异常类型和必要的诊断信息。
- 继续使用 Secrets Redactor 处理日志内容。

---

## 21. 问题十八：Maven Wrapper 不稳定

### 现象

- `mvnw.cmd` 格式或下载逻辑异常。
- Maven 下载位置默认落到用户 C 盘。
- Wrapper 目录结构异常可能导致后续构建失败。

### 解决方案

- 重写 Windows Maven Wrapper 启动脚本。
- 统一 Maven 3.9.16。
- 使用 CRLF，兼容 Windows CMD。
- Maven 分发和本地仓库放在项目 E 盘。
- `build_all.ps1` 直接调用项目内 `.mvnw.cmd`。
- 不再在构建过程中删除不确定归属的用户 Maven 目录。

---

## 22. 主要新增或修改的模块

### Python

| 文件/模块 | 作用 |
|---|---|
| `reasonix/history/store.py` | SQLite 会话、消息、检查点、变更和工作流 |
| `reasonix/agent/runner.py` | 多轮消息、工具继续执行和变更记录 |
| `reasonix/control/controller.py` | 会话恢复、变更日志、撤销、工作流 |
| `reasonix/diff/__init__.py` | Unified Diff 和增删行统计 |
| `reasonix/skill/__init__.py` | Skills 发现与渐进式披露 |
| `reasonix/desktop/__init__.py` | 桌面 WebSocket 协议和动作 |
| `reasonix/tool/builtin/*` | 写文件、编辑和删除的预览与记录 |

### React 前端

| 文件 | 作用 |
|---|---|
| `desktop/python-frontend/src/App.tsx` | 主工作台与全局状态 |
| `desktop/python-frontend/src/protocol.ts` | 前后端类型和协议 |
| `desktop/python-frontend/src/components/ToolsPanel.tsx` | 工具时间线与 Diff |
| `desktop/python-frontend/src/components/WorkflowModule.tsx` | 工作流界面 |
| `desktop/python-frontend/src/App.css` | 模块、Diff、Workflow、Skills 样式 |

### Electron

| 文件 | 作用 |
|---|---|
| `desktop/electron/main.js` | 后端启动、首次供应商配置、凭据加密、加载日志 |
| `desktop/electron/preload.js` | 安全 IPC 桥 |
| `desktop/electron/package.json` | Axiom 产品名、NSIS 和资源打包 |

### Java

| 文件/模块 | 作用 |
|---|---|
| `SandboxExecutor` | 严格策略、资源与网络防护 |
| `WindowsSandbox` | Job Object 和进程树守卫 |
| `GuardianService` | Guardian 结果处理和安全日志 |
| `application.yml` | 本地监听和严格模式 |
| `mvnw.cmd` | E 盘 Maven 构建入口 |

### 构建

| 文件 | 作用 |
|---|---|
| `build_all.ps1` | Python、前端、Java、Electron 统一构建 |
| `build_all.bat` | Windows 快捷入口 |

---

## 23. 最终交付物

### 推荐安装包

```text
E:\reasonix\axiom-build\Axiom Setup 0.2.0.exe
```

### 完整免安装版

```text
E:\reasonix\axiom-build\desktop
```

启动文件：

```text
E:\reasonix\axiom-build\desktop\Axiom.exe
```

### Python 核心

```text
E:\reasonix\axiom-build\axiom-engine.exe
```

### Java 安全服务

```text
E:\reasonix\axiom-build\security\axiom-security.jar
```

---

## 24. 验证清单

| 验证项 | 结果 |
|---|---|
| Python 全量测试 | 100 passed |
| Java 全量测试 | 66 passed |
| React 测试 | 6 passed |
| Ruff | passed |
| Mypy strict | passed |
| Vite build | passed |
| npm audit | 0 vulnerabilities |
| Electron build | passed |
| NSIS installer | generated |
| Python EXE smoke test | passed |
| Electron 实际启动 | passed |
| Renderer DOM 检查 | passed |
| Python 桌面桥连接 | passed |
| 无 API 环境变量首次启动 | 显示供应商配置 |
| 临时运行数据清理 | completed |

---

## 25. 当前仍需明确的限制

以下不是本轮遗漏，而是当前架构的真实边界：

1. **Windows 沙箱不是 AppContainer 级隔离。**  
   高风险不可信代码应放入容器、Windows Sandbox 或虚拟机。

2. **免安装版不能只复制一个 EXE。**  
   Electron 运行依赖完整 `desktop` 目录。

3. **安装包目前没有配置 Windows 代码签名。**  
   在其他电脑上可能触发 SmartScreen。正式分发前应配置可信代码签名证书。

4. **Workflow Lite 当前仅支持串行步骤。**  
   条件分支、DAG 和并行执行尚未实现。

5. **MCP 工具是否可用还取决于外部 MCP 服务。**  
   外部服务断开时，Axiom 只能报告连接或加载失败，不能保证第三方服务本身可用。

6. **模型供应商兼容性依赖其 API。**  
   OpenAI Compatible 服务必须正确实现项目所需的聊天和工具调用协议。

7. **首次完整构建仍可能需要联网下载依赖。**  
   后续构建会优先复用 E 盘缓存。

---

## 26. 后续优化优先级

### P0：发布可靠性

- 为安装包配置代码签名。
- 增加安装、启动、后端连接、发送消息的自动化端到端测试。
- 给渲染失败增加可见的本地错误页，而不只记录日志。
- 增加端口占用自动重试和清晰提示。

### P1：安全

- 引入 Windows AppContainer 或隔离执行服务。
- 对命令执行增加更细的目录和网络白名单。
- 增加 API Key 更新、删除和凭据迁移界面。
- 为审批策略增加项目级可信规则管理。

### P1：Agent 体验

- 工作流条件分支、失败重试和步骤级重跑。
- 更细的 Tool Call 过滤、搜索和导出。
- 会话分支、标签和搜索。
- 多文件 Diff 汇总与逐文件撤销。

### P2：MCP 与 Skills

- MCP 服务启停、编辑和连接测试界面。
- 展示每个 MCP 服务贡献的工具列表。
- Skills 启用/禁用和作用域管理。
- Skill 冲突和版本诊断。

### P2：前端

- 虚拟化长会话和长工具列表。
- 响应式布局和键盘快捷键。
- 深色/浅色主题变量体系。
- 更完整的空状态、错误态和加载骨架。

---

## 27. 维护建议

每次发布前至少执行：

```powershell
cd E:\reasonix
.\build_all.ps1
```

并人工确认：

1. 使用一个全新的用户数据目录启动。
2. 首次供应商配置窗口正常出现。
3. 保存密钥后后端能够重启。
4. 发送一条纯聊天消息。
5. 执行一个只读工具。
6. 执行一个需要审批的写工具。
7. 批量审批正常。
8. 工具执行后能够继续对话。
9. Diff 和撤销正常。
10. 关闭并重开应用后会话可以恢复。
11. Workflow 能运行和取消。
12. 日志中不存在 API Key 和不必要的模型原文。

---

## 27.1 输入区审批、斜杠命令与工作区引用补全

2026-07-24 对照三个参考项目后，继续补齐了 Composer 交互层：

- 参考 DeepSeek-Reasonix 的分组 Slash Menu，将命令、会话、审批模式、导航、集成和 Skills 分组展示。
- 参考 Hermes 的审批浮动兜底条，把当前待审批操作固定到会话输入区上方，同时在消息流中保留历史记录。
- 参考 CodeWhale 将 `/` 与 `@` 分成两套补全逻辑，并把文件遍历放到后台执行。

当前输入区支持：

- `/review`、`/fix`、`/test`。
- `/new`、`/undo`。
- `/ask`、`/allow`、`/deny`。
- `/tools`、`/sessions`、`/workflows`、`/status`、`/settings`。
- `/mcp`、`/skills`、`/help`。
- 自动把已发现的 Skills 加入 `/` 菜单。
- `@文件名` 后台搜索工作区文件和目录。
- 方向键选择、Tab 补全、Esc 关闭。
- 审批快捷键 `Ctrl+Enter` 允许一次、`Esc` 拒绝。

工作区检索最多扫描 25,000 个条目、最多返回 40 个结果，并排除 `.git`、`node_modules`、缓存、构建目录和安装产物，避免大仓库阻塞前端或显示 DLL 等噪声。

真实安装版验证结果：

- `/` 菜单能够显示 `/review`、`/allow` 和动态 Skills。
- `@comp` 能找到 `Composer.tsx`。
- 结果中不再包含 `axiom-build` 或 `reasonix-build`。
- 桌面桥状态为在线，阶段显示 `idle`，重连后不再残留 `offline`。

## 28. 最终结论

经过本轮审查和修复，Axiom 已从“能够展示基础聊天界面的原型”推进为具备以下能力的本地 Agent 工作台：

- 可安装、可实际启动的 Windows 桌面应用。
- 多模型供应商首次配置。
- 安全保存 API Key。
- 可持续多轮工具会话。
- Ask / Allow / Deny 与批量审批。
- 工具时间线、Diff 和冲突保护撤销。
- SQLite 会话与崩溃恢复。
- 可保存和运行的轻量工作流。
- Skills 与 MCP 诊断。
- Python 与 Java 双层安全控制。
- 可重复执行的统一打包流程。

后续工作的重点应从“补齐基础功能”转向“发布可靠性、Windows 强隔离、端到端测试和高级工作流”，避免再次在没有运行验证的情况下仅以“构建成功”判断桌面应用可用。

## 28. 首次安装 API 引导与 503 服务商过载处理

### 问题

安装后的桌面端以前只看“后端是否能解析出一个 provider”。如果机器上已有环境变量、用户级配置或项目配置，前端会把它当成已配置，从而跳过首次服务商/API 引导。用户会直接进入会话，一旦所选服务商返回 `503 service_unavailable_error`，界面只展示原始异常，不会提示可以切换 API 服务商。

### 修复

- Electron provider 状态拆分为 `configured`、`managed`、`needsSetup` 和 `externalConfigured`。
- `configured` 仍表示后端可用；`needsSetup` 表示桌面端还没有完成安全 API 引导。
- 前端首次启动改为根据 `needsSetup` 打开服务商设置弹窗，因此即使检测到外部环境变量，也会先提醒用户选择/确认 API 服务商。
- 前端识别 `503`、`service_unavailable`、`too busy` 和供应商建议切换服务的错误文本，自动打开服务商设置弹窗，并把原始错误翻译为可操作提示。
- API Key 仍只通过 Electron IPC 交给主进程，主进程用 `safeStorage` 加密后写入用户数据目录；不会写入前端资源、`app.asar` 或安装包。

### 验证

- `npx vitest run --pool=forks --maxWorkers=1 --no-file-parallelism`：10 passed。
- `npm run build`：前端构建通过。
- Electron installer rebuild：生成 `Axiom Setup 0.2.0.exe`，时间戳 `2026-07-24 14:51:30`。
- 真实便携版烟测：`E:\reasonix\axiom-build\desktop\Axiom.exe` 首屏存在 `.axiom-provider-overlay`、`.axiom-provider-modal` 和 API Key 输入框，页面不是白屏。
## 29. 模型供应商多协议兼容

### 问题

用户可能使用同一个服务商的不同 API 协议格式，例如 DeepSeek 同时提供 OpenAI-compatible 和 Anthropic-compatible 入口。旧版桌面设置只有一个模糊的兼容供应商入口，容易把 OpenAI provider 和 `/anthropic` base URL 混用，导致 404。

### 修复

- 桌面端供应商预设拆分协议格式：DeepSeek OpenAI、DeepSeek Anthropic、OpenAI、Anthropic、OpenAI Compatible、Anthropic Compatible。
- Electron 写出的 `provider.toml` 会根据所选预设设置 `kind = "openai"` 或 `kind = "anthropic"`。
- DeepSeek OpenAI 格式默认使用 `https://api.deepseek.com`；DeepSeek Anthropic 格式默认使用 `https://api.deepseek.com/anthropic`。
- 保存逻辑增加自动纠错：DeepSeek OpenAI 误填 `/anthropic` 时会回正；DeepSeek Anthropic 误填根地址时会补 `/anthropic`。
- 首次设置 UI 显示协议格式标签，避免用户只看到供应商名称而不知道实际协议。

### 验证

- 前端交互测试：`npx vitest run --pool=forks --maxWorkers=1 --no-file-parallelism`，11 passed。
- Electron 打包契约测试：`python -m pytest reasonix-py\tests\unit\test_electron_packaging.py -q`，11 passed。
- Electron installer rebuild 成功。
- 真实 exe 首启烟测确认配置弹窗包含 DeepSeek OpenAI、DeepSeek Anthropic、OpenAI Compatible、Anthropic Compatible。

## 30. 清理旧 Wails/Go 桌面遗留代码

### 问题

GitHub 语言统计显示 Go 占比最高，但当前 Axiom 的实际运行链路已经是 Electron + React + Python + Java。`desktop/` 根目录下的 Go 文件来自旧 Wails 桌面壳，没有被当前 `build_all.ps1` 或 Electron 打包路径使用，还会误导仓库语言统计和维护判断。

### 修复

- 删除旧 Wails/Go 桌面源文件、旧 Wails README、`desktop/wails.json` 和对应 macOS Objective-C 辅助文件。
- 保留当前使用的 `desktop/electron`、`desktop/python-frontend`、`reasonix-py`、`reasonix-java`。
- 保留 `desktop/installer.nsi` 与 `desktop/launcher.bat`，因为现有构建脚本仍包含 legacy installer 路径。

### 验证

- `git ls-files '*.go' '*.m' desktop/wails.json desktop/README.md`：无输出。
- `desktop/` 根目录只剩 `electron`、`python-frontend`、`.gitignore`、`installer.nsi`、`launcher.bat`。
- 仓库语言体积重新排序后 Python 位于第一，Go 不再计入。
- `python -m pytest reasonix-py\tests\unit\test_electron_packaging.py -q`：11 passed。

## 31. Java 安全服务接入桌面实际执行链路

### 原问题

Java 安全模块虽然能够独立运行，但 Electron 首次启动没有拉起它，Python 的桌面 `bash` 工具也仍可能走本地执行，因此“Java 沙箱”没有真正处于 Axiom.exe 的工具执行路径中。Java gRPC 端口也缺少每次启动独立的调用凭据，不能可靠区分本应用与其他本机进程。

### 修复

- Electron 首次启动时先启动 Java 安全服务，再启动 Python 桌面桥；保存供应商配置重启时先关闭旧 Java/Python 进程，避免后台进程残留。
- 安装包同时携带 `reasonix-security.jar` 和由 `jlink` 生成的私有 Java 运行时，终端用户无需另装 JDK/JRE。
- Electron 每次启动生成 256 位随机令牌，通过进程环境交给 Java 与 Python；所有安全 gRPC 请求都携带 `x-axiom-security-token`，Java 使用常量时间比较并拒绝缺失或错误令牌。
- 桌面端 `bash` 统一经过“前端 Ask/Allow/Deny → Python 审批 → Java Permission Gate → Java guarded process”链路。Java 不可用时命令 fail closed，但工具结果会返回会话，后续对话仍可继续。
- 修复 gRPC 依赖版本不一致导致 fat JAR 启动时报 `NoClassDefFoundError` 的问题，统一通过 gRPC BOM 管理版本。
- 后端冷启动等待由 10 秒提高到 45 秒，并为 WebSocket 探测增加 socket timeout，兼容 PyInstaller one-file 首次解压的启动延迟。

### 安全边界

当前 Windows 后端提供命令策略、敏感环境变量移除、超时、输出上限以及 Job Object/进程树守护；它不是 AppContainer 级的文件系统或网络隔离。严格模式会拒绝要求当前后端无法保证的隔离策略，界面使用“安全执行”而不是夸大为“完全沙箱”。

### 验证

- Python 定向测试：23 passed。
- Python 全量测试：106 passed。
- React 前端测试：11 passed。
- Java Maven 测试：68 passed。
- 使用打包目录内私有 `javaw.exe`、安全 JAR 和正确令牌执行 `echo packaged-java-ok` 成功。
- 使用错误令牌调用时返回 gRPC `UNAUTHENTICATED`。
- 完整构建生成 `reasonix-build\desktop-electron\Axiom Setup 0.2.1.exe`，并确认安装资源中同时存在 Python 后端、Java 安全 JAR 和私有 Java 运行时。
