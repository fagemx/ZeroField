"""Stable identity and bounded, explicit document structure transformations."""
from __future__ import annotations
import copy
import re
import uuid
from contextlib import contextmanager
from collections import Counter
from project_docs import writing_store as store, repository as repo, story_openapi as story
from project_docs.doc_schema import node_text, new_id
from project_docs.scene_headings import HEADING  # the one shared rule (R44-3); re-exported for callers


def heading_line(node):
    """A scene's title is its heading line: the block text before the first hard break."""
    line=[]
    for child in node.get('content') or []:
        if child.get('type')=='hardBreak': break
        line.append(node_text(child))
    return ''.join(line)


def identifier(scope):
    return 'wstr_'+store.hash_value([scope.slug,scope.episode_id])


def bid(node):
    return node.get('attrs',{}).get('bid')


def sections(doc):
    result=[]
    for node in doc.get('content',[]):
        if HEADING.match(node_text(node)):
            result.append({'heading':node,'nodes':[]})
        elif result:
            result[-1]['nodes'].append(node)
    if not result and doc.get('content'):
        result=[{'heading':None,'nodes':doc['content']}]
    return result


def _content_hash(nodes):
    # Exact content includes type/marks but not mutable identity/ownership attributes.
    def clean(value):
        if isinstance(value,list): return [clean(v) for v in value]
        if not isinstance(value,dict): return value
        return {k:clean(v) for k,v in value.items() if k!='attrs'} | ({'attrs':{k:v for k,v in value['attrs'].items() if k not in ('bid','owner','created')}} if isinstance(value.get('attrs'),dict) else {})
    return store.hash_value(clean(nodes))


def authored_structure(doc, previous):
    """Promote trusted imported/authored block boundaries, not heading text, to authority."""
    result=copy.deepcopy(previous)
    nodes={bid(n):n for n in doc.get('content',[])}
    seen=set();document_hash=store.doc_hash(doc)
    for scene in result.get('scenes',[]):
        identifiers=([scene.get('headingBid')] if scene.get('headingBid') else [])+scene.get('blockBids',[])
        if not identifiers or len(identifiers)!=len(set(identifiers)) or seen.intersection(identifiers) or set(identifiers)-set(nodes):
            store.fail('MAPPING_REQUIRED','Authored scene boundaries must reference disjoint existing blocks.')
        seen.update(identifiers)
        if not isinstance(scene.get('title'),str) or not 1<=len(scene['title'])<=200 or any(c in scene['title'] for c in ('\r','\n')):
            story.invalid('Authored scene titles must be single-line text of 1–200 characters.')
        scene['authoredBoundary']=True
        scene.setdefault('authoredOrigin',{'docHash':document_hash,'headingBid':scene.get('headingBid'),
            'blockBids':copy.deepcopy(scene.get('blockBids',[])),'title':scene['title']})
    result['structureHash']=fingerprint(result)
    return result


def authored_parts(doc, previous):
    """Locate explicit partitions only through surviving bids, never title/order guesses."""
    nodes=doc.get('content',[]);positions={bid(n):i for i,n in enumerate(nodes)}
    anchored=[]
    for scene in previous.get('scenes',[]):
        identifiers=([scene.get('headingBid')] if scene.get('headingBid') else [])+scene.get('blockBids',[])
        surviving=[positions[b] for b in identifiers if b in positions]
        if surviving:
            anchored.append((min(surviving),max(surviving),scene))
    anchored.sort(key=lambda item:item[0])
    for left,right in zip(anchored,anchored[1:]):
        if left[1]>=right[0]:
            store.fail('MAPPING_REQUIRED','Authored block memberships overlap or interleave; resolve the boundaries explicitly.')
    explicit={start:scene for start,_,scene in anchored if scene.get('authoredBoundary')}
    ranges=[(start,anchored[i+1][0] if i+1<len(anchored) else len(nodes))
        for i,(start,_,scene) in enumerate(anchored) if scene.get('authoredBoundary')]
    boundaries=set(explicit)
    for index,node in enumerate(nodes):
        if HEADING.match(node_text(node)) and not any(start<=index<end for start,end in ranges):
            boundaries.add(index)
    if not boundaries: return sections(doc)
    ordered=sorted(boundaries);result=[]
    for i,start in enumerate(ordered):
        end=ordered[i+1] if i+1<len(ordered) else len(nodes)
        scene=explicit.get(start)
        heading=nodes[start] if (scene and bid(nodes[start])==scene.get('headingBid')) or (not scene and HEADING.match(node_text(nodes[start]))) else None
        result.append({'heading':heading,'nodes':nodes[start+(1 if heading else 0):end],
            '_sceneKey':scene['sceneKey'] if scene else None})
    return result


def reconcile_structure(doc, previous, *, lineage=None):
    doc=store.checked_doc(doc)
    document_hash=store.doc_hash(doc)
    previous=previous or {}
    old=previous.get('scenes',[])
    parts=authored_parts(doc,previous) if any(s.get('authoredBoundary') for s in old) else sections(doc)
    if len(parts)>1000 or sum(len(p['nodes']) for p in parts)>1000:
        store.fail('LIMIT_EXCEEDED','Split resources above 1,000 structure units.',413)
    old_scene_hash=Counter(s.get('contentHash') for s in old)
    new_scene_hash=Counter(_content_hash(([p['heading']] if p['heading'] else [])+p['nodes']) for p in parts)
    all_beats=[b for s in old for b in s.get('beats',[])]
    old_beat_hash=Counter(b.get('contentHash') for b in all_beats)
    new_beat_hash=Counter(_content_hash([n]) for p in parts for n in p['nodes'])
    used_s,used_b=set(),set()
    output=[]
    lineage=copy.deepcopy(lineage or {})
    for i,part in enumerate(parts,1):
        heading=part['heading']; heading_bid=bid(heading or {})
        content_hash=_content_hash(([heading] if heading else [])+part['nodes'])
        candidates=[s for s in old if s['sceneKey'] not in used_s and heading_bid and s.get('headingBid')==heading_bid]
        if not candidates and old_scene_hash[content_hash]==new_scene_hash[content_hash]==1:
            candidates=[s for s in old if s['sceneKey'] not in used_s and s.get('contentHash')==content_hash]
        explicit=part.get('_sceneKey') or lineage.get(heading_bid)
        if explicit:
            candidates=[s for s in old if s['sceneKey']==explicit and s['sceneKey'] not in used_s]
        matched=candidates[0] if len(candidates)==1 else None
        key=matched['sceneKey'] if matched else 'wsc_'+uuid.uuid5(uuid.NAMESPACE_URL,'writing-scene:'+document_hash+':'+str(heading_bid or [bid(n) for n in part['nodes']])).hex
        used_s.add(key)
        scene={k:copy.deepcopy(v) for k,v in (matched or {}).items() if k in ('summary','storyTime','act','plot','foreshadowing','payoff','authoredBoundary','authoredOrigin','materialized')}
        scene.update(sceneKey=key,headingBid=heading_bid,blockBids=[bid(n) for n in part['nodes']],
            title=matched['title'] if matched and matched.get('authoredBoundary') else heading_line(heading) if heading else 'Scene 01',order=i,contentHash=content_hash,
            mapping='exact' if matched or not old else 'unresolved',beats=[])
        for node in part['nodes']:
            if not node_text(node).strip(): continue
            content=_content_hash([node])
            candidates=[b for b in all_beats if b['beatKey'] not in used_b and bid(node) in b.get('blockBids',[])]
            if not candidates and old_beat_hash[content]==new_beat_hash[content]==1:
                candidates=[b for b in all_beats if b['beatKey'] not in used_b and b.get('contentHash')==content]
            explicit=lineage.get(bid(node))
            if explicit:
                candidates=[b for b in all_beats if b['beatKey']==explicit and b['beatKey'] not in used_b]
            matched_b=candidates[0] if len(candidates)==1 else None
            bkey=matched_b['beatKey'] if matched_b else 'wbt_'+uuid.uuid5(uuid.NAMESPACE_URL,'writing-beat:'+document_hash+':'+str(bid(node))).hex
            used_b.add(bkey)
            scene['beats'].append({'beatKey':bkey,'blockBids':[bid(node)],'textHash':store.hash_value(node_text(node)),
                'contentHash':content,'mapping':'exact' if matched_b or not old else 'unresolved'})
        output.append(scene)
    tombstones=copy.deepcopy(previous.get('tombstones',[]))
    existing={t.get('sceneKey') or t.get('beatKey') for t in tombstones}
    for s in old:
        if s['sceneKey'] not in used_s and s['sceneKey'] not in existing:
            tombstones.append({'sceneKey':s['sceneKey'],'reason':'source_removed','scene':copy.deepcopy(s)})
        for b in s.get('beats',[]):
            if b['beatKey'] not in used_b and b['beatKey'] not in existing:
                tombstones.append({'beatKey':b['beatKey'],'sceneKey':s['sceneKey'],'reason':'source_removed'})
    result={'scenes':output,'lanes':copy.deepcopy(previous.get('lanes',[])), 'tombstones':tombstones,
        'lineage':copy.deepcopy(previous.get('lineage',{}))|lineage,'legacyBindings':copy.deepcopy(previous.get('legacyBindings',[])),'docHash':document_hash}
    result['structureHash']=fingerprint(result)
    return result


READ_SCENE_FIELDS=frozenset(('assetCodes','shotIds','shotLinks'))


def _scene_authority(scene):
    return {k:copy.deepcopy(v) for k,v in scene.items() if k not in READ_SCENE_FIELDS}


def fingerprint(value):
    authority={k:value.get(k,[]) for k in ('scenes','lanes','tombstones','lineage','legacyBindings')}
    authority['scenes']=[_scene_authority(s) for s in authority['scenes']]
    return store.hash_value(authority)


def read_structure(conn, scope):
    doc=repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']
    saved=store.get_record(conn,scope,'writing_structure',identifier(scope),required=False)
    stale=bool(saved and saved['docHash']!=store.doc_hash(doc))
    result=reconcile_structure(doc,saved) if not saved or stale else copy.deepcopy(saved)
    result.setdefault('legacyBindings',[])
    for scene in result['scenes']:
        scene['legacySceneId']=f"sc_{scope.slug}_{scope.episode['episodeIndex']:02d}_S{scene['order']:02d}"
    # Legacy compatibility IDs are derived, never identity/freshness authority.
    result.update(initialized=bool(saved),stale=stale,version=saved['version'] if saved else 0)
    result['structureHash']=fingerprint(result)
    return result


def resolve_scene_key(value, key):
    """Follow only explicit merge lineage; an active key wins after an Undo."""
    present={s['sceneKey'] for s in value.get('scenes',[])}
    lineage=value.get('lineage',{});seen=set()
    while key not in present:
        if key in seen or key not in lineage: return None
        seen.add(key);key=lineage[key]
    return key


def shot_relationship(value, shot):
    """Current source projection, never inferred from a positional sceneId/title."""
    origin=shot.get('storyOrigin')
    if origin is None:
        binding=next((b for b in value.get('legacyBindings',[]) if b['shotId']==shot['shotId']),{})
        origin={'sceneKeys':[binding['sceneKey']] if binding.get('sceneKey') else [],
            'mapping':binding.get('mapping','unbound')}
    mapping=origin.get('mapping','unbound')
    if mapping not in ('exact','scene_only'): return [],mapping,'ambiguous' if mapping=='ambiguous' else 'unbound'
    beats=origin.get('beatKeys',[])
    if beats:
        by_beat={b['beatKey']:s['sceneKey'] for s in value.get('scenes',[]) for b in s.get('beats',[])}
        if set(beats)-set(by_beat): return [],mapping,'source_removed'
        return list(dict.fromkeys(by_beat[k] for k in beats)),mapping,None
    keys=origin.get('sceneKeys',[])
    if any(v=='split:'+k for k in keys for v in value.get('lineage',{}).values()):
        return [],mapping,'ambiguous'
    resolved=[resolve_scene_key(value,k) for k in keys]
    if not keys or None in resolved: return [],mapping,'source_removed' if keys else 'unbound'
    return list(dict.fromkeys(resolved)),mapping,None


def compatibility_relationship(value, shot):
    """Legacy rebuild is scene-wide: a proven surviving scene can replace its beats.

    This is NOT an exact beat/media origin and must not be used by the outline or
    alignment. Deleted scenes cannot fall back to their reused positional ID.
    """
    keys,mapping,missing=shot_relationship(value,shot)
    origin=shot.get('storyOrigin')
    if missing=='source_removed' and origin and origin.get('sceneKeys'):
        scene_only=copy.deepcopy(origin);scene_only['beatKeys']=[]
        return shot_relationship(value,shot|{'storyOrigin':scene_only})
    return keys,mapping,missing


def project_references(conn, scope, value, doc):
    """Authorized READ-only outline fields. Never pass this projection to persistence."""
    store.reauthorize(conn,scope)
    result=copy.deepcopy(value)
    nodes={bid(n):node_text(n) for n in doc.get('content',[])}
    scenes={s['sceneKey']:s for s in result['scenes']}
    for scene in scenes.values():
        text='\n'.join(nodes.get(k,'') for k in [scene.get('headingBid')]+scene.get('blockBids',[]))
        scene['assetCodes']=list(dict.fromkeys(story.asset_code(m[1]) for m in story.ASSET_RE.finditer(text)))
        scene['shotIds']=[];scene['shotLinks']=[]
    for shot in story.shots(conn,scope.episode):
        keys,mapping,missing=shot_relationship(value,shot)
        if missing: continue
        for key in keys:
            scenes[key]['shotIds'].append(shot['shotId'])
            scenes[key]['shotLinks'].append({'shotId':shot['shotId'],'mapping':mapping})
    return result


def association_changes(conn, scope, before, after):
    """Detach deleted/uncertain compatibility links in the same structure transaction.

    Origins and all takes remain untouched. Explicit merges redirect compatibility
    associations; split scene-only relationships cannot safely choose either half.
    """
    changes=[]
    old_ids={s['legacySceneId']:s['sceneKey'] for s in before['scenes']}
    new_ids={s['sceneKey']:(f"sc_{scope.slug}_{scope.episode['episodeIndex']:02d}_S{i:02d}",i)
        for i,s in enumerate(after['scenes'],1)}
    for shot in story.shots(conn,scope.episode):
        keys,mapping,missing=compatibility_relationship(after,shot)
        old_key=old_ids.get(shot.get('sceneId'))
        # The typed operation also carries a frozen compatibility snapshot for
        # legacy rows not yet bound. Never use this fallback for an explicit origin.
        bound=any(b['shotId']==shot['shotId'] for b in before.get('legacyBindings',[]))
        if shot.get('storyOrigin') is None and not bound and old_key:
            keys,mapping,missing=shot_relationship(after,{'shotId':shot['shotId'],
                'storyOrigin':{'sceneKeys':[old_key],'mapping':'scene_only'}})
        if not old_key and not shot.get('sceneId') and not shot.get('detachedScene'): continue
        legacy,index=new_ids[keys[0]] if not missing and len(keys)==1 else (None,None)
        if legacy==shot.get('sceneId'): continue
        changes.append((shot,legacy,index,old_key,missing))
    return sorted(changes,key=lambda change:change[0]['shotId'])


def lock_associations(conn, scope, changes):
    """No reverse project lock: source is already locked; other tabs never wait."""
    from project_docs import writing_impact
    store.reauthorize(conn,scope,write=True)
    for key in sorted({shot['tabKey'] for shot,_,_,_,_ in changes}):
        with conn.cursor() as cur:
            cur.execute('SELECT tab_key FROM projectops.tab WHERE project_slug=%s AND tab_key=%s AND deleted_at IS NULL FOR UPDATE NOWAIT',
                (scope.slug,key))
            if not cur.fetchone(): store.fail('CONFLICT','An affected production page changed.')
    for shot,_,_,_,_ in changes: writing_impact._check_row(conn,scope,shot)


def remap_shot_associations(conn, scope, before, after, *, changes=None):
    if changes is None:
        changes=association_changes(conn,scope,before,after)
        lock_associations(conn,scope,changes)
    for shot,legacy,index,old_key,missing in changes:
        meta=story.shot_meta(conn,shot['shotId'])|{'sceneId':legacy}
        if legacy is None:
            meta['detachedScene']={'sceneKeys':copy.deepcopy((shot.get('storyOrigin') or {}).get('sceneKeys') or ([old_key] if old_key else [])),
                'legacySceneId':shot.get('detachedScene',{}).get('legacySceneId',shot.get('sceneId')),
                'state':missing or 'ambiguous'}
        else:
            meta.pop('detachedScene',None)
            label=re.sub(r'^SC\d+',f'SC{index:02d}',shot['shotIndex'],flags=re.I)
            if label!=shot['shotIndex']:
                story.mutate_row(conn,scope.me,scope.slug,shot['tabKey'],shot['rowId'],{0:label})
        story.store(conn,'meta_'+shot['shotId'],'shot_meta',meta,scope.slug)


@contextmanager
def savepoint(conn):
    """Rollback boundary without ever committing the caller's outer transaction."""
    from psycopg.pq import TransactionStatus
    if conn.info.transaction_status==TransactionStatus.IDLE:
        conn.execute('SELECT 1')  # Begin the caller's transaction before nesting.
    with conn.transaction(): yield


@contextmanager
def deferred_reconciliation(conn, slug, key):
    """Internal connection/transaction-scoped suppression for declared lineage only.

    The enclosing savepoint rolls back source/history AND associations on failure;
    connection state is unwound on every exit, never set from a request body.
    """
    state=getattr(conn,'_writing_structure_deferred',None)
    if state is None:
        state={};conn._writing_structure_deferred=state
    token=(slug,key);previous=state.get(token,0)
    from psycopg.errors import LockNotAvailable
    try:
        with savepoint(conn):
            state[token]=previous+1
            try: yield
            finally:
                if previous: state[token]=previous
                else: state.pop(token,None)
    except LockNotAvailable:
        store.fail('LOCKED','An affected production page is busy; nothing was saved.')
    finally:
        if not state: del conn._writing_structure_deferred


def _layout(value):
    return ([s['sceneKey'] for s in value['scenes']],
        {b['beatKey']:s['sceneKey'] for s in value['scenes'] for b in s.get('beats',[])})


def prepare_tab_save(conn, slug, key, old_doc, doc, trusted_writer):
    """Repository seam for enrolled screenplay writes; no authority from actor_id.

    Unrelated tabs/keystrokes do not acquire production locks or persist sidecars.
    No project advisory lock is ever requested from this already-tab-locked seam.
    """
    if getattr(conn,'_writing_structure_deferred',{}).get((slug,key)): return None
    with conn.cursor() as cur:
        cur.execute("SELECT data->>'episodeId',data FROM projectops.story_record WHERE project_slug=%s AND kind='writing_structure' ORDER BY id",(slug,))
        enrolled=cur.fetchall()
    if not enrolled: return None
    episode_tabs={ep['episodeId']:ep for ep in story.episodes(conn,slug) if ep['tabKey']==key}
    for episode_id,saved in enrolled:
        ep=episode_tabs.get(episode_id)
        if ep is None: continue
        # Read/reconcile against the still-locked OLD document, never a new ordinal snapshot.
        before=reconcile_structure(old_doc,repo._loads(saved))
        for scene in before['scenes']:
            scene['legacySceneId']=f"sc_{slug}_{ep['episodeIndex']:02d}_S{scene['order']:02d}"
        after=reconcile_structure(doc,before)
        if _layout(before)==_layout(after): return None
        if trusted_writer is None:
            store.fail('CONFLICT','A structural screenplay save requires a current trusted writer.')
        scope=store.scope_for(conn,trusted_writer,episode_id,write=True)
        # Validate the enrolled record's scope/kind before any derived write.
        store.get_record(conn,scope,'writing_structure',identifier(scope))
        changes=association_changes(conn,scope,before,after)
        if changes:
            lock_associations(conn,scope,changes)
        return scope,before,after,changes
    return None


def finish_tab_save(conn, plan):
    if plan is None: return
    scope,before,after,changes=plan
    # Keep the existing lazy stale-sidecar contract when no association changes.
    if not changes: return
    result=persist(conn,scope,after)
    remap_shot_associations(conn,scope,before,result,changes=changes)


def finalize_structure_change(conn, scope, before, after):
    after=copy.deepcopy(after)
    # Adopting a draft's layout cannot replace the episode's frozen legacy evidence.
    after['legacyBindings']=copy.deepcopy(before.get('legacyBindings',[]))
    live={s['sceneKey'] for s in after['scenes']}
    removed={t['sceneKey'] for t in after.get('tombstones',[]) if 'scene' in t}
    for scene in before['scenes']:
        if scene['sceneKey'] not in live and scene['sceneKey'] not in removed:
            after.setdefault('tombstones',[]).append({'sceneKey':scene['sceneKey'],'reason':'source_removed','scene':copy.deepcopy(scene)})
    changes=association_changes(conn,scope,before,after)
    lock_associations(conn,scope,changes)
    result=persist(conn,scope,after)
    remap_shot_associations(conn,scope,before,result,changes=changes)
    return result


def persist(conn, scope, value, *, base_version=None):
    data={k:copy.deepcopy(value.get(k,[]) if k=='legacyBindings' else value[k]) for k in ('docHash','scenes','lanes','tombstones','lineage','legacyBindings','structureHash')}
    data['scenes']=[_scene_authority(s) for s in data['scenes']]
    data['structureHash']=fingerprint(data)
    saved=store.get_record(conn,scope,'writing_structure',identifier(scope),required=False,lock=True)
    if saved:
        return store.cas_record(conn,scope,'writing_structure',identifier(scope),base_version=saved['version'] if base_version is None else base_version,changes=data)
    if base_version not in (None,0): store.fail()
    return store.insert_record(conn,scope,'writing_structure',identifier(scope),data|{'initialized':True})


def initialize(conn, scope, expected_doc_hash):
    store.reauthorize(conn,scope,write=True)
    store.lock_project(conn,scope)
    doc=repo.get_tab_for_update(conn,scope.slug,scope.episode['tabKey'])['doc']
    if store.doc_hash(doc)!=expected_doc_hash: store.fail()
    saved=store.get_record(conn,scope,'writing_structure',identifier(scope),required=False)
    if not saved or saved['docHash']!=expected_doc_hash:
        current=read_structure(conn,scope)
        if not saved:
            by_legacy={s['legacySceneId']:s['sceneKey'] for s in current['scenes']}
            current['legacyBindings']=[{'shotId':shot['shotId'],'sceneKey':by_legacy.get(shot.get('sceneId')),
                'mapping':'scene_only' if shot.get('sceneId') in by_legacy else 'unresolved'} for shot in story.shots(conn,scope.episode)]
        persist(conn,scope,current)
    return read_structure(conn,scope)


def metadata_patch(conn, scope, body):
    store.fields(body,{'baseVersion','clientMutationId','scenePatches','lanePatches'},{'baseVersion','clientMutationId'})
    current=read_structure(conn,scope)
    if not current['initialized'] or current['stale'] or current['version']!=body['baseVersion']:
        store.fail(message='Initialize or reload the current structure before editing metadata.')
    current=copy.deepcopy(current)
    if any(not isinstance(body.get(k,[]),list) or len(body.get(k,[]))>1000 for k in ('scenePatches','lanePatches')):
        story.invalid('Use bounded scene and lane patch arrays.')
    scenes={s['sceneKey']:s for s in current['scenes']}
    for patch in body.get('scenePatches',[]):
        store.fields(patch,{'sceneKey','summary','storyTime','act','plot','foreshadowing','payoff'},{'sceneKey'})
        if patch['sceneKey'] not in scenes: store.fail('MAPPING_REQUIRED')
        for key,value in patch.items():
            if key=='sceneKey': continue
            if key=='plot':
                if not isinstance(value,dict) or set(value)-{l['laneId'] for l in current['lanes']} or any(not isinstance(v,str) or len(v)>10000 for v in value.values()): story.invalid('Invalid plot cells.')
            elif not isinstance(value,str) or len(value)>10000: story.invalid('Invalid scene metadata.')
            scenes[patch['sceneKey']][key]=copy.deepcopy(value)
    for patch in body.get('lanePatches',[]):
        store.fields(patch,{'laneId','name','order','remove'},{'laneId'})
        if patch.get('remove'): story.invalid('Lane deletion requires a structure preview.')
        if not isinstance(patch['laneId'],str) or not 1<=len(patch['laneId'])<=128: story.invalid('Invalid lane ID.')
        if 'order' in patch and (type(patch['order']) is not int or not 0<=patch['order']<=8): story.invalid('Invalid lane order.')
        lane=next((l for l in current['lanes'] if l['laneId']==patch['laneId']),None)
        if not lane:
            lane={'laneId':patch['laneId'],'name':'','order':len(current['lanes'])+1};current['lanes'].append(lane)
        if not isinstance(patch.get('name',lane['name']),str) or len(patch.get('name',lane['name']))>200: story.invalid('Invalid lane name.')
        lane.update({k:v for k,v in patch.items() if k in ('name','order')})
    if len(current['lanes'])>8: store.fail('LIMIT_EXCEEDED','At most eight plot lanes are supported.',413)
    result=persist(conn,scope,current,base_version=body['baseVersion'])
    return result|{'clientMutationId':body['clientMutationId'],'savedAt':result['updatedAt']}


def build_preview(conn, scope, body):
    store.fields(body,{'kind','targetDocHash','structureVersion','operation'},{'kind','targetDocHash','structureVersion','operation'})
    target=store.resolve_ref(conn,scope,{'kind':'working'})
    current=target['structure']
    if not current['initialized'] or current['stale'] or body['targetDocHash']!=target['docHash'] or body['structureVersion']!=current['version']:
        store.fail('PREVIEW_STALE')
    operation=body['operation'];store.fields(operation,{'type','sceneKey','afterSceneKey','title','atBid','sceneKeys','keepSceneKey','laneId','snapshotId'},{'type'})
    doc=copy.deepcopy(target['doc']);groups=sections(doc);scenes=current['scenes'];lineage={}
    lookup={s['sceneKey']:i for i,s in enumerate(scenes)}
    def index(key):
        if key not in lookup: store.fail('MAPPING_REQUIRED')
        return lookup[key]
    typ=operation['type']
    operation_fields={'add':{'afterSceneKey','title'},'move':{'sceneKey','afterSceneKey'},'remove':{'sceneKey'},
        'split':{'sceneKey','atBid','title'},'merge':{'sceneKeys','keepSceneKey'},'remove_lane':{'laneId'},'restore':{'snapshotId'}}
    if not isinstance(typ,str) or typ not in operation_fields: story.invalid('Unknown structure operation.')
    store.fields(operation,operation_fields[typ]|{'type'})
    if typ=='add':
        title=operation.get('title','New scene')
        if not isinstance(title,str) or not 1<=len(title.strip())<=200: story.invalid('Use a scene title of 1–200 characters.')
        heading={'type':'heading','attrs':{'bid':new_id('b'),'level':2},'content':[{'type':'text','text':title if HEADING.match(title) else 'Scene 01: '+title}]}
        at=0 if operation.get('afterSceneKey') is None else index(operation['afterSceneKey'])+1
        groups.insert(at,{'heading':heading,'nodes':[]})
    elif typ=='move':
        original=groups.pop(index(operation.get('sceneKey')))
        key=operation.get('afterSceneKey')
        if key==operation.get('sceneKey'): story.invalid('A scene cannot move after itself.')
        at=0 if key is None else groups.index(next(g for g in groups if bid(g['heading'] or {})==scenes[index(key)]['headingBid']))+1
        groups.insert(at,original)
    elif typ=='remove':
        groups.pop(index(operation.get('sceneKey')))
    elif typ=='split':
        i=index(operation.get('sceneKey'));group=groups[i]
        at=next((j for j,n in enumerate(group['nodes']) if bid(n)==operation.get('atBid')),None)
        if at is None or at==0: story.invalid('Split at a body block after the first beat.')
        title=operation.get('title','Split scene')
        if not isinstance(title,str) or not 1<=len(title.strip())<=200: story.invalid('Use a scene title of 1–200 characters.')
        heading={'type':'heading','attrs':{'bid':new_id('b'),'level':2},'content':[{'type':'text','text':title if HEADING.match(title) else 'Scene 01: '+title}]}
        groups.insert(i+1,{'heading':heading,'nodes':group['nodes'][at:]});group['nodes']=group['nodes'][:at]
        lineage[bid(heading)]='split:'+operation['sceneKey']
    elif typ=='merge':
        keys=operation.get('sceneKeys',[]);keep=operation.get('keepSceneKey')
        if not isinstance(keys,list) or len(keys)<2 or len(set(keys))!=len(keys) or keep not in keys: story.invalid('Choose scenes and the retained scene key.')
        indices=sorted(index(k) for k in keys)
        merged={'heading':copy.deepcopy(groups[index(keep)]['heading']),'nodes':[n for i in indices for n in groups[i]['nodes']]}
        groups=[g for i,g in enumerate(groups) if i not in indices];groups.insert(indices[0],merged)
        for key in keys:
            if key!=keep: lineage[key]=keep
    elif typ=='remove_lane':
        current=copy.deepcopy(current);current['lanes']=[l for l in current['lanes'] if l['laneId']!=operation.get('laneId')]
        for s in current['scenes']: s.get('plot',{}).pop(operation.get('laneId'),None)
    elif typ=='restore':
        snapshot=store.get_record(conn,scope,'writing_version',operation.get('snapshotId'))['snapshot']
        doc=copy.deepcopy(snapshot['doc']);current=copy.deepcopy(snapshot['structure']);groups=sections(doc)
    else: story.invalid('Unknown structure operation.')
    if typ not in ('remove_lane','restore'):
        # Preserve any screenplay preamble before the first scene heading.
        first=next((i for i,n in enumerate(doc['content']) if HEADING.match(node_text(n))),len(doc['content']))
        preamble=doc['content'][:first] if any(g['heading'] for g in sections(doc)) else []
        doc['content']=preamble+[n for g in groups for n in ([g['heading']] if g['heading'] else [])+g['nodes']]
    doc=store.checked_doc(doc,scope.slug)
    # A typed structural operation deliberately changes the partition. Its explicit
    # group layout may add/split boundaries that a normal authored text save must not infer.
    prior=copy.deepcopy(current)
    if typ not in ('remove_lane','restore'):
        for scene in prior['scenes']: scene.pop('authoredBoundary',None)
    proposed=reconcile_structure(doc,prior,lineage=lineage)
    authored={s['sceneKey']:s for s in current['scenes'] if s.get('authoredBoundary')}
    for scene in proposed['scenes']:
        if scene['sceneKey'] in authored:
            source=authored[scene['sceneKey']]
            scene.update({k:copy.deepcopy(source[k]) for k in ('authoredBoundary','authoredOrigin','materialized','title') if k in source})
    proposed['structureHash']=fingerprint(proposed)
    return {'sourceFingerprints':[],'targetFingerprints':[{'sourceRef':{'kind':'working'},'docHash':target['docHash'],'structureHash':target['structureHash']}],
        'allowedActions':[{'actionId':'structure','kind':typ}], 'proposedChanges':{'doc':doc,'structure':proposed,'operation':operation},
        'warnings':['Automatic SC-prefixed shot labels follow scene order. Manually named shot labels retain their film order; review shot ordering separately.'] if typ=='move' else []}


def apply_preview(conn, scope, preview, selection):
    with deferred_reconciliation(conn,scope.slug,scope.episode['tabKey']):
        return _apply_preview(conn,scope,preview,selection)


def _apply_preview(conn, scope, preview, selection):
    from project_docs import writing_service as service, writing_versions as versions
    before=store.resolve_ref(conn,scope,{'kind':'working'})
    snapshot=versions.snapshot_of(scope,before)
    version_id='wver_'+uuid.uuid4().hex
    store.insert_snapshot(conn,scope,version_id,snapshot,name='Before structure change',created_by=scope.actor_id)
    proposed=preview['proposedChanges']
    service.replace_working(conn,scope,proposed['doc'],expected_hash=before['docHash'])
    actual=repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']
    reconciled=reconcile_structure(actual,proposed['structure'])
    result=finalize_structure_change(conn,scope,before['structure'],reconciled)
    return {'docHash':store.doc_hash(repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']),'structure':read_structure(conn,scope),'beforeVersionId':version_id}
