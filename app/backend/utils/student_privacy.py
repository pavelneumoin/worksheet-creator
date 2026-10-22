"""One-time conversion of old rosters; private mapping is exported before mutation."""
import csv
import os
from pathlib import Path

from utils.class_store import student_code
from utils.workspace_store import connection


def migrate(export_path):
    target = Path(export_path).resolve()
    with connection() as conn:
        conn.execute('PRAGMA secure_delete=ON')
        conn.execute('BEGIN IMMEDIATE')
        students = conn.execute('''SELECT s.*,c.owner_id,c.name AS class_name FROM students s
                                   JOIN classrooms c ON c.id=s.class_id''').fetchall()
        old = [s for s in students if s['name'] != student_code(s['id'])]
        snapshots = conn.execute('''SELECT s.*,a.owner_id,a.class_name FROM assignment_students s
                                   JOIN assignments a ON a.id=s.assignment_id''').fetchall()
        old_snapshots = [s for s in snapshots if s['name'] != student_code(s['student_id'])]
        if not old and not old_snapshots:
            return {'students': 0, 'snapshots': 0, 'export': None}
        target.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation: never replace the teacher's correspondence table.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8-sig', newline='') as output:
            writer = csv.writer(output, delimiter=';')
            writer.writerow(['owner_id', 'class', 'student_id', 'code', 'previous_name', 'assignment_id'])
            def safe(value):
                text = str(value)
                return "'" + text if text[:1] in '=+-@\t\r' else text
            for s in old:
                writer.writerow(map(safe, [s['owner_id'], s['class_name'], s['id'], student_code(s['id']), s['name'], '']))
            for s in old_snapshots:
                writer.writerow(map(safe, [s['owner_id'], s['class_name'], s['student_id'], student_code(s['student_id']), s['name'], s['assignment_id']]))
            output.flush()
            os.fsync(output.fileno())
        conn.executemany('UPDATE students SET name=? WHERE id=?', [(student_code(s['id']), s['id']) for s in old])
        conn.executemany('UPDATE assignment_students SET name=? WHERE assignment_id=? AND student_id=?',
                         [(student_code(s['student_id']), s['assignment_id'], s['student_id']) for s in old_snapshots])
        conn.executemany('UPDATE classrooms SET revision=revision+1 WHERE id=?', [(c,) for c in {s['class_id'] for s in old}])
        conn.executemany('UPDATE assignments SET revision=revision+1 WHERE id=?', [(a,) for a in {s['assignment_id'] for s in old_snapshots}])
    with connection() as conn:
        conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        conn.execute('VACUUM')
    return {'students': len(old), 'snapshots': len(old_snapshots), 'export': str(target)}
