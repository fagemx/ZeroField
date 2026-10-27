"""SPEC_20 R24, R25 (and R13, R40): the continuity check and the crew's pre-production flow with the director's locks.

The pure tests need nothing. The rest run the real story server on PostgreSQL (OPENBENCH_TEST_DB_URI) with every crew
job executed inline on a fake OpenAI-compatible opener: no test reaches a model, Ollama or a GPU, and the socket guard
of test_crew_jobs refuses port 11434 here too.
"""
import json
import os
import re
import unittest
from unittest.mock import patch

from project_assistant import crew_continuity as continuity, crew_jobs, crew_preproduction as flows, crew_readiness
import test_crew_jobs as crew_fixture
import test_crew_story_jobs as story_fixture
from test_crew_jobs import FakeEndpoint, crew_eval


def setUpModule():
    crew_fixture.setUpModule()


def tearDownModule():
    crew_fixture.tearDownModule()


BIBLE = [{'code': '@CAST-01', 'name': 'Kael', 'look': 'charcoal field jacket'},
         {'code': '@CAST-01:NIGHT', 'name': 'Kael - night', 'look': 'soaked black rain coat'},
         {'code': '@CAST-02', 'name': 'Mira', 'look': 'green wool coat'},
         {'code': '@SET-01', 'name': 'Observatory', 'look': 'glass dome at dawn'}]


def shot(identifier, text, cast, transition='continuous', plan=None, **extra):
    entry = {'id': identifier, 'shotId': 'sh_x_b' + identifier, 'take': '', 'seconds': 4, 'transition': transition, 'text': text,
             'cast': cast, 'set': '@SET-01', 'optical_rig': '35mm prime, medium shot, eye level', 'camera_motion': 'Slow dolly push-in'}
    if plan:
        entry['plan'] = plan
    return {**entry, **extra}


INPUT = {'scope': {'kind': 'scene', 'id': 'sc_x_01_S01', 'title': 'Scene 01: Observatory'}, 'bible': BIBLE, 'shots': [
    shot('S01', 'Kael @CAST-01:night stands at the console. @SET-01', ['@CAST-01:NIGHT'], 'scene_change',
         {'source': 'stored', 'set': 'observatory', 'mood': 'night', 'mark': [0, 0]}),
    shot('S02', 'Kael @CAST-01 turns to the glass. @SET-01', ['@CAST-01'], plan={'source': 'stored', 'set': 'observatory', 'mood': 'grey', 'mark': [2.5, 0]},
         grade={'score': 41, 'passed': False, 'issues': ['identity drift']}),
    shot('S03', 'Mira @CAST-02 answers from the door. @SET-01', ['@CAST-02']),
    shot('S04', 'A new day: Kael @CAST-01 returns. @SET-01', ['@CAST-01'], 'scene_change')]}


def finding(**change):
    value = {'kind': 'wardrobe', 'shots': ['S01', 'S02'], 'subject': '@CAST-01', 'severity': 'major', 'certainty': 'likely',
             'detail': 'Kael wears the night coat in S01 and the field jacket in S02 across a continuous join.',
             'evidence': [{'shot': 'S01', 'field': 'cast'}, {'shot': 'S02', 'field': 'cast'}]}
    value.update(change)
    return value


class ContinuityContractTests(unittest.TestCase):
    def test_a_finding_with_evidence_passes(self):
        answer = {'score': 55, 'findings': [finding(), finding(kind='lighting', subject='scene', severity='minor', certainty='check',
                                                                 detail='The mood changes from night to grey.',
                                                                 evidence=[{'shot': 'S01', 'field': 'plan.mood'}, {'shot': 'S02', 'field': 'plan.mood'}])]}
        self.assertEqual(continuity.validate(answer, INPUT), [])
        self.assertEqual(continuity.validate({'score': 100, 'findings': []}, INPUT), [], 'clean joins are a valid answer')

    def test_every_finding_cites_real_shots_and_fields(self):
        def errors(**change):
            return ' '.join(continuity.validate({'score': 50, 'findings': [finding(**change)]}, INPUT))
        self.assertRegex(errors(shots=['S01', 'S09']), r"names shot\(s\) 'S09', which are not in this check; use only the ids given: S01, S02, S03, S04")
        self.assertRegex(errors(evidence=[{'shot': 'S03', 'field': 'cast'}]), r"evidence cites shot 'S03', which is not one of the finding's shots")
        self.assertRegex(errors(evidence=[{'shot': 'S01', 'field': 'first_frame'}]), r'cites S01\.first_frame, but that shot has only text, cast, set')
        self.assertRegex(errors(evidence=[{'shot': 'S02', 'field': 'grade'}]), r'rests on a grade alone; a grade is information, not evidence')
        self.assertEqual(errors(evidence=[{'shot': 'S02', 'field': 'grade'}, {'shot': 'S01', 'field': 'cast'}]), '', 'a grade beside a field is fine')
        self.assertRegex(errors(subject='@CAST-07'), r"subject '@CAST-07' is not a code of the bible")
        self.assertEqual(errors(subject='@cast-01:night'), '', 'codes compare without case')
        self.assertRegex(errors(kind='costume'), r"kind 'costume' is not one of")
        self.assertRegex(errors(certainty='sure'), r'certainty must be confirmed, likely or check')
        self.assertRegex(errors(evidence=[]), r'"evidence" must list 1 to 6')
        self.assertRegex(' '.join(continuity.validate({'score': 101, 'findings': []}, INPUT)), r'"score" must be a whole number from 0 to 100')
        self.assertRegex(' '.join(continuity.validate({'score': 1, 'findings': [], 'notes': 'x'}, INPUT)), r'unexpected field "notes"')

    def test_a_fix_is_a_field_of_one_of_the_finding_s_shots(self):
        def errors(fix, *more):
            return ' '.join(continuity.validate({'score': 50, 'findings': [finding(fix=fix), *more]}, INPUT))
        good = {'shot': 'S02', 'field': 'text', 'value': 'Kael @CAST-01:night turns to the glass. @SET-01'}
        self.assertEqual(errors(good), '')
        self.assertRegex(errors({**good, 'shot': 'S03'}), r"changes shot 'S03', which is not one of this finding's shots")
        self.assertRegex(errors({**good, 'field': 'status'}), r"field 'status' is not one of text, optical_rig, camera_motion")
        self.assertRegex(errors({**good, 'value': INPUT['shots'][1]['text']}), r"leaves S02's text as it is")
        self.assertRegex(errors({**good, 'value': 'Kael @CAST-05 turns. @SET-01'}), r'names @CAST-05, which the bible does not have')
        self.assertRegex(errors({**good, 'field': 'optical_rig', 'value': 'ARRI Alexa / 40mm'}), r'brand\(s\) ARRI, Alexa.*lens\(es\) 40mm')
        twice = finding(kind='hair_makeup', detail='Hair changes too.', fix={**good, 'value': good['value'] + ' Wet hair.'})
        self.assertRegex(errors(good, twice), r"both change S02's text; give that field one fix")

    def test_the_rule_fallback_checks_continuous_joins_only(self):
        output = continuity.fallback(INPUT)
        self.assertEqual(continuity.validate(output, INPUT), [])
        found = [(f['kind'], f['shots'], f['subject'], f['certainty']) for f in output['findings']]
        self.assertEqual(found, [('wardrobe', ['S01', 'S02'], '@CAST-01', 'likely'), ('lighting', ['S01', 'S02'], '@SET-01', 'likely'),
                                 ('position', ['S01', 'S02'], '@CAST-01', 'check'), ('position', ['S02', 'S03'], '@CAST-01', 'check')])
        self.assertEqual(output['findings'][0]['fix'], {'shot': 'S02', 'field': 'text', 'value': 'Kael @CAST-01:night turns to the glass. @SET-01'},
                         'the look established first carries forward')
        self.assertIn('2.5 m apart', output['findings'][2]['detail'])
        self.assertFalse(any('S04' in f['shots'] for f in output['findings']), 'a scene change is not a continuous join')
        self.assertEqual(output['score'], 100 - 30 * 2 - 10 * 2)
        quiet = {**INPUT, 'shots': [shot('A', 'Kael waits. @CAST-01 @SET-01', ['@CAST-01']), shot('B', 'A hand on the dial. @SET-01', [])]}
        self.assertEqual(continuity.fallback(quiet), {'score': 100, 'findings': []}, 'an insert binds only the scene: no cast finding')

    def test_answers_are_retried_once_then_fall_back(self):
        invented = {'score': 40, 'findings': [finding(shots=['S01', 'S99'])]}
        call = crew_fixture.calls(invented, {'score': 70, 'findings': [finding()]})
        outcome = crew_jobs.run_pipeline(continuity.CONTINUITY, INPUT, call)
        self.assertEqual((outcome.source, [a['valid'] for a in outcome.attempts]), ('model', [False, True]))
        self.assertIn("'S99', which are not in this check", call.sent[1]['text'])
        self.assertIn('[S02] · 4 s · continuous from S01', call.sent[0]['text'])
        self.assertIn('grade: 41 issues: identity drift', call.sent[0]['text'])
        broken = crew_jobs.run_pipeline(continuity.CONTINUITY, INPUT, crew_fixture.calls(invented, invented))
        self.assertEqual((broken.source, broken.output), ('rule_fallback', continuity.fallback(INPUT)))
        with self.assertRaises(crew_jobs.ModelUnavailable):
            crew_jobs.run_pipeline(continuity.CONTINUITY, INPUT, crew_fixture.calls(crew_jobs.Reply(ok=False, failure='local', error='down')))
        self.assertEqual(continuity.CONTINUITY.targets, ('scene', 'episode'))
        self.assertEqual(continuity.KINDS, crew_eval.KINDS)


class ContinuityEvalAdapterTests(unittest.TestCase):
    def test_the_adapter_runs_the_real_job_on_two_cases(self):
        cases = [c for c in crew_eval.load_cases(['continuity']) if c['id'].startswith(('continuity-01', 'continuity-02'))]
        self.assertEqual(len(cases), 2)

        def with_evidence(reference):
            return {'score': reference['score'], 'findings': [
                {**f, 'certainty': 'likely', 'evidence': [{'shot': f['shots'][0], 'field': 'last_frame'}, {'shot': f['shots'][-1], 'field': 'first_frame'}]}
                for f in reference['findings']]}
        first, second = cases
        answers = {'S08': [with_evidence(first['reference'])], 'S12': [{'score': 50, 'findings': [finding(shots=['S12', 'S77'])]}, 'not json']}
        seen = []

        def model(instructions, text, history):
            opening = re.search(r'\[(S\d+)\]', text if not history else history[0]['content'])[1]
            seen.append(opening)
            reply = answers[opening][len(history) // 2]
            return crew_jobs.Reply(ok=True, answer=reply if isinstance(reply, str) else json.dumps(reply), model='fake')
        report = crew_eval.run(cases, continuity.eval_adapter(model), label='fake model')
        one, two = report['types']['continuity']['results']
        self.assertEqual((one['hard_ok'], one['score']), (True, 1.0), one)
        self.assertEqual(seen, ['S08', 'S12', 'S12'], 'one retry, then the rule fallback')
        self.assertFalse(two['hard_ok'], 'the rule fallback is what the user would get, and it is scored')
        with self.assertRaises(NotImplementedError):
            continuity.eval_adapter(model)('beats-01', 'beats', {})


class LockContentTests(unittest.TestCase):
    def test_changes_say_what_changed_by_name(self):
        old = {'script': 'a', 'scenes': [{'sceneId': 's1', 'title': 'Scene 01: Observatory', 'text': 'x'}, {'sceneId': 's2', 'title': 'Scene 02', 'text': 'y'}]}
        new = {'script': 'b', 'scenes': [{'sceneId': 's1', 'title': 'Scene 01: Observatory', 'text': 'z'}]}
        self.assertEqual(flows.changes('script', old, new), ['Scene "Scene 02" was removed.', 'The text of scene "Scene 01: Observatory" changed.'])
        self.assertEqual(flows.changes('script', {**old, 'script': 'b'}, {**old, 'script': 'c'}), ['The script text changed outside its scenes.'])
        listed = {'assets': {'CAST-01': {'name': 'Kael', 'hash': '1'}}, 'shots': {'sh1': {'label': 'SC01-S01', 'tags': ['CAST-01']}}}
        moved = {'assets': {'CAST-01': {'name': 'Kael', 'hash': '2'}}, 'shots': {'sh1': {'label': 'SC01-S01', 'tags': ['CAST-02']}}}
        self.assertEqual(flows.changes('list', listed, moved), ["CAST-01 Kael's card changed (name or description).",
                                                                "SC01-S01's cast and sets changed: @CAST-01 -> @CAST-02."])
        board = {'shots': {'sh1': {'label': 'SC01-S01', 'sceneId': 'a', 'text': '1', 'rig': '1', 'motion': '1', 'plan': 0}}}
        later = {'shots': {'sh1': {'label': 'SC01-S01', 'sceneId': 'a', 'text': '2', 'rig': '1', 'motion': '1', 'plan': 1},
                           'sh2': {'label': 'SC01-S02', 'sceneId': 'a', 'text': '1', 'rig': '1', 'motion': '1', 'plan': 0}}}
        self.assertEqual(flows.changes('storyboard', board, later), ['Shot SC01-S02 was added.', "SC01-S01's prompt changed.", "SC01-S01's 3D plan changed."])
        self.assertEqual((flows.GATE, flows.OPENS['script'], flows.CLOSES['storyboard']),
                         ({'art': 'script', 'cinematographer': 'list', 'continuity': 'storyboard'}, 'art', 'cinematographer'))


# ---------- against the real servers ----------

@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI for crew flow tests')
class PreproductionServerTests(unittest.TestCase):
    request = crew_fixture.fixture.StoryHTTPTests.request
    call = crew_fixture.fixture.StoryHTTPTests.call
    ok = crew_fixture.fixture.StoryHTTPTests.ok
    setUp = crew_fixture.CrewJobServerTests.setUp
    tearDown = crew_fixture.CrewJobServerTests.tearDown
    run_job = crew_fixture.CrewJobServerTests.run_job
    proposal = crew_fixture.CrewJobServerTests.proposal
    decide = crew_fixture.CrewJobServerTests.decide
    counted = crew_fixture.CrewJobServerTests.counted
    prepare = story_fixture.CrewStoryJobServerTests.prepare
    ask = story_fixture.CrewStoryJobServerTests.ask
    asset = story_fixture.CrewStoryJobServerTests.asset
    cell = story_fixture.CrewStoryJobServerTests.cell
    scene_shots = story_fixture.CrewStoryJobServerTests.scene_shots

    # ---- helpers ----
    def alive(self):
        from project_assistant import orchestrator as cp, store
        self.conn.rollback()
        store.set_setting(self.conn, self.slug, 'builtin_worker_seen_at', cp.now().isoformat())
        self.conn.commit()

    def state(self):
        return self.ok(f'/episodes/{self.ep}/preproduction')

    def lock(self, name, expect=200, hash=None):
        current = self.state()
        body = {'lock': name, 'hash': hash or (current['next'] or {}).get('hash') or 'sha256:none'}
        code, payload = self.call(f'/episodes/{self.ep}/preproduction/locks', 'POST', body)
        self.assertEqual(code, expect, payload)
        return payload['data'] if expect == 200 else payload

    def drain(self, answers=lambda record: ('not json', 'still not json')):
        """Run every queued crew job inline (rule fallback by default); [(kind, status)]."""
        done = []
        while True:
            self.alive()
            claimed = crew_jobs.claim(self.conn, 'test-worker', slug=self.slug)
            self.conn.commit()
            if not claimed:
                return done
            record = crew_jobs._load(self.conn, claimed['crewJob'])
            self.conn.rollback()
            status = crew_jobs.execute(self.connect, claimed, 'test-worker', opener=FakeEndpoint(*answers(record)))
            done.append((record['kind'], status))

    def stage(self, data, key):
        return next(s for s in data['flow']['stages'] if s['key'] == key)

    def flow_jobs(self, flow_id):
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT data FROM projectops.story_record WHERE kind='crew_job' AND data->>'flowId'=%s", (flow_id,))
            return [row[0] for row in cur.fetchall()]

    def set_role(self, role):
        from project_docs import repository as repo
        self.conn.rollback()
        repo.upsert_member(self.conn, self.actor, 'Execution test', role)
        self.conn.commit()

    # ---- the continuity job ----
    def test_a_continuity_check_cites_real_shots_and_proposes_only_field_fixes(self):
        first, second, insert, fourth = self.scene_shots(1)
        labels = [s['shotIndex'] for s in (first, second, insert, fourth)]
        job = self.ask(f"/scenes/{first['sceneId']}/continuity-proposals", {'note': 'Watch the jacket.'})
        self.assertEqual((job['kind'], job['role'], job['target']['kind']), ('continuity', 'qa_critic', 'scene'))
        fixed = second['description'] + ' Kael still wears the charcoal field jacket.'
        good = {'score': 62, 'findings': [
            {'kind': 'wardrobe', 'shots': labels[:2], 'subject': '@CAST-01', 'severity': 'major', 'certainty': 'likely',
             'detail': f'{labels[1]} drops the jacket that {labels[0]} establishes.',
             'evidence': [{'shot': labels[0], 'field': 'text'}, {'shot': labels[1], 'field': 'text'}],
             'fix': {'shot': labels[1], 'field': 'text', 'value': fixed}},
            {'kind': 'gaze', 'shots': labels[2:], 'subject': '@CAST-02', 'severity': 'minor', 'certainty': 'check',
             'detail': 'Mira looks toward the door while the insert shows the dial.',
             'evidence': [{'shot': labels[3], 'field': 'text'}]}]}
        invented = {'score': 50, 'findings': [{**good['findings'][1], 'shots': [labels[3], 'SC09-S99']}]}
        endpoint = FakeEndpoint(invented, good)
        status, done = self.run_job(endpoint)
        self.assertEqual((status, done['source'], [a['valid'] for a in done['attempts']]), ('succeeded', 'model', [False, True]), done)
        sent = endpoint.requests[0]['messages'][-1]['content']
        self.assertIn(f'[{labels[1]}]', sent)
        self.assertIn("Director's note: Watch the jacket.", sent)
        self.assertEqual(endpoint.requests[0]['response_format']['json_schema']['name'], 'crew_continuity')
        self.assertIn("'SC09-S99', which are not in this check", endpoint.requests[1]['messages'][-1]['content'])
        result = done['result']
        real = {s['shotId'] for s in self.scene_shots(1)}
        for item in result['findings']:
            self.assertTrue(set(item['shotIds']) <= real, item)
        [proposal_id] = result['proposalIds']
        proposal = self.proposal(proposal_id)
        [group] = proposal['target']['review']['groups']
        self.assertEqual((proposal['agent_key'], group['row_id'], [c['column'] for c in group['changes']], group['changes'][0]['after']),
                         ('qa_critic', second['rowId'], ['Action & Audio Prompt'], fixed))
        self.assertEqual(proposal['target']['crew']['kind'], 'continuity')
        self.assertEqual(self.cell(second['shotId'], 'prompt'), second['description'], 'a proposal writes nothing')
        self.assertEqual([j['verdict'] for j in result['joins']], ['break', 'clean', 'check'])
        self.assertEqual(result['notChecked'][0]['what'], 'takes')
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['done'] if i.get('job_id') == done['jobId'])
        self.assertEqual(item['summary'], f'2 continuity findings on 3 joins (1 to fix first); proposals #{proposal_id} wait on the shots.')
        # Rule fallback after two bad answers; a scene with one shot has no join; no model means 409 and nothing written.
        self.ask(f'/episodes/{self.ep}/continuity-proposals')
        status, fallback = self.run_job(FakeEndpoint('nope', 'nope'))
        self.assertEqual((status, fallback['source']), ('succeeded', 'rule_fallback'), fallback)
        self.assertTrue(all(f['certainty'] in ('likely', 'check') for f in fallback['result']['findings']))
        self.assertEqual(self.ask(f"/scenes/{self.scene_shots(2)[0]['sceneId']}/continuity-proposals", expect=422)['code'], 'DRAMA_VALIDATION_FAILED')
        before = self.counted("SELECT count(*) FROM projectops.story_record WHERE kind='crew_job' AND project_slug=%s")
        self.probe.stop()
        try:
            with patch.object(crew_readiness, '_probe', return_value=('down', None)):
                crew_readiness.forget()
                refused = self.ask(f"/scenes/{first['sceneId']}/continuity-proposals", expect=409)
        finally:
            self.probe.start()
            crew_readiness.forget()
        self.assertEqual((refused['code'], refused['details']['agentKey']), (crew_jobs.NOT_READY, 'qa_critic'))
        self.assertEqual(self.counted("SELECT count(*) FROM projectops.story_record WHERE kind='crew_job' AND project_slug=%s"), before)

    # ---- R24: stage order, lock gating, completion ----
    def test_stages_run_in_order_and_each_waits_for_its_lock(self):
        empty = self.state()
        self.assertEqual((empty['flow'], empty['canStart'], empty['canLock'], empty['next']), (None, True, True, None))
        started = self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {})
        flow = started['flow']
        self.assertEqual((flow['status'], flow['current']), ('running', 'screenwriter'))
        writer = self.stage(started, 'screenwriter')
        self.assertEqual([j['kind'] for j in writer['jobs']], ['breakdown'])
        self.assertEqual([s['kind'] for s in writer['skipped']], ['adaptation'], 'no saved idea: the adaptation is left out, with why')
        self.assertIn('Save your idea or novel', writer['skipped'][0]['reason'])
        self.assertEqual(self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {})['flow']['flowId'], flow['flowId'], 'one active flow per episode')
        self.assertEqual(self.lock('list', 409)['message'], 'Lock the script first.')
        self.assertRegex(self.lock('script', 409)['message'], r'The Screenwriter is still working \(1 job open\)')
        self.assertEqual({s['status'] for s in started['flow']['stages'][1:]}, {'pending'}, 'nothing after the script lock has started')
        self.assertEqual(self.drain(), [('breakdown', 'succeeded')])
        waiting = self.state()
        self.assertEqual((waiting['flow']['status'], waiting['flow']['waitingFor'], waiting['next']['lock']), ('waiting', 'script', 'script'))
        self.assertEqual(waiting['next']['summary']['scenes'], 2)
        self.assertEqual(self.lock('script', 409, hash='sha256:' + '0' * 64)['code'], flows.CHANGED)
        art = self.lock('script')
        self.assertEqual((art['flow']['status'], art['flow']['current']), ('running', 'art'))
        held = art['flow']['locks']['script']
        self.assertEqual((held['by'], held['role'], held['hash']), (self.actor, 'admin', waiting['next']['hash']))
        kinds = [j['kind'] for j in self.flow_jobs(flow['flowId']) if j['flowStage'] == 'art']
        cards = [a for a in self.ok(f'/episodes/{self.ep}/assets?limit=100')['items'] if a['isDefault']]
        self.assertEqual((kinds.count('description'), kinds.count('appearances'), len(kinds)), (len(cards), 2, len(cards) + 2),
                         'a description per card the episode names, who is in the shots per scene')
        self.assertFalse([j for j in self.flow_jobs(flow['flowId']) if j['kind'] in ('beats', 'camera')], 'the Cinematographer waits for the list lock')
        self.assertTrue(all(j['automatic'] for j in self.flow_jobs(flow['flowId'])))
        self.assertEqual(self.lock('storyboard', 409)['message'], 'Lock the cast and sets list first.')
        self.drain()
        cine = self.lock('list')
        self.assertEqual(cine['flow']['current'], 'cinematographer')
        self.assertEqual(self.stage(cine, 'cinematographer')['counts']['total'], 2 * len(self.shots))
        self.drain()
        checking = self.lock('storyboard')
        self.assertEqual([j['kind'] for j in self.stage(checking, 'continuity')['jobs']], ['continuity'], 'one scene has a join')
        self.assertEqual(self.drain(), [('continuity', 'succeeded')])
        finished = self.state()
        self.assertEqual((finished['flow']['status'], finished['flow']['current'], finished['canStart']), ('completed', None, True))
        self.assertEqual([s['status'] for s in finished['flow']['stages']], ['done'] * 4)
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.limb_task WHERE project_slug=%s'), 0, 'R13: the flow plans, it never renders')
        self.conn.rollback()
        with self.conn.cursor() as cur:
            cur.execute("SELECT DISTINCT data->>'type' FROM projectops.story_record WHERE kind='task' AND project_slug=%s", (self.slug,))
            self.assertEqual({row[0] for row in cur.fetchall()}, {'ASSET_EXTRACT', 'STORYBOARD_GENERATE'}, 'no generation was requested')
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['done'] if i.get('flow_id') == flow['flowId'])
        self.assertEqual((item['kind'], item['status']), ('crew_flow', 'succeeded'))

    def test_only_the_director_or_the_showrunner_locks(self):
        self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})
        waiting = self.state()
        self.assertEqual((waiting['flow']['status'], waiting['flow']['stages'][0]['status'], waiting['next']['lock']), ('waiting', 'skipped', 'script'))
        self.set_role('writer')
        self.assertFalse(self.state()['canLock'])
        refused = self.lock('script', 403, hash=waiting['next']['hash'])
        self.assertEqual(refused['code'], 'DRAMA_OPERATION_NOT_ALLOWED')
        self.assertIsNone(self.state()['flow']['locks']['script'])
        self.set_role('director')
        locked = self.lock('script', hash=waiting['next']['hash'])
        self.assertEqual((locked['flow']['locks']['script']['role'], locked['flow']['current']), ('director', 'art'))

    # ---- R24: a lock whose content changes stops the flow ----
    def test_a_changed_script_stops_the_flow_and_says_what_changed(self):
        self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})
        flow = self.lock('script')['flow']
        queued = [j for j in self.flow_jobs(flow['flowId']) if j['status'] == 'queued']
        self.assertTrue(queued)
        script = self.ok(f'/episodes/{self.ep}')['scriptContent']
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': script.replace('Kael leaves.', 'Kael leaves into the storm.')})
        stopped = self.state()['flow']
        self.assertEqual((stopped['status'], stopped['stop']['lock']), ('stopped', 'script'))
        self.assertIn('The text of scene "Scene 02: Departure" changed.', stopped['stop']['changed'])
        self.assertNotIn('was removed', ' '.join(stopped['stop']['changed']))
        self.assertIn('changed after the script lock', stopped['stop']['message'])
        self.assertEqual({j['status'] for j in self.flow_jobs(flow['flowId'])}, {'canceled'})
        self.assertEqual(self.drain(), [], 'nothing of the stopped flow runs')
        self.assertEqual(self.stage({'flow': stopped}, 'art')['status'], 'stopped')
        self.assertEqual(self.lock('list', 409)['code'], flows.STATE)
        self.assertEqual(self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})['flow']['status'], 'waiting',
                         'starting again makes a new flow')

    def test_the_worker_stops_a_flow_whose_list_changed_before_a_job_proposes(self):
        self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})
        self.lock('script')
        self.drain()
        art_proposals = self.state()['flow']['stages'][1]['counts']['proposals']
        flow = self.lock('list')['flow']
        kael = self.asset('CAST-01')
        self.ok(f"/assets/{kael['assetId']}", 'PATCH', {'prompt': 'Kael, a lean courier in a red parka.'})  # no GET in between
        proposals = self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s')
        self.alive()
        claimed = crew_jobs.claim(self.conn, 'test-worker', slug=self.slug)
        self.conn.commit()
        endpoint = FakeEndpoint()
        self.assertEqual(crew_jobs.execute(self.connect, claimed, 'test-worker', opener=endpoint), 'canceled')
        self.assertEqual(endpoint.requests, [], 'the model is never called')
        self.assertEqual(self.counted('SELECT count(*) FROM projectops.assistant_proposal WHERE project_slug=%s'), proposals)
        self.conn.rollback()
        stored = flows._load(self.conn, flow['flowId'])
        self.assertEqual((stored['status'], stored['stop']['lock']), ('stopped', 'list'))
        self.assertEqual(stored['stop']['changed'], ["CAST-01 Kael's card changed (name or description)."])
        self.assertEqual({j['status'] for j in self.flow_jobs(flow['flowId']) if j['flowStage'] == 'cinematographer'}, {'canceled'})
        self.assertGreaterEqual(art_proposals, 1)

    # ---- R40: the switch stops automatic stage jobs, never a manual ask ----
    def test_pause_blocks_the_flow_but_not_a_manual_ask(self):
        from project_assistant import automation
        self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})
        self.conn.rollback()
        automation.set_paused(self.conn, self.me, self.slug, {'paused': True, 'reason': 'GPU busy'})
        self.conn.commit()
        blocked = self.lock('script')['flow']
        self.assertEqual((blocked['status'], blocked['blocked']['code'], blocked['blocked']['stage']), ('blocked', 'paused', 'art'))
        self.assertIsNotNone(blocked['locks']['script'], "the director's lock stands")
        self.assertEqual(self.flow_jobs(blocked['flowId']), [], 'nothing was asked')
        manual = self.ask(f"/assets/{self.asset('CAST-01')['assetId']}/description-proposals")
        self.assertEqual((manual['status'], manual['automatic']), ('queued', False))
        self.assertEqual(self.drain(), [('description', 'succeeded')], 'a manual ask runs while paused')
        self.assertEqual(self.call(f'/episodes/{self.ep}/preproduction/resumptions', 'POST', {})[1]['data']['flow']['status'], 'blocked')
        self.conn.rollback()
        automation.set_paused(self.conn, self.me, self.slug, {'paused': False})
        self.conn.commit()
        resumed = self.ok(f'/episodes/{self.ep}/preproduction/resumptions', 'POST', {})['flow']
        self.assertEqual((resumed['status'], resumed['current'], resumed['blocked']), ('running', 'art', None))
        self.conn.rollback()
        automation.set_paused(self.conn, self.me, self.slug, {'paused': True})
        self.conn.commit()
        self.alive()
        self.assertIsNone(crew_jobs.claim(self.conn, 'test-worker', slug=self.slug), 'queued automatic jobs wait while paused')
        self.conn.rollback()
        automation.set_paused(self.conn, self.me, self.slug, {'paused': False})
        self.conn.commit()
        self.assertTrue(self.drain())

    def test_a_crew_that_is_not_ready_blocks_the_stage_until_resumed(self):
        self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})
        hash_ = self.state()['next']['hash']
        self.probe.stop()
        try:
            with patch.object(crew_readiness, '_probe', return_value=('down', None)):
                crew_readiness.forget()
                blocked = self.lock('script', hash=hash_)['flow']
        finally:
            self.probe.start()
            crew_readiness.forget()
        self.assertEqual((blocked['status'], blocked['blocked']['code']), ('blocked', 'not_ready'))
        self.assertIn("The crew can't work yet: the model server is not reachable", blocked['blocked']['message'])
        self.assertEqual(self.flow_jobs(blocked['flowId']), [])
        self.assertEqual(self.ok(f'/episodes/{self.ep}/preproduction/resumptions', 'POST', {})['flow']['status'], 'running')

    # ---- cancel as a whole, from the panel or the crew board ----
    def test_the_flow_is_canceled_as_a_whole_from_the_crew_board(self):
        started = self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {})['flow']
        board = self.request(f'/projects/api/{self.slug}/orchestration/board?limit=50')[1]
        item = next(i for i in board['working'] if i.get('flow_id') == started['flowId'])
        self.assertEqual((item['kind'], item['status'], item['can_cancel'], item['agent_key']), ('crew_flow', 'running', True, 'doc_writer'))
        self.assertIn('Pre-production', item['title'])
        self.assertGreaterEqual(board['counts']['working'], 2, 'the flow and its job')
        code, payload, _ = self.request(f"/projects/api/{self.slug}/orchestration/crew-flows/{started['flowId']}/cancel", method='POST', data={})
        self.assertEqual((code, payload['flow']['status']), (200, 'canceled'), payload)
        self.assertEqual({j['status'] for j in self.flow_jobs(started['flowId'])}, {'canceled'})
        again = self.request(f"/projects/api/{self.slug}/orchestration/crew-flows/{started['flowId']}/cancel", method='POST', data={})
        self.assertEqual(again[0], 409)
        self.assertEqual(self.state()['flow']['status'], 'canceled')
        second = self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})['flow']
        canceled = self.ok(f'/episodes/{self.ep}/preproduction/cancellations', 'POST', {'reason': 'not today'})['flow']
        self.assertEqual((canceled['flowId'], canceled['status']), (second['flowId'], 'canceled'))
        self.set_role('writer')
        third = self.ok(f'/episodes/{self.ep}/preproduction', 'POST', {'scriptFinal': True})['flow']
        self.assertTrue(third['canCancel'], 'who started it may cancel it')


if __name__ == '__main__':
    unittest.main()
