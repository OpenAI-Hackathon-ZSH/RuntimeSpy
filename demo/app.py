"""Development entry point with RuntimeSpy embedded before application imports."""

import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = PROJECT_ROOT.parent

# Run directly from the checkout even when macOS/Python skips editable-install
# .pth files inside the hidden .venv directory.
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

import runtimespy  # noqa: E402

runtimespy.init(
    project_root=PROJECT_ROOT,
    context="flask-server",
    endpoint=os.environ.get("RUNTIMESPY_REPORT_ENDPOINT"),
)

from commerce_demo import create_app  # noqa: E402


app = create_app()


if __name__ == "__main__":
    port = int(os.environ.get("RUNTIMESPY_DEMO_PORT", "5000"))
    app.run(
        host="127.0.0.1",
        port=port,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
