import sqlite3
import os
from pathlib import Path

DB_PATH = Path("agents/data/call_center.db").resolve()
conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()
cursor.execute("SELECT * FROM call_center_data LIMIT 5")
rows = cursor.fetchall()
print(rows)
conn.close()
