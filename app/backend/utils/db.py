import sqlite3
import os
from datetime import datetime

# DB file will be saved in the backend directory
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'worksheets.db')

def init_db():
    conn = sqlite3.connect(DB_PATH)
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
    conn.commit()
    conn.close()

def save_worksheet(topic, teacher_name, latex_code, pdf_url, keys_url=None):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute('''
        INSERT INTO history (topic, teacher_name, latex_code, pdf_url, keys_url, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (topic, teacher_name, latex_code, pdf_url, keys_url, created_at))
    conn.commit()
    conn.close()

def get_history(limit=50):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute('SELECT * FROM history ORDER BY id DESC LIMIT ?', (limit,))
    rows = c.fetchall()
    conn.close()
    return [dict(row) for row in rows]
