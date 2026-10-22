"""Journal only uploads made by this application; never scan/delete other account files."""
import time
from utils.workspace_store import connection


def uploaded(file_id):
    with connection() as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS provider_uploads (file_id TEXT PRIMARY KEY, created_at REAL NOT NULL)')
        conn.execute('INSERT OR IGNORE INTO provider_uploads VALUES (?,?)', (file_id, time.time()))


def deleted(file_id):
    with connection() as conn:
        conn.execute('DELETE FROM provider_uploads WHERE file_id=?', (file_id,))


def cleanup(client, apply=False):
    with connection() as conn:
        ids = [r[0] for r in conn.execute('SELECT file_id FROM provider_uploads WHERE created_at<?', (time.time() - 86400,))]
    success = failures = 0
    if apply:
        for file_id in ids:
            try:
                client.delete_file(file_id)
                deleted(file_id)
                success += 1
            except Exception as exc:
                if getattr(exc, 'status_code', None) == 404:
                    deleted(file_id)
                    success += 1
                else:
                    failures += 1  # Keep journal for the next attempt; no credentials or IDs in logs.
    return {'pending': len(ids), 'deleted': success, 'failed': failures, 'applied': apply}
