"""Presentation locale for server pages and additive legacy API error metadata."""
from __future__ import annotations

import html
from http.cookies import SimpleCookie, CookieError
import re
from urllib.parse import parse_qs, urlparse

from project_docs.error_messages import MESSAGES

SUPPORTED = ('en', 'zh-TW')
COOKIE = 'zerofield_locale'
_EXACT = {text: key for text, key, pattern in MESSAGES if pattern is None}
_PATTERNS = [(re.compile(pattern), key) for text, key, pattern in MESSAGES if pattern]


def preference_headers(locale):
    locale = locale if locale in SUPPORTED else 'en'
    return {'Set-Cookie': f'{COOKIE}={locale}; Path=/; Max-Age=31536000; SameSite=Lax'}


def request_locale(handler) -> str:
    query = parse_qs(urlparse(getattr(handler, 'path', '')).query, keep_blank_values=True)
    if 'lang' in query:
        value = query['lang'][0]
    else:
        cookie = SimpleCookie()
        try:
            cookie.load(handler.headers.get('Cookie', ''))
            value = cookie[COOKIE].value if COOKIE in cookie else 'en'
        except CookieError:
            value = 'en'
    return value if value in SUPPORTED else 'en'


def error_details(payload):
    """Bridge existing services at the HTTP boundary; keep their error and policy code intact."""
    if not isinstance(payload, dict) or not isinstance(payload.get('error'), str) or payload.get('message_key'):
        return payload
    if payload.get('code') in ('projects_login', 'projects_membership', 'projects_unavailable'):
        return {**payload, 'message_key': 'access.' + payload['code'][9:], 'message_params': {}}
    text = payload['error']
    key, params = _EXACT.get(text), {}
    if key is None:
        for pattern, candidate in _PATTERNS:
            match = pattern.fullmatch(text)
            if match:
                key, params = candidate, match.groupdict()
                break
    if key is None:
        return payload
    return {**payload, 'code': payload.get('code', key), 'message_key': 'errors.' + key, 'message_params': params}


_COPY = {
    'en': {'signIn':'Sign In', 'token':'Access Token', 'proxy':'Sign in through the configured reverse proxy.',
           'open':'Open Studio', 'invalid':'Invalid token or disabled account.', 'current':'Signed in as: ',
           'loginTitle':'Sign In Required', 'login':'Sign in to your studio account to open this page.',
           'membershipTitle':'Production Access Required', 'membership':'This production is available to its crew. Contact the showrunner to request access.',
           'unavailableTitle':'Identity Verification Unavailable', 'unavailable':'Sign-in verification is temporarily unavailable. Refresh this page shortly.', 'language':'Interface Language'},
    'zh-TW': {'signIn':'登入', 'token':'存取權杖', 'proxy':'請透過已設定的反向代理登入。',
              'open':'開啟工作室', 'invalid':'權杖無效或帳號已停用。', 'current':'目前登入：',
              'loginTitle':'請先登入', 'login':'請先登入工作室帳號，再開啟此頁面。',
              'membershipTitle':'需要專案存取權', 'membership':'此專案僅供劇組成員使用。請聯絡製片總監申請存取權。',
              'unavailableTitle':'暫時無法確認身分', 'unavailable':'登入驗證暫時無法使用，請稍後重新整理。', 'language':'介面語言'},
}


def _page(locale, title, content):
    locale = locale if locale in SUPPORTED else 'en'
    copy = _COPY[locale]
    links = '<nav aria-label="' + copy['language'] + '">' + ' · '.join(
        f'<a href="/login?lang={language}" lang="{language}"' + (' aria-current="true"' if locale == language else '') + f'>{label}</a>'
        for language, label in [('en','English'), ('zh-TW','繁體中文')]) + '</nav>'
    return (f'<!doctype html><html lang="{locale}"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>ZeroField Studio — {html.escape(title)}</title><style>body{{font:16px system-ui;max-width:480px;margin:12vh auto;padding:24px;background:#f8fafc;color:#1e293b}}'
            'input,button{padding:12px;margin:12px 0;display:block;width:100%;box-sizing:border-box}button{background:#4338ca;color:white;border:0;border-radius:6px}'
            'nav{margin-bottom:32px;font-size:14px}nav a{color:#4338ca}nav [aria-current]{font-weight:700}p{line-height:1.7}</style>'
            f'{links}<main><h1>ZeroField Studio</h1>{content}</main></html>')


def login_html(mode, locale='en', error=''):
    locale = locale if locale in SUPPORTED else 'en'
    copy = _COPY[locale]
    if error == _COPY['en']['invalid']:
        error = copy['invalid']
    content = f'<p role="alert">{html.escape(str(error))}</p>' if error else ''
    if mode == 'token':
        content += (f'<form method="post" action="/login"><label>{copy["token"]}'
                    '<input name="token" type="password" autocomplete="current-password" required></label>'
                    f'<button>{copy["signIn"]}</button></form>')
    elif mode == 'header':
        content += f'<p>{copy["proxy"]}</p>'
    else:
        content += f'<a href="/projects/">{copy["open"]}</a>'
    return _page(locale, copy['signIn'], content)


def problem_html(problem, locale='en', email=''):
    locale = locale if locale in SUPPORTED else 'en'
    copy = _COPY[locale]
    title = copy[problem + 'Title']
    content = f'<h2>{title}</h2><p>{copy[problem]}</p>'
    if email:
        content += f'<p>{copy["current"]}{html.escape(str(email))}</p>'
    content += f'<a href="/login">{copy["signIn"]}</a>'
    return {'login':401, 'membership':403, 'unavailable':503}[problem], _page(locale, title, content)


def problem_details(problem):
    """The API retains its stable English fallback independently of browser preferences."""
    copy = _COPY['en']
    return {'login':401, 'membership':403, 'unavailable':503}[problem], copy[problem + 'Title'], copy[problem]
