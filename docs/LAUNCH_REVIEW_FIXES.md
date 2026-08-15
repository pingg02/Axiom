# Axiom 上线前修复记录 与 DeepSeek Harness 对标建议

> 日期：2026-08-11
> 范围：上线前审查发现的阻断/一致性问题修复，以及对照 `E:\deepseek-harness`（DeepSeek Harness, DSH）的工程实践借鉴。

## 1. 本轮修复（已完成并验证）

### 1.1 P0：Python 依赖缺失导致全新环境启动崩溃

- `reasonix-py/pyproject.toml`：
  - 新增 `protobuf>=7.35,<8`。仓库内已提交的 `reasonix/grpc/security_pb2.py` 是 protobuf 7.35.0 生成的代码，运行期要求 `protobuf >= 7.35`；此前未声明该依赖，干净机器 `pip install -e .` 后导入即崩（`ModuleNotFoundError` / `VersionError`）。
  - `grpcio>=1.60,<2` 收紧为 `grpcio>=1.82.1,<2`，与 `security_pb2_grpc.py` 内嵌的 `GRPC_GENERATED_VERSION = '1.82.1'` 一致，避免低版本运行时 import 即抛 `RuntimeError`。

### 1.2 版本号统一

- `reasonix-java/pom.xml`：`<version>0.1.0</version>` → `0.2.1`。
- `reasonix-py/reasonix/cli/cli.py`：删除硬编码 `VERSION = "0.2.1"`，改为 `from reasonix import __version__`，单一事实来源。

### 1.3 遗留 "Reasonix" 品牌清理（安装包一致性）

- `desktop/installer.nsi`：产品名/版本/输出文件全部改为 Axiom 0.2.1（`Axiom-windows-amd64-installer.exe`），移除 `EnVar::AddValue "PATH"`（同时去掉对外部 EnVar NSIS 插件的依赖）与安装目录误删风险。
- `build_all.ps1`：第 6 步复制的安装包文件名同步改为 `Axiom-windows-amd64-installer.exe`。

### 1.4 安全：桌面 WebSocket 桥增加 per-launch token 鉴权

此前 `ws://127.0.0.1:<port>` 无任何鉴权，任何本机进程或浏览器页面都能连接并驱动 agent（send/approve_all/set_permission_mode/bash）。现已对齐 Java gRPC 层已有的 token 模型：

- `reasonix-py/reasonix/desktop/__init__.py`：
  - `BridgeClient` 改为**惰性构建 controller**：连接后必须先发 `{"action":"auth","token":...}`，成功前拒绝一切其他动作（返回 `authentication required`），token 错误返回 `invalid security token`。
  - 认证成功后才构建 controller 并回发 status；Electron 就绪探测（无 token 的 TCP 握手）不再白白构建 provider/MCP，代价为零。
  - `run_server` 新增 `required_token` 参数，默认取环境变量 `AXIOM_SECURITY_TOKEN`；未设置时（CLI/dev 模式）保持开放，向后兼容。
- `desktop/electron/main.js`：新增 `ipcMain.handle('bridge:token', ...)` 返回每启动随机生成的 token。
- `desktop/electron/preload.js`：暴露 `getBridgeToken`。
- `desktop/python-frontend/src/App.tsx`：`onopen` 后先发 auth 消息再进入正常流程。
- 新增测试：`tests/unit/test_desktop.py`（鉴权三件套）、`tests/unit/test_electron_packaging.py`（token 链路契约）、`App.test.tsx`（首消息改为 auth）。

### 1.5 验证结果（全部实测通过）

| 项 | 结果 |
|---|---|
| 干净 venv `pip install -e .` + 导入 | ✅（protobuf 修复生效） |
| Python 全量测试 | ✅ 110 passed（原 106 + 新增 4） |
| Ruff / Mypy(strict) | ✅ 通过 |
| 前端 vitest | ✅ 11 passed |
| 前端 vite build | ✅ 通过 |
| Java `mvnw test` | ✅ 68 passed |
| Java `mvnw compile`（版本号改动后） | ✅ 通过 |

## 2. 尚未修复、上线前仍建议处理

1. **Windows 安装包代码签名**（SmartScreen）：需要 Authenticode 证书，接入 electron-builder 签名或 CI 签名服务。
2. **正式应用图标**：`desktop/electron/` 下无 `icon.png` / `build/icon.ico`，安装包与托盘用的是默认图标。
3. **工作区/项目目录选择器**：目前工作区 = `process.cwd()`，安装版从开始菜单启动会以安装目录为工作区，写文件会失败。建议加目录选择器并透传 `REASONIX_WORKSPACE`。
4. **`serve` 模式 FastAPI `/chat` 无鉴权**：`ServeConfig.auth_required` 已存在但未启用；启用后需前端配合。
5. **docker-compose 已失效**：服务绑 127.0.0.1 容器内不可达、Redis/RabbitMQ 无鉴权直出宿主机、Python 容器只跑 serve 却声明 9092。若上线目标含 docker，需要重写；否则建议标注为 dev-only 或删除。

## 3. 对标 DeepSeek Harness（E:\deepseek-harness）可借鉴的优化

DSH 是 DeepSeek 官方的 agent harness：monorepo（pnpm workspace）、"一切皆插件"（Cordis）、发布/CI/文档体系非常成熟。以下是按"直接可用 → 中期 → 长期"排列的可借鉴点。

### 3.1 直接可用（已在 2026-08-11 落地）

**A1. 全仓单版本线 + 版本一致性 gate** ✅ 已实现
DSH release.yml 强制所有包共用一个版本号，并有 `verify-package-invariants` 一类的 gate 在 CI 校验。Axiom 现在版本号分散在 5+ 处靠手工同步（已实际出现 Java 0.1.0 vs 产品 0.2.1 漂移）。
→ 已落地：`scripts/verify_versions.py` 断言 pyproject / pom.xml / package.json×2 / preload.js / installer.nsi / `__init__.py` 七处版本一致，本地验证通过（全部 0.2.1）。

**A2. 发布流水线自动化（两阶段）** ✅ 已实现
DSH 的做法：PR/推送即"打包验证"（不发布），打 `dsh-v*` tag 后手动触发发布，且发布只消费已验证的打包产物。
→ 已落地：
- `.github/workflows/ci.yml`：PR/推送在 windows-latest 上跑版本/密钥 gate + Python/Java/前端全量测试 + `build_all.ps1` 完整构建并上传安装包 artifact。
- `.github/workflows/build-windows.yml`：可复用的 Windows 构建工作流（CI 与发布共用同一构建，保证发布消费的就是验证过的产物）。
- `.github/workflows/release.yml`：打 `v*` tag 后自动把安装包 attach 成 draft Release（人工确认后发布）。
- 需推送到 GitHub 后生效；本地 YAML 语法已验证。

**A3. "gates" 单命令质量门** ✅ 已实现
DSH `scripts/run-gates.ts` 把测试、静态检查、文档校验、包不变量统一成具名模式（`check-all` 等），CI 与本地共用，pre-push 由 lefthook 触发。
→ 已落地：`scripts/verify_launch.ps1`（一条命令跑 Python pytest + Java mvn test + 前端 vitest/vite + 版本一致性 + `scripts/scan_secrets.py` 密钥扫描），支持 `-InstallDeps / -SkipPython / -SkipJava / -SkipFrontend`，任何一步失败即非零退出。CI 的 verify job 与该脚本共用同一组检查。

**A4. 构建链先测后打包** ✅ 已实现
`build_all.ps1` 目前 `mvn package -DskipTests`。
→ 已改为 `mvnw.cmd test` 通过后再 `package -DskipTests`；另增加 `AXIOM_BUILD_USE_PYTHON=1` 环境变量开关（CI 在 actions/setup-python 下强制使用 PATH 上的 python，避免系统 `py` launcher 版本干扰）。

### 3.2 中期（架构/安全对齐）

**B1. 沙箱"能力 + Provider"抽象 + 真实内核证明测试**
DSH 的 sandbox/shell 是 capability + 可插拔 provider（Linux bwrap/Landlock、macOS Seatbelt 各自实现同一接口，fail-closed），并有独立 `sandbox.yml` 在每个真实内核上做"关键证明"（keyless real-kernel confinement proofs），还**断言测试真的运行了**（防止 runner 缺失时 self-skip 造成假绿）。Axiom 的 Java 沙箱是 Windows 单实现 + 正则黑名单。
→ 建议：把"策略守卫"与"OS 强隔离"分成两层接口；黑名单策略补一组绕过尝试测试（大小写变体、`^`/反引号转义、`%COMSPEC%`、编码绕过）并在 CI 的 windows runner 上断言这些测试真的执行。

**B2. 凭据来源可视化**
DSH 的 credentials 是"引用 + provider"，且能列出谁引用了哪个凭据。Axiom 的 provider.toml（只存 env 名）+ safeStorage 设计思路一致、已经做对了；可补的是诊断页展示密钥来源（managed / 环境变量 / 用户级 config / 项目 config），并支持"删除/轮换凭据"（DSH 的 credentials 有完整生命周期）。

**B3. 决策记录（Agent Notes）替代巨型历史文档**
DSH 用 `.agents/notes/{implemented,proposed,rejected,archived}` 存带日期的决策记录：一篇一主题、说明"为什么/放弃了什么/如何验证"。Axiom 的 `docs/AXIOM_PROJECT_ISSUES_AND_SOLUTIONS.md` 是 1100 行按时间堆叠的历史文档，已出现过时内容（"最终交付物"还写着 0.2.0 的产物名）。
→ 建议：把该文档拆成"当前架构事实"（README/架构页）+ "决策记录"（按主题的小文件），历史章节归档。

### 3.3 长期（文档与测试文化）

**C1. 文档预算 + 链接/产物名校验**
DSH 的 `verify-md-links`、`verify-doc-budgets` 在 CI 里查断链和文档规模。Axiom 文档已出现断链级过时（产物名/版本号与仓库不一致）。
→ 建议：加 `verify_docs.py`：检查 README/docs 中出现的安装包名、jar 名、版本号与仓库实际一致；断链检查可用现成工具（如 markdown-link-check）接入 CI。

**C2. 从源码生成目录并做 freshness 门禁**
DSH 从源码生成 tool-catalog / config-catalog / persistence-catalog，生成物由 CI 校验"已更新"。Axiom 已有 `protocol.ts`（前端）与 Python event 类型，且有 `test_event_contract.py` 防漂移；可以进一步生成一份"工具/事件目录"文档放进 docs/，替换手写的清单。

**C3. 不变量测试文化**
DSH 有大量 spec 测试专门"保护仓库不变量"（package-invariants、expected-filenames、cordis-config-files）。Axiom 的 `test_electron_packaging.py` 已是这个模式，值得推广：例如"git 中不得出现密钥模式""发布目录只有一个安装包""版本号一致""安装包必须包含 Java 运行时与安全 jar"。

**C4. 预发布立场：不要为兼容保留 shim**
DSH 在首个 tag 前明确"foundation over blast radius"：没有外部消费者时宁可重命名/重构，不留兼容层。Axiom 仍保留整套 legacy "Reasonix" 启动脚本/NSIS/构建脚本，与新品牌并存，正是这类历史包袱——建议在首个正式发布前删除或明确退役，避免用户装到旧版命名/旧版安装包。

## 4. 结论

- 阻断级依赖问题、版本漂移、遗留品牌、WebSocket 鉴权均已修复并通过全链路验证。
- 上线前还差三件事：**代码签名**、**正式图标**、**工作区选择器**（以及 serve/docker 的明确处置）。
- 对标 DSH，最高性价比的三项是：**全仓版本一致性 gate、两阶段自动化发布流水线、单命令质量门（verify_launch）**；安全上建议把沙箱测试做成"真实内核证明 + 防假绿"。

## 5. 架构问题：Axiom 是否需要"最小化内核、一切皆插件"？

> 结论：**不需要，而且上线前更不应该做。** Axiom 的现状架构（注册表式扩展点）已经覆盖了它需要的"插件能力"；DSH / pi 的"一切皆插件/全链路 hooks"是为**平台型产品**（使用者是写扩展的开发者）设计的，与 Axiom（终端用户桌面工作台）的定位不匹配。

### 5.1 对比三个项目的内核策略

| 项目 | 内核策略 | 目标用户 | 插件能力从哪来 |
|---|---|---|---|
| DeepSeek Harness | Cordis 组合：无特权内核，一切皆插件（服务/事件/效果），运行时可挂载/卸载 | 开发者、agent 平台使用者 | 写插件 = 挂载一个 Cordis 插件行 |
| pi-agent (pi-mono) | "一个核心循环 + 全链路 hooks"：session/agent/tool/provider 每层可拦截、可替换 | 开发者、扩展作者 | 写 hooks 扩展 |
| Axiom | 注册表式扩展点：工具注册表、provider 工厂注册、skill 渐进披露、MCP 加载器、Java 安全服务独立进程 | **终端用户**（Windows 桌面 AI 工作台） | 用户不写扩展 |

### 5.2 为什么 Axiom 不需要"一切皆插件"

1. **收益趋近于零**：一切皆插件的价值是第三方生态、运行时热装、按配置组合能力、多前端/多运行时复用内核。Axiom 的"用户"不开发插件，这些收益 Axiom 拿不到。
2. **成本是重写**：runner/controller/事件系统全部要按"可挂载单元"重拆，110 个 Python 测试、桌面桥协议、PyInstaller/Electron 打包链全部重做，上线推迟数月、回归风险爆炸。
3. **"最小化内核"与 Axiom 的卖点相悖**：Axiom 的卖点是"内置 16+ 工具开箱即用 + 双层安全"。最小化内核意味着把这些内置能力拆成插件，对终端用户零可感知收益。
4. **Axiom 已有轻量插件化的正确形态**：`Registry`（工具）、`register_provider()`（模型厂商）、skill 发现器、MCP 加载器、独立 Java 进程——这些已经是"扩展点"，只是没有 hooks 化和动态加载化，而这两点 Axiom 用不上。

### 5.3 值得借鉴的"轻"做法（不重写内核）

- **把扩展点固化成契约**：写一份 `docs/EXTENSIONS.md`，定义 tool / provider / skill / mcp 四类接口的"能做什么、不能做什么、如何注册"，让内核边界稳定——这是 DSH 文档纪律里最可移植的部分。
- **配置驱动而非代码插件**：provider 预设、权限策略、工作流已经都是数据（provider.toml / 权限模式 / 工作流存储），继续保持"改配置即可组合能力"，这正是 DSH"一切皆插件"想达到的可组合性的低成本版本。
- **未来真要三方生态时，从工具层 hooks 开始**：pi 最有价值的一层是 `tool_call / tool_result` 拦截（参数修改、阻断、脱敏）。Axiom 若未来需要，可以先在这一层加 hooks，不需要 Cordis 级重写。
- **架构演进放在 v1.1+**：先靠本轮落地的工程化（版本 gate、CI、质量门）保证上线质量；架构改造必须有明确的用户故事驱动（例如"第三方工具市场"），而不是为了架构时髦。

## 6. 依赖与 API 调用探查（2026-08-11 第二轮）

> CI/CD = 流水线自动构建+测试（CI）+ 自动发布（CD）。本轮的产出是：把依赖审计与 API 契约检查纳入流水线，并修复探查到的问题。

### 6.1 依赖审计结果与修复

| 层 | 工具 | 结果 | 处置 |
|---|---|---|---|
| Python | `pip check` | ✅ 无损坏依赖 | — |
| Python | `pip-audit` | ⚠️ starlette 0.52.1 共 7 个已知漏洞（PYSEC-2026-161/248/249/2280/2281），修复版本在 1.x | **pyproject 上限 `<1` 挡死了安全修复**，fastapi/sse-starlette 均不限制 starlette 1.x → 改为 `starlette>=1.3.1,<2`；实测 starlette 1.6.0 下 112 个测试全过 |
| 前端 | `npm audit` | ⚠️ postcss（中）+ undici（高×2） | `npm audit fix` → 0 vulnerabilities（lock 已更新，vitest/vite build 回归通过） |
| Electron | `npm audit` | ⚠️ undici 高×4 | `npm audit fix` → 0 vulnerabilities |
| Java | `mvn dependency:tree` | ✅ 无版本冲突 | 已通过 gRPC BOM 统一（此前修过） |

### 6.2 API 调用链路核查

| 链路 | 结论 |
|---|---|
| `security.proto` ↔ Python `security_pb2.py` | 字段号/类型/服务方法逐一比对**一致**；但 Python 侧是手提交的生成文件，存在漂移风险 → 新增 `scripts/verify_proto_contract.py`（以 proto 为单一事实来源比对 pb2 描述符），实测 8 messages / 4 rpcs 全部匹配 |
| 前后端事件协议（Python `event_to_frontend_dict` ↔ `protocol.ts`） | 字段一致；小项：Python `UsageInfo.cost_usd` 前端类型未声明（运行时无碍） |
| Electron IPC（main.js ↔ preload ↔ 前端） | `provider-setup:status/save`、`bridge:token` 三条链路齐全，已有契约测试覆盖 |
| Provider 外部 API | **发现 bug：`generate()/generate_stream()` 的 `temperature`/`max_tokens` 参数被静默丢弃**（配置 `[agent] temperature` 从未生效，构造时固定 0.0）→ 已修复：每次调用通过 `.bind()` 透传，新增 2 个测试 |
| `web_fetch` 工具 | **SSRF 风险**：只校验 URL 前缀，可访问 127.0.0.1/内网/云元数据（169.254.169.254）→ 已修复：默认拒绝环回/私有/链路本地/保留地址（`AXIOM_ALLOW_PRIVATE_WEB_FETCH=1` 可显式放开）；User-Agent 硬编码 "0.2" → 改用 `__version__`，新增 6 个测试 |

### 6.3 流水线新增检查（verify_launch / CI 已接入）

- `pip-audit --skip-editable`（Python 依赖漏洞审计，需联网）
- `npm audit --audit-level=moderate`（前端 + Electron）
- `scripts/verify_proto_contract.py`（gRPC 契约）
- 本地可用 `-SkipAudit` 跳过联网审计。

### 6.4 遗留建议（未在本轮修复）

- **web_fetch 的 DNS 重绑定**：阻止逻辑基于 getaddrinfo 解析结果，DNS rebinding 仍可能绕过；彻底方案是出网代理或由 Java 沙箱统一管控网络（与沙箱路线合并）。
- **`cost_usd` 前端类型声明**：protocol.ts 补 `cost_usd?: number`（一行，低优先级）。
- **electron-builder 依赖**：`npm audit` 只覆盖 npm 依赖；Electron 自身二进制（Chromium）漏洞需跟踪 Electron 发布节奏（当前 ^43）。
