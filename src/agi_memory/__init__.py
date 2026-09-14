"""agi-memory: Turnkey zero-dependency four-pillar cognitive memory framework for AI coding assistants."""
from pathlib import Path


def _resolve_version() -> str:
    """Report the version of the code that is actually running.

    This was a hardcoded string and drifted: 0.6.0 shipped reporting 0.5.0,
    which also broke the Homebrew formula's own `--version` test block.

    Order matters and is not the obvious one. pyproject.toml sits beside a
    source tree and never inside an installed wheel, so finding it means this
    IS a checkout -- which is exactly how the install.sh wrapper runs, via
    PYTHONPATH. Asking importlib.metadata first would then report whatever
    unrelated copy pip last installed: on this machine that was 0.2.0 while the
    code being executed was 0.6.0. Installed, there is no pyproject.toml and
    the metadata is both correct and authoritative.

    Regex rather than tomllib, because tomllib is 3.11+ and this supports 3.10.
    """
    import re
    pyproject = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"
    try:
        match = re.search(r'^version\s*=\s*"([^"]+)"',
                          pyproject.read_text(encoding="utf-8"), re.M)
        if match:
            return match.group(1)
    except OSError:
        pass

    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("agi-memory")
        except PackageNotFoundError:
            return "0.0.0+unknown"
    except ImportError:
        return "0.0.0+unknown"


__version__ = _resolve_version()

from .layers.session_layer import SessionLayer
from .layers.graph_layer import GraphLayer
from .layers.episodic_layer import EpisodicLayer
from .layers.code_layer import CodeLayer
from .recall import recall
from .config import get_data_dir, get_vault_dir, get_default_db
from .vault import (
    init_vault,
    export_dirty_to_vault,
    import_from_vault,
    deduplicate_and_compact,
)
from .bootstrap import bootstrap_project

__all__ = [
    "SessionLayer",
    "GraphLayer",
    "EpisodicLayer",
    "CodeLayer",
    "recall",
    "get_data_dir",
    "get_vault_dir",
    "get_default_db",
    "init_vault",
    "export_dirty_to_vault",
    "import_from_vault",
    "deduplicate_and_compact",
    "bootstrap_project",
    "__version__",
]
