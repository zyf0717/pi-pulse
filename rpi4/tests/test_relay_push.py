import importlib.util
from pathlib import Path
from unittest.mock import patch

RPI4_DIR = Path(__file__).resolve().parents[1]


def _load_relay_push():
    spec = importlib.util.spec_from_file_location(
        "rpi4_relay_push_fresh", RPI4_DIR / "relay_push.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_detect_node_id_prefers_explicit_env_override():
    relay_push = _load_relay_push()
    with patch.dict("os.environ", {"PI_PULSE_NODE_ID": "11"}, clear=False):
        assert relay_push.detect_node_id("http://192.168.121.1:8010") == "11"


def test_detect_node_id_uses_local_ip_last_octet():
    relay_push = _load_relay_push()

    class _FakeSocket:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def connect(self, target):
            self.target = target

        def getsockname(self):
            return ("192.168.121.10", 54321)

    with patch.dict("os.environ", {}, clear=True):
        with patch.object(relay_push.socket, "socket", return_value=_FakeSocket()):
            assert relay_push.detect_node_id("http://192.168.121.1:8010") == "10"


def test_ingest_url_joins_paths_cleanly():
    relay_push = _load_relay_push()
    assert (
        relay_push.ingest_url("/ingest/pulse/10/stream", "http://192.168.121.1:8010")
        == "http://192.168.121.1:8010/ingest/pulse/10/stream"
    )
