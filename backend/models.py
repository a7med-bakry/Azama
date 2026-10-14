import re
import json
from urllib.parse import urlsplit
from typing import Literal, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError


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
            raise PydanticCustomError('session_too_large', 'Session file too large')
        # Ignore runtime/retry overrides and unrelated fields from uploaded JSON.
        allowed = ('uuids', 'mid', 'ig_u_rur', 'ig_www_claim', 'authorization_data',
                   'cookies', 'last_login', 'device_settings', 'user_agent',
                   'country', 'country_code', 'locale', 'timezone_offset')
        value = {key: item for key, item in value.items() if key in allowed}
        cookies, auth = value.get('cookies', {}), value.get('authorization_data', {})
        if not isinstance(cookies, dict) or not isinstance(auth, dict):
            raise PydanticCustomError('session_credentials_format', 'Invalid session credentials')
        token = auth.get('sessionid') or cookies.get('sessionid')
        if not isinstance(token, str) or not token:
            raise PydanticCustomError('session_credentials_missing', 'Session credentials missing')
        return value


def session_validation_message(errors):
    """Describe file validation without returning its private contents."""
    reasons = {
        'session_too_large': 'ملف السيشن أكبر من الحد المسموح (12 كيلوبايت).',
        'session_credentials_format': 'صيغة بيانات السيشن غير مدعومة. اختر ملف JSON ناتجًا من client.dump_settings في instagrapi.',
        'session_credentials_missing': 'الملف لا يحتوي على بيانات جلسة تسجيل دخول. اختر ملف session.json الناتج من client.dump_settings بعد دخول ناجح.',
    }
    for error in errors:
        message = reasons.get(error.get('type'))
        if message:
            return message
    return 'تعذر قراءة بيانات السيشن. اختر ملف JSON ناتجًا من client.dump_settings في instagrapi؛ استيراد السيشن لا يحتاج اسم مستخدم أو كلمة مرور.'


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
        match = re.fullmatch(r'/(?:(?P<username>[A-Za-z0-9_.]{1,30})/)?(?P<kind>p|reel|reels|tv)/(?P<shortcode>[A-Za-z0-9_-]+)/?', parts.path)
        username = match.group('username') if match else None
        if not match or (username and (not username.strip('.') or username.lower() in ('share', 'stories', 'explore', 'accounts', 'direct', 'p', 'reel', 'reels', 'tv'))):
            raise ValueError('Use a post or reel URL')
        kind = 'reel' if match.group('kind') == 'reels' else match.group('kind')
        return f'https://www.instagram.com/{kind}/{match.group("shortcode")}/'

    @model_validator(mode='after')
    def valid_request(self):
        if len(set(self.account_ids)) != len(self.account_ids):
            raise PydanticCustomError('duplicate_accounts', 'Duplicate accounts')
        if self.quantity > len(self.account_ids):
            raise PydanticCustomError('quantity_exceeds_accounts', 'Quantity must not exceed the number of selected accounts')
        if self.action == 'comment' and not self.comment.strip():
            raise PydanticCustomError('comment_required', 'A comment is required')
        self.comment = self.comment.strip()
        return self


def job_validation_message(errors):
    """Use fixed field/error messages; validation input/context can contain secrets."""
    fields = {
        'action': 'اختر لايكات أو تعليقات لنوع العملية.',
        'url': 'أدخل رابط المنشور أو الريل مباشرة؛ نقبل /p/ و/reel/ و/reels/ حتى لو سبقها اسم الحساب. رابط الحساب أو الستوري أو المشاركة المختصر لا يصلح هنا.',
        'account_ids': 'اختر من 1 إلى 100 حساب مسجل للعملية.',
        'quantity': 'اكتب عددًا صحيحًا من 1 إلى 100؛ عملية واحدة لكل حساب.',
        'comment': 'اكتب نص التعليق، بحد أقصى 1000 حرف.',
    }
    rules = {
        'duplicate_accounts': 'كل حساب يُختار مرة واحدة فقط في الطلب.',
        'quantity_exceeds_accounts': 'عدد العمليات أكبر من الحسابات المحددة؛ لحساب واحد استخدم العدد 1.',
        'comment_required': 'اكتب نص التعليق قبل إنشاء طلب التعليقات.',
    }
    messages = []
    for error in errors:
        location = error.get('loc', ())
        field = location[1] if len(location) > 1 and location[0] == 'body' else None
        message = fields.get(field) or rules.get(error.get('type'))
        if message and message not in messages:
            messages.append(message)
    return ' '.join(messages) or 'بيانات الطلب غير صالحة؛ راجع نوع العملية والرابط والعدد والحسابات المحددة.'
