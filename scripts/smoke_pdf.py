"""Real TeX compilation smoke test, offline and usable inside the Docker image."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app" / "backend"))
from utils.worksheet import demo_worksheet, compile_worksheet
from utils import latex


def main():
    results = []
    cases = [("math", 1, 3, "grid"), ("physics", 1, 3, "grid"),
             ("math", 2, 2, "blank"), ("math", 2, 6, "none")]
    for subject, columns, count, field in cases:
        sheet = demo_worksheet(subject)
        sheet["settings"] = {"columns": columns, "tasks_per_page": count, "field": field}
        base = f"smoke_{subject}_{columns}_{count}_{field}"
        files = compile_worksheet(sheet, base)
        for name in files:
            p = Path(latex.OUTPUT_DIR) / name
            assert p.read_bytes().startswith(b"%PDF-"), name
        results.append({"case": base, "files": files})
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
