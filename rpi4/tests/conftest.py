import sys
from pathlib import Path

import pytest

# Ensure the repo root and rpi4/ are on the path so modules can be imported
# directly (e.g. `import pulse`) as well as via the package namespace.
ROOT = Path(__file__).resolve().parents[2]
RPI4_DIR = ROOT / "rpi4"

for p in (str(ROOT), str(RPI4_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)


@pytest.fixture(autouse=True)
def _reset_relay_push_backoff():
    """Reset relay_push backoff globals before each test to prevent cross-test pollution."""
    import relay_push

    relay_push._reset_backoff_state()
    yield
