import sqlite3
import os

db_path = "data/whatsapp_agent.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# 1. Search in messages content
print("Searching in messages...")
rows = conn.execute("SELECT * FROM messages WHERE content_raw LIKE ? LIMIT 10", ("%wax%",)).fetchall()
for r in rows:
    print(f"MSG: {r['content_raw']} | GroupID: {r['group_id']}")

# 2. List all groups just in case
print("\nAll Groups in DB:")
rows = conn.execute("SELECT * FROM groups").fetchall()
for r in rows:
    print(dict(r))

conn.close()
