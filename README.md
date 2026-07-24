# Axiom

Axiom is a local-first AI coding workbench for Windows. It combines a Python agent runtime, an Electron desktop shell, a React frontend, and a Java security layer to provide conversations, tool execution, approvals, workflow state, and provider configuration in one desktop application.

> The Python package is still named `reasonix` internally for compatibility, while the product-facing name is **Axiom**.

## Highlights

- Desktop AI coding workbench built with Electron + React.
- Python agent engine based on LangChain / LangGraph / MCP integrations.
- Java security layer for permission gates, Guardian checks, audit boundaries, and sandbox-related services.
- Provider setup screen after installation, so users configure their own API provider and key.
- OpenAI, Anthropic, DeepSeek, OpenAI-compatible, and Anthropic-compatible provider formats.
- Ask / Allow / Deny approval flow for tool calls and potentially sensitive actions.
- Slash command and workspace mention UX foundations for faster interaction.
- Local packaging flow for Windows installer and portable desktop output.

## Project structure

```text
.
|-- desktop/
|   |-- electron/            # Electron desktop shell and packaging config
|   `-- python-frontend/     # React + Vite frontend
|-- reasonix-py/             # Python agent runtime and desktop bridge
|-- reasonix-java/           # Java security / sandbox service
|-- docs/                    # Review notes, issue summaries, and migration records
|-- build_all.ps1            # Full Windows build script
`-- docker-compose.yml       # Optional infrastructure services
```

## Requirements

- Windows 10 or later
- Python 3.12+
- Node.js / npm
- Java 21
- Maven Wrapper support through `reasonix-java/mvnw.cmd`

## Development

Install and test the Python runtime:

```powershell
cd E:\reasonix\reasonix-py
python -m pip install -e ".[dev]"
python -m pytest
```

Run the frontend:

```powershell
cd E:\reasonix\desktop\python-frontend
npm install
npm run build
```

Build the Electron desktop shell:

```powershell
cd E:\reasonix\desktop\electron
npm install
npm run build
```

Build the full Windows package:

```powershell
cd E:\reasonix
.\build_all.ps1
```

Typical build outputs are created under local build directories such as `reasonix-build/` or `axiom-build/`. These generated artifacts are intentionally ignored by Git.

## Provider configuration

Axiom does not need API keys committed into the repository or bundled into the installer. After installation, users should configure their own provider in the desktop app.

Supported provider styles include:

- DeepSeek OpenAI-compatible API
- DeepSeek Anthropic-compatible API
- OpenAI
- Anthropic
- Custom OpenAI-compatible endpoint
- Custom Anthropic-compatible endpoint

## Safety model

Axiom is designed around explicit approval for sensitive operations:

- `Ask`: request user confirmation before continuing.
- `Allow`: approve selected tool calls or trusted classes of actions.
- `Deny`: reject unsafe or unwanted actions.

The Java security service exists to keep permission checks, audit records, and sandbox-related decisions separated from the chat UI and Python runtime.

## Release workflow

After a stable build, create a Git tag and attach the installer to a GitHub Release:

```powershell
git tag v0.2.0
git push origin v0.2.0
```

Then upload the generated installer from the local build output directory in the GitHub Releases page.

## Notes

- Legacy Wails / Go desktop code has been removed. The active desktop app is Electron-based.
- Runtime secrets, provider config, local caches, generated installers, and build outputs are excluded from Git.
- The repository is intended to keep source code and documentation only.
