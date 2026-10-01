import asyncio
import json

from reasonix.control.controller import Controller, ControllerOptions
from reasonix.desktop import BridgeClient, DesktopRuntime
from reasonix.event import Event, Kind
from reasonix.provider import Message, Role, StreamEvent
from reasonix.tool.registry import Registry


class SlowProvider:
    model_name = "test"

    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = False

    async def generate_stream(self, messages, tools=None, temperature=0):
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        yield StreamEvent(message=Message(role=Role.ASSISTANT, content="finished"))


class Socket:
    async def send(self, data):
        pass


async def test_disconnect_does_not_cancel_and_reconnect_adopts_same_session():
    runtime = DesktopRuntime()
    provider = SlowProvider()
    runtime.owner.controller = Controller(
        ControllerOptions(
            registry=Registry().snapshot(),
            provider=provider,
            sink=runtime.owner.sink,
        )
    )
    await runtime.start()
    first = BridgeClient(Socket(), required_token="token", runtime=runtime)
    await first.handle_message(json.dumps({"action": "auth", "token": "token"}))
    session_id = runtime.owner.controller.session.id
    await first.handle_message(json.dumps({"action": "send", "text": "train"}))
    await provider.started.wait()
    await first.close()
    assert not provider.cancelled
    assert runtime.owner.controller.session.state.value == "running"
    second = BridgeClient(Socket(), required_token="token", runtime=runtime)
    await second.handle_message(json.dumps({"action": "auth", "token": "wrong"}))
    assert second not in runtime.clients
    await second.handle_message(json.dumps({"action": "auth", "token": "token"}))
    assert runtime.owner.controller.session.id == session_id
    runtime.owner.sink.emit(Event(kind=Kind.TEXT, text="shared"))
    await asyncio.sleep(0)
    assert any("shared" in data for data in list(second.sink.queue._queue))
    provider.release.set()
    await runtime.owner.controller.wait_for_turn()
    await second.close()
    await runtime.close()
    assert not provider.cancelled
