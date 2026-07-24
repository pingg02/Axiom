"""
gRPC 安全服务客户端 — 调用 Java reasonix-security 服务。

用法：
    from reasonix.grpc import SecurityClient

    client = SecurityClient(host="127.0.0.1", port=9091)
    await client.connect()
    decision = await client.check_permission("bash", '{"command":"ls"}')
    await client.close()
"""

from reasonix.grpc.client import SecurityClient

__all__ = ["SecurityClient"]
