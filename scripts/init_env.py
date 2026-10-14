"""Generate local configuration without printing secrets or overwriting an existing file."""
import os
import secrets
from pathlib import Path
from cryptography.fernet import Fernet

path = Path(__file__).resolve().parent.parent / '.env'
try:
    descriptor = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
except FileExistsError:
    raise SystemExit('.env already exists; edit it directly.')
with os.fdopen(descriptor, 'w') as config:
    config.write('ADMIN_TOKEN=' + secrets.token_urlsafe(32) + '\n')
    config.write('SESSION_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n')
    config.write('DATABASE_PATH=data/insta.sqlite3\n')
    config.write('SUPABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=\n')
    config.write('ALLOWED_ORIGINS=http://localhost:8000\nACTION_DELAY_SECONDS=10\n')
print('Created private .env. Keep the encryption key backed up; enter ADMIN_TOKEN in the frontend.')
