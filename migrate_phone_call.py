"""migrate_phone_call.py — Add phone_number and call_status to companies table."""
import sqlite3
from pathlib import Path

db_path = Path.home() / '.jobtracker' / 'data.db'
con = sqlite3.connect(str(db_path))
cur = con.cursor()

cur.execute('PRAGMA table_info(companies)')
cols = [row[1] for row in cur.fetchall()]
print('Existing cols:', cols[-8:])

added = []
if 'phone_number' not in cols:
    cur.execute('ALTER TABLE companies ADD COLUMN phone_number TEXT')
    added.append('phone_number')

if 'call_status' not in cols:
    cur.execute("ALTER TABLE companies ADD COLUMN call_status TEXT DEFAULT 'not_called'")
    added.append('call_status')

con.commit()
con.close()
print('Added columns:', added if added else 'none (already existed)')
print('Migration complete.')
