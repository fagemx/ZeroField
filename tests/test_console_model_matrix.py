"""SPEC_20 R37 role x model matrix and the hosted open-weights switch over real HTTP and PostgreSQL.

No real model, Ollama or hosted service is contacted: the model listing probe is replaced by a table of loopback
answers and fails the test if it is ever asked about a non-local endpoint.
"""
import json
import os
import unittest
import uuid
from unittest.mock import patch

from project_assistant import agent_registry, console_model_matrix as matrix, crew_readiness
from project_assistant import orchestration_store as db
from project_assistant.providers import local_url
from test_console_operations import OperationsFixture

PRESET = 'http://127.0.0.1:11434/v1'
HOSTED = 'https://openrouter.ai/api/v1'
HOSTED_MODEL = 'qwen/qwen3.8-27b'
OLLAMA = ['mistral:7b', 'qwen3.8:27b', 'qwen3.8:27b-16k']
PRICE = {HOSTED_MODEL: {'input_usd_per_million': 0.1, 'output_usd_per_million': 0.2, 'max_input_tokens': 32000, 'max_output_tokens': 2000,
                        'byte_bounded_tokenizer': True, 'base_url': HOSTED, 'kind': 'openai_compat'}}


class MatrixFixture(OperationsFixture):
    def setUp(self):
        super().setUp()
        self.use_model(PRESET)  # the deployment default is the local preset, like a fresh install
        self.listings = {PRESET: ('ok', set(OLLAMA))}
        self.probed = []

        def probe(base):
            self.probed.append(base)
            self.assertTrue(local_url(base), 'a non-local endpoint must never be probed: ' + base)
            return self.listings.get(base, ('down', None))

        patcher = patch.object(crew_readiness, '_probe', probe)
        patcher.start()
        self.addCleanup(patcher.stop)
        matrix.forget()
        self.addCleanup(matrix.forget)

    def view(self, refresh=True):
        crew_readiness.forget(self.slug)  # the roster check is cached for 30 s and forced rechecks are rate limited
        return self.api('/model-matrix' + ('?refresh=1' if refresh else ''))

    def rows(self, payload=None):
        return {row['agentKey']: row for row in (payload or self.view())['rows']}

    def choices(self, payload=None):
        return {choice['key']: choice for choice in (payload or self.view())['choices']}

    def choice(self, payload, model):
        found = [c for c in payload['choices'] if c['model'] == model]
        self.assertEqual(len(found), 1, model)
        return found[0]

    def version(self, agent='sheet_ops'):
        return self.rows()[agent]['version']

    def settings_version(self):
        return self.view()['policy']['settingsVersion']

    def price(self, prices=PRICE):
        body = {'version': self.api('/spend-rate-limits')['settings']['version'], 'model_pricing': prices}
        self.api('/spend-rate-limits', 'POST', body)

    def allow_key(self, name='OPENROUTER_API_KEY', value='synthetic-credential-0001'):
        patcher = patch.dict(os.environ, {'OPENBENCH_AGENT_KEY_ENVS': name, name: value})
        patcher.start()
        self.addCleanup(patcher.stop)

    def hosted_switch(self, enabled):
        return self.api('/provider-policy', 'POST', {'hosted_open_enabled': enabled, 'version': self.settings_version()})

    def make_hybrid(self):
        from project_docs import story_openapi as story
        os.environ.pop('OPENBENCH_PRODUCTION_POLICY', None)
        story.store(self.conn, 'policy_' + self.slug, 'policy', {'productionPolicy': 'hybrid_studio'}, self.slug)
        self.conn.commit()
        crew_readiness.forget(self.slug)


class MatrixViewTests(MatrixFixture):
    def test_every_role_shows_its_model_tier_capabilities_and_readiness(self):
        payload = self.view()
        self.assertEqual([r['agentKey'] for r in payload['rows']], ['coordinator', 'doc_writer', 'sheet_ops', 'qa_critic'])
        coordinator = self.rows(payload)['coordinator']
        self.assertEqual((coordinator['displayName'], coordinator['custom'], coordinator['enabled'], coordinator['inherits']), ('Showrunner', False, True, True))
        current = coordinator['current']
        self.assertEqual((current['model'], current['catalogId'], current['tier'], current['local'], current['baseUrl']),
                         ('qwen3.8:27b', 'ollama-qwen3.8-27b', 'local_open', True, PRESET))
        self.assertEqual(current['capabilities'], {'tools': True, 'tool_choice': False, 'json_schema': True, 'vision': True, 'image_url': False})
        self.assertEqual((current['contextTokens'], current['assumed'], coordinator['denials'], coordinator['state']), (16384, False, [], 'ok'))
        self.assertEqual((coordinator['readiness']['state'], coordinator['readiness']['blockers']), ('ready', []))
        self.assertEqual(payload['policy'], {'production': 'open_weights_only', 'hybrid': False, 'hostedOpenEnabled': False,
                                              'settingsVersion': payload['policy']['settingsVersion'], 'closedHidden': 2})
        self.assertEqual(payload['endpoints'], [{'baseUrl': PRESET, 'host': '127.0.0.1', 'port': 11434, 'state': 'ok', 'count': 3}])
        self.assertNotIn('config', coordinator)
        self.assertNotIn('synthetic', json.dumps(payload))

    def test_a_model_the_catalog_does_not_know_shows_assumed_capabilities_and_a_missing_model_blocks(self):
        self.api('/model-matrix', 'POST', {'agent_key': 'doc_writer', 'version': self.version('doc_writer'), 'base_url': PRESET, 'model': 'mistral:7b'})
        doc = self.rows()['doc_writer']
        self.assertEqual((doc['inherits'], doc['current']['model'], doc['current']['catalogId'], doc['current']['label'], doc['current']['assumed']),
                         (False, 'mistral:7b', None, None, True))
        self.assertEqual((doc['current']['tier'], doc['current']['contextTokens']), ('local_open', 8192))
        self.assertTrue(doc['current']['capabilities']['tools'] and not doc['current']['capabilities']['json_schema'])
        self.listings[PRESET] = ('ok', {'qwen3.8:27b'})  # mistral is no longer installed
        doc = self.rows()['doc_writer']
        self.assertEqual(doc['readiness']['state'], 'blocked')
        self.assertEqual([(b['code'], b['fix'], b['model']) for b in doc['readiness']['blockers']], [('model_missing', 'ollama_pull', 'mistral:7b')])
        self.listings[PRESET] = ('down', None)
        crew = self.rows()
        self.assertEqual(crew['doc_writer']['readiness']['state'], 'blocked')
        self.assertEqual(crew['doc_writer']['readiness']['blockers'][0]['code'], 'provider_unreachable')
        self.assertEqual(self.view()['endpoints'][0]['state'], 'down')

    def test_custom_agents_get_a_row_and_other_runtimes_do_not(self):
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'continuity_notes', 'display_name': 'Continuity Notes', 'version': 0})
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'shell_runner', 'display_name': 'CLI', 'version': 0, 'role_kind': 'observer'})
        self.conn.commit()
        rows = self.rows()
        self.assertEqual(list(rows)[-1], 'continuity_notes')
        self.assertEqual((rows['continuity_notes']['custom'], rows['continuity_notes']['displayName']), (True, 'Continuity Notes'))
        self.assertNotIn('shell_runner', rows)
        self.assertNotIn('studio:prepare', rows)
        agent_registry.save_agent(self.conn, self.me, self.slug, {'agent_key': 'continuity_notes', 'version': rows['continuity_notes']['version'], 'enabled': False})
        self.conn.commit()
        self.assertEqual(self.rows()['continuity_notes']['readiness']['state'], 'off')

    def test_choices_come_from_the_live_listing_and_the_catalog_and_never_from_a_remote_probe(self):
        payload = self.view()
        models = [(c['model'], c['source'], c['catalogId'], c['listed']) for c in payload['choices']]
        self.assertEqual(models, [('mistral:7b', 'listing', None, True), ('qwen3.8:27b', 'listing', 'ollama-qwen3.8-27b', True),
                                  ('qwen3.8:27b-16k', 'listing', 'ollama-qwen3.8-27b', True),
                                  (HOSTED_MODEL, 'catalog', 'openrouter-qwen3.8-27b', None),
                              ('deepseek/deepseek-v4.1-flash-1017', 'catalog', 'openrouter-deepseek-v4.1-flash-1017', None)])
        self.assertEqual(set(self.probed), {PRESET})
        hosted = self.choice(payload, HOSTED_MODEL)
        self.assertEqual((hosted['tier'], hosted['local'], hosted['baseUrl'], hosted['host'], hosted['apiKeyEnv'], hosted['keyConfigured']),
                         ('hosted_open', False, None, 'openrouter.ai', 'OPENROUTER_API_KEY', False))
        self.assertEqual((hosted['allowed'], hosted['denials']), (False, ['hosted_open_disabled', 'key_not_allowed', 'pricing_missing']))
        self.assertEqual(hosted['capabilities']['tool_choice'], True)
        self.assertTrue(all(c['allowed'] for c in payload['choices'] if c['local']))
        self.assertNotIn('openai-gpt-4.1', json.dumps(payload), 'closed presets are hidden under open_weights_only')
        # An installed catalog model is offered once, by its listed name; one that is not installed is still offered.
        self.listings[PRESET] = ('ok', {'mistral:7b'})
        payload = self.view()
        ollama = [c for c in payload['choices'] if c['catalogId'] == 'ollama-qwen3.8-27b']
        self.assertEqual([(c['model'], c['source'], c['listed']) for c in ollama], [('qwen3.8:27b', 'catalog', False)])
        self.listings[PRESET] = ('down', None)
        ollama = [c for c in self.view()['choices'] if c['catalogId'] == 'ollama-qwen3.8-27b']
        self.assertEqual([(c['source'], c['listed']) for c in ollama], [('catalog', None)])

    def hosted_role(self):
        self.price()
        self.allow_key()
        self.hosted_switch(True)
        self.api('/model-matrix', 'POST', {'agent_key': 'sheet_ops', 'version': self.version(), 'catalog_id': 'openrouter-qwen3.8-27b'})

    def test_a_hosted_role_shows_what_still_blocks_it_and_is_never_probed(self):
        self.hosted_role()
        row = self.rows()['sheet_ops']
        self.assertEqual((row['current']['tier'], row['current']['local'], row['current']['baseUrl'], row['current']['host']),
                         ('hosted_open', False, None, 'openrouter.ai'))
        self.assertEqual((row['current']['catalogId'], row['denials']), ('openrouter-qwen3.8-27b', []))
        self.assertEqual((row['readiness']['state'], row['readiness']['reachable']), ('blocked', None))
        codes = {b['code'] for b in row['readiness']['blockers']}
        self.assertIn('network_policy', codes, 'the environment still has to allow the host')
        self.assertNotIn('provider_unreachable', codes)
        self.assertEqual(set(self.probed), {PRESET})
        self.assertNotIn('synthetic-credential', json.dumps(self.view()))

    def test_a_hosted_role_with_nothing_blocking_is_untested_not_ready(self):
        from project_assistant import agent_console_store as console
        self.hosted_role()
        environment = console.get_resource(self.conn, self.me, self.slug, 'environment', 'env_local_4090')
        console.save_resource(self.conn, self.me, self.slug, 'environment', {'env_key': 'env_local_4090', 'version': environment['version'], 'network_access': 'full'})
        self.conn.commit()
        with patch('urllib.request.OpenerDirector.open', side_effect=AssertionError('no outbound request')):
            row = self.rows()['sheet_ops']
        self.assertEqual((row['readiness']['state'], row['readiness']['blockers'], row['readiness']['reachable']), ('untested', [], None))
        self.assertEqual(set(self.probed), {PRESET}, 'the hosted endpoint was never listed or contacted')

    def test_hybrid_lists_closed_presets_with_their_own_reasons(self):
        self.make_hybrid()
        payload = self.view()
        self.assertEqual((payload['policy']['production'], payload['policy']['hybrid'], payload['policy']['closedHidden']), ('hybrid_studio', True, 0))
        gpt = self.choice(payload, 'gpt-4.1')
        self.assertEqual((gpt['tier'], gpt['denials']), ('closed', ['key_not_allowed', 'pricing_missing']))
        self.assertEqual({c['catalogId'] for c in payload['choices']} - {None}, {'ollama-qwen3.8-27b', 'openrouter-qwen3.8-27b', 'openrouter-deepseek-v4.1-flash-1017', 'openai-gpt-4.1', 'gemini-2.5-pro'})
        self.assertEqual(self.choice(payload, HOSTED_MODEL)['denials'], ['key_not_allowed', 'pricing_missing'],
                         'hybrid_studio allows every tier; the key and the price ceiling still apply')

    def test_only_the_showrunner_sees_the_matrix(self):
        self.role('member')
        self.api('/model-matrix', status=403)
        self.api('/model-matrix', 'POST', {'agent_key': 'sheet_ops', 'version': 1, 'inherit': True}, 403)
        self.api('/provider-policy', 'POST', {'hosted_open_enabled': True, 'version': 1}, 403)
        self.assertEqual(self.probed, [], 'a refused request probes nothing')


class MatrixChangeTests(MatrixFixture):
    def apply(self, body, status=200, agent='sheet_ops'):
        return self.api('/model-matrix', 'POST', {'agent_key': agent, 'version': self.version(agent), **body}, status)

    def stored(self, agent):
        self.conn.rollback()
        return agent_registry.get_agent(self.conn, self.slug, agent, effective=False)

    def test_a_local_model_is_picked_from_the_listing_through_the_ordinary_agent_save(self):
        before = self.stored('sheet_ops')
        result = self.apply({'base_url': PRESET, 'model': 'qwen3.8:27b-16k'})['agent']
        self.assertEqual((result['agentKey'], result['inherits'], result['version']), ('sheet_ops', False, before['version'] + 1))
        saved = self.stored('sheet_ops')
        self.assertEqual(saved['provider_config'], {'kind': 'openai_compat', 'base_url': PRESET, 'model': 'qwen3.8:27b-16k'})
        row = self.rows()['sheet_ops']
        self.assertEqual((row['inherits'], row['current']['model'], row['current']['catalogId'], row['current']['assumed']), (False, 'qwen3.8:27b-16k', 'ollama-qwen3.8-27b', False))
        self.assertEqual(self.stored('coordinator')['provider_config'], {}, 'other roles keep inheriting')
        self.conn.rollback()
        audit = db.many(self.conn, "SELECT action FROM projectops.audit_log WHERE project_slug=%s AND action IN ('agent_profile','console_agent_model') ORDER BY id", (self.slug,))
        self.assertEqual(audit[-2:], ['agent_profile', 'console_agent_model'])
        # Pointing the role back at the default is a save of an empty provider configuration.
        self.assertTrue(self.apply({'inherit': True})['agent']['inherits'])
        self.assertEqual(self.stored('sheet_ops')['provider_config'], {})

    def test_a_stale_page_cannot_overwrite_a_newer_save(self):
        stale = self.version()
        self.apply({'inherit': True})
        payload = self.api('/model-matrix', 'POST', {'agent_key': 'sheet_ops', 'version': stale, 'base_url': PRESET, 'model': 'mistral:7b'}, 409)
        self.assertEqual(payload['code'], 'VERSION_CONFLICT')
        self.assertEqual(self.stored('sheet_ops')['provider_config'], {})

    def test_hosted_open_weights_need_the_switch_a_key_reference_and_a_price_ceiling(self):
        body = {'catalog_id': 'openrouter-qwen3.8-27b'}
        refused = self.apply(body, 409)
        self.assertEqual(refused['code'], 'hosted_open_disabled')
        self.assertIn('hosted open-weights', refused['error'])
        self.hosted_switch(True)
        self.assertEqual(self.apply(body, 409)['code'], 'key_not_allowed')
        self.allow_key()
        self.assertEqual(self.apply(body, 409)['code'], 'pricing_missing')
        self.price()
        self.apply(body)
        saved = self.stored('sheet_ops')['provider_config']
        self.assertEqual(saved, {'kind': 'openai_compat', 'base_url': HOSTED, 'model': HOSTED_MODEL, 'api_key_env': 'OPENROUTER_API_KEY'})
        self.assertNotIn('synthetic-credential', json.dumps(saved))
        self.conn.rollback()
        audit = db.many(self.conn, "SELECT detail FROM projectops.audit_log WHERE project_slug=%s AND action='console_agent_model' ORDER BY id DESC", (self.slug,))
        self.assertEqual(audit[0], {'tier': 'hosted_open', 'model': HOSTED_MODEL, 'host': 'openrouter.ai'})
        # Turning the switch off again leaves the role pointed at the model but says it cannot run.
        self.hosted_switch(False)
        row = self.rows()['sheet_ops']
        self.assertEqual(row['denials'], ['hosted_open_disabled'])
        blockers = [b for b in row['readiness']['blockers'] if b['code'] == 'network_policy']
        self.assertEqual([(b['fix'], b['tier'], b['model']) for b in blockers], [('enable_hosted_open', 'hosted_open', HOSTED_MODEL)])

    def test_closed_models_need_the_hybrid_policy_and_other_remote_endpoints_are_refused(self):
        self.hosted_switch(True)  # the hosted switch never opens closed models
        self.assertEqual(self.apply({'catalog_id': 'openai-gpt-4.1'}, 409)['code'], 'closed_needs_hybrid')
        self.assertEqual(self.apply({'catalog_id': 'no-such-model'}, 400)['code'], 'POLICY_DENIED')
        refused = self.apply({'base_url': 'https://models.example.test/v1', 'model': 'closed-model'}, 400)
        self.assertEqual(refused['code'], 'not_in_catalog')
        self.assertEqual(self.stored('sheet_ops')['provider_config'], {})
        self.make_hybrid()
        self.allow_key('OPENAI_API_KEY')
        self.assertEqual(self.apply({'catalog_id': 'openai-gpt-4.1'}, 409)['code'], 'pricing_missing')
        self.price({'gpt-4.1': {**PRICE[HOSTED_MODEL], 'base_url': 'https://api.openai.com/v1'}})
        self.apply({'catalog_id': 'openai-gpt-4.1'})
        row = self.rows()['sheet_ops']
        self.assertEqual((row['current']['tier'], row['current']['host'], row['denials']), ('closed', 'api.openai.com', []))

    def test_malformed_changes_are_refused_before_anything_is_saved(self):
        for body in ({}, {'inherit': True, 'model': 'mistral:7b', 'base_url': PRESET}, {'inherit': False}, {'base_url': PRESET},
                     {'model': 'mistral:7b'}, {'base_url': PRESET, 'model': 'two words'}, {'base_url': PRESET, 'model': 'x' * 161},
                     {'catalog_id': 'ollama-qwen3.8-27b', 'model': 'mistral:7b', 'base_url': PRESET}, {'catalog_id': 7},
                     {'inherit': True, 'extra': 1}, {'base_url': 'http://127.0.0.1:11434/v1?key=1', 'model': 'mistral:7b'}):
            with self.subTest(body=body):
                self.apply(body, 400)
        self.api('/model-matrix', 'POST', {'agent_key': 'nobody', 'version': 1, 'inherit': True}, 404)
        self.api('/model-matrix', 'POST', {'agent_key': 'sheet_ops', 'inherit': True}, 400)
        self.assertEqual(self.stored('sheet_ops')['provider_config'], {})


class HostedSwitchTests(MatrixFixture):
    def test_the_switch_saves_with_the_settings_version_and_is_audited(self):
        self.assertFalse(self.view()['policy']['hostedOpenEnabled'])
        start = self.settings_version()
        policy = self.api('/provider-policy', 'POST', {'hosted_open_enabled': True, 'version': start})['policy']
        self.assertEqual((policy['hostedOpenEnabled'], policy['settingsVersion'], policy['production']), (True, start + 1, 'open_weights_only'))
        self.assertTrue(self.view()['policy']['hostedOpenEnabled'])
        self.assertEqual(self.api('/provider-policy', 'POST', {'hosted_open_enabled': True, 'version': start}, 409)['code'], 'VERSION_CONFLICT')
        for body in ({'hosted_open_enabled': 'yes', 'version': start + 1}, {'hosted_open_enabled': 1, 'version': start + 1},
                     {'version': start + 1}, {'hosted_open_enabled': True}, {'hosted_open_enabled': True, 'version': start + 1, 'extra': 1}):
            with self.subTest(body=body):
                self.api('/provider-policy', 'POST', body, 400)
        off = self.api('/provider-policy', 'POST', {'hosted_open_enabled': False, 'version': start + 1})['policy']
        self.assertEqual((off['hostedOpenEnabled'], off['settingsVersion']), (False, start + 2))
        self.conn.rollback()
        audit = db.many(self.conn, "SELECT detail FROM projectops.audit_log WHERE project_slug=%s AND action='console_hosted_open' ORDER BY id", (self.slug,))
        self.assertEqual(audit, [{'hosted_open_enabled': True}, {'hosted_open_enabled': False}])
        self.assertEqual(db.one(self.conn, 'SELECT provider_policy FROM projectops.agent_console_settings WHERE project_slug=%s', (self.slug,)), {'hosted_open_enabled': False})

    def test_the_switch_leaves_the_other_settings_alone(self):
        before = self.api('/spend-rate-limits')['settings']
        self.hosted_switch(True)
        after = self.api('/spend-rate-limits')['settings']
        self.assertEqual({k: v for k, v in after.items() if k != 'version'}, {k: v for k, v in before.items() if k != 'version'})


class QueueFailureClassTests(MatrixFixture):
    def test_a_failed_dispatch_carries_only_a_known_failure_class(self):
        run = str(uuid.uuid4())
        db.execute(self.conn, """INSERT INTO projectops.orchestration_run(id,project_slug,created_by,client_request_id,request_hash,objective)
            VALUES(%s,%s,%s,%s,'h','Private objective')""", (run, self.slug, self.actor, run))
        for output, status in (({'error': 'ECONNREFUSED 127.0.0.1:11434', 'failure': 'local'}, 'failed'), ({'error': 'odd', 'failure': 'bogus'}, 'failed'),
                               ({'error': 'old shape'}, 'failed'), ({'error': 'timed out', 'failure': 'timeout'}, 'timeout')):
            task = str(uuid.uuid4())
            db.execute(self.conn, "INSERT INTO projectops.orchestration_task(id,run_id,project_slug,title,spec) VALUES(%s,%s,%s,'t','s')", (task, run, self.slug))
            db.execute(self.conn, """INSERT INTO projectops.orchestration_dispatch(id,run_id,task_id,project_slug,admission_no,agent_key,slot_key,profile_snapshot,deadline_at,status,error,output_json,finished_at)
                VALUES(%s,%s,%s,%s,%s,'sheet_ops','main','{}',NOW()+INTERVAL '1 hour',%s,%s,%s::jsonb,NOW())""",
                       (str(uuid.uuid4()), run, task, self.slug, int(uuid.uuid4().int % 1_000_000_000), status, output['error'], json.dumps(output)))
        self.conn.commit()
        failed = {d['error']: d for d in self.api('/queue')['dispatches']['failed']}
        self.assertEqual(failed['ECONNREFUSED 127.0.0.1:11434']['failure'], 'local')
        self.assertIsNone(failed['odd']['failure'], 'a value that is not a class is dropped')
        self.assertIsNone(failed['old shape']['failure'])
        self.assertIsNone(failed['timed out']['failure'], 'only a failed dispatch is classified')


if __name__ == '__main__':
    unittest.main()
