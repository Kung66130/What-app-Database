import sqlite3
import os

db_path = "data/whatsapp_agent.db"
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    exit(1)

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
rows = conn.execute("SELECT * FROM groups WHERE group_name LIKE ?", ("%wax%",)).fetchall()
for r in rows:
    print(dict(r))
conn.close()
