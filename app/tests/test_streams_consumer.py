import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType


APP_ROOT = Path(__file__).resolve().parents[1]


class _AsyncNullContext:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakeResponse:
    def __init__(self, *, lines=None, enter_exc=None):
        self._lines = list(lines or [])
        self._enter_exc = enter_exc

    async def __aenter__(self):
        if self._enter_exc is not None:
            raise self._enter_exc
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        for line in self._lines:
            yield line


def _fake_async_client(plans):
    class _FakeAsyncClient:
        def __init__(self, timeout=None):
            self._timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        def stream(self, method, url):
            plan = plans.pop(0)
            return _FakeResponse(**plan)

    return _FakeAsyncClient


def _load_consumer_module(monkeypatch):
    fake_httpx = ModuleType("httpx")

    class _PlaceholderAsyncClient:
        def __init__(self, timeout=None):
            self.timeout = timeout

    fake_httpx.AsyncClient = _PlaceholderAsyncClient

    fake_shiny = ModuleType("shiny")

    class _Reactive:
        @staticmethod
        def lock():
            return _AsyncNullContext()

        @staticmethod
        async def flush() -> None:
            return None

    fake_shiny.reactive = _Reactive()

    fake_app = ModuleType("app")
    fake_app.__path__ = []
    fake_streams = ModuleType("streams")
    fake_streams.__path__ = []

    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    monkeypatch.setitem(sys.modules, "shiny", fake_shiny)
    monkeypatch.setitem(sys.modules, "app", fake_app)
    monkeypatch.setitem(sys.modules, "app.streams", fake_streams)

    module_name = "app.streams.consumer_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(
        module_name, APP_ROOT / "streams" / "consumer.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_stream_consumer_processes_only_legacy_data_lines(monkeypatch) -> None:
    consumer_module = _load_consumer_module(monkeypatch)
    plans = [
        {
            "lines": [
                "event: ignored",
                'data: {"cpu": 1}',
                'data:{"cpu": 2}',
            ]
        },
        {"enter_exc": asyncio.CancelledError()},
    ]
    received: list[dict] = []

    monkeypatch.setattr(
        consumer_module.httpx, "AsyncClient", _fake_async_client(plans)
    )
    monkeypatch.setattr(consumer_module.reactive, "lock", lambda: _AsyncNullContext())

    async def fake_flush() -> None:
        return None

    monkeypatch.setattr(consumer_module.reactive, "flush", fake_flush)

    async def on_data(data: dict) -> None:
        received.append(data)

    asyncio.run(consumer_module.stream_consumer("test", "http://example", on_data))

    assert received == [{"cpu": 1}]


def test_stream_consumer_skips_malformed_json(monkeypatch) -> None:
    consumer_module = _load_consumer_module(monkeypatch)
    plans = [
        {"lines": ['data: {"cpu": ']},
        {"enter_exc": asyncio.CancelledError()},
    ]
    received: list[dict] = []

    monkeypatch.setattr(
        consumer_module.httpx, "AsyncClient", _fake_async_client(plans)
    )
    monkeypatch.setattr(consumer_module.reactive, "lock", lambda: _AsyncNullContext())

    async def fake_flush() -> None:
        return None

    monkeypatch.setattr(consumer_module.reactive, "flush", fake_flush)

    async def on_data(data: dict) -> None:
        received.append(data)

    asyncio.run(consumer_module.stream_consumer("test", "http://example", on_data))

    assert received == []


def test_stream_consumer_retries_with_backoff_after_errors(monkeypatch) -> None:
    consumer_module = _load_consumer_module(monkeypatch)
    plans = [
        {"enter_exc": RuntimeError("boom")},
        {"enter_exc": asyncio.CancelledError()},
    ]
    delays: list[int] = []

    monkeypatch.setattr(
        consumer_module.httpx, "AsyncClient", _fake_async_client(plans)
    )
    monkeypatch.setattr(consumer_module.reactive, "lock", lambda: _AsyncNullContext())

    async def fake_flush() -> None:
        return None

    async def fake_sleep(delay: int) -> None:
        delays.append(delay)

    monkeypatch.setattr(consumer_module.reactive, "flush", fake_flush)
    monkeypatch.setattr(consumer_module.asyncio, "sleep", fake_sleep)

    async def on_data(data: dict) -> None:
        raise AssertionError("on_data should not run when the stream never connects")

    asyncio.run(consumer_module.stream_consumer("test", "http://example", on_data))

    assert delays == [1]
