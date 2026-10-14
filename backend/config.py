import os
from dataclasses import dataclass
from dotenv import load_dotenv
from cryptography.fernet import Fernet

load_dotenv()


@dataclass
class Settings:
    admin_token: str
    encryption_key: str
    database_path: str = 'data/insta.sqlite3'
    supabase_url: str = ''
    supabase_key: str = ''
    origins: tuple = ('http://localhost:8000',)
    login_timeout: int = 300
    action_delay: float = 10.0

    def __post_init__(self):
        if len(self.admin_token) < 32:
            raise ValueError('ADMIN_TOKEN must contain at least 32 characters')
        Fernet(self.encryption_key.encode())
        if bool(self.supabase_url) != bool(self.supabase_key):
            raise ValueError('Set both SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY')
        if self.supabase_url and not self.supabase_url.startswith('https://'):
            raise ValueError('Supabase requires an HTTPS URL')
        if self.login_timeout < 1 or self.action_delay < 0:
            raise ValueError('Invalid timeout or delay')

    @classmethod
    def from_env(cls):
        return cls(
            admin_token=os.environ.get('ADMIN_TOKEN', ''),
            encryption_key=os.environ.get('SESSION_ENCRYPTION_KEY', ''),
            database_path=os.getenv('DATABASE_PATH', 'data/insta.sqlite3'),
            supabase_url=os.getenv('SUPABASE_URL', '').rstrip('/'),
            supabase_key=os.getenv('SUPABASE_SERVICE_ROLE_KEY', ''),
            origins=tuple(x.strip() for x in os.getenv('ALLOWED_ORIGINS', 'http://localhost:8000').split(',') if x.strip()),
            action_delay=float(os.getenv('ACTION_DELAY_SECONDS', '10')),
        )
