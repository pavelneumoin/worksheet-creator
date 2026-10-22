import sqlite3
import os
from datetime import datetime

# DB file will be saved in the backend directory
DB_PATH = os.environ.get('LISTOK_DB_PATH') or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'worksheets.db')

def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic TEXT,
            teacher_name TEXT,
            latex_code TEXT,
            pdf_url TEXT,
            keys_url TEXT,
            created_at TEXT
        )
    ''')
    c.executescript('''
        BEGIN IMMEDIATE;
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY, first_name TEXT NOT NULL, kind TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            csrf TEXT NOT NULL, expires_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);
        CREATE TABLE IF NOT EXISTS materials (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            worksheet TEXT NOT NULL, source TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS materials_owner ON materials(owner_id, updated_at);
        CREATE TABLE IF NOT EXISTS artifacts (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            material_id TEXT REFERENCES materials(id) ON DELETE CASCADE,
            pdf TEXT NOT NULL, answers TEXT, tex TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS artifacts_owner ON artifacts(owner_id);
        CREATE TABLE IF NOT EXISTS material_meta (
            material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
            folder TEXT NOT NULL DEFAULT '', archived INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS editions (
            id TEXT PRIMARY KEY REFERENCES artifacts(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL REFERENCES users(id),
            material_id TEXT REFERENCES materials(id) ON DELETE SET NULL,
            worksheet TEXT NOT NULL, code TEXT NOT NULL, revision INTEGER NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS editions_material ON editions(owner_id,material_id,created_at);
        CREATE TABLE IF NOT EXISTS classrooms (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS classrooms_owner ON classrooms(owner_id,updated_at);
        CREATE TABLE IF NOT EXISTS students (
            id TEXT PRIMARY KEY, class_id TEXT NOT NULL REFERENCES classrooms(id),
            name TEXT NOT NULL, archived INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS students_class ON students(class_id,archived);
        CREATE TABLE IF NOT EXISTS assignments (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            class_id TEXT NOT NULL REFERENCES classrooms(id),
            edition_id TEXT NOT NULL REFERENCES editions(id) ON DELETE RESTRICT,
            class_name TEXT NOT NULL, title TEXT NOT NULL, due_date TEXT NOT NULL,
            instructions TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
            revision INTEGER NOT NULL DEFAULT 1, request_key TEXT NOT NULL,
            fingerprint TEXT NOT NULL, created_at TEXT NOT NULL,
            UNIQUE(owner_id,request_key)
        );
        CREATE INDEX IF NOT EXISTS assignments_class ON assignments(owner_id,class_id,created_at);
        CREATE TABLE IF NOT EXISTS assignment_students (
            assignment_id TEXT NOT NULL REFERENCES assignments(id),
            student_id TEXT NOT NULL REFERENCES students(id),
            name TEXT NOT NULL, PRIMARY KEY(assignment_id,student_id)
        );
        CREATE TABLE IF NOT EXISTS download_tickets (
            token_hash TEXT PRIMARY KEY,
            session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
            artifact_id TEXT NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
            expires_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS library_publications (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            material_id TEXT NOT NULL UNIQUE REFERENCES materials(id) ON DELETE CASCADE,
            worksheet TEXT NOT NULL, title TEXT NOT NULL, subject TEXT NOT NULL,
            grade TEXT NOT NULL, author TEXT NOT NULL, description TEXT NOT NULL,
            search_text TEXT NOT NULL, origin TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS library_subject ON library_publications(subject, created_at);
        CREATE TABLE IF NOT EXISTS library_ratings (
            publication_id TEXT NOT NULL REFERENCES library_publications(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL REFERENCES users(id),
            stars INTEGER NOT NULL CHECK(stars BETWEEN 1 AND 5),
            updated_at TEXT NOT NULL, PRIMARY KEY(publication_id, owner_id)
        );
        CREATE TABLE IF NOT EXISTS library_copies (
            publication_id TEXT NOT NULL REFERENCES library_publications(id) ON DELETE CASCADE,
            owner_id TEXT NOT NULL REFERENCES users(id),
            PRIMARY KEY(publication_id, owner_id)
        );
        CREATE TABLE IF NOT EXISTS material_origins (
            material_id TEXT PRIMARY KEY REFERENCES materials(id) ON DELETE CASCADE,
            publication_id TEXT REFERENCES library_publications(id) ON DELETE SET NULL,
            author TEXT NOT NULL, title TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
            kind TEXT NOT NULL, lane TEXT NOT NULL,
            request_key TEXT NOT NULL, fingerprint TEXT NOT NULL,
            payload TEXT NOT NULL, status TEXT NOT NULL,
            result TEXT, error TEXT, error_code TEXT,
            created_at REAL NOT NULL, updated_at REAL NOT NULL,
            started_at REAL, finished_at REAL, heartbeat REAL,
            claim TEXT, acknowledged INTEGER NOT NULL DEFAULT 0,
            UNIQUE(owner_id, request_key)
        );
        CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(lane,status,created_at);
        CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner_id,created_at);
        CREATE TABLE IF NOT EXISTS workers (
            id TEXT PRIMARY KEY, lane TEXT NOT NULL, heartbeat REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS provider_uploads (
            file_id TEXT PRIMARY KEY, created_at REAL NOT NULL
        );
    ''')
    if 'owner_id' not in {row[1] for row in c.execute('PRAGMA table_info(history)')}:
        c.execute('ALTER TABLE history ADD COLUMN owner_id TEXT')
    if 'marp' not in {row[1] for row in c.execute('PRAGMA table_info(artifacts)')}:
        c.execute('ALTER TABLE artifacts ADD COLUMN marp TEXT')
    if 'scheduled_date' not in {row[1] for row in c.execute('PRAGMA table_info(assignments)')}:
        c.execute("ALTER TABLE assignments ADD COLUMN scheduled_date TEXT NOT NULL DEFAULT ''")
    c.execute('CREATE INDEX IF NOT EXISTS assignments_schedule ON assignments(owner_id,scheduled_date)')
    conn.commit()
    conn.close()

def save_worksheet(topic, teacher_name, latex_code, pdf_url, keys_url=None, owner_id=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO history (topic, teacher_name, latex_code, pdf_url, keys_url, created_at, owner_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (topic, teacher_name, latex_code, pdf_url, keys_url, created_at, owner_id))
    conn.commit()
    conn.close()

def get_history(limit=50, owner_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM history WHERE owner_id = ? ORDER BY id DESC LIMIT ?', (owner_id, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]
