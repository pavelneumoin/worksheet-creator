"""Opt-in live evaluation: six requests, using only our synthetic school examples.

Never prints credentials or raw provider exceptions. Results stay in ignored output/.
Run: python scripts/compare_models.py --run
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app/backend"))
from dotenv import load_dotenv
load_dotenv(ROOT / ".env")
from utils.structured_ai import generate
from utils.gigachat_client import AIServiceError, _create_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Make billable provider requests")
    parser.add_argument("--models", nargs="+", default=["GigaChat-3-Lightning", "GigaChat-3-Pro", "GigaChat-3-Ultra"])
    parser.add_argument("--output", default="output/qa/gigachat-comparison.json")
    args = parser.parse_args()
    if not args.run:
        parser.error("Pass --run to authorize the live comparison")
    with _create_client() as client:
        available = {m.id_ for m in client.get_models().data}
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    report = {"date": datetime.now(timezone.utc).isoformat(), "available_models": sorted(available), "cases": []}
    for model in args.models:
        if model not in available:
            print(model, "not available", flush=True)
            continue
        os.environ["GIGACHAT_MODEL"] = model
        for subject in ("math", "physics"):
            entry = {"model": model, "subject": subject, "input": f"docs/examples/{subject}-source.png"}
            start = time.monotonic()
            try:
                entry["worksheet"] = generate(subject, image_paths=[str(ROOT / entry["input"])])
                entry["status"] = "ok"
            except AIServiceError as exc:
                entry.update(status="error", error_code=exc.code, message=str(exc))
            entry["seconds"] = round(time.monotonic() - start, 2)
            report["cases"].append(entry)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(model, subject, entry["status"], entry["seconds"], entry.get("error_code", ""), flush=True)
    print("Report:", output)


if __name__ == "__main__":
    main()
