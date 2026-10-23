"""Immutable creative snapshots, owner-only branches and explicit adoption."""
from __future__ import annotations
import copy
import uuid
from project_docs import writing_store as store, writing_structure as structure, repository as repo, story_openapi as story
from project_docs.doc_schema import doc_text


def snapshot_of(scope, source):
    doc=store.checked_doc(source['doc'],scope.slug)
    inputs=copy.deepcopy(source.get('productionInputs',store.production_inputs(scope)))
    return {'doc':doc,'docHash':store.doc_hash(doc),'scriptHash':story.digest(doc_text(doc)),
        'structure':copy.deepcopy(source.get('structure',{})),'structureHash':source.get('structureHash',store.hash_value(source.get('structure',{}))),
        'composition':store.composition(doc),'productionInputs':inputs,'productionInputsHash':store.hash_value(inputs)}


def create_version(conn, scope, body):
    store.fields(body,{'name','sourceRef','expectedSourceHash','share'},{'name','sourceRef','expectedSourceHash','share'})
    if body['share'] is not True: story.invalid('Explicit share:true is required to create a shared snapshot.')
    source=store.resolve_ref(conn,scope,body['sourceRef'])
    if source['docHash']!=body['expectedSourceHash']: store.fail()
    if body['sourceRef']['kind']=='working' and (not source['structure']['initialized'] or source['structure']['stale']):
        structure.initialize(conn,scope,source['docHash'])
        source=store.resolve_ref(conn,scope,body['sourceRef'])
    if body['sourceRef']['kind']=='source':
        story.invalid('Adapt a private idea or novel into a screenplay branch before sharing.')
    identifier='wver_'+uuid.uuid4().hex
    return store.insert_snapshot(conn,scope,identifier,snapshot_of(scope,source),name=body['name'],created_by=scope.actor_id)


def update_catalog(conn, scope, version_id, body):
    store.fields(body,{'baseCatalogVersion','clientMutationId','name','locked','archived'},{'baseCatalogVersion','clientMutationId'})
    data=store.get_record(conn,scope,'writing_version',version_id,lock=True)
    if data['createdBy']!=scope.actor_id and not scope.me.can_edit:
        raise story.StoryError(403,'DRAMA_OPERATION_NOT_ALLOWED','Only the creator or Showrunner manages version catalogs.')
    if type(body['baseCatalogVersion']) is not int or body['baseCatalogVersion']!=data['catalogVersion']: store.fail()
    ep=story.episode(conn,scope.episode_id)
    if (data.get('productionPinned') or ep.get('productionScriptVersionId')==version_id) and (body.get('locked') is False or body.get('archived') is True):
        store.fail('LOCKED','Production baselines cannot be unlocked or archived.')
    changes={k:body[k] for k in ('name','locked','archived') if k in body}
    if data.get('locked') and changes!={'locked':False}:
        store.fail('LOCKED','Unlock the catalog before changing it.')
    if 'name' in changes and (not isinstance(changes['name'],str) or not 1<=len(changes['name'].strip())<=200): story.invalid('Invalid version name.')
    if any(type(changes[k]) is not bool for k in ('locked','archived') if k in changes): story.invalid('Catalog flags must be boolean.')
    data.update(changes);data.update(catalogVersion=data['catalogVersion']+1,updatedAt=story.now())
    store._replace(conn,scope,'writing_version',version_id,data)
    return data|{'clientMutationId':body['clientMutationId'],'savedAt':data['updatedAt']}


def create_branch(conn, scope, body):
    store.fields(body,{'sourceRef','name','expectedSourceHash'},{'sourceRef','name','expectedSourceHash'})
    source=store.resolve_ref(conn,scope,body['sourceRef'])
    if source['docHash']!=body['expectedSourceHash']: store.fail()
    if body['sourceRef']['kind']=='working' and (not source['structure']['initialized'] or source['structure']['stale']):
        structure.initialize(conn,scope,source['docHash'])
        source=store.resolve_ref(conn,scope,body['sourceRef'])
    name=body['name']
    if not isinstance(name,str) or not 1<=len(name.strip())<=200: story.invalid('A branch name is required.')
    identifier='wbr_'+uuid.uuid4().hex
    return store.insert_record(conn,scope,'writing_branch',identifier,{'branchId':identifier,'name':name,'locked':False,'archived':False,
        'doc':source['doc'],'docHash':source['docHash'],'structure':source['structure'],'structureHash':source['structureHash'],
        'composition':source.get('composition',{}),'baseFingerprint':{'sourceRef':body['sourceRef'],'docHash':source['docHash']}})


def save_branch(conn, scope, branch_id, body):
    store.fields(body,{'baseVersion','clientMutationId','doc','structure','composition','name','locked','archived'},{'baseVersion','clientMutationId'})
    current=store.get_record(conn,scope,'writing_branch',branch_id)
    changes={k:copy.deepcopy(v) for k,v in body.items() if k in ('name','locked','archived')}
    if 'name' in changes and (not isinstance(changes['name'],str) or not 1<=len(changes['name'].strip())<=200): story.invalid('Invalid branch name.')
    if any(type(changes[k]) is not bool for k in ('locked','archived') if k in changes): story.invalid('Branch flags must be boolean.')
    if 'doc' in body:
        doc=store.checked_doc(body['doc'],scope.slug)
        proposed=structure.reconcile_structure(doc,current.get('structure'))
        changes|={'doc':doc,'docHash':store.doc_hash(doc),'structure':proposed,'structureHash':proposed['structureHash'],'composition':store.composition(doc)}
    elif 'structure' in body or 'composition' in body:
        story.invalid('Structure/composition content requires the branch document.')
    data=store.cas_record(conn,scope,'writing_branch',branch_id,base_version=body['baseVersion'],changes=changes)
    return {k:v for k,v in data.items() if k!='beforeCheckpoint'}|{'clientMutationId':body['clientMutationId'],'savedAt':data['updatedAt']}


def compare(conn, scope, body):
    store.fields(body,{'leftRef','rightRef','expectedHashes'},{'leftRef','rightRef','expectedHashes'})
    left=store.resolve_ref(conn,scope,body['leftRef']);right=store.resolve_ref(conn,scope,body['rightRef'])
    expected=body['expectedHashes'];store.fields(expected,{'left','right'},{'left','right'})
    if expected!={'left':left['docHash'],'right':right['docHash']}: store.fail()
    lsc=left.get('structure',{}).get('scenes',[]);rsc=right.get('structure',{}).get('scenes',[])
    lm={s['sceneKey']:s for s in lsc};rm={s['sceneKey']:s for s in rsc}
    changes=[]
    for key in list(lm)+[k for k in rm if k not in lm]:
        a,b=lm.get(key),rm.get(key)
        state='added' if a is None else 'removed' if b is None else 'modified' if a.get('contentHash')!=b.get('contentHash') else 'moved' if a['order']!=b['order'] else 'unchanged'
        changes.append({'sceneKey':key,'state':state,'left':a,'right':b,'mapping':'unresolved' if (a or b).get('mapping')=='unresolved' else 'exact'})
    # Block aligned comparison is linear/bounded even for repetitive half-million-character scripts.
    def nodes(source): return {structure.bid(n):n for n in source['doc'].get('content',[])}
    ln,rn=nodes(left),nodes(right)
    blocks=[{'bid':key,'left':ln.get(key),'right':rn.get(key),'state':'added' if key not in ln else 'removed' if key not in rn else 'modified'}
        for key in list(ln)+[k for k in rn if k not in ln] if ln.get(key)!=rn.get(key)]
    return {'leftHash':left['docHash'],'rightHash':right['docHash'],'scenes':changes,'blocks':blocks,'equal':left['docHash']==right['docHash']}


def build_preview(conn, scope, body):
    kind=body.get('kind')
    allowed={'kind','sourceRef','expectedSourceHash','targetDocHash','sceneKeys','whole'}
    if kind=='adaptation': allowed|={'targetScenes','breakdownMode','mediumLens','genreLens','choiceTrace'}
    store.fields(body,allowed,{'kind','sourceRef','expectedSourceHash','targetDocHash'})
    source=store.resolve_ref(conn,scope,body['sourceRef'])
    target=store.resolve_ref(conn,scope,{'kind':'working'})
    if source['docHash']!=body['expectedSourceHash'] or target['docHash']!=body['targetDocHash']: store.fail('PREVIEW_STALE')
    if not target['structure']['initialized'] or target['structure']['stale']: store.fail('MAPPING_REQUIRED','Initialize the current script structure first.')
    fingerprints=[{'sourceRef':body['sourceRef'],'docHash':source['docHash'],'structureHash':source['structureHash'],
        'version':source['version'],'compositionHash':source['compositionHash']}]
    candidate=None
    if kind=='adaptation':
        if body['sourceRef'].get('kind')!='source': story.invalid('Adaptation requires your saved idea or novel source.')
        from project_docs.story_adaptation import adapt_source_to_script, screenplay_markdown
        from project_docs import markdown_import
        composition=source.get('composition',{})
        medium=body.get('mediumLens',composition.get('mediumLens'));genre=body.get('genreLens',composition.get('genreLens'))
        breakdown=body.get('breakdownMode','auto')
        if breakdown not in story.BREAKDOWN_MODES: story.invalid('Unknown breakdown mode.')
        content=adapt_source_to_script(doc_text(source['doc']),body['sourceRef']['mode'],body.get('targetScenes',3),
            medium_lens=medium,genre_lens=genre,choice_trace=body.get('choiceTrace',composition.get('choiceTrace')))
        doc,_=markdown_import.markdown_to_doc(screenplay_markdown(content),tab_keys=set(),image_src=lambda _:None)
        doc=store.checked_doc(doc,scope.slug)
        proposed_structure=structure.reconcile_structure(doc,{})
        candidate='wbr_'+uuid.uuid4().hex
        candidate_record={'branchId':candidate,'name':'Adaptation candidate','doc':doc,
            'docHash':store.doc_hash(doc),'structure':proposed_structure,'structureHash':proposed_structure['structureHash'],
            'composition':store.composition(doc),'locked':False,'archived':False,'baseFingerprint':fingerprints[0]}
        fingerprints.append({'sourceRef':{'kind':'branch','id':candidate},'docHash':store.doc_hash(doc),'structureHash':proposed_structure['structureHash'],
            'version':1,'compositionHash':store.hash_value(store.composition(doc))})
        source={'doc':doc,'docHash':store.doc_hash(doc),'structure':proposed_structure,'structureHash':proposed_structure['structureHash']}
        whole=True
    elif kind=='promotion':
        if body['sourceRef']['kind'] not in ('branch','version'): story.invalid('Promote a screenplay branch or snapshot.')
        whole=body.get('whole',False)
        if type(whole) is not bool: story.invalid('whole must be boolean.')
    else: story.invalid('Unknown adoption preview kind.')
    keys=body.get('sceneKeys',[])
    if not isinstance(keys,list) or len(set(keys))!=len(keys): story.invalid('sceneKeys must contain unique stable keys.')
    if not whole and not keys: story.invalid('Choose whole:true or at least one scene.')
    if whole and keys: story.invalid('Choose whole or sceneKeys, not both.')
    if whole:
        doc=copy.deepcopy(source['doc']);proposed_structure=copy.deepcopy(source['structure'])
        actions=[{'actionId':'whole','kind':'adopt_whole'}]
    else:
        sm={s['sceneKey']:s for s in source['structure'].get('scenes',[])}
        tm={s['sceneKey']:s for s in target['structure']['scenes']}
        if set(keys)-(set(sm)|set(tm)): store.fail('MAPPING_REQUIRED','Select existing source or target scene keys.')
        doc=copy.deepcopy(target['doc']);proposed_structure=None
        actions=[{'actionId':key,'kind':'adopt_scene' if key in sm and key in tm else 'add_scene' if key in sm else 'remove_scene','sceneKey':key} for key in keys]
    result={'sourceFingerprints':fingerprints,'targetFingerprints':[{'sourceRef':{'kind':'working'},'docHash':target['docHash'],'structureHash':target['structureHash']}],
        'productionInputsHash':target['productionInputsHash'],
        'allowedActions':actions,'proposedChanges':{'doc':doc,'structure':proposed_structure,'sourceDoc':source['doc'],
            'sourceStructure':source['structure'],'whole':whole},
        'warnings':['Unaligned selected source scenes are added at the end, never guessed as replacements.'] if any(a['kind']=='add_scene' for a in actions) else []}
    if candidate:
        result['candidateBranchId']=candidate
        result['_candidateRecord']=candidate_record
    return result


def apply_preview(conn, scope, preview, selection):
    from project_docs import writing_service as service
    before=store.resolve_ref(conn,scope,{'kind':'working'})
    proposed=preview['proposedChanges'];doc=copy.deepcopy(proposed['doc'])
    if not proposed['whole']:
        selected={a['actionId'] for a in selection['actions']}
        source_nodes={structure.bid(n):n for n in proposed['sourceDoc']['content']}
        source_scenes={s['sceneKey']:s for s in proposed['sourceStructure']['scenes']}
        target_scenes={s['sceneKey']:s for s in before['structure']['scenes']}
        replacements={};removed=set();additions=[]
        for key in [a['actionId'] for a in preview['allowedActions'] if a['actionId'] in selected]:
            src=source_scenes.get(key);tgt=target_scenes.get(key)
            old=([tgt.get('headingBid')]+tgt['blockBids']) if tgt else []
            new=([src.get('headingBid')]+src['blockBids']) if src else []
            nodes=[copy.deepcopy(source_nodes[b]) for b in new if b]
            if tgt:
                first=next((b for b in old if b),None)
                replacements[first]=nodes
                removed.update(old)
            else:
                additions.extend(nodes)
        content=[]
        for node in doc['content']:
            key=structure.bid(node)
            if key in replacements: content.extend(replacements[key])
            elif key not in removed: content.append(node)
        doc['content']=content+additions
    version_id='wver_'+uuid.uuid4().hex
    store.insert_snapshot(conn,scope,version_id,snapshot_of(scope,before),name='Before adoption',created_by=scope.actor_id)
    service.replace_working(conn,scope,doc,expected_hash=before['docHash'])
    actual=repo.get_tab(conn,scope.slug,scope.episode['tabKey'])['doc']
    previous=copy.deepcopy(proposed['sourceStructure'] if proposed['whole'] else before['structure'])
    if not proposed['whole']:
        known={s['sceneKey'] for s in previous['scenes']}
        previous['scenes'].extend(copy.deepcopy(s) for s in proposed['sourceStructure'].get('scenes',[])
            if s['sceneKey'] in selected and s['sceneKey'] not in known)
    reconciled=structure.reconcile_structure(actual,previous)
    structure.persist(conn,scope,reconciled)
    return {'docHash':store.doc_hash(actual),'beforeVersionId':version_id,'candidateBranchId':preview.get('candidateBranchId'),'savedAt':story.now()}


def confirm_baseline(conn, scope, *, expected_doc_hash, extracted=False):
    store.reauthorize(conn,scope,write=True)
    store.lock_project(conn,scope)
    repo.get_tab_for_update(conn,scope.slug,scope.episode['tabKey'])
    ep=story.episode(conn,scope.episode_id)
    current=store.resolve_ref(conn,scope,{'kind':'working'})
    if current['docHash']!=expected_doc_hash: store.fail('PREVIEW_STALE')
    if not doc_text(current['doc']).strip(): story.invalid('Confirm a nonempty screenplay.')
    if ep.get('confirmedHash')!=story.digest(doc_text(current['doc'])):
        store.fail('CONFLICT','The historical confirmed screenplay is not retained; extract the current screenplay first.')
    # extracted is trusted internal evidence only. Historical exact-hash baselines can be backfilled.
    existing=ep.get('productionScriptVersionId')
    if existing:
        saved=store.get_record(conn,scope,'writing_version',existing)
        if saved['snapshot']['docHash']==current['docHash'] and saved['snapshot'].get('productionInputsHash')==current['productionInputsHash']:
            return saved
    if not current['structure']['initialized'] or current['structure']['stale']:
        structure.initialize(conn,scope,expected_doc_hash)
        current=store.resolve_ref(conn,scope,{'kind':'working'})
    identifier='wver_'+uuid.uuid4().hex
    data=store.insert_snapshot(conn,scope,identifier,snapshot_of(scope,current),name='Production baseline',created_by=scope.actor_id)
    data.update(locked=True,productionPinned=True)
    store._replace(conn,scope,'writing_version',identifier,data)
    ep['productionScriptVersionId']=identifier
    story.store(conn,scope.episode_id,'episode',ep,scope.slug)
    return data
