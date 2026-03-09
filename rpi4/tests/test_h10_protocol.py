import importlib.util
from pathlib import Path

RPI4_DIR = Path(__file__).resolve().parents[1]


def _load_h10_protocol():
    spec = importlib.util.spec_from_file_location(
        "rpi4_h10_protocol_fresh", RPI4_DIR / "h10_protocol.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_load_h10_addresses_prefers_explicit_local_config(tmp_path: Path):
    h10_protocol = _load_h10_protocol()
    local_path = tmp_path / "h10_addresses.yaml"
    example_path = tmp_path / "h10_addresses.example.yaml"
    local_path.write_text('STRAP1: "11:22:33:44:55:66"\n', encoding="utf-8")
    example_path.write_text('STRAP2: "AA:BB:CC:DD:EE:FF"\n', encoding="utf-8")

    assert h10_protocol.load_h10_addresses(local_path, example_path) == {
        "STRAP1": "11:22:33:44:55:66"
    }


def test_load_h10_addresses_falls_back_to_example_when_local_missing(tmp_path: Path):
    h10_protocol = _load_h10_protocol()
    local_path = tmp_path / "missing.yaml"
    example_path = tmp_path / "h10_addresses.example.yaml"
    example_path.write_text('STRAP2: "AA:BB:CC:DD:EE:FF"\n', encoding="utf-8")

    assert h10_protocol.load_h10_addresses(local_path, example_path) == {
        "STRAP2": "AA:BB:CC:DD:EE:FF"
    }
