"""Analysis snapshots never mutate grades or teacher drafts."""
import json
import time
from utils import review_store, student_store
from utils.gigachat_client import AIServiceError

def context(conn,owner,kind,target_id):
    if kind=='review':
        row=review_store.owned(conn,owner,target_id)
        paths=[review_store.photo_path(target_id,i) for i in range(row['photo_count'])] if row['photo_expires']>time.time() else []
    elif kind=='student':
        row=student_store.owned_attempt(conn,owner,target_id)
        names=json.loads(row['files']) if row['expires_at']>time.time() else []
        raw=[n for n in names if not n.startswith('page_')]
        paths=[student_store.folder(target_id)/n for n in raw]
    else:raise AIServiceError('Неизвестный вид работы.','analysis_invalid',400)
    if row['status']=='processing':raise AIServiceError('Дождитесь распознавания.','analysis_not_ready',409)
    if not paths or not all(p.is_file() for p in paths):raise AIServiceError('Сканы недоступны или истёк срок хранения.','photo_not_found',404)
    assignment=review_store.context(conn,owner,row['assignment_id'],row['student_id'])
    return row,assignment,paths

def latest(conn,owner,kind,target_id,revision):
    row=conn.execute('SELECT * FROM solution_analyses WHERE owner_id=? AND target_kind=? AND target_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(owner,kind,target_id)).fetchone()
    return dict(json.loads(row['content']),created_at=row['created_at'],stale=row['base_revision']!=revision) if row else None
