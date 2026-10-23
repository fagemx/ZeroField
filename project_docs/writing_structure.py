"""Stable identity and bounded, explicit document structure transformations."""
from __future__ import annotations
import copy
import re
import uuid
from collections import Counter
from project_docs import writing_store as store, repository as repo, story_openapi as story
from project_docs.doc_schema import node_text, new_id

HEADING = re.compile(r'^\s*(?:#{1,6}\s*)?(?:Scene\s*\d+|場景\s*[一二三四五六七八九十\d]+|场景\s*[一二三四五六七八九十\d]+|INT\.|EXT\.)',re.I)


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


def reconcile_structure(doc, previous, *, lineage=None):
    doc=store.checked_doc(doc)
    previous=previous or {}
    old=previous.get('scenes',[])
    parts=sections(doc)
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
        explicit=lineage.get(heading_bid)
        if explicit:
            candidates=[s for s in old if s['sceneKey']==explicit and s['sceneKey'] not in used_s]
        matched=candidates[0] if len(candidates)==1 else None
        key=matched['sceneKey'] if matched else 'wsc_'+uuid.uuid4().hex
        used_s.add(key)
        scene={k:copy.deepcopy(v) for k,v in (matched or {}).items() if k in ('summary','storyTime','act','plot','foreshadowing','payoff')}
        scene.update(sceneKey=key,headingBid=heading_bid,blockBids=[bid(n) for n in part['nodes']],
            title=node_text(heading) if heading else 'Scene 01',order=i,contentHash=content_hash,
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
            bkey=matched_b['beatKey'] if matched_b else 'wbt_'+uuid.uuid4().hex
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
        'lineage':copy.deepcopy(previous.get('lineage',{}))|lineage,'docHash':store.doc_hash(doc)}
    result['structureHash']=fingerprint(result)
    return result


def fingerprint(value):
    return store.hash_value({k:value.get(k,[]) for k in ('scenes','lanes','tombstones','lineage')})


def read_structure(conn, scope):
    doc=repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']
    saved=store.get_record(conn,scope,'writing_structure',identifier(scope),required=False)
    stale=bool(saved and saved['docHash']!=store.doc_hash(doc))
    result=reconcile_structure(doc,saved) if not saved or stale else copy.deepcopy(saved)
    for scene in result['scenes']:
        scene['legacySceneId']=f"sc_{scope.slug}_{scope.episode['episodeIndex']:02d}_S{scene['order']:02d}"
    # Legacy compatibility IDs are derived, never identity/freshness authority.
    result.update(initialized=bool(saved),stale=stale,version=saved['version'] if saved else 0)
    result['structureHash']=fingerprint(result)
    return result


def persist(conn, scope, value, *, base_version=None):
    data={k:copy.deepcopy(value[k]) for k in ('docHash','scenes','lanes','tombstones','lineage','structureHash')}
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
        persist(conn,scope,read_structure(conn,scope))
    return read_structure(conn,scope)


def metadata_patch(conn, scope, body):
    store.fields(body,{'baseVersion','clientMutationId','scenePatches','lanePatches'},{'baseVersion','clientMutationId'})
    current=read_structure(conn,scope)
    if not current['initialized'] or current['stale'] or current['version']!=body['baseVersion']:
        store.fail(message='Initialize or reload the current structure before editing metadata.')
    current=copy.deepcopy(current)
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
    if typ=='add':
        heading={'type':'heading','attrs':{'bid':new_id('b'),'level':2},'content':[{'type':'text','text':operation.get('title','Scene 01: New scene')}]}
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
        heading={'type':'heading','attrs':{'bid':new_id('b'),'level':2},'content':[{'type':'text','text':operation.get('title','Scene 01: Split scene')}]}
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
    proposed=reconcile_structure(doc,current,lineage=lineage)
    return {'sourceFingerprints':[],'targetFingerprints':[{'sourceRef':{'kind':'working'},'docHash':target['docHash'],'structureHash':target['structureHash']}],
        'allowedActions':[{'actionId':'structure','kind':typ}], 'proposedChanges':{'doc':doc,'structure':proposed,'operation':operation},'warnings':[]}


def apply_preview(conn, scope, preview, selection):
    from project_docs import writing_service as service, writing_versions as versions
    before=store.resolve_ref(conn,scope,{'kind':'working'})
    snapshot=versions.snapshot_of(scope,before)
    version_id='wver_'+uuid.uuid4().hex
    store.insert_snapshot(conn,scope,version_id,snapshot,name='Before structure change',created_by=scope.actor_id)
    proposed=preview['proposedChanges']
    service.replace_working(conn,scope,proposed['doc'],expected_hash=before['docHash'])
    result=persist(conn,scope,proposed['structure'])
    # Remap only proven surviving stable keys, keeping rows/takes and shot identities.
    old_ids={s['legacySceneId']:s['sceneKey'] for s in before['structure']['scenes']}
    new_ids={s['sceneKey']:(f"sc_{scope.slug}_{scope.episode['episodeIndex']:02d}_S{i:02d}",i) for i,s in enumerate(result['scenes'],1)}
    for shot in story.shots(conn,scope.episode):
        key=old_ids.get(shot.get('sceneId'))
        if key in new_ids:
            legacy,index=new_ids[key]
            if legacy!=shot.get('sceneId'):
                meta=story.shot_meta(conn,shot['shotId'])|{'sceneId':legacy}
                story.store(conn,'meta_'+shot['shotId'],'shot_meta',meta,scope.slug)
                label=re.sub(r'^SC\d+',f'SC{index:02d}',shot['shotIndex'],flags=re.I)
                story.mutate_row(conn,scope.me,scope.slug,shot['tabKey'],shot['rowId'],{0:label})
    return {'docHash':store.doc_hash(repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']),'structure':read_structure(conn,scope),'beforeVersionId':version_id}
