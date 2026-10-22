"""Run a persistent ListOK worker or one bounded child process."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
if os.environ.get('LISTOK_SKIP_DOTENV') != '1':
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--lane', choices=('ai', 'compile'))
    group.add_argument('--execute')
    args = parser.parse_args()
    from utils import db, job_runner
    db.init_db()
    if args.execute:
        return job_runner.execute(args.execute)
    job_runner.serve(args.lane)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
