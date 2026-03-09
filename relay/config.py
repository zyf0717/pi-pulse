from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).with_name("config.yaml")


def load_config(config_path: Path = _CONFIG_PATH) -> dict:
    with config_path.open() as config_file:
        return yaml.safe_load(config_file) or {}


_CONFIG = load_config()
_SERVER = _CONFIG.get("server", {})

HOST = str(_SERVER.get("host", "0.0.0.0"))
PORT = int(_SERVER.get("port", 8010))
QUEUE_MAXSIZE = int(_SERVER.get("queue_maxsize", 64))
