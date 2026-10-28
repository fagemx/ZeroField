"""R44-3: one scene-heading rule, a pasted screenplay that keeps its scenes, and the same scene count downstream.

Pure in-memory checks plus the actual browser start helper run in Node; no DB, model or provider.
"""
import json
from pathlib import Path
import subprocess
import unittest

from project_docs import scene_headings, story_adaptation, story_estimates as planner, story_openapi as story
from project_docs import writing_files, writing_structure as structure
from project_docs.doc_schema import doc_text

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((ROOT / 'tests' / 'fixtures' / 'scene_heading_cases.json').read_text(encoding='utf-8'))
EP = {'slug': 'r44', 'episodeIndex': 1, 'episodeId': 'ep_r44_01'}
# The R44 walk: a numbered three-scene screenplay with a title page, cues and blank-line paragraphs.
SPILLWAY = ('SPILLWAY\nan original short\n\n'
            '1. INT. CONTROL ROOM - NIGHT\n'
            'Rain hammers the glass. NORA VESK (40s) faces the gauges, jaw tight.\n\n'
            'NORA\n"The gate is jammed."\n\n'
            '2. EXT. DAM CREST - CONTINUOUS\n'
            'Wind. ELI VESK (20s) grips the rail and looks straight at us.\n\n'
            'ELI\n"Then we open it by hand."\n\n'
            '3. EXT. SPILLWAY - NIGHT\n'
            'Eli runs toward us as the water rises.')
TITLES = ['1. INT. CONTROL ROOM - NIGHT', '2. EXT. DAM CREST - CONTINUOUS', '3. EXT. SPILLWAY - NIGHT']


def start_document(text, limit_kind='working'):
    """The blocks the real ui/src/writing/writingStartHandoff.js submits for this text."""
    js = r'''
import {readFileSync} from 'node:fs';
import {persistStartHandoff, startDocument, START_BLOCK_LIMIT} from './ui/src/writing/writingStartHandoff.js';
const [text, kind] = JSON.parse(readFileSync(0, 'utf8'));
if (kind !== 'working') {
  console.log(JSON.stringify({doc:startDocument(text, 'f'.repeat(64), START_BLOCK_LIMIT)}));
} else {
  let saved;
  const transport = async (tail, method = 'GET', body) => {
    if (tail === 'workspace') return {doc:{type:'doc', content:[]}, docHash:'empty', revision:1, structure:{initialized:true}};
    if (tail === 'script/ops') {
      saved = {type:'doc', content:body.ops.map(op => op.node)};
      return {doc:saved, docHash:'saved', version:2, clientMutationId:body.clientMutationId, conflicts:[]};
    }
    throw new Error('unexpected ' + tail);
  };
  await persistStartHandoff({transport, start:{mode:'script', text}, actorId:'r44', idempotencyKey:'r44-start', onCheckpoint:() => true});
  console.log(JSON.stringify({doc:saved}));
}
'''
    result = subprocess.run(['node', '--input-type=module', '-e', js], cwd=ROOT, input=json.dumps([text, limit_kind]),
                            capture_output=True, text=True, encoding='utf-8', timeout=30, check=True)
    return json.loads(result.stdout)['doc']


class SceneHeadingRuleTests(unittest.TestCase):
    def test_shared_fixture_headings_and_prose(self):
        for line in CASES['headings']:
            with self.subTest(line=line):
                self.assertTrue(scene_headings.is_heading(line))
        for line in CASES['prose']:
            with self.subTest(line=line):
                self.assertFalse(scene_headings.is_heading(line))

    def test_every_reader_uses_the_shared_rule(self):
        self.assertIs(structure.HEADING, scene_headings.HEADING)
        self.assertIs(story_adaptation.HEADING, scene_headings.HEADING_LINES)
        numbered = '1. INT. CONTROL ROOM - NIGHT\nNora waits.\n2. EXT. CREST - NIGHT\nEli runs.'
        self.assertEqual(story_adaptation.source_mode(numbered), 'script')
        self.assertEqual([s['title'] for s in story.scene_sections(numbered)],
                         ['1. INT. CONTROL ROOM - NIGHT', '2. EXT. CREST - NIGHT'])
        sections = writing_files.section_preview(numbered + '\n', 'script')
        self.assertEqual([s['title'] for s in sections], ['1. INT. CONTROL ROOM - NIGHT', '2. EXT. CREST - NIGHT'])
        self.assertIn('## 1. INT. CONTROL ROOM - NIGHT', story_adaptation.screenplay_markdown(numbered))

    def test_titles_and_scene_names(self):
        self.assertEqual(scene_headings.heading_title('  ## 3. INT. STAIRWELL - NIGHT  '), '3. INT. STAIRWELL - NIGHT')
        for line, name in [('1. INT. DAM - NIGHT', 'INT. DAM - NIGHT'), ('12A. Scene 3: Dam', 'Dam'),
                           ('Scene 12A - Roof', 'Roof'), ('## Scene 02: Dawn', 'Dawn'), ('場景一：觀測站', '觀測站'),
                           ('3. 場景三：碼頭', '碼頭'), ('#3 INT. STAIRWELL', 'INT. STAIRWELL'), ('Scene 01', ''),
                           ('INT./EXT. CAR - MOVING', 'INT./EXT. CAR - MOVING')]:
            with self.subTest(line=line):
                self.assertEqual(scene_headings.scene_name(line), name)
        adapted = story_adaptation.adapt_source_to_script(SPILLWAY, 'script')
        self.assertEqual([line for line in adapted.splitlines() if line.startswith('## ')],
                         ['## Scene 01: INT. CONTROL ROOM - NIGHT', '## Scene 02: EXT. DAM CREST - CONTINUOUS',
                          '## Scene 03: EXT. SPILLWAY - NIGHT'])
        self.assertIn('SPILLWAY\nan original short\n\n## Scene 01:', adapted, 'blank lines before a heading survive')

    def test_heading_block_with_a_hard_break_is_titled_by_its_first_line(self):
        heading = {'type': 'paragraph', 'attrs': {'bid': 'head0001'}, 'content': [
            {'type': 'text', 'text': '1. INT. CONTROL ROOM - NIGHT'}, {'type': 'hardBreak'}, {'type': 'text', 'text': 'Nora waits.'}]}
        stable = structure.reconcile_structure({'type': 'doc', 'content': [heading]}, {})
        self.assertEqual(stable['scenes'][0]['title'], '1. INT. CONTROL ROOM - NIGHT')
        self.assertEqual(story.scenes_of_doc(EP, {'type': 'doc', 'content': [heading]})[0]['title'], '1. INT. CONTROL ROOM - NIGHT')


class PastedScreenplayTests(unittest.TestCase):
    def test_pasted_numbered_screenplay_keeps_three_scenes_everywhere(self):
        doc = start_document(SPILLWAY)
        texts = [doc_text({'content': [node]}) for node in doc['content']]
        self.assertEqual(texts, ['SPILLWAY\nan original short', TITLES[0],
                                 'Rain hammers the glass. NORA VESK (40s) faces the gauges, jaw tight.',
                                 'NORA\n"The gate is jammed."', TITLES[1],
                                 'Wind. ELI VESK (20s) grips the rail and looks straight at us.',
                                 'ELI\n"Then we open it by hand."', TITLES[2], 'Eli runs toward us as the water rises.'])
        self.assertTrue(all(node['type'] == 'paragraph' for node in doc['content']))
        # Writing structure (scene list and Split scene): one scene per heading block, titled by the heading line.
        stable = structure.reconcile_structure(doc, {})
        self.assertEqual([s['title'] for s in stable['scenes']], TITLES)
        self.assertEqual([len(s['blockBids']) for s in stable['scenes']], [2, 2, 1])
        # Crew shot breakdown and storyboard build read story.scenes, i.e. scenes_of_doc.
        scenes = story.scenes_of_doc(EP, doc)
        self.assertEqual([s['title'] for s in scenes], TITLES)
        plans = planner.beat_plans(scenes, 'auto')
        self.assertEqual([len(beats) for _, beats in plans], [2, 2, 1])
        self.assertEqual(plans[0][1][1], 'NORA\n"The gate is jammed."')
        # Story import (PUT script) of the same text, the text-based scene reader and the rule adaptation agree.
        imported = story.scenes_of_doc(EP, story.script_doc(EP['slug'], SPILLWAY))
        self.assertEqual([s['title'] for s in imported], TITLES)
        self.assertEqual(len(story.scene_sections(doc_text(doc))), 3)
        self.assertEqual(story_adaptation.adapt_source_to_script(doc_text(doc), 'script').count('\n## Scene '), 3)
        self.assertEqual(sum(len(story_adaptation.scene_shot_beats(s['content'], 'scene')) for s in scenes), 3)

    def test_large_screenplays_keep_every_heading_and_all_text(self):
        def script(count):
            return 'TITLE PAGE\n\n' + '\n\n'.join(
                f'{i}. INT. ROOM {i} - DAY\nLine one of {i}.\nLine two of {i}.\n\nLine three of {i}.' for i in range(1, count + 1))
        # 40 scenes fit block for block; 150 in one 200-op save fold later bodies into their heading block;
        # a branch or source save (1,000 blocks) keeps every paragraph of 150 scenes.
        for count, kind, blocks in [(40, 'working', 121), (150, 'working', 200), (150, 'branch', 451)]:
            with self.subTest(count=count, kind=kind):
                text = script(count)
                doc = start_document(text, kind)
                self.assertEqual(len(doc['content']), blocks)
                stable = structure.reconcile_structure(doc, {})
                self.assertEqual(len(stable['scenes']), count)
                self.assertEqual([s['title'] for s in stable['scenes']][-1], f'{count}. INT. ROOM {count} - DAY')
                self.assertEqual(len(story.scenes_of_doc(EP, doc)), count)
                # No text is dropped; only blank lines become block boundaries.
                self.assertEqual(doc_text(doc).replace('\n\n', '\n'), text.replace('\n\n', '\n'))


if __name__ == '__main__':
    unittest.main()
