"""Create/update administrator using private environment variables."""
import os
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
from app import users, client

email = os.getenv('ADMIN_EMAIL', '').strip().lower()
password = os.getenv('ADMIN_PASSWORD', '')
if not email or '@' not in email or len(password) < 12:
    raise SystemExit('Configura ADMIN_EMAIL y ADMIN_PASSWORD (mínimo 12 caracteres) en .env.')
client.admin.command('ping')
users.update_one({'email': email}, {'$set': {'name': 'Administrador', 'email': email,
                   'password_hash': generate_password_hash(password), 'admin': True,
                   'updated_at': datetime.now(timezone.utc)}}, upsert=True)
print('Administrador configurado correctamente.')
