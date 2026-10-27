"""SPEC_20 R16: the crew's structured context tools (read_episode, read_scene, read_shot, read_cast, list_takes).

Rule tests need nothing; the story tests seed a production in PostgreSQL (OPENBENCH_TEST_DB_URI) and call the tools
through tools.call, the boundary every transport (internal crew, MCP) uses.
"""
import copy
import json
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from project_assistant import agent_registry, context_tools, store, studio_tools, tool_registry, tool_specs, tools
from project_docs import markdown_import, repository as repo, service, story_openapi as story, story_previs, templates
from project_docs.doc_schema import validate_doc

ROOT = Path(__file__).resolve().parents[1]
CONTEXT = ['read_episode', 'read_scene', 'read_shot', 'read_cast', 'list_takes']
ENVELOPE = ['status', 'data', 'sources', 'warnings', 'limitations', 'hash']
SCRIPT = ("## Scene 01: Observatory\n@CAST-01 enters the observatory and studies the brass dial.\n\n"
          "@CAST-01 turns toward the window as rain hits the glass.\n\n"
          "## Scene 02: Departure\n@CAST-01 leaves through the rain past @CAST-02.")
PLAN = {"set": "observatory", "move": "orbit", "lens": 50, "action": "turnreach", "facing": "console", "mood": "night",
        "seconds": 6, "keys": [[0, [1.4, 1.45, -5.8], [-0.2, 2.75, 0.4]], [96, [-0.75, 1.95, -0.85], [0, 1.3, 0.5]]],
        "mark": [0.5, -1], "turn": 15, "code": "@CAST-01"}
PNG = b'\x89PNG\r\n\x1a\n' + b'\x00' * 32
SECRET = 'a1' * 20  # 40 letters and digits: the page reader's "looks like a password" rule


def mp4(tag):
    return b'\x00\x00\x00\x18ftypisom' + tag.encode() + b'\x00' * 16


class ContextRegistryTests(unittest.TestCase):
    def test_tools_are_declared_read_only_offered_and_granted_to_every_built_in_role(self):
        for name in CONTEXT:
            with self.subTest(name=name):
                tool = tool_registry.get(name)
                self.assertEqual((tool.category, tool.policy, tool.mutating, tool.ui, tool.mcp, tool.console),
                                 ('context', 'auto', False, True, True, True))
                self.assertEqual(tool.grants, tool_registry.BUILTIN_ROLES)
                self.assertTrue(tool.annotations['readOnlyHint'])
                self.assertIs(tools.HANDLERS[name], tool_registry.handler(name))
                self.assertIs(context_tools.HANDLERS[name], tools.HANDLERS[name])
                self.assertNotIn(name, tool_specs.MUTATING_TOOLS)
                self.assertNotIn(name, tool_registry.ANALYSIS_ONLY_DENIED | tool_registry.RACE_DENIED | tool_registry.PRIMARY_ONLY)
                for role in tool_registry.BUILTIN_ROLES:
                    self.assertIn(name, agent_registry.default_tools(role))
        self.assertEqual(list(tool_registry.UI)[-5:], CONTEXT)
        # JSON results bounded and sanitized by their handlers: tools.call neither re-masks nor clips them.
        self.assertEqual(tools._STRUCTURED, frozenset(studio_tools.HANDLERS) | frozenset(CONTEXT))

    def test_arguments_are_validated(self):
        for name, args in [('read_episode', {}), ('read_episode', {'episode_id': 'ep_x_01'}), ('read_scene', {'scene_id': 's'}),
                           ('read_shot', {'shot_id': 'sh', 'include_plan': False}), ('read_cast', {}),
                           ('read_cast', {'asset': 'CAST-01', 'type': 'CHARACTER'}), ('list_takes', {'shot_id': 'sh', 'kind': 'image'})]:
            tool_registry.validate_args(name, args)
        for name, args, message in [('read_scene', {}, 'Unknown or missing tool arguments.'),
                                    ('read_shot', {'shot_id': ''}, 'Invalid tool string length.'),
                                    ('read_shot', {'shot_id': 'sh', 'include_plan': 'yes'}, 'Invalid tool option.'),
                                    ('read_cast', {'type': 'LOCATION'}, 'Invalid tool option.'),
                                    ('list_takes', {'shot_id': 'sh', 'kind': 'audio'}, 'Invalid tool option.'),
                                    ('read_episode', {'episode': 'ep'}, 'Unknown or missing tool arguments.')]:
            with self.subTest(name=name, args=args), self.assertRaises(ValueError) as caught:
                tool_registry.validate_args(name, args)
            self.assertEqual(str(caught.exception), message)

    def test_audit_snapshot_lists_the_tools_for_every_role(self):
        snapshot = json.loads((ROOT / 'tests' / 'fixtures' / 'tool_surface.json').read_text(encoding='utf-8'))
        for role, views in snapshot['roles'].items():
            for view in ('grants', 'internal', 'mcp'):
                with self.subTest(role=role, view=view):
                    self.assertLessEqual(set(CONTEXT), set(views[view]))
        self.assertEqual(snapshot['ui_catalog'][-5:], CONTEXT)

    def test_hash_is_canonical(self):
        self.assertEqual(context_tools.content_hash({'a': 1, 'b': [1, 2]}), context_tools.content_hash({'b': [1, 2], 'a': 1}))
        self.assertNotEqual(context_tools.content_hash({'a': 1}), context_tools.content_hash({'a': 2}))
        self.assertRegex(context_tools.content_hash(None), r'^sha256:[0-9a-f]{64}$')

    def test_sanitize_masks_prose_and_keeps_structure_and_own_urls(self):
        read = context_tools._Read.__new__(context_tools._Read)
        read.slug, read.mode = 'demo', 'mask_numbers'
        own = '/projects/api/demo/assets/pa_' + 'a' * 32
        value = {'shotId': 'sh_demo_b12345', 'description': 'Budget 123456 dollars, key ' + SECRET, 'status': 'Approved',
                 'planRevision': 123456, 'plan': {'keys': [[0, [1.25, 2.5, 3.75]]], 'move': 'orbit'},
                 'selectedVideoUrl': own, 'selectedImageUrl': '/projects/api/other/assets/pa_' + 'b' * 32,
                 'cells': [{'col': 3, 'url': 'https://example.com/clip.mp4'}], 'referenceImages': [own, 'https://x.test/a.png']}
        clean = context_tools._sanitize(value, read)
        self.assertNotIn('123456', clean['description'])
        self.assertNotIn(SECRET, clean['description'])
        self.assertEqual((clean['shotId'], clean['status'], clean['planRevision'], clean['plan']),
                         (value['shotId'], 'Approved', 123456, value['plan']))
        self.assertEqual((clean['selectedVideoUrl'], clean['selectedImageUrl'], clean['cells'][0]['url'], clean['referenceImages']),
                         (own, None, None, [own, None]))
        read.mode = 'full_access'
        self.assertIn('123456', context_tools._sanitize(value, read)['description'])
        self.assertNotIn(SECRET, context_tools._sanitize(value, read)['description'])

    def test_halving_keeps_marked_items_and_reports_the_total(self):
        data = {'takes': [{'n': i, 'selected': i == 7} for i in range(8)]}
        shrink = context_tools._halve(('takes',), 'Takes', 'hint', keep=lambda t: t['selected'])
        self.assertEqual(shrink(data), ('Takes', 'Takes: 5 of 8 shown; hint.'))
        self.assertEqual([t['n'] for t in data['takes']], [0, 1, 2, 3, 7])
        self.assertEqual(shrink(data)[1], 'Takes: 3 of 8 shown; hint.')
        self.assertIsNone(context_tools._halve(('missing',), 'X', 'y')(data))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class ContextToolStoryTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        self.connect = lambda: psycopg.connect(os.environ['OPENBENCH_TEST_DB_URI'])
        self.extra = []
        self.studio(self.slug)
        # As an API-created production: no demo shots on the slate (the lab keeps its demo clip, an unplaced shot).
        tab = repo.get_tab(self.conn, self.slug, 'cinema-studio')
        doc = copy.deepcopy(tab['doc'])
        for table in doc['content']:
            if table.get('type') == 'table':
                table['content'] = table['content'][:1]
        story.save_doc(self.conn, self.me, self.slug, 'cinema-studio', doc)
        self.ep = f'ep_{self.slug}_01'
        self.dispatch('PUT', f'/episodes/{self.ep}/script', {'scriptContent': SCRIPT})
        self.dispatch('POST', f'/episodes/{self.ep}/asset-extractions', {})
        self.dispatch('POST', f'/episodes/{self.ep}/storyboards', {})
        shots = [s for s in story.shots(self.conn, story.episode(self.conn, self.ep)) if s.get('sceneId')]
        self.scene1, self.scene2 = (s['sceneId'] for s in story.scenes(self.conn, story.episode(self.conn, self.ep)))
        self.shots = sorted(shots, key=lambda s: context_tools._natural(s['shotIndex']))
        self.shot1, self.shot2 = self.shots[0]['shotId'], self.shots[1]['shotId']
        self.assertEqual({s['sceneId'] for s in self.shots[:2]}, {self.scene1})
        cast = {a['assetCode']: a for a in story.assets(self.conn, story.episode(self.conn, self.ep))}
        self.cast01 = cast['CAST-01']
        story_previs.put(self.conn, self.slug, self.shot1, PLAN, 0, self.actor)
        self.dispatch('POST', f"/assets/{self.cast01['assetId']}/variants",
                      {'name': 'Night coat', 'key': 'night', 'prompt': 'rain-dark longcoat', 'kind': 'OUTFIT'})
        self.image = self.asset(PNG, 'image/png')
        story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', self.cast01['rowId'], {3: f'[Image]({self.image})'})
        self.take_a, self.take_b, self.pending = (self.asset(mp4(tag), 'video/mp4') for tag in ('take-a', 'take-b', 'pending'))
        for url in (self.take_a, self.take_b):
            story.store(self.conn, 'ca_' + uuid.uuid4().hex, 'candidate', {'entityId': self.shot1, 'kind': 'video', 'url': url}, self.slug)
        _, row = story.find_row(self.conn, self.shot1, 'shot')
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', row['rid'], {5: f'[Video]({self.take_b})'})
        self.grade(self.take_b, score=62, passed=False, issues=['Wardrobe drifts in frame 6'], retakePrompt='Hold the coat. @CAST-01')
        self.grade(self.pending, score=91, passed=True)
        agent_registry.ensure_default_agents(self.conn, self.slug)
        self.conn.commit()
        self.ctx = tools.ToolContext(self.connect, self.slug, self.me, Path('.'), None, agent_key='sheet_ops')

    def tearDown(self):
        import test_execution as execution_fixture
        self.conn.rollback()
        from psycopg import sql
        with self.conn.cursor() as cur:  # an extra production goes the way the fixture removes its own
            cur.execute("SELECT table_name FROM information_schema.columns WHERE table_schema='projectops' AND column_name='project_slug'")
            tables = [r[0] for r in cur.fetchall() if r[0] not in ('agent_resource_revision', 'agent_usage_ledger')]
            for slug in self.extra:
                for name in tables:
                    cur.execute(sql.SQL('DELETE FROM projectops.{} WHERE project_slug=%s').format(sql.Identifier(name)), (slug,))
                cur.execute('DELETE FROM projectops.project WHERE slug=%s', (slug,))
        self.conn.commit()
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    # ---------- seeding ----------

    def studio(self, slug):
        for key, title, surface, md in templates.tab_specs('zerofield_studio', 'Context Test', ''):
            doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
            doc, _ = validate_doc(doc, slug=slug)
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, slug, key=key, title=title, parent_key=None, doc=doc, actor_id=self.actor, surface_type=surface)

    def dispatch(self, method, path, body):
        result = story.dispatch(self.conn, self.me, method, path, body, {}, [])
        self.conn.commit()
        return result

    def asset(self, data, content_type):
        return f'/projects/api/{self.slug}/assets/' + repo.put_asset(self.conn, self.slug, data=data, content_type=content_type, actor_id=self.actor)

    def grade(self, url, **card):
        from project_assistant import take_grader
        asset_id = url.rsplit('/', 1)[1]
        key = take_grader.record_id(self.shot1, asset_id)
        story.store(self.conn, key, take_grader.KIND, {
            'gradeId': key, 'shotId': self.shot1, 'assetId': asset_id, 'assetUrl': url, 'status': 'graded', 'auto': False,
            'requestedBy': self.actor, 'requestedAt': '2026-10-27T09:00:00+00:00', 'gradedAt': '2026-10-27T09:05:00+00:00',
            'model': 'qwen3.8:27b', 'issues': [], 'feedback': 'Reads well.', 'retakePrompt': '', **card}, self.slug)

    def call(self, name, args, ctx=None):
        result = json.loads(tools.call(ctx or self.ctx, name, args))
        self.assertEqual(list(result), ENVELOPE)
        self.assertEqual(result['hash'], context_tools.content_hash(result['data']))
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False, separators=(',', ':'))), context_tools.MAX_CHARS)
        return result

    def audits(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT target, detail FROM projectops.audit_log WHERE project_slug=%s AND action=%s ORDER BY id",
                        (self.slug, context_tools.AUDIT_ACTION))
            rows = cur.fetchall()
        self.conn.rollback()
        return rows

    def set_cell(self, shot, column, value):
        _, row = story.find_row(self.conn, shot, 'shot')
        story.mutate_row(self.conn, self.me, self.slug, row['tabKey'], row['rid'], {column: value})
        self.conn.commit()

    # ---------- each tool ----------

    def test_read_episode_lists_scenes_with_their_shots(self):
        result = self.call('read_episode', {})
        self.assertEqual(result['status'], 'ok')
        data = result['data']
        self.assertEqual((data['episode']['episodeId'], data['episode']['scriptConfirmed']), (self.ep, True))
        self.assertEqual([s['sceneId'] for s in data['scenes']], [self.scene1, self.scene2])
        first = data['scenes'][0]
        self.assertEqual([s['shotId'] for s in first['shots']], [self.shot1, self.shot2])
        self.assertEqual((first['shots'][0].get('plan'), first['shots'][0].get('take')), (True, True))
        self.assertNotIn('plan', first['shots'][1])
        self.assertIn('brass dial', first['excerpt'])
        self.assertEqual([s['tabKey'] for s in data['unplacedShots']], ['openjutsu-lab'])  # the lab's demo clip
        self.assertEqual(data['episodes'][0]['episodeId'], self.ep)
        self.assertIn('CAST-02', data['missingAssetCodes'])
        self.assertEqual(data['counts']['withPlan'], 1)
        revisions = {t['key']: t['revision'] for t in repo.list_tabs(self.conn, self.slug)}
        self.conn.rollback()
        self.assertIn({'kind': 'tab', 'id': 'cinema-studio', 'revision': revisions['cinema-studio']}, result['sources'])
        self.assertIn({'kind': 'episode', 'id': self.ep}, result['sources'])
        self.assertEqual(self.call('read_episode', {'episode_id': self.ep})['hash'], result['hash'])

    def test_read_scene_has_its_text_neighbours_shots_and_cast(self):
        data = self.call('read_scene', {'scene_id': self.scene1})['data']
        self.assertIn('rain hits the glass', data['scene']['content'])
        self.assertEqual((data['previousSceneId'], data['nextSceneId']), (None, self.scene2))
        self.assertEqual([s['shotId'] for s in data['shots']], [self.shot1, self.shot2])
        self.assertEqual(data['shots'][0]['assets'][:1], ['CAST-01'])
        self.assertEqual(data['cast'][0], {'assetCode': 'CAST-01', 'name': self.cast01['name'], 'type': 'CHARACTER',
                                           'selectedImageUrl': self.image})
        second = self.call('read_scene', {'scene_id': self.scene2})['data']
        self.assertEqual((second['previousSceneId'], second['nextSceneId']), (self.scene1, None))
        self.assertEqual([c['assetCode'] for c in second['cast']][:2], ['CAST-01', 'CAST-02'])

    def test_read_shot_has_cells_plan_neighbours_and_cast(self):
        result = self.call('read_shot', {'shot_id': self.shot1})
        data = result['data']
        shot = data['shot']
        self.assertEqual((shot['episodeId'], shot['sceneId'], shot['tabKey']), (self.ep, self.scene1, 'cinema-studio'))
        cells = {cell['header']: cell for cell in shot['cells']}
        self.assertEqual(cells['Cinema Shot'], {'col': 5, 'header': 'Cinema Shot', 'url': self.take_b})
        self.assertEqual(cells['Shot']['col'], 0)
        self.assertIn('brass dial', cells['Action & Audio Prompt']['value'])
        self.assertEqual(shot['selectedVideoUrl'], self.take_b)
        self.assertEqual((data['previs']['stored'], data['previs']['planRevision'], data['previs']['planDetail']), (True, 1, 'full'))
        self.assertEqual(data['previs']['plan'], PLAN)
        self.assertEqual(data['previs']['updatedBy'], self.actor)
        self.assertIsNone(data['previous'])
        self.assertEqual(data['next']['shotId'], self.shot2)
        self.assertEqual(data['cast'][0]['assetCode'], 'CAST-01')
        self.assertIn({'kind': 'shot_meta', 'id': 'meta_' + self.shot1, 'planRevision': 1}, result['sources'])
        second = self.call('read_shot', {'shot_id': self.shot2, 'include_plan': False})['data']
        self.assertEqual(second['previous']['shotId'], self.shot1)
        self.assertEqual(second['previs'], {'stored': False, 'planRevision': 0, 'updatedAt': None, 'updatedBy': None,
                                            'seed': second['previs']['seed']})
        self.assertEqual(self.call('read_shot', {'shot_id': self.shot1, 'include_plan': False})['data']['previs']['planDetail'], 'omitted')

    def test_read_cast_lists_assets_with_looks_and_reads_one_in_full(self):
        listing = self.call('read_cast', {})['data']
        kael = next(a for a in listing['assets'] if a['assetCode'] == 'CAST-01')
        self.assertEqual(kael['looks'], [{'assetCode': 'CAST-01:NIGHT', 'name': 'Night coat', 'kind': 'OUTFIT', 'selectedImageUrl': None}])
        self.assertEqual(kael['selectedImageUrl'], self.image)
        self.assertTrue(all(a['type'] == 'SCENE' for a in self.call('read_cast', {'type': 'SCENE'})['data']['assets']))
        one = self.call('read_cast', {'asset': '@cast-01'})
        data = one['data']
        self.assertEqual((data['asset']['assetId'], data['asset']['referenceImages']), (self.cast01['assetId'], [self.image]))
        self.assertEqual([look['assetCode'] for look in data['looks']], ['CAST-01:NIGHT'])
        self.assertEqual(data['looks'][0]['description'], 'rain-dark longcoat')
        self.assertLessEqual({self.shot1, self.shot2}, set(data['usage']['shotIds']))
        self.assertIn(self.scene1, data['usage']['sceneIds'])
        self.assertIn({'kind': 'asset', 'id': self.cast01['assetId'], 'code': 'CAST-01'}, one['sources'])
        look = self.call('read_cast', {'asset': 'CAST-01:night'})['data']
        self.assertEqual((look['asset']['assetCode'], look['requested']), ('CAST-01', 'CAST-01:NIGHT'))
        self.assertEqual(self.call('read_cast', {'asset': self.cast01['assetId']})['data']['asset']['assetCode'], 'CAST-01')
        self.assertEqual(self.call('read_cast', {'asset': 'CAST-99'})['status'], 'not_found')

    def test_list_takes_attaches_each_grade_to_its_take(self):
        result = self.call('list_takes', {'shot_id': self.shot1})
        data = result['data']
        takes = {take['url']: take for take in data['takes']}
        self.assertEqual(set(takes), {self.take_a, self.take_b})
        self.assertTrue(takes[self.take_b]['selected'])
        self.assertFalse(takes[self.take_a]['selected'])
        self.assertIsNone(takes[self.take_a]['grade'])
        grade = takes[self.take_b]['grade']
        self.assertEqual((grade['score'], grade['passed'], grade['issues'], grade['retakePrompt']),
                         (62, False, ['Wardrobe drifts in frame 6'], 'Hold the coat. @CAST-01'))
        self.assertEqual([g['url'] for g in data['otherGrades']], [self.pending])
        self.assertEqual((data['selectedUrl'], data['autoGrade'], data['counts']['takes'], data['counts']['failed']),
                         (self.take_b, False, 2, 1))
        self.assertIn({'kind': 'setting', 'id': 'auto_grade_takes'}, result['sources'])
        images = self.call('list_takes', {'shot_id': self.shot1, 'kind': 'image'})['data']
        self.assertEqual((images['takes'], images['otherGrades'], images['autoGrade']), ([], [], None))

    # ---------- envelope guarantees ----------

    def test_hash_is_stable_and_follows_the_content(self):
        first = self.call('read_shot', {'shot_id': self.shot1})
        self.assertEqual(self.call('read_shot', {'shot_id': self.shot1})['hash'], first['hash'])
        self.set_cell(self.shot1, 3, 'Kael studies the dial in silence. @CAST-01')
        changed = self.call('read_shot', {'shot_id': self.shot1})
        self.assertNotEqual(changed['hash'], first['hash'])
        revision = lambda r: next(s['revision'] for s in r['sources'] if s == {**s, 'kind': 'tab', 'id': 'cinema-studio'})
        self.assertGreater(revision(changed), revision(first))
        story_previs.put(self.conn, self.slug, self.shot1, {**PLAN, 'lens': 85}, 1, self.actor)
        self.conn.commit()
        replanned = self.call('read_shot', {'shot_id': self.shot1})
        self.assertNotEqual(replanned['hash'], changed['hash'])
        self.assertIn({'kind': 'shot_meta', 'id': 'meta_' + self.shot1, 'planRevision': 2}, replanned['sources'])

    def test_long_content_is_cut_and_noted(self):
        long_scene = '## Scene 01: Observatory\n' + ('@CAST-01 waits by the dial. ' * 250) + '\n\n## Scene 02: Departure\n@CAST-01 leaves.'
        story.set_script(self.conn, self.me, story.episode(self.conn, self.ep), long_scene)
        self.conn.commit()
        result = self.call('read_scene', {'scene_id': self.scene1})
        self.assertEqual(result['status'], 'partial')
        self.assertLessEqual(len(result['data']['scene']['content']), 3001)
        self.assertGreater(result['data']['scene']['chars'], 3000)
        self.assertTrue(any('3000' in note for note in result['limitations']))
        episode = self.call('read_episode', {})
        self.assertTrue(any('read_scene' in note for note in episode['limitations']))
        self.assertIn('script is not confirmed', ' '.join(episode['warnings']))
        big = {**PLAN, 'acts': [{'at': i / 400, 'yaw': 0.5, 'reach': 0.25, 'body': 'stand'} for i in range(400)]}
        story_previs.put(self.conn, self.slug, self.shot1, big, 1, self.actor)
        self.conn.commit()
        shot = self.call('read_shot', {'shot_id': self.shot1})
        previs = shot['data']['previs']
        self.assertEqual((previs['planDetail'], previs['plan']['counts']['acts'], previs['plan']['move']), ('summary', 400, 'orbit'))
        self.assertNotIn('acts', previs['plan'])
        self.assertTrue(any('previs-plan' in note for note in shot['limitations']))
        with patch.object(context_tools, 'MAX_CHARS', 1500):
            tight = json.loads(tools.call(self.ctx, 'read_episode', {}))
        self.assertLessEqual(len(json.dumps(tight, ensure_ascii=False, separators=(',', ':'))), 1500)
        self.assertEqual(tight['status'], 'partial')
        self.assertTrue(tight['limitations'])

    def test_ids_of_another_production_read_as_not_found(self):
        other = 'ctx-other-' + uuid.uuid4().hex[:8]
        self.extra.append(other)
        repo.upsert_project(self.conn, other, 'Other production')
        self.studio(other)
        self.conn.commit()
        foreign_shot = story.shot_id(other, story.table_rows(self.conn, other, 'cinema-studio')[0])
        foreign_asset = story.asset_id(other, story.table_rows(self.conn, other, 'soul-cast')[0])
        self.conn.rollback()
        for name, args in [('read_shot', {'shot_id': foreign_shot}), ('list_takes', {'shot_id': foreign_shot}),
                           ('read_episode', {'episode_id': f'ep_{other}_01'}), ('read_scene', {'scene_id': f'sc_{other}_01_S01'}),
                           ('read_cast', {'asset': foreign_asset}), ('read_shot', {'shot_id': f'sh_{self.slug}_bmissing'})]:
            with self.subTest(name=name):
                result = self.call(name, args)
                self.assertEqual((result['status'], result['data']), ('not_found', None))
                self.assertNotIn(other, json.dumps(result['sources']))  # at most this production's sheet was searched
                self.assertTrue(result['warnings'])
        self.assertEqual([detail['status'] for _, detail in self.audits()], ['not_found'] * 6)

    def test_denied_callers_get_policy_errors_and_no_audit(self):
        stranger = tools.ToolContext(self.connect, self.slug, service.Identity(str(uuid.uuid4()), 'Stranger', 'admin'),
                                     Path('.'), None, agent_key='sheet_ops')
        with self.assertRaises(tools.ToolError) as caught:
            tools.call(stranger, 'read_shot', {'shot_id': self.shot1})
        self.assertIn('POLICY_DENIED', str(caught.exception))
        store.set_member_enabled(self.conn, self.slug, self.actor, False, self.actor)
        self.conn.commit()
        with self.assertRaises(tools.ToolError) as caught:
            tools.call(self.ctx, 'read_shot', {'shot_id': self.shot1})
        self.assertIn('POLICY_DENIED', str(caught.exception))
        store.set_member_enabled(self.conn, self.slug, self.actor, True, self.actor)
        profile = agent_registry.get_agent(self.conn, self.slug, 'sheet_ops', effective=False)
        agent_registry.save_agent(self.conn, self.me, self.slug, {
            'agent_key': 'sheet_ops', 'allowed_tools': [t for t in profile['allowed_tools'] if t != 'read_shot'],
            'tool_policies': {'list_takes': 'disabled'}})
        self.conn.commit()
        for name, args in [('read_shot', {'shot_id': self.shot1}), ('list_takes', {'shot_id': self.shot1})]:
            with self.subTest(name=name), self.assertRaises(tools.ToolError) as caught:
                tools.call(self.ctx, name, args)
            self.assertIn('POLICY_DENIED', str(caught.exception))
        self.assertEqual(self.call('read_scene', {'scene_id': self.scene1})['status'], 'ok')  # the rest still works
        self.assertEqual([detail['tool'] for _, detail in self.audits()], ['read_scene'])

    def test_masked_production_masks_text_but_not_structure(self):
        self.set_cell(self.shot1, 3, f'Budget 123456 for the dial shot; key {SECRET} @CAST-01')
        full = self.call('read_shot', {'shot_id': self.shot1})
        prompt = lambda r: next(c['value'] for c in r['data']['shot']['cells'] if c['col'] == 3)
        self.assertIn('123456', prompt(full))
        self.assertNotIn(SECRET, prompt(full))
        repo.update_project_meta(self.conn, self.slug, privacy_mode='mask_numbers')
        self.conn.commit()
        masked = self.call('read_shot', {'shot_id': self.shot1})
        self.assertNotIn('123456', prompt(masked))
        self.assertIn('▢', prompt(masked))
        self.assertEqual((masked['data']['shot']['shotId'], masked['data']['previs']['plan'], masked['data']['previs']['planRevision']),
                         (self.shot1, PLAN, 1))
        self.assertEqual(masked['data']['shot']['selectedVideoUrl'], self.take_b)
        self.assertNotEqual(masked['hash'], full['hash'])
        self.assertNotIn('123456', json.dumps(self.call('read_scene', {'scene_id': self.scene1})['data']))

    def test_each_call_writes_one_audit_record(self):
        result = self.call('read_shot', {'shot_id': self.shot1})
        rows = self.audits()
        self.assertEqual(len(rows), 1)
        target, detail = rows[0]
        self.assertEqual(target, self.shot1)
        self.assertEqual((detail['tool'], detail['agentKey'], detail['status'], detail['hash'], detail['sources']),
                         ('read_shot', 'sheet_ops', 'ok', result['hash'], result['sources']))
        self.assertEqual(detail['arguments'], {'shot_id': self.shot1})
        self.call('list_takes', {'shot_id': self.shot1})
        self.assertEqual(len(self.audits()), 2)

    def test_media_cells_outside_the_production_are_left_out(self):
        self.set_cell(self.shot1, 4, '[Image](https://example.com/still.png)')
        result = self.call('read_shot', {'shot_id': self.shot1})
        keyframe = next(c for c in result['data']['shot']['cells'] if c['col'] == 4)
        self.assertEqual(keyframe, {'col': 4, 'header': 'Keyframe', 'url': None})
        self.assertIn('Column 4 links media outside this production', ' '.join(result['warnings']))


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI')
class GrantTopUpTests(unittest.TestCase):
    def setUp(self):
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.setUp(self)
        agent_registry.ensure_default_agents(self.conn, self.slug)

    def tearDown(self):
        import test_execution as execution_fixture
        execution_fixture.PostgreSQLExecutionTests.tearDown(self)

    def profiles(self):
        return {key: agent_registry.get_agent(self.conn, self.slug, key, effective=False) for key in tool_registry.BUILTIN_ROLES}

    def legacy(self, lists):
        """An existing production from before the context tools: older grants and no record of any offer."""
        with self.conn.cursor() as cur:
            for key, allowed in lists.items():
                cur.execute('UPDATE projectops.agent_profile SET allowed_tools=%s::jsonb WHERE project_slug=%s AND agent_key=%s',
                            (json.dumps(allowed), self.slug, key))
            cur.execute('DELETE FROM projectops.assistant_setting WHERE project_slug=%s AND key=%s', (self.slug, context_tools.TOPUP_SETTING))

    def test_new_agents_are_seeded_with_the_tools_and_recorded_as_offered(self):
        for key, profile in self.profiles().items():
            self.assertEqual(profile['allowed_tools'], agent_registry.default_tools(key))
            self.assertLessEqual(set(CONTEXT), set(profile['allowed_tools']))
        offered = json.loads(store.get_setting(self.conn, self.slug, context_tools.TOPUP_SETTING))
        self.assertEqual(offered, {key: CONTEXT for key in tool_registry.BUILTIN_ROLES})

    def test_existing_crews_get_the_read_tools_once(self):
        old = {key: [t for t in agent_registry.default_tools(key) if t not in CONTEXT] for key in tool_registry.BUILTIN_ROLES}
        self.legacy(old)
        before = {key: p['version'] for key, p in self.profiles().items()}
        agent_registry.ensure_default_agents(self.conn, self.slug)
        after = self.profiles()
        for key in tool_registry.BUILTIN_ROLES:
            with self.subTest(key=key):
                self.assertEqual(after[key]['allowed_tools'], old[key] + CONTEXT)
                self.assertEqual(after[key]['version'], before[key] + 1)
        with self.conn.cursor() as cur:
            cur.execute('SELECT target, detail FROM projectops.audit_log WHERE project_slug=%s AND action=%s ORDER BY target',
                        (self.slug, context_tools.TOPUP_ACTION))
            self.assertEqual(cur.fetchall(), sorted((key, {'added': CONTEXT, 'category': 'context'}) for key in tool_registry.BUILTIN_ROLES))
        agent_registry.ensure_default_agents(self.conn, self.slug)  # idempotent: nothing more to add, no new version
        again = self.profiles()
        self.assertEqual({k: (p['allowed_tools'], p['version']) for k, p in again.items()},
                         {k: (p['allowed_tools'], p['version']) for k, p in after.items()})

    def test_removed_tools_stay_removed_and_write_tools_are_never_added(self):
        me = service.Identity(self.actor, 'Execution test', 'admin')
        current = self.profiles()['sheet_ops']['allowed_tools']
        agent_registry.save_agent(self.conn, me, self.slug, {'agent_key': 'sheet_ops', 'allowed_tools': [t for t in current if t != 'read_cast']})
        agent_registry.save_agent(self.conn, me, self.slug, {'agent_key': 'custom_reader', 'allowed_tools': ['read_page']})
        agent_registry.ensure_default_agents(self.conn, self.slug)
        self.assertNotIn('read_cast', self.profiles()['sheet_ops']['allowed_tools'])
        self.legacy({'sheet_ops': ['read_page'], 'qa_critic': ['read_page', 'read_cast']})
        agent_registry.ensure_default_agents(self.conn, self.slug)
        profiles = self.profiles()
        self.assertEqual(profiles['sheet_ops']['allowed_tools'], ['read_page'] + CONTEXT)
        self.assertEqual(profiles['qa_critic']['allowed_tools'], ['read_page', 'read_cast'] + [t for t in CONTEXT if t != 'read_cast'])
        self.assertEqual(agent_registry.get_agent(self.conn, self.slug, 'custom_reader', effective=False)['allowed_tools'], ['read_page'])


if __name__ == '__main__':
    unittest.main()
