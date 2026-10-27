"""Provider catalog (SPEC_20 R8) and usage tiers (R9).

`provider_catalog.json` lists presets with a usage tier and capability flags. A provider
configuration matches an entry by transport kind, endpoint (scheme, host, port and path;
every loopback name counts as the same host) and model name or alias. A configuration
that matches nothing still works with conservative capabilities: tools on, no
`tool_choice`, no JSON schema, images inlined as base64, an 8k context. Its tier follows
the endpoint: loopback is `local_open`, anything else is `closed` until the catalog says
otherwise.

Tier policy: `open_weights_only` allows `local_open`; `hosted_open` also needs the
showrunner's `provider_policy.hosted_open_enabled` setting; `closed` needs
`hybrid_studio`. The policy passed in is the effective production policy, so the
deployment ceiling `OPENBENCH_PRODUCTION_POLICY` already applies. No network, no secrets.
"""
from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

PATH = Path(__file__).with_name('provider_catalog.json')
TIERS = ('local_open', 'hosted_open', 'closed')
CAPABILITIES = ('tools', 'tool_choice', 'json_schema', 'vision', 'image_url')
EFFORTS = ('low', 'medium', 'high')
POLICIES = ('open_weights_only', 'hybrid_studio')
LOOPBACK = ('127.0.0.1', 'localhost', '::1')
BYTES_PER_TOKEN = 3      # conservative: most tokenizers average more bytes per token
BUDGET_SHARE = 0.8       # trim when an estimated request passes this share of the context
_ID = re.compile(r'[a-z0-9][a-z0-9_.-]{0,63}')


@dataclass(frozen=True)
class Entry:
    id: str | None
    label: str
    kind: str
    base_url: str
    model: str
    tier: str
    capabilities: dict
    context_tokens: int
    image_tokens: int
    default_effort: str | None = None
    api_key_env: str | None = None
    price: dict | None = None
    aliases: tuple = ()
    bytes_per_token: float = BYTES_PER_TOKEN
    matched: bool = field(default=True, compare=False)

    def can(self, capability):
        return bool(self.capabilities.get(capability))

    @property
    def budget_tokens(self):
        return int(self.context_tokens * BUDGET_SHARE)

    def public(self):
        """What a settings page may show: no credentials, only the name of the key variable."""
        return {'id': self.id, 'label': self.label, 'kind': self.kind, 'base_url': self.base_url, 'model': self.model,
                'tier': self.tier, 'capabilities': dict(self.capabilities), 'context_tokens': self.context_tokens,
                'default_effort': self.default_effort, **({'api_key_env': self.api_key_env} if self.api_key_env else {}),
                **({'price': dict(self.price)} if self.price else {})}


def local(url) -> bool:
    try:
        return urlsplit(url).hostname in LOOPBACK
    except ValueError:
        return False


def _endpoint(url):
    try:
        parts = urlsplit(str(url).strip())
        host, port = (parts.hostname or '').lower(), parts.port
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not host:
        return None
    return (parts.scheme, 'loopback' if host in LOOPBACK else host,
            port or (443 if parts.scheme == 'https' else 80), parts.path.rstrip('/'))


def _entry(raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('id'), str) or not _ID.fullmatch(raw['id']):
        raise ValueError('Catalog entries need a lowercase id.')
    name = raw['id']
    caps = raw.get('capabilities')
    if not isinstance(caps, dict) or set(caps) != set(CAPABILITIES) or any(type(v) is not bool for v in caps.values()):
        raise ValueError(f'{name}: capabilities must be the five boolean flags.')
    if raw.get('kind') != 'openai_compat' or raw.get('tier') not in TIERS or _endpoint(raw.get('base_url')) is None:
        raise ValueError(f'{name}: kind, tier or base_url is invalid.')
    if not isinstance(raw.get('model'), str) or not raw['model'] or not isinstance(raw.get('label'), str):
        raise ValueError(f'{name}: label and model are required.')
    for number in ('context_tokens', 'image_tokens'):
        if type(raw.get(number)) is not int or not 256 <= raw[number] <= 10_000_000:
            raise ValueError(f'{name}: {number} must be a positive token count.')
    if raw.get('default_effort') not in (None, *EFFORTS):
        raise ValueError(f'{name}: default_effort must be low, medium, high or null.')
    if (raw['tier'] == 'local_open') != local(raw['base_url']):
        raise ValueError(f'{name}: only loopback endpoints are local_open.')
    if raw['tier'] != 'local_open':
        price = raw.get('price')
        if not isinstance(raw.get('api_key_env'), str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{1,63}', raw['api_key_env']):
            raise ValueError(f'{name}: hosted entries name their api_key_env.')
        if urlsplit(raw['base_url']).scheme != 'https' or not isinstance(price, dict) or not isinstance(price.get('reference'), str):
            raise ValueError(f'{name}: hosted entries use https and carry a price reference.')
        if 'image_tokens_max' in price and (type(price['image_tokens_max']) is not int or price['image_tokens_max'] < raw['image_tokens']):
            raise ValueError(f'{name}: image_tokens_max must bound image_tokens.')
    ratio = raw.get('bytes_per_token', BYTES_PER_TOKEN)
    if isinstance(ratio, bool) or not isinstance(ratio, (int, float)) or not 1 <= ratio <= 8:
        raise ValueError(f'{name}: bytes_per_token must be between 1 and 8.')
    aliases = raw.get('aliases', [])
    if not isinstance(aliases, list) or any(not isinstance(a, str) or not a for a in aliases):
        raise ValueError(f'{name}: aliases must be model names.')
    return Entry(name, raw['label'], raw['kind'], raw['base_url'].rstrip('/'), raw['model'], raw['tier'], dict(caps),
                 raw['context_tokens'], raw['image_tokens'], raw.get('default_effort'), raw.get('api_key_env'),
                 dict(raw['price']) if raw.get('price') else None, tuple(aliases), ratio)


def load(path=PATH):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    unknown = data.get('unknown') or {}
    caps = unknown.get('capabilities')
    if not isinstance(caps, dict) or set(caps) != set(CAPABILITIES) or any(type(v) is not bool for v in caps.values()):
        raise ValueError('The unknown-provider fallback needs the five capability flags.')
    if type(unknown.get('context_tokens')) is not int or type(unknown.get('image_tokens')) is not int:
        raise ValueError('The unknown-provider fallback needs token counts.')
    entries = tuple(_entry(raw) for raw in data.get('entries') or [])
    if len({e.id for e in entries}) != len(entries):
        raise ValueError('Catalog ids must be unique.')
    return {'unknown': {'capabilities': dict(caps), 'context_tokens': unknown['context_tokens'], 'image_tokens': unknown['image_tokens']},
            'entries': entries}


@functools.lru_cache(maxsize=1)
def catalog():
    return load()


def entries(policy='open_weights_only'):
    """Presets offered under a production policy; closed ones only under hybrid_studio."""
    if policy not in POLICIES:
        raise ValueError('Unknown production policy.')
    return [e for e in catalog()['entries'] if e.tier != 'closed' or policy == 'hybrid_studio']


def match(config) -> Entry:
    """The catalog entry for a ProviderConfig-like object, or a conservative unknown entry."""
    kind, base_url, model = getattr(config, 'kind', None), getattr(config, 'base_url', ''), getattr(config, 'model', '')
    where = _endpoint(base_url)
    if where is not None:
        for entry in catalog()['entries']:
            if entry.kind == kind and _endpoint(entry.base_url) == where and model in (entry.model, *entry.aliases):
                return entry
    fallback = catalog()['unknown']
    return Entry(None, model or 'Unknown model', kind or '', (base_url or '').rstrip('/'), model or '',
                 'local_open' if local(base_url) else 'closed', dict(fallback['capabilities']),
                 fallback['context_tokens'], fallback['image_tokens'], matched=False)


def tier_of(config):
    return match(config).tier


def denial(tier, policy, *, hosted_open_enabled=False):
    """None when the effective production policy allows this tier, else why not."""
    if tier not in TIERS or policy not in POLICIES:
        return 'unknown_tier'
    if tier == 'local_open' or policy == 'hybrid_studio':
        return None
    return None if tier == 'hosted_open' and hosted_open_enabled is True else (
        'hosted_open_disabled' if tier == 'hosted_open' else 'closed_needs_hybrid')


def allowed(tier, policy, *, hosted_open_enabled=False):
    return denial(tier, policy, hosted_open_enabled=hosted_open_enabled) is None


DENIALS = {
    'hosted_open_disabled': 'Needs You: hosted open-weights models are off for this production. A showrunner can turn on '
                            'provider_policy.hosted_open_enabled in Agent Console settings, or keep the local model.',
    'closed_needs_hybrid': 'Needs You: closed models need the hybrid_studio production policy; this production (or the '
                           'deployment) is open_weights_only. Nothing was sent.',
    'unknown_tier': 'Needs You: this model has no usage tier; nothing was sent.',
}
