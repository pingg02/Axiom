# Axiom v0.2.1

This release connects the Java security service to the actual Windows desktop tool-execution path and improves desktop reliability.

## Highlights

- Starts the bundled Java security service before the Python agent runtime.
- Routes desktop shell commands through the authenticated Java gRPC service.
- Uses a random 256-bit per-launch token for local security RPC authentication.
- Fails shell execution closed if the Java service is unavailable while keeping chat usable.
- Bundles a private Java runtime; users do not need to install Java separately.
- Fixes the gRPC fat-JAR dependency mismatch that prevented the Java service from starting.
- Improves PyInstaller and Java cold-start readiness timeouts.
- Reports the real security backend state in the desktop diagnostics UI.
- Keeps provider API keys out of the installer and encrypts user-provided keys with Electron `safeStorage`.

## Verification

- Python: 106 tests passed.
- Java: 68 tests passed.
- React frontend: 11 tests passed.
- Packaged desktop launch verified with Java, Python, React, and the Axiom window running together.

## Security boundary

The Windows backend provides command policy checks, sensitive-environment removal, timeouts, output limits, and Job Object/process-tree guards. It does not claim AppContainer-level filesystem or network isolation.
