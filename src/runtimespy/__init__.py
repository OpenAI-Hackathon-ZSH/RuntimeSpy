"""Runtime execution heatmaps for Python projects.

The primary API is :func:`init`, which installs a monitor in the current Python
process and persists its counters automatically at process exit.
"""

from .api import RuntimeSession, init, shutdown
from .collector import RuntimeSpy
from .config import RuntimeSpyConfig, load_config

__all__ = [
    "RuntimeSession",
    "RuntimeSpy",
    "RuntimeSpyConfig",
    "init",
    "load_config",
    "shutdown",
]
__version__ = "0.1.0"
