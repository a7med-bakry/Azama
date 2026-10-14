import re
import json
from urllib.parse import urlsplit
from typing import Literal, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class LoginInput(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(default='', max_length=300)

    @field_validator('username')
    @classmethod
    def username_valid(cls, value):
        value = value.strip().lower()
        if not (re.fullmatch(r'[a-z0-9_.]{1,30}', value) or re.fullmatch(r'[a-z0-9_.+%-]+@[a-z0-9.-]+\.[a-z]{2,}', value)):
            raise ValueError('Use a valid Instagram username or email address')
        return value


class SessionInput(BaseModel):
    settings: dict

    @field_validator('settings')
    @classmethod
    def session_valid(cls, value):
        if len(json.dumps(value).encode()) > 12288:
            raise ValueError('Session file too large')
        # Ignore runtime/retry overrides and unrelated fields from uploaded JSON.
        allowed = ('uuids', 'mid', 'ig_u_rur', 'ig_www_claim', 'authorization_data',
                   'cookies', 'last_login', 'device_settings', 'user_agent',
                   'country', 'country_code', 'locale', 'timezone_offset')
        value = {key: item for key, item in value.items() if key in allowed}
        cookies, auth = value.get('cookies', {}), value.get('authorization_data', {})
        if not isinstance(cookies, dict) or not isinstance(auth, dict):
            raise ValueError('Invalid session credentials')
        token = auth.get('sessionid') or cookies.get('sessionid')
        if not isinstance(token, str) or not token:
            raise ValueError('Session credentials missing')
        return value


class CodeInput(BaseModel):
    code: str = Field(pattern=r'^\d{6,8}$')
    challenge_id: str = Field(min_length=1, max_length=64)


class JobInput(BaseModel):
    action: Literal['like', 'comment']
    url: str = Field(max_length=500)
    account_ids: List[str] = Field(min_length=1, max_length=100)
    quantity: int = Field(ge=1, le=100)
    comment: str = Field(default='', max_length=1000)

    @field_validator('url')
    @classmethod
    def instagram_url(cls, value):
        parts = urlsplit(value.strip())
        if parts.scheme != 'https' or parts.netloc not in ('instagram.com', 'www.instagram.com'):
            raise ValueError('Use an HTTPS Instagram URL')
        if not re.fullmatch(r'/(p|reel|tv)/[A-Za-z0-9_-]+/?', parts.path):
            raise ValueError('Use a post or reel URL')
        return 'https://www.instagram.com' + parts.path

    @model_validator(mode='after')
    def valid_request(self):
        if len(set(self.account_ids)) != len(self.account_ids):
            raise ValueError('Duplicate accounts')
        if self.quantity > len(self.account_ids):
            raise ValueError('Quantity must not exceed the number of selected accounts')
        if self.action == 'comment' and not self.comment.strip():
            raise ValueError('A comment is required')
        self.comment = self.comment.strip()
        return self
