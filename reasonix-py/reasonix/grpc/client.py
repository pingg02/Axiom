"""
gRPC 安全服务客户端 — 调用 Java reasonix-security 服务。

通过 gRPC 连接 Java 端获取：
- Permission Gate 决策 (Allow/Ask/Deny)
- Guardian LLM 审查
- Secrets 擦除
- Sandbox 沙箱执行

当 Java 服务不可用时，自动回退到本地 Python 实现。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, cast

import grpc

from reasonix.grpc import security_pb2, security_pb2_grpc

logger = logging.getLogger(__name__)


class SecurityClient:
    """gRPC 安全服务客户端。

    封装对 Java reasonix-security 服务的 gRPC 调用。
    连接失败时 logger.warning 并抛出异常供调用方决定回退策略。
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9091):
        self._target = f"{host}:{port}"
        self._channel: grpc.aio.Channel | None = None
        self._stub: security_pb2_grpc.SecurityServiceStub | None = None

    async def connect(self) -> bool:
        """连接到 Java 安全服务。返回是否成功。"""
        try:
            self._channel = grpc.aio.insecure_channel(self._target)
            self._stub = security_pb2_grpc.SecurityServiceStub(  # type: ignore[no-untyped-call]
                self._channel
            )
            # 超时探测
            await asyncio.wait_for(self._channel.channel_ready(), timeout=3)
            logger.info("Connected to Java security service at %s", self._target)
            return True
        except Exception as e:
            logger.warning("Failed to connect to Java security service at %s: %s",
                           self._target, e)
            self._channel = None
            self._stub = None
            return False

    async def check_permission(self, tool_name: str, args_json: str,
                                read_only: bool = False) -> str:
        """检查权限。返回 'allow' / 'ask' / 'deny'。"""
        if not self._stub:
            raise ConnectionError("Not connected to Java service")
        try:
            req = security_pb2.PermissionCheckRequest(
                tool_name=tool_name,
                args_json=args_json,
                read_only=read_only,
            )
            resp = await self._stub.CheckPermission(req, timeout=5)
            return security_pb2.PermissionCheckResponse.Decision.Name(
                resp.decision
            ).lower()
        except Exception as e:
            logger.error("check_permission failed: %s", e)
            raise

    async def review_tool(self, tool_name: str, args_json: str,
                           transcript_delta: str, session_id: str) -> dict[str, Any]:
        """Guardian 审查。返回判决 dict。"""
        if not self._stub:
            raise ConnectionError("Not connected to Java service")
        try:
            req = security_pb2.GuardianReviewRequest(
                tool_name=tool_name,
                args_json=args_json,
                transcript_delta=transcript_delta,
                session_id=session_id,
            )
            resp = await self._stub.ReviewTool(req, timeout=30)
            return {
                "risk_level": resp.risk_level,
                "outcome": resp.outcome,
                "rationale": resp.rationale,
                "breaker_tripped": resp.breaker_tripped,
            }
        except Exception as e:
            logger.error("review_tool failed: %s", e)
            raise

    async def redact_secrets(self, text: str,
                              redact_tool_output: bool = True) -> str:
        """擦除密钥信息。"""
        if not self._stub:
            raise ConnectionError("Not connected to Java service")
        try:
            req = security_pb2.RedactRequest(
                text=text,
                redact_tool_output=redact_tool_output,
            )
            resp = await self._stub.RedactSecrets(req, timeout=5)
            return cast(str, resp.redacted_text)
        except Exception as e:
            logger.error("redact_secrets failed: %s", e)
            raise

    async def execute_sandboxed(self, command: str,
                                  write_roots: list[str] | None = None,
                                  network: bool = False,
                                  timeout_seconds: int = 30) -> dict[str, Any]:
        """沙箱执行命令。"""
        if not self._stub:
            raise ConnectionError("Not connected to Java service")
        try:
            req = security_pb2.SandboxExecuteRequest(
                command=command,
                write_roots=write_roots or [],
                network=network,
                timeout_seconds=timeout_seconds,
            )
            resp = await self._stub.ExecuteSandboxed(req, timeout=timeout_seconds + 10)
            return {
                "stdout": resp.stdout,
                "stderr": resp.stderr,
                "exit_code": resp.exit_code,
            }
        except Exception as e:
            logger.error("execute_sandboxed failed: %s", e)
            raise

    async def close(self) -> None:
        """关闭连接。"""
        if self._channel:
            await self._channel.close()
            self._channel = None
            self._stub = None
