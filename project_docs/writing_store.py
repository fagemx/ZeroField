"""Scoped SPEC16 persistence. All writes participate in the caller's transaction."""
from __future__ import annotations
import copy
import hashlib
import json
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from project_docs import repository as repo, story_openapi as story
from project_docs.doc_schema import validate_doc, doc_text, MAX_DOC_BYTES

UNHANDLED = object()
KINDS = {'writing_source','writing_branch','writing_version','writing_structure','writing_bible','writing_preview','writing_export','writing_receipt'}
PRIVATE = {'writing_source','writing_branch','writing_preview','writing_export','writing_receipt'}
PREVIEW_KINDS = {'adaptation','promotion','structure','impact','replace','import'}


def fail(code='CONFLICT', message='The writing resource changed.', status=409, details=None):
    raise story.StoryError(status, 'DRAMA_WRITING_' + code, message, details=details)


def fields(body, allowed, required=()):
    if not isinstance(body, dict) or set(body) - set(allowed) or set(required) - set(body):
        story.invalid('Missing or unknown writing fields.')
    return body


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def hash_value(value):
    return hashlib.sha256(canonical(value).encode('utf8')).hexdigest()


def checked_doc(doc, slug=None):
    if len(json.dumps(doc,ensure_ascii=False,allow_nan=False).encode('utf8')) > MAX_DOC_BYTES:
        fail('LIMIT_EXCEEDED','Split documents above the validated 2 MB limit.',413)
    if slug is None:
        # Hashing already validated docs must preserve same-project media nodes too.
        import re
        slugs=set()
        def image_scopes(node):
            if not isinstance(node,dict): return
            if node.get('type')=='image':
                match=re.fullmatch(r'/projects/api/([a-z0-9-]+)/assets/pa_[0-9a-f]{32}',str(node.get('attrs',{}).get('src','')))
                if match: slugs.add(match[1])
            for child in node.get('content',[]): image_scopes(child)
        image_scopes(doc)
        if len(slugs) > 1:
            story.invalid('A writing document cannot cross project media scopes.')
        slug = next(iter(slugs), '')
    clean, _ = validate_doc(copy.deepcopy(doc), slug=slug)
    if len(doc_text(clean)) > 500000:
        fail('LIMIT_EXCEEDED', 'Split text resources above 500,000 code points.', 413)
    return clean


def doc_hash(doc):
    return hash_value(checked_doc(doc))


@dataclass(frozen=True)
class WritingScope:
    me: object
    slug: str
    episode: dict
    episode_id: str
    actor_id: str
    credential_scope: str


def scope_for(conn, me, episode_id, *, write=False, credential_scope=''):
    ep = story.episode(conn, episode_id)
    with conn.cursor() as cur:
        cur.execute('SELECT kind,project_slug FROM projectops.story_record WHERE id=%s',(episode_id,))
        saved=cur.fetchone()
    if saved and (saved[0]!='episode' or saved[1]!=ep['slug']):
        raise story.StoryError(404,'DRAMA_NOT_FOUND','Episode not found.')
    story.authorize(conn, me, ep['slug'], write=write)
    if ep.get('episodeId') != episode_id:
        story.invalid('Invalid episode scope.')
    return WritingScope(me, ep['slug'], copy.deepcopy(ep), episode_id, me.actor_id, credential_scope)


def reauthorize(conn, scope, *, write=False):
    story.authorize(conn, scope.me, scope.slug, write=write)
    ep = story.episode(conn, scope.episode_id)
    if ep['slug'] != scope.slug:
        fail('CONFLICT', 'Episode scope changed.')


def lock_project(conn, scope):
    from project_assistant.orchestrator import lock_project as lock
    lock(conn, scope.slug)


def source_id(scope, mode):
    if mode not in ('idea','novel'):
        story.invalid('Source mode must be idea or novel.')
    return 'wsrc_' + hash_value([scope.actor_id, scope.episode_id, mode])


def expiry_time(value):
    if isinstance(value,str):
        try:
            parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
            if parsed.tzinfo is None: raise ValueError()
            return parsed.timestamp()
        except (ValueError,OverflowError): story.invalid('Writing expiry must include a timezone.')
    if type(value) not in (int,float): story.invalid('Writing handles require a finite expiry.')
    return value


def _validate(scope, kind, data, owner):
    if kind not in KINDS or not isinstance(data, dict):
        story.invalid('Invalid writing record kind.')
    if (data.get('schemaVersion') != 1 or data.get('projectSlug') != scope.slug
            or (data.get('episodeId') != scope.episode_id and not (kind == 'writing_bible' and data.get('episodeId') is None))
            or type(data.get('version')) is not int or data['version'] < 1):
        story.invalid('Invalid writing record scope or schema.')
    if kind=='writing_bible' and data.get('episodeId') is None and data.get('bibleScope')!='project':
        story.invalid('Project-scoped bible records must declare bibleScope:project.')
    if kind in PRIVATE:
        if str(owner) != scope.actor_id or data.get('ownerId') != scope.actor_id or data.get('visibility') != 'private':
            raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Writing resource not found.')
    elif data.get('visibility') != 'project':
        story.invalid('Shared writing records require explicit project visibility.')
    if kind in ('writing_source','writing_branch'):
        clean=checked_doc(data.get('doc'), scope.slug)
        if data.get('docHash') != doc_hash(clean):
            story.invalid('Writing content hash mismatch.')
        if not isinstance(data.get('structure', {}), dict) or not isinstance(data.get('composition', {}), dict):
            story.invalid('Invalid writing structure or composition.')
        if kind == 'writing_source' and data.get('mode') not in ('idea','novel'):
            story.invalid('Invalid source mode.')
        if 'beforeCheckpoint' in data:
            checkpoint=data['beforeCheckpoint']
            fields(checkpoint,{'doc','structure','docHash','structureHash','resourceKind','projectSlug','episodeId','ownerId'},
                {'doc','structure','docHash','structureHash','resourceKind','projectSlug','episodeId','ownerId'})
            if (checkpoint['resourceKind']!=kind or checkpoint['projectSlug']!=scope.slug or checkpoint['episodeId']!=scope.episode_id
                    or checkpoint['ownerId']!=scope.actor_id or doc_hash(checked_doc(checkpoint['doc'],scope.slug))!=checkpoint['docHash']
                    or not isinstance(checkpoint['structure'],dict) or hash_value(checkpoint['structure'])!=checkpoint['structureHash']):
                story.invalid('Invalid private Undo checkpoint scope or content.')
            if len(canonical(checkpoint['structure']).encode('utf8'))>MAX_DOC_BYTES:
                fail('LIMIT_EXCEEDED','The before checkpoint structure exceeds its limit.',413)
    if kind == 'writing_version':
        snap = data.get('snapshot', {})
        if (doc_hash(snap.get('doc')) != snap.get('docHash')
                or story.digest(doc_text(snap['doc'])) != snap.get('scriptHash')
                or hash_value(snap.get('productionInputs',{})) != snap.get('productionInputsHash')):
            story.invalid('Snapshot hash mismatch.')
    if kind == 'writing_preview':
        if data.get('kind') not in PREVIEW_KINDS or data.get('status') not in ('pending','applied'):
            story.invalid('Invalid preview kind or lifecycle status.')
        if not isinstance(data.get('allowedActions',[]),list):
            story.invalid('Invalid preview action catalog.')
    if kind in ('writing_preview','writing_receipt','writing_export'):
        import math
        if not math.isfinite(expiry_time(data.get('expiresAt'))):
            story.invalid('Writing handles require a finite expiry.')
    return data


def get_record(conn, scope, kind, identifier, *, required=True, lock=False):
    reauthorize(conn, scope)
    if kind not in KINDS or not isinstance(identifier, str):
        story.invalid('Invalid writing resource reference.')
    with conn.cursor() as cur:
        cur.execute('SELECT kind,project_slug,owner_id,data FROM projectops.story_record WHERE id=%s' + (' FOR UPDATE' if lock else ''), (identifier,))
        row = cur.fetchone()
    if not row or row[0] != kind or row[1] != scope.slug or (kind in PRIVATE and str(row[2]) != scope.actor_id):
        if required:
            raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Writing resource not found.')
        return None
    data = repo._loads(row[3])
    if data.get('episodeId') != scope.episode_id and not (kind == 'writing_bible' and data.get('episodeId') is None):
        if required:
            raise story.StoryError(404, 'DRAMA_NOT_FOUND', 'Writing resource not found.')
        return None
    return copy.deepcopy(_validate(scope, kind, data, row[2]))


def list_records(conn, scope, kind, *, query=None):
    reauthorize(conn, scope)
    if kind not in KINDS:
        story.invalid('Invalid writing record kind.')
    query = query or {}
    try:
        limit = int(query.get('limit', 20))
        if not 1 <= limit <= 100:
            raise ValueError()
    except (ValueError, TypeError):
        story.invalid('limit must be between 1 and 100.')
    cursor = query.get('cursor', '') or ''
    with conn.cursor() as cur:
        # Project and episode filtering occurs in SQL; never return private blobs in catalogs.
        cur.execute('''SELECT id, data - 'doc' - 'snapshot' - 'blob' - 'bytes' - 'bytesBase64' - 'archive' - 'beforeCheckpoint' - 'content' - 'proposal' - 'result' AS summary
            FROM projectops.story_record WHERE kind=%s AND project_slug=%s
            AND (data->>'episodeId'=%s OR (%s='writing_bible' AND data->>'episodeId' IS NULL))
            AND (%s=false OR owner_id=%s) AND id>%s ORDER BY id LIMIT %s''',
            (kind,scope.slug,scope.episode_id,kind,kind in PRIVATE,scope.actor_id,cursor,limit+1))
        rows = cur.fetchall()
    items = []
    for identifier, raw in rows[:limit]:
        data = repo._loads(raw)
        if data.get('visibility') != ('private' if kind in PRIVATE else 'project') or (kind in PRIVATE and data.get('ownerId') != scope.actor_id):
            story.invalid('Invalid writing catalog scope.')
        items.append(data | {'id':identifier})
    return {'items': items, 'nextCursor': rows[limit-1][0] if len(rows)>limit else None}


def insert_record(conn, scope, kind, identifier, data):
    reauthorize(conn, scope, write=kind not in ('writing_export','writing_receipt'))
    stamp = story.now()
    private = kind in PRIVATE
    data = copy.deepcopy(data) | {'schemaVersion':1,'projectSlug':scope.slug,
        'episodeId':None if kind=='writing_bible' and data.get('bibleScope')=='project' else data.get('episodeId',scope.episode_id),'version':1,'createdAt':stamp,'updatedAt':stamp,
        'visibility':'private' if private else 'project'}
    if private:
        data['ownerId'] = scope.actor_id
    _validate(scope, kind, data, scope.actor_id if private else None)
    if kind == 'writing_source' and identifier != source_id(scope,data['mode']):
        story.invalid('Private source IDs are derived from actor, episode and mode.')
    with conn.cursor() as cur:
        cur.execute('''INSERT INTO projectops.story_record(id,kind,project_slug,owner_id,data)
            VALUES(%s,%s,%s,%s,%s::jsonb) ON CONFLICT(id) DO NOTHING RETURNING id''',
            (identifier,kind,scope.slug,scope.actor_id if private else None,repo._doc_param(data)))
        if not cur.fetchone():
            fail(message='Writing resource already exists.')
    return data


def _replace(conn, scope, kind, identifier, data):
    _validate(scope, kind, data, scope.actor_id if kind in PRIVATE else None)
    with conn.cursor() as cur:
        cur.execute('UPDATE projectops.story_record SET data=%s::jsonb,updated_at=NOW() WHERE id=%s AND kind=%s AND project_slug=%s',
                    (repo._doc_param(data),identifier,kind,scope.slug))
    return data


MUTABLE_FIELDS = {
    'writing_source': {'doc','docHash','structure','structureHash','composition','sourceFile','archive','name','beforeCheckpoint'},
    'writing_branch': {'doc','docHash','structure','structureHash','composition','name','locked','archived','beforeCheckpoint'},
    'writing_structure': {'docHash','scenes','lanes','tombstones','lineage','legacyBindings','structureHash','initialized'},
    'writing_bible': {'aliases','role','background','constraints','relationships','events','rules','research','notes','references','title','content','archived','productionRelevant','physicalStates'},
}


def cas_record(conn, scope, kind, identifier, *, base_version, changes):
    reauthorize(conn, scope, write=True)
    if kind not in MUTABLE_FIELDS:
        fail('LOCKED', 'This writing record is immutable.')
    fields(changes, MUTABLE_FIELDS[kind])
    data = get_record(conn, scope, kind, identifier, lock=True)
    if type(base_version) is not int or data['version'] != base_version:
        fail(details={'currentVersion':data['version']})
    if data.get('locked') and kind == 'writing_branch' and set(changes) != {'locked'}:
        fail('LOCKED', 'Unlock this branch before editing.')
    changes=copy.deepcopy(changes)
    if 'beforeCheckpoint' in changes:
        checkpoint=changes['beforeCheckpoint']
        fields(checkpoint,{'doc','structure','docHash','structureHash'},{'doc','structure'})
        clean=checked_doc(checkpoint['doc'],scope.slug)
        if not isinstance(checkpoint['structure'],dict) or len(canonical(checkpoint['structure']).encode('utf8'))>MAX_DOC_BYTES:
            fail('LIMIT_EXCEEDED','The before checkpoint structure exceeds its limit.',413)
        if doc_hash(clean)!=data['docHash'] or hash_value(checkpoint['structure'])!=hash_value(data.get('structure',{})):
            fail(message='An Undo checkpoint must preserve the actual current resource before the mutation.')
        changes['beforeCheckpoint']={'doc':clean,'structure':checkpoint['structure'],'docHash':doc_hash(clean),
            'structureHash':hash_value(checkpoint['structure']),'resourceKind':kind,'projectSlug':scope.slug,
            'episodeId':scope.episode_id,'ownerId':scope.actor_id}
    data |= changes
    data.update(version=data['version']+1, updatedAt=story.now())
    return _replace(conn, scope, kind, identifier, data)


def insert_snapshot(conn, scope, identifier, snapshot, *, name, created_by):
    fields(snapshot, {'doc','docHash','scriptHash','structure','structureHash','composition','productionInputs','productionInputsHash'}, {'doc','docHash','structure','structureHash'})
    if not isinstance(name,str) or not 1<=len(name.strip())<=200:
        story.invalid('A version name of 1–200 characters is required.')
    return insert_record(conn,scope,'writing_version',identifier,{'versionId':identifier,'name':name,'snapshot':snapshot,
        'catalogVersion':1,'locked':False,'archived':False,'createdBy':created_by})


def resolve_ref(conn, scope, source_ref, *, write=False):
    reauthorize(conn,scope,write=write)
    if not isinstance(source_ref,dict):
        story.invalid('A discriminated sourceRef is required.')
    kind = source_ref.get('kind')
    fields(source_ref, {'kind'} if kind=='working' else {'kind','mode'} if kind=='source' else {'kind','id'})
    if kind == 'working':
        from project_docs import writing_structure as structure
        for attempt in range(3):
            tab=repo.get_tab(conn,scope.slug,scope.episode['tabKey'])
            doc=checked_doc(tab['doc'],scope.slug)
            current_structure=structure.read_structure(conn,scope)
            if current_structure['docHash']==doc_hash(doc): break
        else:
            fail('CONFLICT','The screenplay changed while reading; reload to compare current content.')
        result={'doc':doc,'docHash':doc_hash(doc),'version':tab['revision'],'structure':current_structure}
        result['structureHash']=result['structure']['structureHash']
        result['composition']=composition(doc)
        result['productionInputs']=production_inputs(replace(scope,episode=story.episode(conn,scope.episode_id)),conn=conn,doc=doc)
        result['resourceId']=scope.episode_id
        result['locked']=False
    elif kind in ('source','branch','version'):
        identifier=source_id(scope,source_ref.get('mode')) if kind=='source' else source_ref.get('id')
        data=get_record(conn,scope,'writing_'+kind,identifier)
        if write and (kind=='version' or data.get('locked')):
            fail('LOCKED','This resource is read-only.')
        result=copy.deepcopy(data['snapshot'] if kind=='version' else data)
        result.setdefault('version',data['version'])
        result['resourceId']=identifier
        result['locked']=True if kind=='version' else bool(data.get('locked',False))
        result['docHash']=doc_hash(result['doc'])
        result.setdefault('structure',{})
        if kind=='branch':
            result['productionInputs']=production_inputs(replace(scope,episode=story.episode(conn,scope.episode_id)),conn=conn,doc=result['doc'])
        result['structureHash']=hash_value(result['structure']) if 'structureHash' not in result else result['structureHash']
    else:
        story.invalid('Unknown sourceRef kind.')
    result['compositionHash']=hash_value(result.get('composition',{}))
    if 'productionInputs' in result:
        result['productionInputsHash']=hash_value(result['productionInputs'])
    return result | {'sourceRef':copy.deepcopy(source_ref)}


def composition(doc):
    match=__import__('re').search(r'^Lens:\s*(manju|cinema|storybook)\s*×\s*(general|melodrama|xianxia|comedy|suspense)\s*$',doc_text(doc),__import__('re').M)
    return {'mediumLens':match[1],'genreLens':match[2]} if match else {}


def production_inputs(scope, *, conn=None, doc=None):
    result={'settings':copy.deepcopy(scope.episode.get('settings',{})),
        'breakdownMode':scope.episode.get('breakdownMode',scope.episode.get('settings',{}).get('breakdownMode','auto'))}
    if doc is not None:
        result['composition']=composition(doc)
    if conn is not None and doc is not None:
        # Freeze only actually referenced visual settings, never notes or media bytea.
        codes={m[1].upper().replace('#',':') for m in story.ASSET_RE.finditer(doc_text(doc))}
        codes|={code.split(':')[0] for code in codes if ':' in code}  # variant image fallback
        known={a['assetCode']:a for a in story.assets(conn,scope.episode)} if codes else {}
        bindings=[]
        for code in sorted(codes):
            asset=known.get(code)
            if asset:
                visual={k:asset.get(k) for k in ('assetId','assetCode','name','prompt','type','kind','selectedImageUrl')}
                bindings.append({'assetId':asset['assetId'],'assetCode':code,'visualSettings':visual,'visualSettingsHash':hash_value(visual)})
            else:
                bindings.append({'assetCode':code,'missing':True})
        result['assetBindings']=bindings
    return result


def create_preview(conn, scope, kind, proposal):
    if kind not in PREVIEW_KINDS:
        story.invalid('Unknown preview kind.')
    identifier='wpre_'+uuid.uuid4().hex
    return insert_record(conn,scope,'writing_preview',identifier,copy.deepcopy(proposal)|{
        'previewId':identifier,'kind':kind,'status':'pending','expiresAt':time.time()+1800})


def get_preview(conn, scope, preview_id, *, lock=False):
    data=get_record(conn,scope,'writing_preview',preview_id,lock=lock)
    if expiry_time(data['expiresAt']) < time.time():
        fail('PREVIEW_STALE','This preview has expired.')
    return data


def finish_preview(conn, scope, preview_id, *, expected_version, body_hash, result):
    data=get_preview(conn,scope,preview_id,lock=True)
    if data['version']!=expected_version or data['status']!='pending':
        fail('PREVIEW_STALE','This preview was already applied.')
    data.update(status='applied',version=data['version']+1,applyBodyHash=body_hash,result=copy.deepcopy(result),updatedAt=story.now())
    return _replace(conn,scope,'writing_preview',preview_id,data)


def _receipt_id(scope,resource_key,mutation_id):
    if not isinstance(mutation_id,str) or not 1<=len(mutation_id)<=128:
        story.invalid('clientMutationId or Idempotency-Key must contain 1–128 characters.')
    return 'wrc_'+hash_value([scope.actor_id,scope.credential_scope,scope.episode_id,resource_key,mutation_id])


def replay_receipt(conn, scope, resource_key, mutation_id, body_hash):
    identifier=_receipt_id(scope,resource_key,mutation_id)
    data=get_record(conn,scope,'writing_receipt',identifier,required=False)
    if not data or expiry_time(data['expiresAt'])<time.time():
        return None
    if data['bodyHash']!=body_hash:
        raise story.StoryError(409,'DRAMA_IDEMPOTENCY_CONFLICT','Mutation identity was used with a different body.')
    return copy.deepcopy(data['ack'])


def save_receipt(conn, scope, resource_key, mutation_id, body_hash, ack):
    identifier=_receipt_id(scope,resource_key,mutation_id)
    # Bound ACKs, retaining script conflicts/doc for reliable block acknowledgements.
    if len(canonical(ack).encode('utf8'))>16000000:
        fail('LIMIT_EXCEEDED','Writing acknowledgement exceeds the response limit.',413)
    existing=get_record(conn,scope,'writing_receipt',identifier,required=False,lock=True)
    if existing:
        if expiry_time(existing['expiresAt'])>=time.time():
            return replay_receipt(conn,scope,resource_key,mutation_id,body_hash)
        with conn.cursor() as cur:
            cur.execute('DELETE FROM projectops.story_record WHERE id=%s AND kind=%s',(identifier,'writing_receipt'))
    with conn.cursor() as cur:
        cur.execute('''WITH expired AS (
            SELECT id FROM projectops.story_record WHERE kind='writing_receipt' AND project_slug=%s AND owner_id=%s
            AND data->>'episodeId'=%s AND jsonb_typeof(data->'expiresAt')='number'
            AND (data->>'expiresAt')::double precision<%s ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED)
            DELETE FROM projectops.story_record WHERE id IN (SELECT id FROM expired)''',
            (scope.slug,scope.actor_id,scope.episode_id,time.time()))
    insert_record(conn,scope,'writing_receipt',identifier,{'resourceKey':resource_key,'mutationId':mutation_id,
        'bodyHash':body_hash,'ack':copy.deepcopy(ack),'expiresAt':time.time()+86400})
    return ack
