"""Writing application boundary: saves, authorization and atomic preview coordination."""
from __future__ import annotations
import copy
import importlib
import hashlib
import re
from project_docs import writing_store as store, writing_structure as structure, writing_versions as versions
from project_docs import repository as repo, story_openapi as story, service
from project_docs.doc_schema import doc_text


def feature(name):
    module='project_docs.writing_'+name
    try: return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        if exc.name!=module: raise
        raise story.StoryError(501,'DRAMA_WRITING_FEATURE_UNAVAILABLE','This writing feature is not installed.') from None


def preview_owner(kind):
    if kind in ('adaptation','promotion'): return versions
    if kind=='structure': return structure
    if kind in ('impact','replace','import'): return feature({'impact':'impact','replace':'tools','import':'files'}[kind])
    story.invalid('Unknown preview kind.')


def authorize_references(conn, scope, value):
    """Reauthorization is independent of receipts and applies recursively to frozen refs."""
    if isinstance(value,list):
        for item in value: authorize_references(conn,scope,item)
    elif isinstance(value,dict):
        if value.get('episodeId') and any(k in value for k in ('sourceRef','resourceRef')):
            referenced=store.scope_for(conn,scope.me,value['episodeId'],credential_scope=scope.credential_scope)
            if referenced.slug!=scope.slug: raise story.StoryError(404,'DRAMA_NOT_FOUND','Writing resource not found.')
            scope=referenced
        for key,item in value.items():
            if key in ('sourceRef','leftRef','rightRef','targetRef') and isinstance(item,dict):
                store.resolve_ref(conn,scope,item)
            elif key in ('previewId','uploadPreviewId','uploadId') and isinstance(item,str) and item.startswith('wpre_'):
                preview=store.get_record(conn,scope,'writing_preview',item)
                authorize_references(conn,scope,preview.get('sourceFingerprints',[]))
            elif key=='candidateBranchId' and isinstance(item,str):
                store.get_record(conn,scope,'writing_branch',item)
            elif key=='bibleIds' and isinstance(item,list):
                for identifier in item: store.get_record(conn,scope,'writing_bible',identifier)
            else: authorize_references(conn,scope,item)


def authorize_route(conn, scope, method, tail, body):
    readonly=method=='GET' or (method=='POST' and tail in ('search','compare','exports'))
    store.reauthorize(conn,scope,write=not readonly)
    parts=tail.split('/')
    if len(parts)>1 and parts[0] in ('branches','versions','previews','exports'):
        kind={'branches':'branch','versions':'version','previews':'preview','exports':'export'}[parts[0]]
        data=store.get_record(conn,scope,'writing_'+kind,parts[1])
        if kind=='preview':
            authorize_references(conn,scope,data.get('sourceFingerprints',[]))
            authorize_references(conn,scope,data.get('targetFingerprints',[]))
            if data.get('candidateBranchId'): store.get_record(conn,scope,'writing_branch',data['candidateBranchId'])
        if kind=='export': authorize_references(conn,scope,data)
    if parts[0]=='sources' and len(parts)>1:
        store.get_record(conn,scope,'writing_source',store.source_id(scope,parts[1]),required=False)
    authorize_references(conn,scope,body)


def workspace(conn, scope):
    current=store.resolve_ref(conn,scope,{'kind':'working'})
    ep=story.episode(conn,scope.episode_id)
    version_id=ep.get('productionScriptVersionId')
    baseline={'versionId':version_id,'legacy':not bool(version_id),'retained':bool(version_id),'confirmedHash':ep.get('confirmedHash'),
        'scriptDirty':ep.get('confirmedHash')!=story.digest(doc_text(current['doc']))}
    return {'episodeId':scope.episode_id,'projectSlug':scope.slug,'doc':current['doc'],'docHash':current['docHash'],
        'revision':current['version'],'structure':current['structure'],'structureHash':current['structureHash'],
        'versions':store.list_records(conn,scope,'writing_version'),'sources':store.list_records(conn,scope,'writing_source'),
        'branches':store.list_records(conn,scope,'writing_branch'),'baseline':baseline,'composition':current['composition'],
        'productionInputs':current['productionInputs'],'capabilities':{'writable':bool(scope.me.can_write)}}


def _source_structure(value):
    if not isinstance(value,dict): story.invalid('Source structure must be an object.')
    store.fields(value,{'chapters','sections','title'})
    def walk(items,level=0):
        if not isinstance(items,list) or level>1: story.invalid('Source structure supports chapters and sections only.')
        count=0
        for item in items:
            store.fields(item,{'key','title','blockBids','sections','chapterKey','sectionKey' })
            if not isinstance(item.get('blockBids',[]),list) or not all(isinstance(x,str) for x in item.get('blockBids',[])): story.invalid('Invalid source block IDs.')
            if 'title' in item and (not isinstance(item['title'],str) or len(item['title'])>200): story.invalid('Invalid source section title.')
            if any(not isinstance(item[k],str) or not 1<=len(item[k])<=128 for k in ('key','chapterKey','sectionKey') if k in item): story.invalid('Invalid source section key.')
            count+=1+walk(item['sections'],level+1) if 'sections' in item else 1
        return count
    if walk(value.get('chapters',[]))+walk(value.get('sections',[]))>1000:
        store.fail('LIMIT_EXCEEDED','At most 1,000 source units are supported.',413)
    return copy.deepcopy(value)


def _composition(value):
    if not isinstance(value,dict): story.invalid('composition must be an object.')
    store.fields(value,{'mediumLens','genreLens','choiceTrace'})
    if value:
        from project_docs.story_adaptation import composition_lenses, choice_trace_input
        composition_lenses(value.get('mediumLens'),value.get('genreLens'))
        if 'choiceTrace' in value: choice_trace_input(value['choiceTrace'])
    return copy.deepcopy(value)


def save_source(conn, scope, mode, body):
    store.fields(body,{'baseVersion','clientMutationId','doc','structure','composition'},{'baseVersion','clientMutationId','doc','structure','composition'})
    identifier=store.source_id(scope,mode)
    doc=store.checked_doc(body['doc'],scope.slug)
    data={'doc':doc,'docHash':store.doc_hash(doc),'structure':_source_structure(body['structure']),'composition':_composition(body['composition'])}
    # Structural locations must reference actual blocks; no arbitrary document paths.
    bids={structure.bid(n) for n in doc.get('content',[])}
    def check(value):
        if isinstance(value,dict):
            if set(value.get('blockBids',[]))-bids: story.invalid('Source structure references missing blocks.')
            for v in value.values(): check(v)
        elif isinstance(value,list):
            for v in value: check(v)
    check(data['structure'])
    data['structureHash']=store.hash_value(data['structure'])
    if type(body['baseVersion']) is not int or body['baseVersion']<0: story.invalid('baseVersion must be a nonnegative integer.')
    if body['baseVersion']==0:
        result=store.insert_record(conn,scope,'writing_source',identifier,data|{'sourceId':identifier,'mode':mode})
    else:
        result=store.cas_record(conn,scope,'writing_source',identifier,base_version=body['baseVersion'],changes=data)
    return {k:v for k,v in result.items() if k!='beforeCheckpoint'}|{'clientMutationId':body['clientMutationId'],'savedAt':result['updatedAt']}


def save_script(conn, scope, body):
    store.fields(body,{'ops','clientMutationId','session_id','atomic','base_revision'},{'ops','clientMutationId','session_id'})
    if not isinstance(body['session_id'],str) or not 1<=len(body['session_id'])<=64: story.invalid('Invalid editor session.')
    if 'atomic' in body and type(body['atomic']) is not bool: story.invalid('atomic must be boolean.')
    tab=repo.get_tab_for_update(conn,scope.slug,scope.episode['tabKey'])
    if not structure.read_structure(conn,scope)['initialized']: store.fail('MAPPING_REQUIRED','Initialize the writing workspace before saving mainline blocks.')
    mutation_resource='script-block-mutation'
    mutation_hash=store.hash_value(body)
    cached=store.replay_receipt(conn,scope,mutation_resource,body['clientMutationId'],mutation_hash)
    if cached is not None: return cached
    # The legacy order op has no lock check of its own; protect affected blocks here.
    if any(op.get('op')=='order' for op in body['ops'] if isinstance(op,dict)):
        locks=repo.tab_locks(conn,scope.slug,scope.episode['tabKey'])
        if any(locks.get(structure.bid(n)) not in (None,scope.actor_id) for n in tab['doc']['content']):
            store.fail('LOCKED','A crew member holds a reordered block lock.')
    result,doc,revision,saved=service._run_ops(conn,scope.me,scope.slug,scope.episode['tabKey'],tab,body['ops'],body['session_id'],atomic=body.get('atomic',False),audit_extra={'via':'writing'})
    store.checked_doc(doc,scope.slug)
    current=structure.read_structure(conn,scope)
    if current['stale']: structure.persist(conn,scope,current)
    ack={'clientMutationId':body['clientMutationId'],'doc':doc,'docHash':store.doc_hash(doc),'version':revision,'revision':revision,
        'savedAt':saved,'applied':result.applied,'conflicts':result.conflicts}
    return store.save_receipt(conn,scope,mutation_resource,body['clientMutationId'],mutation_hash,ack)


def replace_working(conn, scope, doc, *, expected_hash):
    """Content CAS plus existing block ops/locks/audit/reanchor; never blind save."""
    store.reauthorize(conn,scope,write=True)
    tab=repo.get_tab_for_update(conn,scope.slug,scope.episode['tabKey'])
    if store.doc_hash(tab['doc'])!=expected_hash: store.fail('PREVIEW_STALE')
    doc=store.checked_doc(doc,scope.slug)
    old={structure.bid(n):n for n in tab['doc']['content']};new={structure.bid(n):n for n in doc['content']}
    order_changed=list(old)!=list(new)
    locks=repo.tab_locks(conn,scope.slug,scope.episode['tabKey'])
    touched=(set(old)|set(new)) if order_changed else {k for k in old.keys()|new.keys() if old.get(k)!=new.get(k)}
    if any(locks.get(k) not in (None,scope.actor_id) for k in touched): store.fail('LOCKED','A crew member holds an affected block lock.')
    ops=[{'op':'del','bid':k,'base':old[k]} for k in old if k not in new]
    ops += [{'op':'put','bid':k,'base':old.get(k),'node':node} for k,node in new.items() if old.get(k)!=node]
    if order_changed: ops.append({'op':'order','bids':list(new)})
    for offset in range(0,len(ops),200):
        current=repo.get_tab_for_update(conn,scope.slug,scope.episode['tabKey'])
        result,_,_,_=service._run_ops(conn,scope.me,scope.slug,scope.episode['tabKey'],current,ops[offset:offset+200],
            'writing-adoption',atomic=True,audit_extra={'via':'writing-preview'})
        if result.conflicts: store.fail('CONFLICT','Affected blocks changed or are locked.',details={'conflicts':result.conflicts})


def validate_fingerprints(conn, scope, preview):
    from dataclasses import replace
    live_scope=replace(scope,episode=story.episode(conn,scope.episode_id))
    if 'productionInputsHash' in preview and store.hash_value(store.production_inputs(live_scope))!=preview['productionInputsHash']:
        store.fail('PREVIEW_STALE','Production settings changed.')
    for frozen in preview.get('sourceFingerprints',[])+preview.get('targetFingerprints',[]):
        if 'sourceRef' not in frozen: continue  # feature owners validate shot/domain fingerprints
        current=store.resolve_ref(conn,scope,frozen['sourceRef'])
        if any(key in frozen and current.get(key)!=frozen[key] for key in ('docHash','structureHash','version','compositionHash','productionInputsHash')):
            store.fail('PREVIEW_STALE','The frozen source or target changed.')


def _selection(preview, selection):
    store.fields(selection,{'actions'},{'actions'})
    if not isinstance(selection['actions'],list) or not selection['actions']: story.invalid('Select at least one frozen action.')
    allowed={a['actionId']:a for a in preview.get('allowedActions',[])}
    seen=set()
    for action in selection['actions']:
        store.fields(action,{'actionId','kind','fields'},{'actionId'})
        identifier=action['actionId'];frozen=allowed.get(identifier)
        if identifier in seen or not frozen or ('kind' in action and action['kind']!=frozen.get('kind')): story.invalid('Selection must be a subset of frozen actions.')
        seen.add(identifier)
        if 'fields' in action:
            if not isinstance(action['fields'],list) or set(action['fields'])-set(frozen.get('fields',[])): story.invalid('Unknown frozen fields.')
    if preview['kind']=='structure' and len(selection['actions'])!=len(allowed): story.invalid('A structure operation is indivisible.')


def build_preview(conn, scope, body, *, prepared=None):
    kind=body.get('kind')
    proposal=preview_owner(kind).build_preview(conn,scope,body) if prepared is None else copy.deepcopy(prepared)
    store.lock_project(conn,scope)
    authorize_references(conn,scope,body)
    candidate=proposal.pop('_candidateRecord',None)
    if candidate:
        store.insert_record(conn,scope,'writing_branch',proposal['candidateBranchId'],candidate)
    validate_fingerprints(conn,scope,proposal)
    return store.create_preview(conn,scope,kind,proposal)


def apply_preview(conn, scope, preview_id, body):
    store.fields(body,{'selection','expectedPreviewVersion'},{'selection','expectedPreviewVersion'})
    preview=store.get_preview(conn,scope,preview_id)
    if type(body['expectedPreviewVersion']) is not int or preview['version']!=body['expectedPreviewVersion'] or preview['status']!='pending': store.fail('PREVIEW_STALE')
    _selection(preview,body['selection']);validate_fingerprints(conn,scope,preview)
    result=preview_owner(preview['kind']).apply_preview(conn,scope,preview,body['selection'])
    store.finish_preview(conn,scope,preview_id,expected_version=body['expectedPreviewVersion'],body_hash=store.hash_value(body),result=result)
    return result


def dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    headers=headers or {}
    authorize_route(conn,scope,method,tail,body)
    mutation=method in ('POST','PUT','PATCH')
    resource=method+' /episodes/'+scope.episode_id+'/writing/'+tail
    identity=headers.get('Idempotency-Key') if method=='POST' else body.get('clientMutationId')
    body_hash=store.hash_value(body) if raw is None else store.hash_value([hashlib.sha256(raw).hexdigest(),headers.get('X-Filename',headers.get('X-File-Name')),headers.get('X-Writing-Purpose',headers.get('X-File-Purpose')),resource])
    def replay():
        cached=store.replay_receipt(conn,scope,resource,identity,body_hash)
        if cached is not None:
            authorize_references(conn,scope,cached)
            return cached
        return None
    if mutation:
        cached=replay()
        if cached is not None: return cached['value']
    # Parse/diff proposals and readonly computation on fixed authorized inputs, before DB locks.
    prepared=None
    if method=='POST' and tail=='previews': prepared=preview_owner(body.get('kind')).build_preview(conn,scope,body)
    computation=method=='POST' and tail in ('compare','search','imports','exports')
    result=store.UNHANDLED
    if computation:
        # Imports/exports own their parse -> project lock -> hash recheck -> insert boundary.
        result=_dispatch(conn,scope,method,tail,body,query,raw=raw,headers=headers)
    if mutation:
        store.lock_project(conn,scope)
        scope=store.scope_for(conn,scope.me,scope.episode_id,write=not (method=='POST' and tail in ('search','compare','exports')),credential_scope=scope.credential_scope)
        authorize_route(conn,scope,method,tail,body)
        # Acquire affected tabs in lexical order before metadata/receipt writes.
        tabs=set()
        if tail.startswith(('script/','structure')) or tail=='initialize':
            tabs.add(scope.episode['tabKey'])
        if re.fullmatch(r'previews/[^/]+/apply',tail):
            preview=store.get_record(conn,scope,'writing_preview',tail.split('/')[1])
            if preview['kind'] in ('adaptation','promotion','structure','impact'): tabs.add(scope.episode['tabKey'])
            if preview['kind'] in ('structure','impact'): tabs.add('cinema-studio')
            if preview['kind']=='impact': tabs.add('soul-cast')
        for key in sorted(tabs): repo.get_tab_for_update(conn,scope.slug,key)
        cached=replay()
        if cached is not None: return cached['value']
    if method=='POST' and tail=='previews':
        result=build_preview(conn,scope,body,prepared=prepared)
    elif not computation:
        result=_dispatch(conn,scope,method,tail,body,query,raw=raw,headers=headers)
    if result is store.UNHANDLED: raise story.StoryError(404,'DRAMA_NOT_FOUND','Writing route not found.')
    if mutation:
        from project_docs.writing_http import BinaryResponse
        if isinstance(result,BinaryResponse): story.invalid('Binary results cannot be mutation receipts.')
        store.save_receipt(conn,scope,resource,identity,body_hash,{'value':result})
    return result


def _dispatch(conn, scope, method, tail, body, query, *, raw=None, headers=None):
    parts=tail.split('/')
    if tail=='workspace' and method=='GET': return workspace(conn,scope)
    if tail=='initialize' and method=='POST':
        store.fields(body,{'expectedDocHash'},{'expectedDocHash'})
        return structure.initialize(conn,scope,body['expectedDocHash'])
    if len(parts)==2 and parts[0]=='sources':
        if method=='GET': return store.get_record(conn,scope,'writing_source',store.source_id(scope,parts[1]),required=False)
        if method=='PUT': return save_source(conn,scope,parts[1],body)
    if tail=='script/ops' and method=='POST': return save_script(conn,scope,body)
    if tail=='structure' and method=='GET': return structure.read_structure(conn,scope)
    if tail=='structure/metadata' and method=='PATCH': return structure.metadata_patch(conn,scope,body)
    if tail=='versions':
        if method=='GET': return store.list_records(conn,scope,'writing_version',query=query)
        if method=='POST': return versions.create_version(conn,scope,body)
    if tail=='branches':
        if method=='GET': return store.list_records(conn,scope,'writing_branch',query=query)
        if method=='POST': return versions.create_branch(conn,scope,body)
    if len(parts)==2 and parts[0] in ('versions','branches'):
        kind='writing_version' if parts[0]=='versions' else 'writing_branch'
        if method=='GET': return store.get_record(conn,scope,kind,parts[1])
        if parts[0]=='versions' and method=='PATCH': return versions.update_catalog(conn,scope,parts[1],body)
        if parts[0]=='branches' and method in ('PUT','PATCH'):
            allowed={'baseVersion','clientMutationId','doc','structure','composition'} if method=='PUT' else {'baseVersion','clientMutationId','name','locked','archived'}
            store.fields(body,allowed)
            return versions.save_branch(conn,scope,parts[1],body)
    if tail=='compare' and method=='POST': return versions.compare(conn,scope,body)
    if tail=='previews' and method=='POST': return build_preview(conn,scope,body)
    if len(parts)==2 and parts[0]=='previews' and method=='GET':
        preview=store.get_preview(conn,scope,parts[1]);stale=False
        try: validate_fingerprints(conn,scope,preview)
        except story.StoryError as exc:
            if exc.code!='DRAMA_WRITING_PREVIEW_STALE': raise
            stale=True
        return preview|{'stale':stale}
    if len(parts)==3 and parts[0]=='previews' and parts[2]=='apply' and method=='POST': return apply_preview(conn,scope,parts[1],body)
    name='files' if parts[0] in ('imports','exports') else 'tools' if parts[0] in ('bible','appearances','search') else 'impact' if parts[0] in ('impact','alignment') else None
    if name:
        return feature(name).dispatch(conn,scope,method,tail,body,query,raw=raw,headers=headers)
    return store.UNHANDLED
