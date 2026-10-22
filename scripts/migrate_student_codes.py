"""Run while the application is stopped. Keep the export on the teacher's device."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app/backend'))
from dotenv import load_dotenv
load_dotenv(ROOT / '.env')
from utils import db, student_privacy

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--export', required=True, help='New private CSV path; never put this file in Git or the image.')
    args = parser.parse_args()
    db.init_db()
    print(json.dumps(student_privacy.migrate(args.export), ensure_ascii=True))
