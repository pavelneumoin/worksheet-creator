"""Local-only demo launcher for the current Worksheet Creator backend.

Run from a repository that contains app/backend/app.py:
    python run_local.py

The launcher adapts the existing frontend API prefix without editing backend
source files. It is a local development adapter, not production hardening.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys


class LocalApiAdapter:
    """Map the frontend prefix and disable credential diagnostics."""

    def __init__(self, wrapped_app):
        self.wrapped_app = wrapped_app

    def __call__(self, environ, start_response):
        path = environ.get("PATH_INFO", "")
        if path == "/worksheet-api":
            path = "/api"
        elif path.startswith("/worksheet-api/"):
            path = "/api/" + path[len("/worksheet-api/"):]

        if path.rstrip("/") == "/api/debug-env":
            body = json.dumps({"error": "Not available in local demo"}).encode("utf-8")
            start_response(
                "404 Not Found",
                [("Content-Type", "application/json"), ("Content-Length", str(len(body)))],
            )
            return [body]

        forwarded = environ.copy()
        forwarded["PATH_INFO"] = path
        return self.wrapped_app(forwarded, start_response)


def load_application(repo_root: Path):
    repo_root = repo_root.resolve()
    backend_dir = repo_root / "app" / "backend"
    entrypoint = backend_dir / "app.py"
    if not entrypoint.is_file():
        raise FileNotFoundError(f"Backend not found: {entrypoint}")

    # The existing modules import utils.* and optional config.py from this folder.
    sys.path.insert(0, str(backend_dir))
    spec = importlib.util.spec_from_file_location("worksheet_local_backend", entrypoint)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load backend module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    application = module.app
    application.config.update(DEBUG=False, TESTING=False)
    application.wsgi_app = LocalApiAdapter(application.wsgi_app)
    return application


def main():
    parser = argparse.ArgumentParser(description="Run Worksheet Creator on localhost.")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent,
        help="Repository root containing app/backend/app.py.",
    )
    parser.add_argument("--port", type=int, default=3005)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")

    os.environ.setdefault("USE_CLOUD_LATEX", "false")
    application = load_application(args.repo_root)
    print(f"Open http://127.0.0.1:{args.port}", flush=True)
    application.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()

