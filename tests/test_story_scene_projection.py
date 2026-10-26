"""C1：純記憶體場次／拍點投影，以及真正 JS handoff 跨模組回歸；不使用 DB。"""
import copy
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from project_docs import story_openapi as story, story_estimates as planner
from project_docs import writing_structure as structure, writing_store

EP = {'slug': 'projection', 'episodeIndex': 1, 'episodeId': 'ep_projection_01'}
ACTION = '@CAST-01 faces the lens at @SET-07, fighting back tears.'
DIALOGUE = '@CAST-02: "Tell me the truth."'


def block(text, bid, kind='paragraph'):
    children = []
    for index, line in enumerate(text.split('\n')):
        if index:
            children.append({'type': 'hardBreak'})
        if line:
            children.append({'type': 'text', 'text': line})
    return {'type': kind, 'attrs': {'bid': bid, 'owner': None, 'created': None,
            **({'level': 2} if kind == 'heading' else {})}, 'content': children}


def document(*nodes):
    return {'type': 'doc', 'content': list(nodes)}


class SceneProjectionPureTests(unittest.TestCase):
    def test_heading_and_paragraph_keep_inline_body_out_of_scene_title(self):
        for kind in ('heading', 'paragraph'):
            with self.subTest(kind=kind):
                doc = document(block('Scene 01: Room\n'+ACTION+'\n'+DIALOGUE, 'heading1', kind))
                before = copy.deepcopy(doc)
                scenes = story.scenes_of_doc(EP, doc)
                print(json.dumps({'case': kind, 'scenes': scenes,
                                  'beats': planner.beat_plans(scenes, 'auto')}, ensure_ascii=False))
                self.assertEqual(scenes[0]['title'], 'Scene 01: Room')
                self.assertEqual(scenes[0]['content'], ACTION+'\n'+DIALOGUE)
                self.assertEqual(planner.beat_plans(scenes, 'auto')[0][1], [ACTION, DIALOGUE])
                self.assertEqual(doc, before, '文字投影不可變更原始文件')

    def test_inline_scene_looking_lines_keep_order_and_breaks_but_never_partition(self):
        body = ACTION+'\n\nScene 99: quoted words, not a boundary\n'+DIALOGUE+'\n'
        for kind in ('heading', 'paragraph'):
            with self.subTest(kind=kind):
                doc = document(block('Scene 01: Room\n'+body, 'heading1', kind),
                               block('The next block stays last.', 'body0001'))
                scenes = story.scenes_of_doc(EP, doc)
                self.assertEqual(len(scenes), 1)
                self.assertEqual(scenes[0]['title'], 'Scene 01: Room')
                self.assertEqual(scenes[0]['content'], body+'\n\nThe next block stays last.')
                stable = structure.reconcile_structure(doc, {})
                self.assertEqual(len(stable['scenes']), 1)
                self.assertEqual(stable['scenes'][0]['headingBid'], 'heading1')
                self.assertEqual(stable['scenes'][0]['blockBids'], ['body0001'])
                self.assertEqual(len(structure.sections(doc)), len(scenes))

    def test_normal_block_scenes_and_title_only_fallback_still_work(self):
        doc = document(block('Scene 01: Room', 'heading1', 'heading'),
                       block(ACTION+'\n'+DIALOGUE, 'body0001'),
                       block('Scene 02: Empty', 'heading2'))
        scenes = story.scenes_of_doc(EP, doc)
        self.assertEqual([s['title'] for s in scenes], ['Scene 01: Room', 'Scene 02: Empty'])
        self.assertEqual([s['content'] for s in scenes], [ACTION+'\n'+DIALOGUE, ''])
        self.assertEqual([beats for _, beats in planner.beat_plans(scenes, 'auto')],
                         [[ACTION, DIALOGUE], ['Scene 02: Empty']])
        self.assertEqual([s['sceneIndex'] for s in scenes], [1, 2])
        self.assertEqual([s['sceneId'] for s in scenes], ['sc_projection_01_S01', 'sc_projection_01_S02'])
        self.assertEqual(story.scenes_of_doc(EP, document()), [])
        plain = story.scenes_of_doc(EP, document(block(ACTION, 'body0001')))
        self.assertEqual((plain[0]['title'], plain[0]['content']), ('Scene 01', ACTION))

    def test_repeated_beats_keep_slate_ownership_without_certifying_exact_origin(self):
        doc = document(block('Scene 01: Room', 'heading1'), block(ACTION, 'body0001'),
                       block(DIALOGUE, 'body0002'), block(ACTION, 'body0003'))
        scenes = story.scenes_of_doc(EP, doc)
        beats = planner.beat_plans(scenes, 'auto')[0][1]
        self.assertEqual(beats, [ACTION, DIALOGUE, ACTION])
        stable = structure.reconcile_structure(doc, {})
        stable['initialized'] = True
        stable['scenes'][0]['legacySceneId'] = scenes[0]['sceneId']
        key = stable['scenes'][0]['sceneKey']
        shot = {'shotId': 'repeat', 'tabKey': 'cinema-studio', 'sceneId': scenes[0]['sceneId'],
                'storyOrigin': {'mapping': 'ambiguous', 'sceneKeys': [key], 'beatKeys': []}}
        before = copy.deepcopy(shot)
        # 只替代 scope／structure 讀取邊界；不建立或連接任何 DB。
        with patch.object(writing_store, 'scope_for', return_value=object()), \
             patch.object(structure, 'read_structure', return_value=stable):
            claim = story.scene_claim(object(), object(), EP)
            self.assertEqual(claim(shot, scenes[0]), 'own')
            self.assertIsNone(claim(shot | {'detachedScene': {'state': 'ambiguous'}}, scenes[0]))
        self.assertEqual(structure.shot_relationship(stable, shot), ([], 'ambiguous', 'ambiguous'))
        slate = [shot | {'shotId': str(i)} for i in range(3)]
        steps, surplus = planner.scene_steps(scenes[0], beats, slate, claim=claim)
        self.assertEqual([action for action, *_ in steps], ['keep', 'keep', 'keep'])
        self.assertEqual(surplus, [])
        self.assertEqual(shot, before)

    def test_actual_js_persist_start_handoff_doc_reaches_python_scene_and_beat_planner(self):
        # 非複製 plainDocument：呼叫真 helper，捕捉它實際送出的 atomic put node。
        js = r'''
import {persistStartHandoff} from './ui/src/writing/writingStartHandoff.js';
const text = 'Scene 01: Room\r\n@CAST-01 faces the lens at @SET-07, fighting back tears.\r\n@CAST-02: "Tell me the truth."';
let saved, checkpoints=[];
const transport=async(tail,method='GET',body)=>{
 if(tail==='workspace'&&method==='GET')return {doc:{type:'doc',content:[]},docHash:'empty',revision:1,structure:{initialized:true}};
 if(tail==='script/ops'&&method==='POST') {
  if(checkpoints.at(-1).stage!=='working-save')throw new Error('缺少 mutation 前 checkpoint');
  saved={type:'doc',content:[body.ops[0].node]};
  return {doc:saved,docHash:'saved',version:2,clientMutationId:body.clientMutationId,conflicts:[]};
 }
 throw new Error('未知合成路由 '+tail);
};
const ref=await persistStartHandoff({transport,start:{mode:'script',text},actorId:'projection-actor',idempotencyKey:'projection-key',onCheckpoint:plan=>checkpoints.push(plan)});
console.log(JSON.stringify({doc:saved,ref,stage:checkpoints.at(-1).stage}));
'''
        result = subprocess.run(['node', '--input-type=module', '-e', js],
                                cwd=Path(__file__).resolve().parents[1], capture_output=True,
                                text=True, encoding='utf-8', timeout=15, check=True)
        generated = json.loads(result.stdout)
        self.assertEqual(generated['ref'], {'kind': 'working'})
        self.assertEqual(generated['stage'], 'done')
        self.assertEqual(len(generated['doc']['content']), 1)
        self.assertEqual(generated['doc']['content'][0]['type'], 'paragraph')
        scenes = story.scenes_of_doc(EP, generated['doc'])
        plans = planner.beat_plans(scenes, 'auto')
        print(json.dumps({'case': 'actual-persistStartHandoff', 'scenes': scenes, 'plans': plans}, ensure_ascii=False))
        self.assertEqual(scenes[0]['title'], 'Scene 01: Room')
        self.assertEqual(scenes[0]['content'], ACTION+'\n'+DIALOGUE)
        self.assertEqual(plans[0][1], [ACTION, DIALOGUE])
        self.assertEqual(len(scenes), len(structure.sections(generated['doc'])))


if __name__ == '__main__':
    unittest.main()
