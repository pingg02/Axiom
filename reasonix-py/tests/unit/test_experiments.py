import base64
import json
import shlex

import httpx
import pytest

from reasonix.experiments.service import ExperimentService
from reasonix.experiments.store import ExperimentStore
from reasonix.remote import OpenCodeClient, RemoteConfig, RemoteError


async def test_experiment_command_protocol_and_durable_record(tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        body = json.loads(request.content)
        assert body["agent"] == "build"
        args = shlex.split(body["command"])
        payload = json.loads(args[-3])
        compile(base64.b64decode(args[-2]), "remote-worker.py", "exec")
        assert args[-1] in {"submit", "status", "stop"}
        result = {
            **payload,
            "directory": "/canonical/project",
            "state": "running",
            "pid": 123,
            "commit": "abc",
            "log_tail": "epoch 1",
            "output_dir": "/project/.axiom/experiments/test",
        }
        return httpx.Response(
            200,
            json={
                "parts": [
                    {
                        "type": "tool",
                        "state": {
                            "output": "AXIOM_JOB=" + json.dumps(result),
                        },
                    }
                ]
            },
        )

    client = OpenCodeClient(
        RemoteConfig("http://localhost:4096", "/project"), transport=httpx.MockTransport(handle)
    )
    store = ExperimentStore(tmp_path / "state.db")
    service = ExperimentService(client, store)
    result = await service.submit("session", "baseline", "python train.py", "config.yaml")
    assert result["pid"] == 123
    assert ExperimentStore(store.path).get(result["id"])["commit"] == "abc"
    await service.refresh(result["id"])
    assert len(requests) == 2
    await client.close()


async def test_lost_submit_ack_is_unknown_not_automatically_repeated(tmp_path):
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(502)

    client = OpenCodeClient(
        RemoteConfig("http://localhost:4096", "/project"), transport=httpx.MockTransport(handle)
    )
    store = ExperimentStore(tmp_path / "state.db")
    with pytest.raises(RemoteError):
        await ExperimentService(client, store).submit("session", "test", "train")
    records = store.list(client.config.url, client.config.directory)
    assert records[0]["state"] == "unknown"
    assert len(requests) == 1
    await client.close()


async def test_cannot_poll_or_stop_job_on_different_server(tmp_path):
    store = ExperimentStore(tmp_path / "state.db")
    store.save({"id": "job", "target": "http://localhost:1", "directory": "/project"})
    client = OpenCodeClient(RemoteConfig("http://localhost:2", "/project"))
    with pytest.raises(ValueError, match="original server"):
        await ExperimentService(client, store).refresh("job", stop=True)
    await client.close()
