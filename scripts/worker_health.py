"""Docker healthcheck; reads shared SQLite heartbeats without network access."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app/backend'))
from utils.job_store import workers_ready
raise SystemExit(0 if workers_ready(sys.argv[1]) else 1)
