"""Development entry point with RuntimeSpy embedded before application imports."""

from pathlib import Path

import runtimespy


PROJECT_ROOT = Path(__file__).resolve().parent

runtimespy.init(
    project_root=PROJECT_ROOT,
    context="flask-server",
    report=False,
)

from commerce_demo import create_app  # noqa: E402


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)

