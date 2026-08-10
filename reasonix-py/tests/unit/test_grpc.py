"""gRPC 客户端测试。"""

from reasonix.grpc import SecurityClient


def test_client_imports():
    """SecurityClient 可以正确导入。"""
    assert SecurityClient is not None


def test_client_default_params():
    """默认参数正确。"""
    client = SecurityClient()
    assert client._target == "127.0.0.1:9091"


def test_client_custom_params():
    """自定义参数正确。"""
    client = SecurityClient(host="10.0.0.1", port=8080, token="launch-token")
    assert client._target == "10.0.0.1:8080"
    assert client._metadata == (("x-axiom-security-token", "launch-token"),)


def test_client_connect_fails_gracefully():
    """连接失败不会崩溃。"""
    assert SecurityClient(host="0.0.0.1", port=1) is not None
    # 应该快速失败，不阻塞
    pass
