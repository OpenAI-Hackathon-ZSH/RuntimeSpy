"""Runtime execution heatmaps for Python projects.

The primary API is :func:`init`, which installs a monitor in the current Python
process and persists its counters automatically at process exit.
"""

from .api import (
    RuntimeRequest,
    RuntimeSession,
    begin_request,
    end_request,
    init,
    shutdown,
)
from .collector import RuntimeSpy
from .config import RuntimeSpyConfig, load_config

__all__ = [
    "RuntimeSession",
    "RuntimeRequest",
    "RuntimeSpy",
    "RuntimeSpyConfig",
    "begin_request",
    "end_request",
    "init",
    "load_config",
    "shutdown",
]
__version__ = "0.1.0"
