"""Run the server, send real HTTP traffic, stop it, and verify its graph JSON."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen
import webbrowser

from simulate_traffic import run_scenario


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PROJECT_ROOT.parent
EXPORT_PATH = PROJECT_ROOT / ".runtimespy" / "export.json"


def available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def wait_until_ready(process: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited before becoming ready: {process.returncode}")
        try:
            with urlopen(f"{base_url}/health", timeout=1) as response:
                if response.status == 200:
                    return
        except (OSError, URLError):
            time.sleep(0.1)
    raise TimeoutError("server did not become ready within 15 seconds")


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def wait_for_new_export(previous_generated_at: str | None) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            payload = json.loads(EXPORT_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if payload.get("generated_at") != previous_generated_at:
            return payload
        time.sleep(0.1)
    raise TimeoutError(f"server stopped but did not refresh {EXPORT_PATH}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, help="server port; defaults to a free port")
    parser.add_argument(
        "--swagger",
        action="store_true",
        help="open Swagger UI and wait for Enter before stopping the server",
    )
    args = parser.parse_args()
    port = args.port or available_port()
    base_url = f"http://127.0.0.1:{port}"

    previous_generated_at = None
    if EXPORT_PATH.is_file():
        try:
            previous_generated_at = json.loads(
                EXPORT_PATH.read_text(encoding="utf-8")
            ).get("generated_at")
        except (OSError, json.JSONDecodeError):
            pass

    environment = os.environ.copy()
    python_paths = [str(REPOSITORY_ROOT / "src"), str(PROJECT_ROOT / "src")]
    if environment.get("PYTHONPATH"):
        python_paths.append(environment["PYTHONPATH"])
    environment["PYTHONPATH"] = os.pathsep.join(python_paths)
    environment["RUNTIMESPY_DEMO_PORT"] = str(port)

    print(f"Starting instrumented Flask server at {base_url}")
    process = subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "app.py")],
        cwd=PROJECT_ROOT,
        env=environment,
    )
    try:
        wait_until_ready(process, base_url)
        swagger_url = f"{base_url}/docs/"
        print(f"Swagger UI: {swagger_url}")
        print("Server is ready; sending real HTTP traffic.\n")
        run_scenario(base_url)
        if args.swagger:
            print(f"\nOpening Swagger UI at {swagger_url}")
            webbrowser.open(swagger_url)
            input("Press Enter when finished; the server will stop and export JSON... ")
    finally:
        print("\nStopping server so RuntimeSpy can write the final graph...")
        stop_server(process)

    if process.returncode not in {0, -signal.SIGINT, 130}:
        raise RuntimeError(f"server exited with code {process.returncode}")
    payload = wait_for_new_export(previous_generated_at)
    summary = payload["summary"]
    print(f"Graph JSON: {EXPORT_PATH}")
    print(
        "Graph summary: "
        f"{summary['nodes']} nodes, "
        f"{summary['edges']} edges, "
        f"{summary['executed_nodes']} executed, "
        f"{summary['unseen_nodes']} unseen"
    )


if __name__ == "__main__":
    main()
