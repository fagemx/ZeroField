"""Official Router 1.0 queued/native protocol; no local graph or vendor adapter.

/estimate is not a price lock. Only explicit project soft-estimate opt-in permits
these non-hard quotes. See docs/COMFY_ROUTER.md for captured official evidence.
"""
from __future__ import annotations

import copy
import datetime as dt
from decimal import Decimal, ROUND_CEILING
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlsplit

from . import card_engine, model_router, runtime
from . import _compat as legacy

MODELS = {
    'ltx/ltx-2-5-pro': '36d5297387ff',
    'ltx/ltx-2-5-fast': '36d5297387ff',
    'bfl/flux-3-image': '3184229fc5e3',
    'bfl/flux-3-video': '14d51fd15b79',
    'minimax/minimax-h3': 'c0e2e941ffff',
    'byteplus/dreamina-seedance-2-5-260628': 'ea6dda283563',
    'higgsfield/higgsfield-genjutsu-motion-transfer-v1.0': '77d0cffa3d15',
}
_CACHE = {}
_LOCK = threading.Lock()
QUOTE_SECONDS = 120


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_config(config, output_mode):
    model = config.get('model')
    if model not in MODELS:
        raise runtime.WorkerError('Router model has no verified contract; future catalog IDs are not executable.')
    if config.get('api_key_env') != 'COMFY_API_KEY' or any(k in config for k in ('api_key', 'token', 'authorization', 'workflow', 'platform', 'adapter_contract')):
        raise runtime.WorkerError('Official Router requires the server COMFY_API_KEY reference, never graph/vendor credentials.')
    if output_mode != ('image' if model == 'bfl/flux-3-image' else 'video'):
        raise runtime.WorkerError('Router model output capability mismatch.')


def base_url():
    base = os.environ.get('COMFY_ROUTER_BASE_URL', '').strip().rstrip('/') or 'https://api.comfy.org'
    model_router._endpoint(base)
    if urlsplit(base).path not in ('', '/') or urlsplit(base).query:
        raise runtime.WorkerError('Router base must be an origin.')
    return base


def asset_base():
    base = os.environ.get('COMFY_ROUTER_ASSET_BASE_URL', '').strip().rstrip('/') or 'https://cloud.comfy.org'
    model_router._endpoint(base)
    if urlsplit(base).path not in ('', '/') or urlsplit(base).query:
        raise runtime.WorkerError('Router asset base must be an origin.')
    return base


def _origins(card):
    entries = list(card['engine_config'].get('media_origins', [])) + [v.strip() for v in os.environ.get('COMFY_ROUTER_MEDIA_ORIGINS','').split(',') if v.strip()]
    if not entries and urlsplit(base_url()).hostname not in ('127.0.0.1','localhost','::1'):
        raise runtime.WorkerError('Configure explicit Router output media origins before paid execution.')
    origins = {model_router._endpoint(base_url())}
    for entry in entries:
        if urlsplit(entry).path not in ('','/') or urlsplit(entry).query:
            raise runtime.WorkerError('Router output media origins must be origins only.')
        origins.add(model_router._endpoint(entry))
    return origins


def configuration_status(card):
    try:
        validate_config(card['engine_config'], card['output_mode'])
        base_url(); asset_base()
        _origins(card)
        if 'COMFY_API_KEY' not in {n.strip() for n in os.environ.get('OPENBENCH_AGENT_KEY_ENVS', '').split(',')}:
            raise runtime.WorkerError('COMFY_API_KEY is not allowlisted.')
        runtime.configured_token(card['engine_config'])
    except runtime.WorkerError as exc:
        return {'configured': False, 'requires_comfyui': False, 'connection_state': 'not_checked', 'reason': str(exc)}
    return {'configured': True, 'requires_comfyui': False, 'connection_state': 'not_checked',
            'model_contract': MODELS[card['engine_config']['model']], 'hard_price_bound': False,
            'price_protocol': 'POST /v2/models/{provider}/{model}/estimate',
            'mcp_state': 'discovery_not_checked_execution_disabled', 'sdk_bridge': 'separate_jobs_assets_v2'}


def _check(head, url=None):
    model_router._check_lease(head)
    if url and callable(getattr(type(head), 'outbound_check', None)):
        head.outbound_check(url)


def _http(head, url, *, method='GET', payload=None, data=None, mime=None, key=None, redirect_url=False, before_send=None, credential_digest=None):
    _check(head, url)
    token = runtime.configured_token({'api_key_env': 'COMFY_API_KEY'})
    token_digest=hashlib.sha256(token.encode()).hexdigest()
    if credential_digest is not None and token_digest != credential_digest:
        raise runtime.WorkerError('Router credential changed after quote; no further export is allowed.')
    timeout = head.outbound_timeout(30) if callable(getattr(type(head), 'outbound_timeout', None)) else 30
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    if key:
        headers['Idempotency-Key'] = key
    if payload is not None:
        data, mime = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode(), 'application/json'
    if mime:
        headers['Content-Type'] = mime
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    if before_send is not None:
        before_send(token_digest)  # Last authority/currency gate immediately before the socket opens.
    try:
        deadline=time.monotonic()+timeout
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=timeout) as response:
            chunks=[];size=0
            while True:
                chunk=response.read1(65536)
                _check(head)
                size+=len(chunk)
                if size>4*1024*1024 or time.monotonic()>deadline:
                    raise runtime.WorkerError('Router response exceeds size or time limit.')
                if not chunk:break
                chunks.append(chunk)
            result = json.loads(b''.join(chunks))
            status, received = response.status, dict(response.headers)
    except urllib.error.HTTPError as exc:
        status = exc.code
        location = exc.headers.get('Location')
        exc.close()
        if redirect_url and status in (301, 302, 303, 307, 308) and location:
            _check(head, location)
            return status, {'url': location}, {}
        raise runtime.NonRetryableWorkerError('Router HTTP ' + str(status) + '; no automatic resubmission.') from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise runtime.NonRetryableWorkerError('Router transport ambiguous; reconcile before explicit retry.') from None
    except (ValueError, TypeError):
        raise runtime.NonRetryableWorkerError('Router returned invalid JSON.') from None
    if not isinstance(result, dict):
        raise runtime.NonRetryableWorkerError('Router returned an invalid document.')
    _check(head)
    return status, result, received


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _nodes(task, card, values):
    # Compilation is pure: no remote export, asset reads or DB calls under locks.
    items = model_router._inputs(task, card, values, None)
    return {n['fieldName']: item['fieldValue'] for n, item in zip(card['nodes'], items)}


def _identity(ctx, task, card, values):
    validate_config(card['engine_config'], card['output_mode'])
    nodes = _nodes(task, card, values)
    # Source/policy/owner also enter the reservation operation digest; immutable media
    # handles plus the expanded form bind this cached native payload to exact inputs.
    return digest([str(ctx.me.actor_id), ctx.slug, card, nodes, task.get('production_policy'), base_url(), asset_base()]), nodes


def _native(card, nodes, media):
    """Supported explicit subset of each captured native schema; reject extras."""
    model = card['engine_config']['model']
    fields = ({'prompt','duration','resolution','fps','generate_audio'} if model.startswith('ltx/') else
              {'prompt','resolution','aspect_ratio','grounding',*[f'image_{i}' for i in range(1,6)]} if model == 'bfl/flux-3-image' else
              {'prompt','mode','duration','resolution','aspect_ratio','generate_audio','image_1','image_2','start_video'} if model == 'bfl/flux-3-video' else
              {'prompt','duration','resolution','ratio','first_frame','reference_image','base_video','reference_audio'} if model.startswith('minimax/') else
              {'prompt','duration','resolution','ratio','generate_audio','first_frame','reference_image','reference_video','reference_audio'} if model.startswith('byteplus/') else
              {'prompt','resolution','video_url',*[f'image_{i}' for i in range(1,6)]})
    known = {n['fieldName'] for n in card['nodes']}
    if set(nodes) != known or known != fields or set(media)-fields:
        raise runtime.WorkerError('Router card inputs do not match the frozen form.')
    p = {}
    for n in card['nodes']:
        name, value = n['fieldName'], nodes[n['fieldName']]
        if n['fieldType'] in ('IMAGE', 'VIDEO', 'AUDIO'):
            continue
        if n['fieldType'] in ('INT', 'FLOAT'):
            value = int(value) if n['fieldType'] == 'INT' else float(value)
        elif name == 'fps':
            value = int(value)
        elif name in ('generate_audio', 'grounding'):
            value = value == 'true'
        p[name] = value
    if not p.get('prompt', '').strip():
        raise runtime.WorkerError('Router prompt is required.')
    if model.startswith('ltx/'):
        if p['duration'] not in (2,3,4,5,6,8,10,12,14,16,18,20):
            raise runtime.WorkerError('Unsupported LTX duration.')
        if model.endswith('-pro') and p['resolution'] not in ('1280x720','720x1280','1920x1080','1080x1920'):
            raise runtime.WorkerError('Unsupported LTX Pro resolution.')
    elif model == 'bfl/flux-3-image':
        if p['resolution'] not in ('768sq','1k','1.5k','2k','4k'):
            raise runtime.WorkerError('Unsupported FLUX image resolution.')
        images = [v for k,v in media.items() if k.startswith('image_')]
        if images:
            p['images'] = images
    elif model == 'bfl/flux-3-video':
        mode = p['mode']
        if mode not in ('t2v','i2v','v2v') or type(p['duration']) is not int or not 5<=p['duration']<=20:
            raise runtime.WorkerError('Unsupported FLUX video mode or bounded duration.')
        keyframes = [v for k,v in media.items() if k.startswith('image_')]
        video = media.get('start_video')
        if (mode == 'i2v' and not keyframes) or (mode == 'v2v' and not video) or (mode != 'i2v' and keyframes) or (mode != 'v2v' and video):
            raise runtime.WorkerError('FLUX video mode and reference media disagree.')
        if keyframes:
            p['keyframes'] = keyframes
        if video:
            p['start_video'] = video
    elif model.startswith(('minimax/', 'byteplus/')):
        p['content'] = [{'type': 'text', 'text': p.pop('prompt')}]
        if media.get('first_frame') and any(k.startswith('reference_') for k in media):
            raise runtime.WorkerError('Keyframes and reference media are mutually exclusive.')
        if model.startswith('byteplus/') and re.search(r'--(?:duration|dur|resolution|rs|ratio|rt|framepersecond|fps|seed|generate_audio|watermark|wm)\b',p['content'][0]['text'],re.I):
            raise runtime.WorkerError('Use typed Seedance controls, not conflicting inline model parameters.')
        if model.startswith('byteplus/') and (p['resolution'] not in ('480p','720p','1080p') or not 4<=p['duration']<=30):
            raise runtime.WorkerError('Unsupported Seedance 2.5 resolution or bounded duration.')
        if p['ratio'] not in ('adaptive','16:9','9:16','1:1','4:3','3:4','21:9','9:21') or (model.startswith('minimax/') and not media and p['ratio']=='adaptive'):
            raise runtime.WorkerError('Unsupported model aspect ratio.')
        if model.startswith('byteplus/') and media.get('first_frame') and p['ratio'] != 'adaptive':
            raise runtime.WorkerError('Seedance first frame requires adaptive aspect ratio.')
        for name, url in media.items():
            kind = 'image_url' if name in ('first_frame','reference_image') else 'audio_url' if name == 'reference_audio' else 'video_url'
            p['content'].append({'type': kind, 'role': name, kind: {'url': url}})
    else:
        if p['resolution'] not in ('480p','720p','1080p'):
            raise runtime.WorkerError('Unsupported Genjutsu resolution.')
        images = [v for k,v in media.items() if k.startswith('image_')]
        if not images or not media.get('video_url'):
            raise runtime.WorkerError('Genjutsu requires reference images and a source video.')
        p.update(image_urls=images, video_url=media['video_url'])
    validate_native(model, p)
    return p


def validate_native(model, payload):
    """Validate our conservative subset against the pinned official input schema."""
    from openbench_data import resource_path
    document = json.loads(resource_path('workflows','router',model.replace('/','--')+'.json').read_text(encoding='utf-8'))
    schema = next(iter(document['paths'].values()))['post']['requestBody']['content']['application/json']['schema']
    def valid(value, rule):
        if '$ref' in rule:
            return valid(value,document['components']['schemas'][rule['$ref'].split('/')[-1]])
        if 'anyOf' in rule and not any(valid(value,r) for r in rule['anyOf']):
            return False
        if 'oneOf' in rule and sum(valid(value,r) for r in rule['oneOf']) != 1:
            return False
        if 'enum' in rule and value not in rule['enum']:
            return False
        kind = rule.get('type')
        if kind == 'object' or (isinstance(value,dict) and ('properties' in rule or 'required' in rule)):
            if not isinstance(value,dict) or set(rule.get('required',[]))-set(value):
                return False
            props=rule.get('properties',{})
            if rule.get('additionalProperties') is False and set(value)-set(props):
                return False
            return all(valid(v,props[k]) for k,v in value.items() if k in props)
        if kind == 'array':
            return isinstance(value,list) and rule.get('minItems',0)<=len(value)<=rule.get('maxItems',100) and all(valid(v,rule.get('items',{})) for v in value)
        if kind == 'string':
            return isinstance(value,str) and rule.get('minLength',0)<=len(value)<=rule.get('maxLength',100000)
        if kind == 'boolean':
            return type(value) is bool
        if kind in ('integer','number'):
            if type(value) not in ((int,) if kind=='integer' else (int,float)) or not math.isfinite(value):
                return False
        if type(value) in (int,float) and not rule.get('minimum',-math.inf)<=value<=rule.get('maximum',math.inf):
            return False
        return True
    if set(payload)-set(schema['properties']) or not valid(payload,schema):
        raise runtime.WorkerError('Router inputs fail the pinned official model schema.')


def _export(head, raw, mime, credential_digest):
    boundary = 'ZeroField' + uuid.uuid4().hex
    filename = 'reference' + {'image/png':'.png','image/jpeg':'.jpg','image/webp':'.webp','video/mp4':'.mp4','video/quicktime':'.mov','audio/wav':'.wav','audio/mpeg':'.mp3'}[mime]
    fields = ''.join(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n' for k,v in [('content_type',mime),('file_path',filename)])
    data = (fields + f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n').encode() + raw + f'\r\n--{boundary}--\r\n'.encode()
    _, asset, _ = _http(head, asset_base() + '/api/v2/assets', method='POST', data=data,
                           mime='multipart/form-data; boundary=' + boundary, key=uuid.uuid4().hex, credential_digest=credential_digest)
    identifier = asset.get('id')
    if not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}', identifier):
        raise runtime.WorkerError('Official asset upload returned no valid asset ID.')
    status, result, _ = _http(head, asset_base() + '/api/v2/assets/' + identifier + '/content', redirect_url=True, credential_digest=credential_digest)
    if status not in (301,302,303,307,308):
        raise runtime.WorkerError('Router references require a public signed Comfy Cloud asset URL, not a local authenticated URL.')
    url = result['url']
    model_router._endpoint(url)
    return url


def quote(ctx, task, card, values, head):
    """Network OUTSIDE transactions. Returns safe metadata, never signed URLs."""
    if not configuration_status(card)['configured']:
        raise runtime.WorkerError('Official Router is not configured with an allowlisted COMFY_API_KEY.')
    model_router.enforce_card_policy(card, task.get('production_policy'))
    key, nodes = _identity(ctx, task, card, values)
    credential_digest=hashlib.sha256(os.environ['COMFY_API_KEY'].encode()).hexdigest()
    references = {n['fieldName']: nodes[n['fieldName']] for n in card['nodes'] if n['fieldType'] in ('IMAGE','VIDEO','AUDIO') and nodes[n['fieldName']] != 'None'}
    # Validate cross-field requirements before any media export or price read.
    _native(card, nodes, references)
    media, duration = {}, None
    for n in card['nodes']:
        name = n['fieldName']
        if name not in references:
            continue
        _check(head)
        raw, mime = head.asset(task, references[name])
        if not raw or len(raw) > runtime.MAX_MEDIA or not mime.startswith(n['fieldType'].lower() + '/'):
            raise runtime.WorkerError('Unsupported or oversized Router reference media.')
        from project_docs import media as media_validation
        media_validation.validate(raw,mime)
        if card['engine_config']['model']=='bfl/flux-3-image' and mime.startswith('image/'):
            from PIL import Image
            import io
            with Image.open(io.BytesIO(raw)) as image:
                if min(image.size)<256 or image.width*image.height>16000000:
                    raise runtime.WorkerError('FLUX 3 reference dimensions must be at least 256px and at most 16 megapixels.')
        if n.get('slot') == 'driving_video':
            with tempfile.TemporaryDirectory(prefix='zerofield-router-source-') as folder:
                path = Path(folder)/'source.mp4'; path.write_bytes(raw)
                duration = legacy._probe_video(path,{'probe_timeout':head.outbound_timeout(30)})['duration']
            if card['engine_config']['model'].startswith('higgsfield/') and duration < 4:
                raise runtime.WorkerError('Genjutsu source video must be at least four seconds.')
        media[name] = _export(head, raw, mime, credential_digest)
    payload = _native(card, nodes, media)
    _, detail, _ = _http(head, base_url() + '/v2/models/' + card['engine_config']['model'], credential_digest=credential_digest)
    if detail.get('id') != card['engine_config']['model']:
        raise runtime.WorkerError('Router model is unavailable or catalog identity disagrees.')
    _, result, _ = _http(head, base_url() + '/v2/models/' + card['engine_config']['model'] + '/estimate', method='POST', payload=payload, credential_digest=credential_digest)
    source = result.get('source')
    amount = result.get('amount') if source == 'exact' else result.get('max_amount') if source == 'estimated' else None
    if result.get('provider') != card['engine_config']['model'].split('/')[0] or result.get('model') != card['engine_config']['model'] or result.get('currency') != 'USD' or not isinstance(amount,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?', amount) or not isinstance(result.get('pricing_as_of'), str):
        raise runtime.WorkerError('Router price is unknown, unavailable or invalid; no generation admitted.')
    if source == 'estimated':
        low = result.get('min_amount')
        if not isinstance(low,str) or not re.fullmatch(r'(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?',low) or Decimal(low)>Decimal(amount) or 'amount' in result:
            raise runtime.WorkerError('Router estimate interval is invalid.')
    from project_assistant import orchestrator as cp
    cp.instant(result['pricing_as_of'])
    entry = {'payload':payload, 'payload_digest':digest(payload), 'amount':Decimal(amount).quantize(Decimal('.0001'),rounding=ROUND_CEILING), 'quoted_amount':amount, 'source':source,
             'expires_at': cp.now()+dt.timedelta(seconds=QUOTE_SECONDS), 'source_duration':duration,
             'pricing_as_of':result['pricing_as_of'], 'credential_digest':credential_digest}
    if credential_digest != hashlib.sha256(os.environ.get('COMFY_API_KEY','').encode()).hexdigest():
        raise runtime.WorkerError('Router credential changed during pricing; obtain a new quote.')
    _check(head)
    with _LOCK:
        for old in [k for k,v in _CACHE.items() if v['expires_at'] <= cp.now()]:
            del _CACHE[old]
        if len(_CACHE) >= 256:
            raise runtime.WorkerError('Router quote cache capacity reached; retry after quotes expire.')
        _CACHE[key] = entry
    return {'model':card['engine_config']['model'], 'amount_usd':entry['quoted_amount'], 'reservation_usd':str(entry['amount']), 'source':source,
            'pricing_as_of':entry['pricing_as_of'], 'expires_at':entry['expires_at'].isoformat(),
            'hard_bound':False, 'budget_mode':'estimate_soft', 'input_digest':entry['payload_digest'],
            'warning':'Estimate only, not a price lock or guaranteed billing cap.'}


def prepared(ctx, task, card, values):
    from project_assistant import orchestrator as cp
    key, _ = _identity(ctx, task, card, values)
    with _LOCK:
        entry = copy.deepcopy(_CACHE.get(key))
    if not entry or entry['expires_at'] <= cp.now():
        raise runtime.WorkerError('Obtain a current official Router quote for these exact inputs before dispatch.')
    if entry['credential_digest'] != hashlib.sha256(os.environ.get('COMFY_API_KEY','').encode()).hexdigest():
        raise runtime.WorkerError('Router credential changed; obtain a new quote.')
    return entry


def health(head, model):
    if model not in MODELS:
        raise runtime.WorkerError('Unverified Router model ID.')
    _, detail, _ = _http(head, base_url() + '/v2/models/' + model)
    return {'connection_state':'reachable' if detail.get('id') == model else 'unavailable', 'model':model,
            'generation_verified':False, 'billing_verified':False, 'mcp_state':'discovery_not_checked_execution_disabled'}


def execute(task, card, values, head):
    from project_assistant import execution_governance as governance
    try:
        ctx = getattr(head, 'accounting_context', None)
        if ctx is None:
            raise runtime.WorkerError('Official hosted Router requires a trusted governed actor/project operation.')
        entry = prepared(ctx, task, card, values)
        path = base_url() + '/v2/models/' + card['engine_config']['model'] + '/requests'
        operation_key = ctx.active_operation_key
        def before_send(token_digest):
            if token_digest != entry['credential_digest'] or token_digest != hashlib.sha256(os.environ.get('COMFY_API_KEY','').encode()).hexdigest():
                raise runtime.WorkerError('Router quote credential was revoked before submit.')
            head.paid_request_submitted = True
            governance.transaction(ctx, lambda conn: governance.router_submission(conn, ctx, operation_key, card, entry['payload_digest']))
        deadline = time.monotonic() + model_router._positive(card['engine_config'].get('timeout',600), 'timeout')
        status, handle, _ = _http(head, path, method='POST', payload=entry['payload'], key='zf-' + digest([ctx.slug,str(ctx.me.actor_id),operation_key]), before_send=before_send, credential_digest=entry['credential_digest'])
        rid = handle.get('request_id')
        if status != 201 or not isinstance(rid,str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,80}',rid) or handle.get('status') != 'IN_QUEUE':
            raise runtime.WorkerError('Router queued submit returned invalid handle; reconcile before retry.')
        # Derive same-origin documented paths; never follow handle URLs with credentials.
        result_path = path + '/' + rid
        while True:
            _check(head)
            if time.monotonic() >= deadline:
                raise runtime.WorkerError('Router timed out; remote generation may remain billable.')
            _, state, _ = _http(head, result_path + '/status', credential_digest=entry['credential_digest'])
            if state.get('request_id') != rid or state.get('status') not in ('IN_QUEUE','IN_PROGRESS','COMPLETED'):
                raise runtime.WorkerError('Invalid Router queue state.')
            if state['status'] == 'COMPLETED':
                if state.get('error_type'):
                    raise runtime.WorkerError('Router generation failed or was canceled; reconcile any charge.')
                break
            time.sleep(min(.25, max(0,deadline-time.monotonic())))
        _, result, headers = _http(head, result_path, credential_digest=entry['credential_digest'])
        credits = next((v for k,v in headers.items() if k.lower() == 'x-comfy-credits-used'), None)
        if credits is not None and re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', credits):
            # Reported price, NOT a settled invoice. Never truncate an over-estimate.
            governance.transaction(ctx, lambda conn: governance.router_reported_cost(conn, ctx, operation_key, Decimal(credits)/Decimal(211)))
        model = card['engine_config']['model']
        if model.startswith('ltx/'):
            url = (result.get('result') or {}).get('video_url') if result.get('status') == 'completed' else None
        elif model.startswith('bfl/'):
            url = (result.get('result') or {}).get('sample') if str(result.get('status')).strip().lower() == 'ready' else None
        elif model.startswith('minimax/'):
            native = result.get('task') or {}
            url = (native.get('content') or {}).get('url') if native.get('status') == 'succeeded' else None
        elif model.startswith('byteplus/'):
            url = (result.get('content') or {}).get('video_url') if result.get('status') == 'succeeded' else None
        else:
            url = (result.get('video') or {}).get('url') if result.get('status') == 'completed' else None
        if not isinstance(url,str):
            raise runtime.WorkerError('Router completed without supported native output.')
        allowed = _origins(card)
        if model_router._endpoint(url) not in allowed:
            raise runtime.WorkerError('Router output origin requires explicit operator media_origins authorization.')
        _check(head,url)
        raw,mime = legacy.fetch(url,limit=runtime.MAX_MEDIA,timeout=head.outbound_timeout(30))
        _check(head)
        nodes = _nodes(task,card,values)
        requested = float(nodes['duration']) if 'duration' in nodes else min(30,entry['source_duration']) if entry['source_duration'] is not None else None
        config = dict(card['engine_config'], _lease_lost=lambda: head.lease_lost())
        return model_router._persist_output(task,card,head,raw,mime,requested,entry['source_duration'],config)
    except runtime.NonRetryableWorkerError:
        raise
    except runtime.WorkerError as exc:
        raise runtime.NonRetryableWorkerError(str(exc)) from None
    except Exception:
        raise runtime.NonRetryableWorkerError('Official Router failed; reconcile any accepted generation before explicit retry.') from None
