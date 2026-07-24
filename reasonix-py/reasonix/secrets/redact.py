"""
Secrets redaction — deterministic, idempotent masking of credentials.

Applied to tool output before returning to model and to durable artifacts.
"""

from __future__ import annotations

import re

# ── Redaction patterns (mirroring Go's internal/secrets/redact.go) ──────────

# Env-var / key-value patterns for credential-like field names
SECRET_KEY_PATTERN = re.compile(
    r'(?i)((^|[_-])(api[_-]?key|access[_-]?key|private[_-]?key|'
    r'secret|token|password|passwd)([_-]|$|)|[_-]pwd([_-]|$))'
)

# KEY=value or "key":"value" patterns
KEY_VALUE_PATTERN = re.compile(
    r'(?i)\b([A-Z0-9_.-]*('
    r'API[_-]?KEY|ACCESS[_-]?KEY|PRIVATE[_-]?KEY|'
    r'SECRET|TOKEN|PASSWORD|PASSWD'
    r')[A-Z0-9_.-]*|'
    r'[A-Z0-9_.-]+[_-]PWD[A-Z0-9_.-]*|'
    r'AUTHORIZATION'
    r')\b'
    r'(["\']?\s*[:=]\s*["\']?)'
    r'((?:Bearer|Basic|Digest|Negotiate|NTLM|Token|Bot|ApiKey)\s+)?'
    r'(["\']?)([^"\\\'\s,;]+)(["\']?)'
)

# Cookie headers
COOKIE_HEADER_PATTERN = re.compile(
    r'(?i)\b((?:set-)?cookie)(\s*[:=]\s*)([^=;\s]+=[^;\s]*(?:;\s*[^=;\s]+(?:=[^;\s]*)?)*)'
)

# Bearer tokens >= 16 chars
BEARER_TOKEN_PATTERN = re.compile(
    r'(?i)\bBearer\s+([A-Za-z0-9._~+/=-]{16,})'
)

# Known credential formats
OPENAI_KEY_PATTERN = re.compile(r'\b((?:sk|rk)-(?:proj-)?[A-Za-z0-9_-]{12,})\b')
GITHUB_TOKEN_PATTERN = re.compile(
    r'\b(gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b'
)
SLACK_TOKEN_PATTERN = re.compile(r'\b(xox[baprs]-[A-Za-z0-9-]{16,})\b')
AWS_ACCESS_KEY_PATTERN = re.compile(r'\b(AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16})\b')
JWT_PATTERN = re.compile(r'\b(eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)\b')

# All patterns in order of application
_PATTERNS = [
    KEY_VALUE_PATTERN,
    COOKIE_HEADER_PATTERN,
    BEARER_TOKEN_PATTERN,
    OPENAI_KEY_PATTERN,
    GITHUB_TOKEN_PATTERN,
    SLACK_TOKEN_PATTERN,
    AWS_ACCESS_KEY_PATTERN,
    JWT_PATTERN,
]

REDACTED = "[redacted]"


def mask(value: str) -> str:
    """Mask a secret value — shows first/last few chars, masks middle.

    Mirrors Go's mask() in secrets/redact.go.
    """
    if len(value) <= 12:
        return REDACTED
    head = 6 if value.startswith(("sk-", "rk-")) else 4
    tail = 4
    if len(value) <= head + tail:
        return REDACTED
    return value[:head] + "*" * (len(value) - head - tail) + value[-tail:]


def _redact_line(text: str) -> str:
    """Apply redaction patterns to a single line of text."""
    # KEY=VALUE patterns
    def replace_kv(m: re.Match[str]) -> str:
        prefix = m.group(1) or ""       # KEY name
        sep = m.group(3) or "="         # = or : separator
        auth_scheme = m.group(4) or ""  # Bearer, Basic, etc.
        quote_open = m.group(5) or ""   # opening quote
        value = m.group(6) or ""        # the secret value
        quote_close = m.group(7) or ""  # closing quote

        if "authorization" in prefix.lower():
            return prefix + sep + auth_scheme + quote_open + REDACTED + quote_close
        return prefix + sep + auth_scheme + quote_open + mask(value) + quote_close

    text = KEY_VALUE_PATTERN.sub(replace_kv, text)

    # Cookie values
    def replace_cookie(m: re.Match[str]) -> str:
        header = m.group(1)  # cookie / set-cookie
        sep = m.group(2)     # : or =
        values = m.group(3)  # key=value pairs
        # Redact each value
        redacted = re.sub(
            r'([^=;\s]+)=([^;\s]*)',
            lambda m2: f"{m2.group(1)}={REDACTED}",
            values,
        )
        return header + sep + redacted

    text = COOKIE_HEADER_PATTERN.sub(replace_cookie, text)

    # Bearer tokens
    def replace_bearer(_: re.Match[str]) -> str:
        return f"Bearer {REDACTED}"

    # Known formats
    def replace_known(match: re.Match[str]) -> str:
        return mask(match.group(0))

    text = BEARER_TOKEN_PATTERN.sub(replace_bearer, text)
    text = OPENAI_KEY_PATTERN.sub(replace_known, text)
    text = GITHUB_TOKEN_PATTERN.sub(replace_known, text)
    text = SLACK_TOKEN_PATTERN.sub(replace_known, text)
    text = AWS_ACCESS_KEY_PATTERN.sub(replace_known, text)
    text = JWT_PATTERN.sub(replace_known, text)

    return text


class RedactHandler:
    """Deterministic credential redaction for tool outputs and artifacts."""

    def __init__(self, redact_tool_output: bool = True):
        self.redact_tool_output = redact_tool_output

    def redact(self, text: str) -> str:
        """Always redact (for durable storage / job artifacts).

        Mirrors Go's secrets.Redact().
        """
        return _redact_line(text)

    def redact_tool_result(self, text: str) -> str:
        """Redact tool output before returning to model.

        Mirrors Go's secrets.RedactToolOutput().
        """
        if not self.redact_tool_output:
            return text
        return _redact_line(text)

    def filter_env(self, env: dict[str, str]) -> dict[str, str]:
        """Filter credential-like env vars from subprocess environment.

        Mirrors Go's secrets.ProcessEnv().
        """
        filtered = {}
        for key, value in env.items():
            if SECRET_KEY_PATTERN.search(key):
                filtered[key] = REDACTED  # mask value but keep key
            else:
                filtered[key] = value
        return filtered
