const { app, BrowserWindow, Tray, Menu, ipcMain, safeStorage } = require('electron')
const crypto = require('crypto')
const fs = require('fs')
const net = require('net')
const path = require('path')
const { spawn } = require('child_process')

let mainWindow = null
let tray = null
let pythonProcess = null
let javaProcess = null
let bridgePort = 9092
let securityPort = 9091
let securityToken = ''
let workspaceCwd = process.cwd()

const PROVIDER_PRESETS = {
  deepseek: {
    label: 'DeepSeek',
    format: 'OpenAI',
    kind: 'openai',
    envName: 'DEEPSEEK_API_KEY',
    defaultModel: 'deepseek-v4-flash',
    defaultBaseUrl: 'https://api.deepseek.com',
  },
  deepseek_anthropic: {
    label: 'DeepSeek',
    format: 'Anthropic',
    kind: 'anthropic',
    envName: 'DEEPSEEK_API_KEY',
    defaultModel: 'deepseek-v4-flash',
    defaultBaseUrl: 'https://api.deepseek.com/anthropic',
  },
  openai: {
    label: 'OpenAI',
    format: 'OpenAI',
    kind: 'openai',
    envName: 'OPENAI_API_KEY',
    defaultModel: 'gpt-4.1',
    defaultBaseUrl: '',
  },
  anthropic: {
    label: 'Anthropic',
    format: 'Anthropic',
    kind: 'anthropic',
    envName: 'ANTHROPIC_API_KEY',
    defaultModel: 'claude-sonnet-4-5',
    defaultBaseUrl: '',
  },
  compatible: {
    label: 'OpenAI Compatible',
    format: 'OpenAI',
    kind: 'openai',
    envName: 'AXIOM_COMPATIBLE_API_KEY',
    defaultModel: '',
    defaultBaseUrl: '',
  },
  anthropic_compatible: {
    label: 'Anthropic Compatible',
    format: 'Anthropic',
    kind: 'anthropic',
    envName: 'AXIOM_ANTHROPIC_COMPATIBLE_API_KEY',
    defaultModel: '',
    defaultBaseUrl: '',
  },
}

const gotLock = app.requestSingleInstanceLock()
if (!gotLock) {
  app.quit()
}

function logLine(message) {
  try {
    const logPath = path.join(app.getPath('userData'), 'axiom-desktop.log')
    fs.mkdirSync(path.dirname(logPath), { recursive: true })
    fs.appendFileSync(logPath, `${new Date().toISOString()} ${message}\n`)
  } catch {
    // Logging is diagnostic only.
  }
}

function providerPaths() {
  const dir = path.join(app.getPath('userData'), 'provider')
  return {
    dir,
    config: path.join(dir, 'provider.toml'),
    metadata: path.join(dir, 'metadata.json'),
    secret: path.join(dir, 'secret.json'),
  }
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, 'utf8'))
  } catch {
    return null
  }
}

function writeFileAtomically(filePath, content) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  const temporary = `${filePath}.${process.pid}.tmp`
  fs.writeFileSync(temporary, content, { encoding: 'utf8', mode: 0o600 })
  fs.renameSync(temporary, filePath)
}

function loadProviderEnvironment() {
  const paths = providerPaths()
  const stored = readJson(paths.secret)
  if (!stored?.envName || !stored?.encrypted) return {}
  if (!safeStorage.isEncryptionAvailable()) {
    logLine('Provider secret exists but OS encryption is unavailable')
    return {}
  }
  try {
    const apiKey = safeStorage.decryptString(Buffer.from(stored.encrypted, 'base64'))
    return apiKey ? { [stored.envName]: apiKey } : {}
  } catch (error) {
    logLine(`Could not decrypt provider secret: ${error.message}`)
    return {}
  }
}

function externalProviderConfigurationDetected() {
  const knownEnvironmentNames = Object.values(PROVIDER_PRESETS).map(item => item.envName)
  if (knownEnvironmentNames.some(name => Boolean(process.env[name]))) return true
  const userConfig = path.join(process.env.APPDATA || '', 'reasonix', 'config.toml')
  const projectConfig = path.join(workspaceCwd, 'reasonix.toml')
  return fs.existsSync(userConfig) || fs.existsSync(projectConfig)
}

function providerSetupStatus() {
  const paths = providerPaths()
  const metadata = readJson(paths.metadata)
  const managed = Boolean(metadata && fs.existsSync(paths.secret) && fs.existsSync(paths.config))
  const externalConfigured = externalProviderConfigurationDetected()
  return {
    configured: managed || externalConfigured,
    managed,
    needsSetup: !managed,
    externalConfigured,
    encryptionAvailable: safeStorage.isEncryptionAvailable(),
    selected: metadata || null,
    presets: Object.entries(PROVIDER_PRESETS).map(([id, preset]) => ({
      id,
      label: preset.label,
      format: preset.format,
      defaultModel: preset.defaultModel,
      defaultBaseUrl: preset.defaultBaseUrl,
    })),
  }
}

function normalizeProviderSetup(providerId, preset, model, baseUrl) {
  let nextModel = model
  let nextBaseUrl = baseUrl
  const normalizedBaseUrl = nextBaseUrl.replace(/\/+$/, '').toLowerCase()

  if (providerId === 'deepseek' && preset.kind === 'openai') {
    if (normalizedBaseUrl === 'https://api.deepseek.com/anthropic') {
      nextBaseUrl = 'https://api.deepseek.com'
    }
  }
  if (providerId === 'deepseek_anthropic' && preset.kind === 'anthropic') {
    if (normalizedBaseUrl === 'https://api.deepseek.com') {
      nextBaseUrl = 'https://api.deepseek.com/anthropic'
    }
  }

  if ((providerId === 'deepseek' || providerId === 'deepseek_anthropic') && nextModel === 'deepseek-chat') {
    nextModel = 'deepseek-v4-flash'
  }
  return { model: nextModel, baseUrl: nextBaseUrl }
}

function validateProviderSetup(input) {
  const providerId = String(input?.providerId || '')
  const preset = PROVIDER_PRESETS[providerId]
  if (!preset) throw new Error('请选择受支持的模型供应商。')
  const apiKey = String(input?.apiKey || '').trim()
  const rawModel = String(input?.model || preset.defaultModel).trim()
  const rawBaseUrl = String(input?.baseUrl || preset.defaultBaseUrl).trim()
  const { model, baseUrl } = normalizeProviderSetup(providerId, preset, rawModel, rawBaseUrl)
  if (!apiKey || apiKey.length > 8192) throw new Error('请输入有效的 API Key。')
  if (!model || model.length > 200) throw new Error('请输入有效的模型 ID。')
  if (baseUrl) {
    const parsed = new URL(baseUrl)
    if (!['http:', 'https:'].includes(parsed.protocol)) {
      throw new Error('API 地址必须使用 http 或 https。')
    }
  }
  if (baseUrl.length > 2048) throw new Error('API 地址过长。')
  return { providerId, preset, apiKey, model, baseUrl }
}

function saveProviderSetup(input) {
  if (!safeStorage.isEncryptionAvailable()) {
    throw new Error('当前系统无法使用安全凭据存储，Axiom 不会以明文保存 API Key。')
  }
  const { providerId, preset, apiKey, model, baseUrl } = validateProviderSetup(input)
  const paths = providerPaths()
  const providerName = providerId
  const config = [
    `default_model = ${JSON.stringify(providerName)}`,
    '',
    `[providers.${providerName}]`,
    `kind = ${JSON.stringify(preset.kind)}`,
    `api_key_env = ${JSON.stringify(preset.envName)}`,
    `default_model = ${JSON.stringify(model)}`,
    `base_url = ${JSON.stringify(baseUrl)}`,
    '',
  ].join('\n')
  const encrypted = safeStorage.encryptString(apiKey).toString('base64')
  writeFileAtomically(paths.config, config)
  writeFileAtomically(paths.metadata, JSON.stringify({
    providerId,
    label: preset.label,
    format: preset.format,
    model,
    baseUrl,
  }, null, 2))
  writeFileAtomically(paths.secret, JSON.stringify({
    envName: preset.envName,
    encrypted,
  }))
}

function findPythonServer() {
  return {
    bundled: path.join(process.resourcesPath, 'reasonix-server.exe'),
    devBuild: path.join(__dirname, '..', '..', 'reasonix-py', 'dist', 'reasonix.exe'),
  }
}

function findJavaSecurityService() {
  const bundledJavaw = path.join(
    process.resourcesPath,
    'java-runtime',
    'bin',
    process.platform === 'win32' ? 'javaw.exe' : 'java'
  )
  const bundledJava = fs.existsSync(bundledJavaw)
    ? bundledJavaw
    : path.join(process.resourcesPath, 'java-runtime', 'bin', 'java.exe')
  const bundledJar = path.join(
    process.resourcesPath,
    'security',
    'reasonix-security.jar'
  )
  const devJar = path.join(
    __dirname,
    '..',
    '..',
    'reasonix-java',
    'target',
    'reasonix-security.jar'
  )
  if (fs.existsSync(bundledJava) && fs.existsSync(bundledJar)) {
    return { java: bundledJava, jar: bundledJar, bundled: true }
  }
  if (fs.existsSync(devJar)) {
    return {
      java: process.platform === 'win32' ? 'javaw.exe' : 'java',
      jar: devJar,
      bundled: false,
    }
  }
  return null
}

function nearestReasonixWorkspace(startPath) {
  if (!startPath) return null
  let current = path.resolve(startPath)
  if (path.basename(current).toLowerCase() === 'app.asar') {
    current = path.dirname(current)
  }
  if (fs.existsSync(current) && !fs.statSync(current).isDirectory()) {
    current = path.dirname(current)
  }
  while (true) {
    if (fs.existsSync(path.join(current, 'reasonix.toml'))) return current
    if (
      fs.existsSync(path.join(current, 'reasonix-py')) &&
      fs.existsSync(path.join(current, 'desktop')) &&
      fs.existsSync(path.join(current, 'build_all.ps1'))
    ) {
      return current
    }
    const parent = path.dirname(current)
    if (parent === current) return null
    current = parent
  }
}

function findWorkspaceCwd() {
  const candidates = [
    process.env.REASONIX_WORKSPACE,
    process.cwd(),
    __dirname,
    process.resourcesPath,
    path.join(process.resourcesPath || '', '..', '..', '..'),
    path.join(process.resourcesPath || '', '..', '..', '..', '..'),
  ].filter(Boolean)

  for (const candidate of candidates) {
    const found = nearestReasonixWorkspace(candidate)
    if (found) return found
  }
  return process.env.REASONIX_WORKSPACE || process.cwd()
}

function getFreePort(preferredPort) {
  return new Promise((resolve) => {
    const server = net.createServer()
    server.unref()
    server.on('error', () => resolve(0))
    server.listen(preferredPort, '127.0.0.1', () => {
      const address = server.address()
      const port = typeof address === 'object' && address ? address.port : preferredPort
      server.close(() => resolve(port))
    })
  }).then((port) => {
    if (port) return port
    return new Promise((resolve) => {
      const fallback = net.createServer()
      fallback.unref()
      fallback.listen(0, '127.0.0.1', () => {
        const address = fallback.address()
        const fallbackPort = typeof address === 'object' && address ? address.port : preferredPort
        fallback.close(() => resolve(fallbackPort))
      })
    })
  })
}

function waitForBridge(port, timeoutMs = 45000) {
  const started = Date.now()
  return new Promise((resolve) => {
    const check = () => {
      const socket = net.createConnection({ host: '127.0.0.1', port })
      let settled = false
      const retry = () => {
        if (settled) return
        settled = true
        socket.destroy()
        if (Date.now() - started >= timeoutMs) {
          logLine(`Backend bridge did not become ready within ${timeoutMs}ms`)
          resolve(false)
        } else {
          setTimeout(check, 250)
        }
      }
      socket.once('connect', () => {
        const key = crypto.randomBytes(16).toString('base64')
        socket.write(
          `GET / HTTP/1.1\r\n` +
          `Host: 127.0.0.1:${port}\r\n` +
          `Upgrade: websocket\r\n` +
          `Connection: Upgrade\r\n` +
          `Sec-WebSocket-Key: ${key}\r\n` +
          `Sec-WebSocket-Version: 13\r\n\r\n`
        )
      })
      socket.once('data', (data) => {
        if (settled) return
        settled = true
        const ready = data.toString('ascii').startsWith('HTTP/1.1 101')
        socket.destroy()
        if (ready) {
          resolve(true)
        } else {
          setTimeout(check, 250)
        }
      })
      socket.once('error', retry)
      socket.setTimeout(1500, retry)
    }
    check()
  })
}

function waitForTcpPort(port, timeoutMs = 45000) {
  const started = Date.now()
  return new Promise((resolve) => {
    const check = () => {
      const socket = net.createConnection({ host: '127.0.0.1', port })
      let settled = false
      const retry = () => {
        if (settled) return
        settled = true
        socket.destroy()
        if (Date.now() - started >= timeoutMs) resolve(false)
        else setTimeout(check, 250)
      }
      socket.once('connect', () => {
        settled = true
        socket.destroy()
        resolve(true)
      })
      socket.once('error', retry)
      socket.setTimeout(1000, retry)
    }
    check()
  })
}

async function startJavaSecurityService() {
  workspaceCwd = findWorkspaceCwd()
  securityPort = await getFreePort(9091)
  securityToken = crypto.randomBytes(32).toString('hex')
  const service = findJavaSecurityService()
  if (!service) {
    logLine('Java security service is not built; Bash will fail closed')
    return false
  }

  const providerEnvironment = loadProviderEnvironment()
  const args = [
    '-jar',
    service.jar,
    `--grpc.server.port=${securityPort}`,
    '--spring.main.web-application-type=none',
    '--spring.main.banner-mode=off',
  ]
  javaProcess = spawn(service.java, args, {
    cwd: workspaceCwd,
    env: {
      ...process.env,
      ...providerEnvironment,
      AXIOM_SECURITY_TOKEN: securityToken,
      AXIOM_SANDBOX_STRICT: 'true',
      // Guardian is not on the shell hot path. Keep its optional Spring bean
      // constructible without sending a non-DeepSeek provider key anywhere.
      DEEPSEEK_API_KEY: providerEnvironment.DEEPSEEK_API_KEY || 'not-configured',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  })
  const startedProcess = javaProcess
  startedProcess.stdout.on('data', data => {
    const message = data.toString().trim()
    if (message) logLine(`[Java stdout] ${message}`)
  })
  startedProcess.stderr.on('data', data => {
    const message = data.toString().trim()
    if (message) logLine(`[Java stderr] ${message}`)
  })
  startedProcess.on('error', error => {
    logLine(`Java security service failed to start: ${error.message}`)
  })
  startedProcess.on('close', code => {
    logLine(`Java security service exited with code ${code}`)
    if (javaProcess === startedProcess) javaProcess = null
  })
  logLine(`Starting Java security service on port ${securityPort}`)
  const ready = await waitForTcpPort(securityPort)
  if (!ready) {
    logLine('Java security service did not become ready; Bash will fail closed')
    if (javaProcess === startedProcess) javaProcess = null
    startedProcess.kill()
  }
  return ready
}

async function stopJavaSecurityService() {
  const processToStop = javaProcess
  if (!processToStop) return
  javaProcess = null
  const closed = new Promise(resolve => processToStop.once('close', resolve))
  processToStop.kill()
  await Promise.race([closed, new Promise(resolve => setTimeout(resolve, 5000))])
}

async function startPythonServer() {
  const { bundled, devBuild } = findPythonServer()
  workspaceCwd = findWorkspaceCwd()
  bridgePort = await getFreePort(9092)

  const spawnOptions = {
    cwd: workspaceCwd,
    env: {
      ...process.env,
      ...loadProviderEnvironment(),
      REASONIX_WORKSPACE: workspaceCwd,
      REASONIX_PARENT_PID: String(process.pid),
      REASONIX_DESKTOP_CONFIG: providerPaths().config,
      AXIOM_SECURITY_REQUIRED: '1',
      AXIOM_SECURITY_PORT: String(securityPort),
      AXIOM_SECURITY_TOKEN: securityToken,
    },
    stdio: ['pipe', 'pipe', 'pipe'],
  }

  if (fs.existsSync(bundled)) {
    pythonProcess = spawn(bundled, ['desktop', '--host', '127.0.0.1', '--port', String(bridgePort)], spawnOptions)
  } else if (fs.existsSync(devBuild)) {
    pythonProcess = spawn(devBuild, ['desktop', '--host', '127.0.0.1', '--port', String(bridgePort)], spawnOptions)
  } else {
    const pythonCmd = process.platform === 'win32' ? 'python' : 'python3'
    pythonProcess = spawn(
      pythonCmd,
      ['-m', 'reasonix', 'desktop', '--host', '127.0.0.1', '--port', String(bridgePort)],
      { ...spawnOptions, cwd: path.join(__dirname, '..', '..', 'reasonix-py') }
    )
  }

  logLine(`Starting backend on port ${bridgePort}; cwd=${workspaceCwd}`)

  pythonProcess.stdout.on('data', (data) => {
    const text = data.toString().trim()
    if (text) logLine(`[Python stdout] ${text}`)
  })

  pythonProcess.stderr.on('data', (data) => {
    const text = data.toString().trim()
    if (text) logLine(`[Python stderr] ${text}`)
  })

  const startedProcess = pythonProcess
  pythonProcess.on('close', (code) => {
    logLine(`Python server exited with code ${code}`)
    if (pythonProcess === startedProcess) pythonProcess = null
  })
}

async function stopPythonServer() {
  const processToStop = pythonProcess
  if (!processToStop) return
  pythonProcess = null
  const closed = new Promise(resolve => processToStop.once('close', resolve))
  processToStop.kill()
  await Promise.race([closed, new Promise(resolve => setTimeout(resolve, 5000))])
}

function loadFrontend() {
  if (!mainWindow) return
  const frontendPath = path.join(__dirname, 'frontend', 'index.html')
  if (fs.existsSync(frontendPath)) {
    mainWindow.loadFile(frontendPath, {
      query: {
        wsPort: String(bridgePort),
        workspace: workspaceCwd,
      },
    })
  } else {
    mainWindow.loadURL(`http://localhost:8080/desktop?wsPort=${bridgePort}`)
  }
}

async function restartPythonServer() {
  await stopPythonServer()
  await stopJavaSecurityService()
  await startJavaSecurityService()
  await startPythonServer()
  await waitForBridge(bridgePort)
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1320,
    height: 860,
    minWidth: 980,
    minHeight: 680,
    title: 'Axiom',
    autoHideMenuBar: true,
    backgroundColor: '#0b0e13',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true,
    },
  })
  mainWindow.setMenuBarVisibility(false)

  mainWindow.webContents.on('did-finish-load', () => {
    logLine(`Renderer loaded: ${mainWindow?.webContents.getURL() || 'unknown'}`)
  })
  mainWindow.webContents.on('did-fail-load', (_event, code, description, url) => {
    logLine(`Renderer failed to load: code=${code} url=${url} error=${description}`)
  })
  mainWindow.webContents.on('render-process-gone', (_event, details) => {
    logLine(`Renderer process exited: ${details.reason}`)
  })

  loadFrontend()

  mainWindow.on('closed', () => {
    mainWindow = null
  })
}

function createTray() {
  const iconPath = path.join(__dirname, 'icon.png')
  if (!fs.existsSync(iconPath)) return
  tray = new Tray(iconPath)
  const contextMenu = Menu.buildFromTemplate([
    { label: 'Show Axiom', click: () => mainWindow?.show() },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ])
  tray.setToolTip('Axiom')
  tray.setContextMenu(contextMenu)
  tray.on('click', () => mainWindow?.show())
}

app.on('second-instance', () => {
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore()
    mainWindow.focus()
  }
})

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null)
  ipcMain.handle('provider-setup:status', () => providerSetupStatus())
  ipcMain.handle('provider-setup:save', async (_event, input) => {
    saveProviderSetup(input)
    await restartPythonServer()
    const status = providerSetupStatus()
    setTimeout(loadFrontend, 150)
    return status
  })
  // The renderer needs the per-launch token to authenticate on the desktop
  // WebSocket bridge. The token is generated before the window is created.
  ipcMain.handle('bridge:token', () => securityToken)
  await startJavaSecurityService()
  await startPythonServer()
  await waitForBridge(bridgePort)
  createWindow()

  try { createTray() } catch (e) { logLine(`Tray disabled: ${e.message}`) }

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow()
  })
})

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  if (pythonProcess) pythonProcess.kill()
  pythonProcess = null
  if (javaProcess) javaProcess.kill()
  javaProcess = null
})
