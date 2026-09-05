"""Create a consistent SQLite backup; destination must not already exist."""
import os,sqlite3,sys
from pathlib import Path
source=Path(os.environ.get('DATABASE_PATH',Path(__file__).resolve().parent.parent/'private.sqlite3'))
if len(sys.argv)!=2: raise SystemExit('Usage: python scripts/backup.py /private/path/backup.sqlite3')
target=Path(sys.argv[1])
if target.exists(): raise SystemExit('Destination exists; choose a new backup filename.')
if not source.exists(): raise SystemExit('Source database does not exist.')
fd=os.open(target,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
with sqlite3.connect(f'file:{source}?mode=ro',uri=True) as src,sqlite3.connect(target) as dst: src.backup(dst)
print('Backup created. Protect it like the original database.')
