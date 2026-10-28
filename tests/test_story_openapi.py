"""Story contract tests use real HTTP, PostgreSQL tabs and FFmpeg; GPU is isolated."""
import io
import json
import os
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

from project_docs import markdown_import, repository as repo, service, story_openapi as story, templates
from project_docs.doc_schema import validate_doc
from project_assistant import limb_worker as worker
import test_product_http as product_fixture


class StoryPureTests(unittest.TestCase):
    def test_offline_adaptation_modes_and_preserved_source(self):
        idea = story.adapt_source_to_script('A lone astronomer discovers a brass dial counting down.', mode='idea')
        self.assertEqual(idea, story.adapt_source_to_script('A lone astronomer discovers a brass dial counting down.', mode='idea'))
        self.assertEqual(len(story.scene_sections(idea)), 3)
        for tag in ('@CAST-01', '@CAST-02', '@SET-03', '@PROP-01'):
            self.assertIn(tag, idea)
        novel = 'Mira entered the station. "The signal is back."\n\nEvan replied, "Then we must leave."\n\nLater, Mira turned toward the brass dial.'
        adapted = story.adapt_source_to_script(novel, mode='novel')
        self.assertEqual(len(story.scene_sections(adapted)), 3)
        self.assertIn('Character: Mira', adapted)
        self.assertIn('Character: Evan', adapted)
        self.assertIn('@CAST-01: "The signal is back."', adapted)
        self.assertIn('@CAST-02: "Then we must leave."', adapted)
        self.assertIn('## Scene 01: INT. STATION - NIGHT', story.adapt_source_to_script('INT. STATION - NIGHT\nMIRA: "Stay."', 'script'))
        chinese = story.adapt_source_to_script('小明說：「快走！」\n\n小美回答：「等等！」\n\n小明走進房間。小美轉身關門。', 'novel')
        self.assertEqual(chinese.count('Character:'), 2)
        self.assertIn('Character: 小明 @CAST-01', chinese)
        self.assertIn('Character: 小美 @CAST-02', chinese)
        self.assertIn('@CAST-01 走進房間', chinese)
        self.assertIn('@CAST-02 轉身關門', chinese)
        for kwargs in ({'mode': 'unknown'}, {'mode': []}, {'target_scenes': 0}, {'target_scenes': 13}, {'target_scenes': True}, {'target_scenes': '3'}):
            with self.assertRaises(ValueError):
                story.adapt_source_to_script('A story.', **kwargs)
        for source in ('', ' ', None, 'x' * 500001):
            with self.assertRaises(ValueError):
                story.adapt_source_to_script(source)

    def test_character_code_allocation_and_rich_asset_descriptions(self):
        from project_docs.story_adaptation import extract_asset_details, allocated_characters
        source = 'Character: Mara @CAST-02 (silver hair)\nCharacter: Evan (green coat)\nMARA: "Wait."\nProp: Brass dial @PROP-07\n\nScene 01: Rooftop Rain\nEnvironment: @SET-07, moonlight through rain.\n@CAST-02:night approaches. @CAST-02#injured (torn sleeve) turns.'
        people = allocated_characters(source)
        self.assertEqual([(name, code) for name, _, code in people], [('Mara', 'CAST-02'), ('Evan', 'CAST-01')])
        details = extract_asset_details(source, story.scene_sections(source))
        self.assertEqual(details['CAST-02']['name'], 'Mara')
        self.assertIn('silver hair', details['CAST-02']['prompt'])
        self.assertEqual(details['CAST-02:NIGHT']['kind'], 'OUTFIT')
        self.assertIn('torn sleeve', details['CAST-02:INJURED']['prompt'])
        self.assertIn('foreground/midground/background', details['SET-07']['prompt'])
        self.assertIn('moonlight', details['SET-07']['prompt'])
        self.assertEqual(details['PROP-07']['name'], 'Brass dial')
        adapted = story.adapt_source_to_script('Character: Mara @CAST-07 (silver hair)\nA secret is discovered.', 'idea')
        self.assertIn('Shot 1: @CAST-07', adapted)
        self.assertIn('Shot 2: @CAST-01:', adapted)
        appearance = story.adapt_source_to_script('Mara (silver hair, dark coat) entered the room. "Wait."\n\nEvan replied, "Stay."', 'novel')
        self.assertIn('Character: Mara @CAST-01 (silver hair, dark coat)', appearance)

    def test_shot_beats_compatibility_dialogue_and_grammar(self):
        for mode in ('auto', 'scene', 'cinematic'):
            self.assertEqual(story.scene_shot_beats('@CAST-01 walks past @PROP-01.', mode), ['@CAST-01 walks past @PROP-01.'])
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 walks across\nthe room.', 'auto')), 1)
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 walks.', 'cinematic_multi')), 2)
        raw = '@CAST-01 enters.\n\n@CAST-02: "We are out of time."\n\nClose-up of tearful eyes.'
        beats = story.scene_shot_beats(raw)
        self.assertEqual(len(beats), 3)
        self.assertEqual(len(story.scene_shot_beats(raw, 'scene')), 1)
        self.assertEqual(len(story.scene_shot_beats('@CAST-01 enters. @CAST-01 stops. @CAST-01 turns.', 'cinematic')), 3)
        self.assertEqual(story.scene_shot_beats('@CAST-01 enters. @CAST-01: "Wait. Stay here." @CAST-01 turns.', 'cinematic'),
                         ['@CAST-01 enters.', '@CAST-01: "Wait. Stay here."', '@CAST-01 turns.'])
        grammar = [story.infer_shot_grammar(b, i, len(beats)) for i, b in enumerate(beats)]
        self.assertIn('ARRI Alexa', grammar[0]['opticalRig'])
        self.assertEqual([g['previsPlan']['lens'] for g in grammar], [35, 50, 85])
        self.assertEqual(grammar[0]['previsPlan']['action'], 'walkin')
        self.assertEqual(grammar[1]['dialogue'][0]['speaker'], 'CAST-02')
        self.assertEqual(grammar[1]['dialogue'][0]['line'], 'We are out of time.')
        self.assertGreater(grammar[1]['dialogue'][0]['estimatedSeconds'], 0)
        self.assertEqual(grammar[2]['cameraMotion'], 'Crane Up')
        self.assertEqual(story.infer_shot_grammar('Close-up of a trembling hand.', 1, 3)['cameraMotion'], 'Slow Dolly In')
        self.assertEqual(story.infer_shot_grammar('MARA: "Stay."', 0, 2)['cameraMotion'], 'Static Tripod')
        self.assertEqual(story.infer_shot_grammar('@CAST-01 chases the drone.', 0, 2)['cameraMotion'], 'Handheld Tracking')
        self.assertEqual(story.infer_shot_grammar('MARA: We should leave.', 1, 2)['dialogue'][0]['line'], 'We should leave.')
        from project_docs.story_adaptation import character_details
        self.assertEqual(character_details('MARA: We should leave.\nEnvironment: Station\nProp: Key'), [('MARA', '', None)])

    COURIER = 'A delivery courier is secretly an immortal sage.'

    def test_condition_collisions_differ_by_genre_and_carry_prop_slices(self):
        from project_docs.story_adaptation import propose_story_collisions
        seen = set()
        for genre in ('melodrama', 'xianxia', 'comedy', 'suspense', 'general'):
            proposal = propose_story_collisions(self.COURIER, 'manju', genre)
            cards = proposal['candidates']
            self.assertEqual([c['id'] for c in cards], ['col_1', 'col_2', 'col_3', 'col_4'])
            self.assertEqual({c['focus'] for c in cards}, {'collision', 'restraint', 'reversal', 'negative_space'})
            for card in cards:
                self.assertTrue(card['conditionA'] and card['conditionB'] and card['conditionA'] != card['conditionB'])
                self.assertEqual(len(set(card['propSlice'])), 3)
                self.assertNotIn(card['conditionA'], seen)
                seen.add(card['conditionA'])
            self.assertEqual((proposal['genreLens'], proposal['mediumLens']), (genre, 'manju'))
            self.assertEqual(set(proposal['forms']), {'actors', 'prop', 'setting'})
        self.assertIn('incense', propose_story_collisions(self.COURIER, 'cinema', 'xianxia')['candidates'][0]['conditionA'])
        for idea, place in (('Kael learns the beacon at the lighthouse is a countdown.', 'the lighthouse'),
                            ('A lone astronomer discovers a brass dial in the old observatory.', 'the old observatory')):
            self.assertEqual(propose_story_collisions(idea, 'manju', 'suspense')['forms']['setting'], place)
        self.assertNotIn("'s own old the", str(propose_story_collisions(self.COURIER, 'manju', 'suspense')['candidates']))
        for lenses in (('film', 'general'), ('manju', 'horror'), ([], 'general')):
            with self.assertRaises(ValueError):
                propose_story_collisions(self.COURIER, *lenses)

    def test_choice_trace_strikes_unchecked_and_weaves_kept_and_extra_into_scenes_one_and_two(self):
        from project_docs.story_adaptation import propose_story_collisions
        cards = propose_story_collisions(self.COURIER, 'manju', 'comedy')['candidates']
        trace = {'focus': 'collision', 'keptLabels': [cards[0]['label'], cards[2]['label']],
                 'uncheckedLabels': [cards[1]['label'], 'amnesia'], 'extraCondition': 'The courier never says their real name.'}
        script = story.adapt_source_to_script(self.COURIER + ' He has amnesia.', 'idea', medium_lens='manju', genre_lens='comedy', choice_trace=trace)
        for kept in (cards[0]['label'], cards[2]['label'], 'is mid-duel with @CAST-02', 'steps on @PROP-01'):
            self.assertIn(kept, script)
        for struck in (cards[1]['label'], "sign for a stranger's parcel", 'amnesia'):
            self.assertNotIn(struck.casefold(), script.casefold())
        scenes = story.scene_sections(script)
        self.assertTrue(all(trace['extraCondition'] in s['content'] for s in scenes[:2]))
        self.assertNotIn(trace['extraCondition'], scenes[2]['content'])
        # P1: the prop's origin → turn → current states run through the scenes in order.
        slices = [s.replace('the delivery phone', '@PROP-01') for s in cards[0]['propSlice']]
        self.assertEqual([next(i for i, s in enumerate(slices) if s in scene['content']) for scene in scenes], [0, 1, 2])
        self.assertIn('Lens: manju × comedy', script)
        self.assertEqual(story.scene_shot_beats(scenes[0]['content'])[0][:11], '[Cold open]')  # Lens/Constraint lines are never shots
        with self.assertRaises(ValueError):
            story.adapt_source_to_script(self.COURIER, 'idea', choice_trace={'focus': 'anger'})
        with self.assertRaises(ValueError):
            story.adapt_source_to_script(self.COURIER, 'idea', choice_trace={'keptLabels': 'all'})

    def test_choice_contrast_detects_a_switch_and_injects_an_action_beat(self):
        from project_docs.story_adaptation import compute_choice_contrast
        traces = lambda *focuses: [{'focus': f} for f in focuses]
        contrast = compute_choice_contrast(traces('restraint', 'restraint'), 'reversal')
        self.assertEqual((contrast['contrastDetected'], contrast['dominantFocus']), (True, 'restraint'))
        self.assertIn('without explanation', contrast['contrastCue'])
        self.assertTrue(compute_choice_contrast(traces('collision', 'reversal', 'collision'), 'negative_space')['contrastDetected'])
        for history, focus in ((traces('restraint'), 'reversal'), (traces('restraint', 'restraint'), 'collision'),
                               (traces('restraint', 'restraint', *['overall'] * 4), 'reversal'), ([], 'reversal')):
            self.assertFalse(compute_choice_contrast(history, focus)['contrastDetected'])
        trace = {'focus': 'reversal'}
        with_contrast = story.adapt_source_to_script(self.COURIER, 'idea', medium_lens='cinema', choice_trace=trace, contrast=contrast)
        beat = next(line for line in with_contrast.splitlines() if '[Contrast]' in line)
        self.assertIn('Twice before, @CAST-01 lowers the hand', beat)
        self.assertIn('This time @CAST-01 sweeps', beat)
        self.assertNotIn('[Contrast]', story.adapt_source_to_script(self.COURIER, 'idea', medium_lens='cinema', choice_trace=trace))

    def test_medium_lens_cuts_the_same_skeleton_into_different_structures_and_camera_grammar(self):
        from project_docs.story_adaptation import script_medium_lens
        trace = {'focus': 'overall', 'keptLabels': [], 'uncheckedLabels': [], 'extraCondition': ''}
        scripts = {m: story.adapt_source_to_script(self.COURIER, 'idea', medium_lens=m, genre_lens='melodrama', choice_trace=trace) for m in ('manju', 'cinema', 'storybook')}
        self.assertEqual(len(set(scripts.values())), 3)
        manju, cinema, storybook = scripts['manju'], scripts['cinema'], scripts['storybook']
        self.assertTrue(manju.startswith('Lens: manju') and '[Cold open]' in manju and '[Cliffhanger]' in manju)
        self.assertEqual(manju.count(': "'), 6)  # two dialogue turns in every scene
        self.assertTrue('[Omission]' in cinema and 'foreground doorway' in cinema and '[Cliffhanger]' not in cinema)
        self.assertEqual(cinema.count(': "'), 0)
        for line in ('The first time', 'The second time', 'The third time', '[Page turn]', 'Narration:'):
            self.assertIn(line, storybook)
        self.assertIn('@CAST-01:revealed', manju)  # melodrama casts the reversal variant
        grammar = {}
        for medium, script in scripts.items():
            self.assertEqual(script_medium_lens(script), medium)
            beats = [b for scene in story.scene_sections(script) for b in story.scene_shot_beats(scene['content'])]
            grammar[medium] = [story.infer_shot_grammar(b, i, len(beats), medium) for i, b in enumerate(beats)]
        self.assertTrue({g['previsPlan']['lens'] for g in grammar['manju']} <= {50, 85})
        self.assertTrue({g['cameraMotion'] for g in grammar['manju']} <= {'Slow Dolly In', 'Handheld Tracking'})
        self.assertTrue({'Slow Dolly In', 'Orbit 45°'} <= {g['cameraMotion'] for g in grammar['cinema']})
        self.assertEqual([g['cameraMotion'] for g in grammar['storybook']][-2:], ['Static Tripod', 'Crane Up'])
        self.assertIsNone(script_medium_lens(story.adapt_source_to_script(self.COURIER, 'idea')))
        for beat, index, total in (('@CAST-01 enters.', 0, 3), ('Close-up of tearful eyes.', 2, 3), ('MARA: "Stay."', 1, 2)):
            self.assertEqual(story.infer_shot_grammar(beat, index, total), story.infer_shot_grammar(beat, index, total, None))

    def test_a_variant_tag_opening_a_beat_is_action_not_a_speaker_cue(self):
        for beat in ('@CAST-88:night enters.', '@CAST-01:revealed takes off the apron; underneath is a tailored suit.'):
            self.assertEqual(story.infer_shot_grammar(beat, 1, 3)['dialogue'], [])
        for beat, speaker in (('@CAST-01:night: "Wait."', 'CAST-01:night'), ('@CAST-02#injured: "Help."', 'CAST-02:injured'),
                              ('@CAST-02: "Stay."', 'CAST-02'), ('CAST-03: Go.', 'CAST-03'), ('@CAST-02：「十秒。」', 'CAST-02')):
            self.assertEqual(story.infer_shot_grammar(beat, 1, 3)['dialogue'][0]['speaker'], speaker)
        for genre, variant in (('melodrama', ':revealed'), ('xianxia', ':awakened')):
            script = story.adapt_source_to_script(self.COURIER, 'idea', medium_lens='manju', genre_lens=genre)
            beats = story.scene_shot_beats(story.scene_sections(script)[-1]['content'])
            reveal = next(i for i, beat in enumerate(beats) if variant in beat)
            self.assertEqual(story.infer_shot_grammar(beats[reveal], reveal, len(beats), 'manju')['dialogue'], [])

    def test_no_label_rule_flags_and_sanitizes_and_engine_output_is_always_clean(self):
        from project_docs.story_adaptation import audit_narrative_voice, sanitize_narrative_voice
        labelled = '她心裡壓著這件事。他霸氣外露地看著眾人。Mira feels deep inside that time is running out.'
        audit = audit_narrative_voice(labelled)
        self.assertFalse(audit['ok'])
        self.assertEqual(audit['violations'], ['心裡壓著', '霸氣外露', 'feels deep inside'])
        clean = sanitize_narrative_voice(labelled)
        self.assertTrue(audit_narrative_voice(clean)['ok'])
        self.assertIn('Mira checks the @PROP-01 indicator as the mark advances.', clean)
        self.assertIn('他將 @PROP-01 重重按在檯面上，全場停下動作。', clean)
        self.assertGreater(audit_narrative_voice(clean)['concreteScore'], audit['concreteScore'])
        novel = 'Mira entered the station. The atmosphere is very tense.\n\nEvan secretly thinks to himself that she lied.'
        for medium in ('manju', 'cinema', 'storybook'):
            self.assertTrue(audit_narrative_voice(story.adapt_source_to_script(novel, 'novel', medium_lens=medium,
                choice_trace={'extraCondition': '氣氛十分緊張，沒有人說話。'}))['ok'])

    def test_pagination_and_scene_parser(self):
        result = story.page(list(range(6)), {"limit": "2"})
        self.assertEqual(result["items"], [0, 1])
        self.assertEqual(story.page(list(range(6)), {"limit": "2", "cursor": result["nextCursor"]})["items"], [2, 3])
        for query in [{"limit": "0"}, {"limit": "101"}, {"cursor": "broken"}]:
            with self.assertRaises(story.StoryError):
                story.page([], query)
        self.assertEqual(len(story.scene_sections("Scene 01: Arrival\n@CAST-01 enters\nScene 02: Exit\nLeaves")), 2)

    def test_dynamic_catalog_and_aliases(self):
        apps = story.catalog()
        self.assertTrue({"h3-short-video-v3", "h3-reference", "ltx25-openjutsu", "flux-soul-cast"} <= {a["card_id"] for a in apps})
        self.assertTrue(all(isinstance(a["skuId"], str) for a in apps))
        self.assertEqual(story.resolve_app("2109942725885075458", "video")["card_id"], "h3-short-video-v3")
        with self.assertRaises(story.StoryError):
            story.resolve_app("h3-reference", "image")

    def test_worker_variant_references_and_hash_alias(self):
        task = {"input": {"rows": [{"tab_key": "cinema-studio", "cells": ["@CAST-01#night"]}], "tabs": [
            {"tab_key": "cinema-studio", "tables": [{"headers": ["Action Prompt"]}]},
            {"tab_key": "soul-cast", "tables": [{"headers": ["Asset ID", "Name", "Appearance", "Reference Image"], "rows": [
                {"cells": ["CAST-01", "Courier", "Base jacket", "![Image](/projects/api/demo/assets/pa_" + "a" * 32 + ")"]},
                {"cells": ["CAST-01:night", "Courier at night", "Night jacket", ""]}]}]}]}}
        ctx = worker.resolve_studio_context(task)
        self.assertEqual(ctx["resolved_assets"][0]["asset_id"], "CAST-01:NIGHT")
        self.assertEqual(ctx["resolved_assets"][0]["appearance_prompt"], "Night jacket")
        self.assertTrue(ctx["asset_images"])

    def test_story_adapter_uses_frozen_graph_and_card_values(self):
        graph = {'1': {'class_type': 'SaveImage', 'inputs': {}}}
        card = worker.load_studio_card('local-smoke')
        paths = []
        def execute(task, config, head):
            paths.append(Path(config['workflow']))
            self.assertEqual(json.loads(paths[0].read_text()), graph)
            self.assertEqual(config['card_values'], {'6.text': 'director prompt'})
            self.assertEqual(config['card']['card_id'], 'local-smoke')
            return {'asset_url': '/test.png'}
        with patch.object(worker, 'comfyui', side_effect=execute):
            self.assertEqual(worker.execute_story_card({'workflow': graph}, card, {'6.text': 'director prompt'}, None), {'asset_url': '/test.png'})
        self.assertFalse(paths[0].exists())

    def test_private_webhooks_rejected(self):
        for url in ["http://example.org", "https://127.0.0.1", "https://[::1]", "https://user:pass@example.org"]:
            with self.assertRaises(story.StoryError):
                story.webhook_address(url)


class FilmCutTests(unittest.TestCase):
    def test_slate_order_and_lab_clips_join_once_approved(self):
        shot = lambda index, tab, url, status="": {"shotIndex": index, "tabKey": tab, "selectedVideoUrl": url, "reviewStatus": status}
        items = [shot("VFX-01", "openjutsu-lab", "/vfx"), shot("S10", "cinema-studio", "/s10"), shot("S02", "cinema-studio", "/s02", "Retake"),
                 shot("S03", "cinema-studio", None), shot("VFX-02", "openjutsu-lab", "/vfx2", "Approved")]
        self.assertEqual(story.film_cut(items), ["/s02", "/s10", "/vfx2"])  # S02 before S10; no video, no unapproved lab sample

    def test_previs_fills_unshot_slate_shots_only_when_asked(self):
        shot = lambda index, tab, url, previs=None: {"shotIndex": index, "tabKey": tab, "selectedVideoUrl": url, "previsVideoUrl": previs, "reviewStatus": ""}
        items = [shot("S01", "cinema-studio", "/s01", "/p01"), shot("S02", "cinema-studio", None, "/p02"), shot("S03", "cinema-studio", None),
                 shot("VFX-01", "openjutsu-lab", None, "/pvfx")]
        self.assertEqual(story.film_cut(items), ["/s01"])
        self.assertEqual(story.film_cut(items, fill_previs=True), ["/s01", "/p02"])  # a take wins; no previs, no clip; lab rows never fill

    def test_adopted_selection_and_fill_choose_the_cut_and_name_each_source(self):
        """SPEC_19 R6: selection "adopted" keeps only adopted shots; fill decides what a slate gap plays."""
        shot = lambda index, tab, url, status="", previs=None: {"shotId": "sh_" + index, "shotIndex": index, "tabKey": tab,
                                                                "selectedVideoUrl": url, "previsVideoUrl": previs, "reviewStatus": status}
        items = [shot("S01", "cinema-studio", "/s01", "Approved", "/p01"), shot("S02", "cinema-studio", "/s02", "Retake", "/p02"),
                 shot("S03", "cinema-studio", None, "", "/p03"), shot("S04", "cinema-studio", None),
                 shot("VFX-01", "openjutsu-lab", "/vfx", "", "/pvfx"), shot("VFX-02", "openjutsu-lab", "/vfx2", "已完成")]
        plan = lambda **options: [(s["shotIndex"], url, source) for s, url, source in story.film_plan(items, **options)]
        adopted = [("S01", "/s01", "adopted"), ("VFX-02", "/vfx2", "adopted")]
        # The RH default is the same cut as before; the sources only name which clips were adopted.
        self.assertEqual(plan(), [("S01", "/s01", "adopted"), ("S02", "/s02", "latest"), ("VFX-02", "/vfx2", "adopted")])
        self.assertEqual(story.film_cut(items), ["/s01", "/s02", "/vfx2"])
        self.assertEqual(plan(fill="previs"), [("S01", "/s01", "adopted"), ("S02", "/s02", "latest"), ("S03", "/p03", "previs"), ("VFX-02", "/vfx2", "adopted")])
        self.assertEqual(plan(fill="latest"), plan())
        self.assertEqual(plan(selection="adopted"), adopted)
        self.assertEqual(plan(selection="adopted", fill="skip"), adopted)
        self.assertEqual(plan(selection="adopted", fill="latest"), [adopted[0], ("S02", "/s02", "latest"), adopted[1]])
        # A gap plays its previs even when it has an unadopted take; a lab clip never fills.
        self.assertEqual(plan(selection="adopted", fill="previs"), [adopted[0], ("S02", "/p02", "previs"), ("S03", "/p03", "previs"), adopted[1]])
        self.assertEqual(story.film_shots(items, fill_previs=True), story.film_shots(items, fill="previs"))
        self.assertEqual([url for _, url in story.film_shots(items, selection="adopted")], ["/s01", "/vfx2"])

    def test_film_request_options_keep_the_rh_meaning(self):
        self.assertEqual(story.film_options({}), ("selected", "skip"))
        self.assertEqual(story.film_options({"fillPrevis": True}), ("selected", "previs"))
        self.assertEqual(story.film_options({"fillPrevis": "yes"}), ("selected", "skip"))  # only true meant true, and still does
        self.assertEqual(story.film_options({"fillPrevis": True, "fill": "previs"}), ("selected", "previs"))
        self.assertEqual(story.film_options({"selection": "adopted", "fill": "latest"}), ("adopted", "latest"))
        self.assertEqual(story.film_options({"selection": "adopted"}), ("adopted", "skip"))
        for body in ({"selection": "all"}, {"selection": None}, {"fill": "none"}, {"fill": ["previs"]}, {"fillPrevis": True, "fill": "latest"}):
            with self.assertRaises(story.StoryError, msg=body) as caught:
                story.film_options(body)
            self.assertEqual((caught.exception.status, caught.exception.code), (422, "DRAMA_VALIDATION_FAILED"))


@unittest.skipUnless(os.environ.get("OPENBENCH_TEST_DB_URI"), "set OPENBENCH_TEST_DB_URI for Story HTTP tests")
class StoryHTTPTests(unittest.TestCase):
    request = product_fixture.ProductHTTPTests.request

    def setUp(self):
        product_fixture.ProductHTTPTests.setUp(self)
        for key, title, surface, md in templates.tab_specs("zerofield_studio", "Story Test", ""):
            doc, _ = markdown_import.markdown_to_doc(md, tab_keys=set(), image_src=lambda _: None)
            doc, _ = validate_doc(doc, slug=self.slug)
            templates.configure_doc(key, doc)
            repo.create_tab(self.conn, self.slug, key=key, title=title, parent_key=None, doc=doc,
                            actor_id=self.actor, surface_type=surface)
        self.ep = f"ep_{self.slug}_01"
        self.conn.commit()
        self.extra_projects = []

    def tearDown(self):
        # All asynchronously submitted jobs are bounded and awaited by each test.
        self.conn.rollback()
        with worker._OPENAPI_LOCK:
            for key, (card, _) in list(worker._OPENAPI_CARDS.items()):
                if card['card_id'] == 'test-card-' + self.slug:
                    worker._OPENAPI_CARDS.pop(key)
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM projectops.story_record WHERE owner_id=%s", (self.actor,))
            for slug in self.extra_projects:
                cur.execute("DELETE FROM projectops.flow_definition WHERE project_slug=%s", (slug,))
                cur.execute("DELETE FROM projectops.project WHERE slug=%s", (slug,))
        self.conn.commit()
        product_fixture.ProductHTTPTests.tearDown(self)

    def call(self, path, method="GET", body=None, headers=None):
        code, payload, _ = self.request(story.BASE + path, method=method, data=body, headers=headers)
        return code, payload

    def ok(self, path, method="GET", body=None, headers=None):
        code, payload = self.call(path, method, body, headers)
        self.assertEqual(code, 200, payload)
        self.assertEqual((payload["code"], payload["msg"], payload["errorMessages"]), (0, "success", None))
        return payload["data"]

    def prepare(self):
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "## Scene 01: Observatory\n@CAST-01 walks past @PROP-01.\n\n## Scene 02: Departure\n@CAST-01 leaves."})
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.ok(f"/episodes/{self.ep}/storyboards", "POST", {})
        return [s for s in self.ok(f"/episodes/{self.ep}/shots")["items"] if s['tabKey'] == 'cinema-studio' and s.get('sceneId')]

    def test_adaptation_endpoint_is_offline_idempotent_and_validated(self):
        from project_assistant import providers
        path = f'/episodes/{self.ep}/script-adaptations'
        body = {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea', 'targetScenes': 3, 'breakdownMode': 'cinematic'}
        with patch.dict(os.environ, {'OPENBENCH_MODEL': 'must-not-call', 'OPENBENCH_API_BASE': 'https://example.invalid'}), patch.object(providers, 'run_openai_compat_turn', side_effect=AssertionError('Offline adaptation must not call a provider')):
            result = self.ok(path, 'POST', body, {'Idempotency-Key': 'adapt-once'})
            self.assertEqual(result, self.ok(path, 'POST', body, {'Idempotency-Key': 'adapt-once'}))
        self.assertEqual(result['engine'], 'deterministic')
        self.assertIn('## Scene 03', result['script']['content'])
        self.assertEqual(self.ok('/episodes/' + self.ep)['breakdownMode'], 'cinematic')
        self.assertEqual(self.call(path, 'POST', {**body, 'targetScenes': 2}, {'Idempotency-Key': 'adapt-once'})[0], 409)
        for change in ({'sourceText': ''}, {'sourceText': []}, {'sourceMode': 'remote'}, {'targetScenes': True}, {'targetScenes': 13}, {'breakdownMode': 'bad'}):
            self.assertEqual(self.call(path, 'POST', body | change)[0], 422)
        self.assertEqual(self.request(story.BASE + path, method='POST', data=body, authenticated=False)[0], 401)
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        generated = [s for s in self.ok(f'/episodes/{self.ep}/shots?limit=100')['items'] if s.get('sceneId')]
        self.assertGreaterEqual(len(generated), 9)
        self.assertTrue(all(s.get('previsPlan') for s in generated))
        repo.upsert_member(self.conn, self.actor, 'Viewer', 'viewer'); self.conn.commit()
        self.assertEqual(self.call(path, 'POST', body)[0], 409)
        self.assertEqual(self.call(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})[0], 409)

    def test_story_collisions_choice_traces_and_composed_adaptation(self):
        idea = 'A delivery courier is secretly an immortal sage.'
        proposal = self.ok(f'/episodes/{self.ep}/story-collisions', 'POST', {'sourceText': idea, 'mediumLens': 'manju', 'genreLens': 'comedy'})
        self.assertEqual((len(proposal['candidates']), proposal['recentTraces']), (4, []))
        for change in ({'mediumLens': 'film'}, {'genreLens': 'horror'}, {'sourceText': ''}):
            self.assertEqual(self.call(f'/episodes/{self.ep}/story-collisions', 'POST', {'sourceText': idea} | change)[0], 422)
        cards, path = proposal['candidates'], f'/episodes/{self.ep}/script-adaptations'
        body = {'sourceText': idea, 'sourceMode': 'idea', 'targetScenes': 3, 'breakdownMode': 'auto', 'mediumLens': 'manju', 'genreLens': 'comedy'}
        results = []
        for focus in ('restraint', 'restraint', 'reversal'):
            results.append(self.ok(path, 'POST', body | {'choiceTrace': {'focus': focus, 'keptLabels': [cards[0]['label']],
                'uncheckedLabels': [cards[1]['label']], 'extraCondition': 'The courier never says their real name.'}}))
        last = results[-1]
        self.assertEqual([r['choiceTrace']['contrastDetected'] for r in results], [False, False, True])
        self.assertTrue(last['choiceTrace']['traceId'].startswith('ctr_'))
        self.assertEqual((last['mediumLens'], last['genreLens'], last['engine']), ('manju', 'comedy', 'deterministic'))
        self.assertTrue(last['voiceAudit']['ok'])
        script = last['script']['content']
        self.assertIn('[Contrast]', script)
        self.assertIn(cards[0]['label'], script)
        self.assertNotIn(cards[1]['label'], script)
        self.assertIn('The courier never says their real name.', script)
        traces = self.ok(f'/episodes/{self.ep}/choice-traces')['items']
        self.assertEqual([t['focus'] for t in traces], ['restraint', 'restraint', 'reversal'])
        self.assertEqual(traces[-1]['uncheckedLabels'], [cards[1]['label']])
        self.assertEqual(len(self.ok(f'/episodes/{self.ep}/story-collisions', 'POST', {'sourceText': idea})['recentTraces']), 3)
        for change in ({'choiceTrace': {'focus': 'anger'}}, {'choiceTrace': {'keptLabels': 'all'}}, {'choiceTrace': []}, {'mediumLens': 'film'}):
            self.assertEqual(self.call(path, 'POST', body | change)[0], 422)
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        plans = [s['previsPlan'] for s in self.ok(f'/episodes/{self.ep}/shots?limit=100')['items'] if s.get('sceneId')]
        self.assertTrue(plans and {p['lens'] for p in plans} <= {50, 85})  # the script's Lens line reaches the storyboard
        plain = self.ok(path, 'POST', {key: body[key] for key in ('sourceText', 'sourceMode', 'targetScenes', 'breakdownMode')})
        self.assertEqual(set(plain), {'episodeId', 'script', 'sourceMode', 'breakdownMode', 'engine'})
        self.assertEqual(plain['script']['content'], story.adapt_source_to_script(idea, 'idea', 3, story.STYLES[0]['name']))
        self.assertEqual(len(self.ok(f'/episodes/{self.ep}/choice-traces')['items']), 3)

    def test_multibeat_readiness_variants_and_rebuild_preserves_media(self):
        content = 'Character: Mara @CAST-88 (silver hair, red coat)\nProp: Brass dial @PROP-88\n\nScene 01: Rooftop Rain\nEnvironment: @SET-88, moonlight through rain.\n\n@CAST-88:night enters.'
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': content})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertIn('CAST-88:NIGHT', self.ok('/episodes/' + self.ep)['missingAssetCodes'])
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        original = next(s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId'))
        self.assertEqual(original['readiness']['missingAssets'], ['CAST-88:NIGHT', 'SET-88'])
        self.assertFalse(original['readiness']['ready'])
        self.assertFalse(original['readiness']['hasPrevis'])
        base = next(a for a in story.assets(self.conn, story.episode(self.conn, self.ep)) if a['assetCode'] == 'CAST-88')
        url = f'/projects/api/{self.slug}/assets/pa_' + 'a' * 32
        story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', base['rowId'], {3: f'![Image]({url})'})
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {8: f'[Previs]({url})'})
        self.conn.commit()
        ready = self.ok('/shots/' + original['shotId'])
        self.assertIn('CAST-88:NIGHT', ready['readiness']['missingAssets'])
        self.assertTrue(ready['readiness']['ready'])
        self.assertTrue(ready['readiness']['hasPrevis'])
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {4: f'![Image]({url})', 8: ''})
        self.conn.commit()
        keyframe_ready = self.ok('/shots/' + original['shotId'])
        self.assertTrue(keyframe_ready['readiness']['ready'])
        self.assertFalse(keyframe_ready['readiness']['hasPrevis'])
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', original['rowId'], {8: f'[Previs]({url})'})
        self.conn.commit()
        scene_id = original['sceneId']
        beats = '@CAST-88:night enters.\n\n@CAST-88:night: "Stay here."\n\nClose-up of @CAST-88:night eyes.'
        self.ok('/scenes/' + scene_id, 'PATCH', {'content': beats})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok('/scenes/' + scene_id + '/shot-rebuilds', 'POST', {})
        rebuilt = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == scene_id]
        self.assertEqual([s['shotIndex'] for s in rebuilt], ['SC01-S01', 'SC01-S02', 'SC01-S03'])
        self.assertEqual(rebuilt[0]['shotId'], original['shotId'])
        self.assertTrue(rebuilt[0]['readiness']['hasPrevis'])
        self.assertTrue(rebuilt[1]['readiness']['hasDialogue'])
        self.assertEqual([s['previsPlan']['lens'] for s in rebuilt], [35, 50, 85])
        self.assertEqual(self.call(f'/episodes/{self.ep}/storyboards', 'POST', {'breakdownMode': 'invalid'})[0], 422)
        self.ok('/scenes/' + scene_id, 'PATCH', {'content': '\n\n'.join('A new action.' for _ in range(201))})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.call(f'/episodes/{self.ep}/storyboards', 'POST', {})[0], 422)
        self.assertEqual(len([s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == scene_id]), 3)

    def test_missing_asset_batch_defaults_scope_accounting_and_atomic_failure(self):
        from project_assistant import execution_governance as governance
        self.prepare()
        ep = story.episode(self.conn, self.ep)
        missing, known = story.missing_episode_assets(self.conn, ep)
        self.assertEqual(set(missing), {'CAST-01', 'SET-01', 'SET-02'})
        path = f'/episodes/{self.ep}/asset-image-generations'
        before = len(story.records(self.conn, 'task', owner=self.actor))
        original_prepare = governance.prepare_operation
        calls = []
        def reject_second(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise governance.AdmissionError('Test budget exhausted')
            return original_prepare(*args, **kwargs)
        with patch.object(story._POOL, 'submit') as submit, patch.object(governance, 'prepare_operation', side_effect=reject_second):
            self.assertEqual(self.call(path, 'POST', {})[0], 409)
            submit.assert_not_called()
        self.assertEqual(len(story.records(self.conn, 'task', owner=self.actor)), before)
        with patch.object(story._POOL, 'submit') as submit:
            group = self.ok(path, 'POST', {}, {'Idempotency-Key': 'assets-once'})
            self.assertEqual(group, self.ok(path, 'POST', {}, {'Idempotency-Key': 'assets-once'}))
            self.assertEqual(set(group['assetCodes']), set(missing))
            self.assertEqual(submit.call_count, 3)
        for task_id in group['taskIds']:
            task = story.record(self.conn, task_id)
            self.assertEqual(task['_job']['card']['card_id'], 'flux-soul-cast')
            self.assertEqual(task['_job']['episodeId'], self.ep)
            self.assertTrue(task['_job']['_accounting_keys'])
            self.ok('/tasks/' + task_id + '/cancellations', 'POST', {})
        for code in missing:
            url = f'/projects/api/{self.slug}/assets/pa_' + 'a' * 32
            story.mutate_row(self.conn, self.me, self.slug, 'soul-cast', known[code]['rowId'], {3: f'![Image]({url})'})
        self.conn.commit()
        self.assertEqual(self.ok(path, 'POST', {})['taskIds'], [])
        self.assertEqual(self.ok('/episodes/' + self.ep)['missingAssetCodes'], [])

    def test_extraction_preserves_manual_drafts_and_settings_select_density(self):
        source = 'Character: Mara @CAST-88 (silver hair)\n\nScene 01: Station\n@CAST-88 enters. @CAST-88 turns.'
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': source})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        asset = next(a for a in self.ok(f'/episodes/{self.ep}/assets')['items'] if a['assetCode'] == 'CAST-88')
        self.ok('/assets/' + asset['assetId'], 'PATCH', {'name': 'Director Mara', 'prompt': 'Custom blue coat and cropped hair'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['prompt'], 'Custom blue coat and cropped hair')
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['name'], 'Director Mara')
        self.ok('/assets/' + asset['assetId'], 'PATCH', {'name': 'Director Mara', 'prompt': 'Director Mara'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['prompt'], 'Director Mara')
        self.assertEqual(self.ok('/assets/' + asset['assetId'])['name'], 'Director Mara')
        self.ok(f'/episodes/{self.ep}/settings', 'PUT', {'breakdownMode': 'cinematic'})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        generated = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId')]
        self.assertEqual(len(generated), 2)
        self.assertEqual(self.call(f'/episodes/{self.ep}/settings', 'PUT', {'breakdownMode': 'unknown'})[0], 422)

    def test_storyboard_build_preserves_director_edits_and_only_appends_missing_beats(self):
        original = self.prepare()[0]
        edits = {'shotIndex': 'DIRECTOR-42', 'opticalRig': 'Director 50mm lens', 'cameraMotion': 'Director locked camera', 'description': 'A hand-edited prompt @CAST-01'}
        self.ok('/shots/' + original['shotId'], 'PATCH', edits)
        before_meta = story.shot_meta(self.conn, original['shotId'])
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        preserved = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: preserved[key] for key in edits}, edits)
        self.assertEqual(story.shot_meta(self.conn, original['shotId']), before_meta)
        self.ok('/scenes/' + original['sceneId'], 'PATCH', {'content': '@CAST-01 enters.\n\n@CAST-01: "Wait."\n\nClose-up of @CAST-01 eyes.'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        preserved = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: preserved[key] for key in edits}, edits)
        related = [s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s.get('sceneId') == original['sceneId']]
        self.assertEqual(len(related), 3)
        self.ok('/scenes/' + original['sceneId'] + '/shot-rebuilds', 'POST', {})
        rebuilt = self.ok('/shots/' + original['shotId'])
        self.assertEqual({key: rebuilt[key] for key in ('shotIndex', 'opticalRig', 'cameraMotion')}, {key: edits[key] for key in ('shotIndex', 'opticalRig', 'cameraMotion')})
        self.assertIn('@CAST-01 enters.', rebuilt['description'])

    def test_missing_asset_batch_completes_more_than_render_concurrency_limit(self):
        from PIL import Image
        source = self.ok(f'/episodes/{self.ep}/script-adaptations', 'POST', {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea'})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        active = maximum = 0
        lock = threading.Lock()
        def render(task, card, values, head):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(.4)
                return head.upload(task, data.getvalue(), 'image/png')
            finally:
                with lock:
                    active -= 1
        with patch.object(worker, 'execute_story_card', side_effect=render):
            group = self.ok(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})
            self.assertEqual(len(group['taskIds']), 5)
            tasks = [self.await_task({'taskId': identifier}) for identifier in group['taskIds']]
        self.assertEqual([task['status'] for task in tasks], ['SUCCEEDED'] * 5, tasks)
        self.assertLessEqual(maximum, 2)
        self.assertEqual(self.ok('/episodes/' + self.ep)['missingAssetCodes'], [])

    def capacity_wait_case(self, cancel):
        from PIL import Image
        from project_assistant import execution_governance as governance
        self.ok(f'/episodes/{self.ep}/script-adaptations', 'POST', {'sourceText': 'A lone astronomer discovers a brass dial.', 'sourceMode': 'idea', 'targetScenes': 1})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        release, waiting = threading.Event(), threading.Event()
        blocked, submitted = [], []
        original_begin, original_run = governance.begin_operation, governance.run_operation
        def begin(conn, ctx, request_key, **kwargs):
            try:
                return original_begin(conn, ctx, request_key, **kwargs)
            except governance.CapacityUnavailable:
                blocked.append(request_key.rsplit(':', 1)[0]); waiting.set()
                raise
        def run(*args, **kwargs):
            return original_run(*args, **kwargs, capacity_timeout=5 if cancel else .15)
        def render(task, card, values, head):
            submitted.append(task['id'])
            release.wait(10)
            return head.upload(task, data.getvalue(), 'image/png')
        with patch.object(governance, 'begin_operation', side_effect=begin), patch.object(governance, 'run_operation', side_effect=run), patch.object(worker, 'execute_story_card', side_effect=render):
            group = self.ok(f'/episodes/{self.ep}/asset-image-generations', 'POST', {})
            try:
                self.assertTrue(waiting.wait(5), 'Third asset did not reach the capacity wait')
                identifier = blocked[0]
                if cancel:
                    self.ok('/tasks/' + identifier + '/cancellations', 'POST', {})
                result = self.await_task({'taskId': identifier})
                self.assertEqual(result['status'], 'CANCELED' if cancel else 'FAILED', result)
                if not cancel:
                    self.assertIn('Timed out waiting for execution capacity', result['error']['message'])
                self.assertNotIn(identifier, submitted)
                with self.conn.cursor() as cur:
                    cur.execute('SELECT state FROM projectops.agent_usage_reservation WHERE project_slug=%s AND request_key=%s', (self.slug, identifier + ':generate'))
                    self.assertEqual(cur.fetchone()[0], 'released')
            finally:
                release.set()
                outcomes = [self.await_task({'taskId': task_id}) for task_id in group['taskIds']]
        self.assertEqual(sum(task['status'] == 'SUCCEEDED' for task in outcomes), 2, outcomes)
        self.assertEqual(len(submitted), 2)

    def test_waiting_asset_cancel_never_submits_and_releases_reservation(self):
        self.capacity_wait_case(cancel=True)

    def test_waiting_asset_deadline_never_submits_and_releases_reservation(self):
        self.capacity_wait_case(cancel=False)

    def test_asset_action_failure_is_not_retried(self):
        from project_assistant import execution_governance as governance
        self.prepare()
        asset = self.ok(f'/episodes/{self.ep}/assets')['items'][0]
        with patch.object(worker, 'execute_story_card', side_effect=governance.CapacityUnavailable('Provider action already started')) as render:
            task = self.ok('/assets/' + asset['assetId'] + '/image-generations', 'POST', {'appCode': 'flux-soul-cast'})
            result = self.await_task(task)
        self.assertEqual(result['status'], 'FAILED')
        render.assert_called_once()

    def await_task(self, task):
        end = time.monotonic() + 30
        while time.monotonic() < end:
            current = self.ok("/tasks/" + task["taskId"])
            if current["status"] not in ("QUEUED", "RUNNING"):
                return current
            time.sleep(.05)
        self.fail("Story task did not finish")

    def test_catalog_envelope_validation_and_auth(self):
        self.assertEqual(self.ok("/capabilities")["stages"], story.STAGES)
        self.assertTrue(self.ok("/catalog/apps?capability=VIDEO")["items"])
        self.assertTrue(self.ok("/catalog/apps?capability=IMAGE")["items"])
        code, payload = self.call("/catalog/apps?capability=AUDIO")
        self.assertEqual((code, payload["code"]), (422, "DRAMA_VALIDATION_FAILED"))
        code, payload, _ = self.request(story.BASE + "/capabilities", authenticated=False)
        self.assertEqual((code, payload["code"]), (401, "DRAMA_AUTH_MISSING"))
        repo.upsert_member(self.conn, self.actor, "Viewer", "viewer"); self.conn.commit()
        self.assertEqual(self.call("/projects", "POST", {"title": "denied"})[0], 409)

    def test_idempotency_is_atomic_and_persisted(self):
        slug = self.slug + "-i"; self.extra_projects.append(slug)
        body = {"title": "Checkpoint", "slug": slug}
        headers = {"Idempotency-Key": "same-project"}
        first = self.ok("/projects", "POST", body, headers)
        self.assertEqual(first, self.ok("/projects", "POST", body, headers))
        code, payload = self.call("/projects", "POST", {**body, "title": "different"}, headers)
        self.assertEqual((code, payload["code"]), (409, "DRAMA_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.call("/projects", "POST", body, {"Idempotency-Key": "x" * 129})[0], 422)

    def test_baseline_variants_and_bidirectional_sheet_edits(self):
        code, payload = self.call(f"/episodes/{self.ep}/storyboards", "POST", {})
        self.assertEqual((code, payload["code"]), (409, "DRAMA_STAGE_PRECONDITION"))
        shots = self.prepare()
        assets = self.ok(f"/episodes/{self.ep}/assets")["items"]
        actor = next(a for a in assets if a["assetCode"] == "CAST-01")
        variant = self.ok(f"/assets/{actor['assetId']}/variants", "POST", {"name": "Night", "key": "night", "kind": "OUTFIT", "prompt": "Night jacket"})
        self.assertEqual(variant["assetCode"], "CAST-01:NIGHT")
        self.assertEqual(variant['kind'], 'OUTFIT')
        self.assertIn('ARRI Alexa', shots[0]['opticalRig'])
        self.assertEqual(len(self.ok("/assets/" + actor["assetId"])["variants"]), 1)
        selected = shots[0]
        self.ok(f"/shots/{selected['shotId']}/assets", "PUT", {"assetCodes": ["CAST-01:NIGHT"]})
        self.assertIn("@CAST-01:NIGHT", story.find_row(self.conn, selected["shotId"], "shot")[1]["cells"][3])
        story.mutate_row(self.conn, self.me, self.slug, "cinema-studio", selected["rowId"], {3: "Manual UI change @CAST-01"})
        self.conn.commit()
        self.assertEqual(self.ok("/shots/" + selected["shotId"])["description"], "Manual UI change @CAST-01")
        self.ok(f"/episodes/{self.ep}/script", "PUT", {"scriptContent": "Scene 01: Changed\n@CAST-01"})
        self.assertTrue(self.ok(f"/episodes/{self.ep}")["scriptDirty"])
        self.assertEqual(self.call(f"/episodes/{self.ep}/storyboards", "POST", {})[0], 409)
        self.ok(f"/episodes/{self.ep}/asset-extractions", "POST", {})
        self.assertFalse(self.ok(f"/episodes/{self.ep}")["scriptDirty"])
        self.assertGreaterEqual(len(self.ok(f"/episodes/{self.ep}/script/versions")["items"]), 3)

    def test_files_import_multi_episode_and_xor(self):
        self.assertEqual(self.call("/project-imports", "POST", {"title": "bad"})[0], 400)
        raw = b"Episode 1\nScene 01: Arrival\n@CAST-01\nEpisode 2\nScene 01: Exit\n@CAST-01"
        code, payload, _ = self.request(story.BASE + "/files", method="POST", raw=raw,
                                       headers={"Content-Type": "text/plain", "X-File-Name": "story.md"})
        self.assertEqual(code, 200, payload)
        file = payload["data"]
        self.assertEqual(file["size"], str(len(raw)))
        with patch.object(story, 'file_bytes', side_effect=AssertionError('metadata must not read a blob')):
            self.assertEqual(self.ok('/files/' + file['fileId'])['size'], str(len(raw)))
            self.assertEqual(self.ok('/files/' + file['fileId'] + '/url')['url'], file['url'])
        slug = self.slug + "-i"; self.extra_projects.append(slug)
        imported = self.ok("/project-imports", "POST", {"slug": slug, "title": "Episodes", "scriptFileId": file["fileId"]})
        self.assertEqual(imported["result"]["episodeCount"], 2)
        self.assertEqual(len(self.ok(f"/projects/pj_{slug}/episodes")["items"]), 2)
        self.assertEqual(self.request(file["url"])[1], raw)

    def generation_inputs(self, identifier, video=None):
        from PIL import Image
        if video is None:
            import subprocess, tempfile
            with tempfile.TemporaryDirectory() as folder:
                path=Path(folder)/'source.mp4'
                subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=blue:s=64x64:r=8:d=0.5',
                    '-c:v','libx264','-pix_fmt','yuv420p','-movflags','+faststart',str(path)],check=True,timeout=15)
                video=path.read_bytes()
        image=io.BytesIO();Image.new('RGB',(16,16),'blue').save(image,format='PNG')
        aid=repo.put_asset(self.conn,self.slug,data=image.getvalue(),content_type='image/png',actor_id=self.actor)
        vid=repo.put_asset(self.conn,self.slug,data=video,content_type='video/mp4',actor_id=self.actor)
        _,row=story.find_row(self.conn,identifier,'shot')
        story.mutate_row(self.conn,self.me,self.slug,row['tabKey'],row['rid'],
            {4:f'![Image](/projects/api/{self.slug}/assets/{aid})',5:f'[Video](/projects/api/{self.slug}/assets/{vid})'})
        self.conn.commit()
        return f'/projects/api/{self.slug}/assets/{vid}'

    def test_generation_candidates_split_merge_and_real_film(self):
        import subprocess
        import tempfile
        shots = self.prepare()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "clip.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x96:r=24", "-t", "0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)], check=True)
            raw = path.read_bytes()
        def render(task, card, values, head):
            self.assertIn(card["card_id"], ("h3-short-video-v3", "h3-optimize"))
            return head.upload(task, raw, "video/mp4")
        identifier = shots[0]["shotId"]
        source = self.generation_inputs(identifier, raw)
        with patch.object(worker, "execute_story_card", side_effect=render):
            done = self.await_task(self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "2109942725885075458", "modelParams":{"driving_video":source}}))
        self.assertEqual(done["status"], "SUCCEEDED", done)
        candidates = self.ok(f"/shots/{identifier}/videos")["items"]
        self.assertTrue(candidates)
        self.ok(f"/shots/{identifier}/selected-video", "PUT", {"videoId": candidates[0]["videoId"]})
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', shots[1]['rowId'], {5: '[video](' + candidates[0]['url'] + ')'})
        self.conn.commit()
        split = self.ok(f"/shots/{identifier}/splits", "POST", {})
        self.assertEqual(len(split["shots"]), 2)
        self.ok("/shot-merges", "POST", {"shotIds": [s["shotId"] for s in split["shots"]]})
        film = self.await_task(self.ok(f"/episodes/{self.ep}/films", "POST", {}))
        self.assertEqual(film["status"], "SUCCEEDED", film)
        output = self.request(film["result"]["videoUrl"])[1]
        self.assertLess(output.find(b"moov"), output.find(b"mdat"))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'episode.mp4'; path.write_bytes(output)
            metadata = worker._probe_video(path)
            self.assertGreaterEqual(metadata['duration'], 0.49)
        self.assertTrue(self.ok(f"/episodes/{self.ep}/films")["items"])

    def test_late_render_is_candidate_only_after_a_manual_edit(self):
        from PIL import Image
        ready, release = threading.Event(), threading.Event()
        raw = io.BytesIO(); Image.new('RGB', (8, 8), 'blue').save(raw, format='PNG')
        identifier = self.prepare()[0]["shotId"]
        def render(task, card, values, head):
            ready.set(); release.wait(10)
            return head.upload(task, raw.getvalue(), 'image/png')
        with patch.object(worker, 'execute_story_card', side_effect=render):
            task = self.ok(f'/shots/{identifier}/image-generations', 'POST', {'appCode': 'LOCAL_SDXL_SMOKE'})
            self.assertTrue(ready.wait(10))
            self.ok('/shots/' + identifier, 'PATCH', {'description': 'A newer director instruction'})
            release.set()
            done = self.await_task(task)
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertFalse(done['result']['selected'])
        self.assertIsNone(self.ok('/shots/' + identifier)['selectedImageUrl'])
        self.assertTrue(self.ok('/shots/' + identifier + '/images')['items'])

    def render_bytes(self, color):
        import subprocess, tempfile
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'take.mp4'
            subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', f'color=c={color}:s=64x64:r=8:d=0.5', '-c:v', 'libx264',
                            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(path)], check=True, timeout=30)
            return path.read_bytes()

    def test_a_render_for_an_adopted_shot_only_joins_its_candidates(self):
        """SPEC_19 R2 (1.2 D): an unadopted shot still previews its newest take in the cell (selected: True); an adopted one keeps
        the take that is in the cut and the render only becomes a dated candidate (selected: False)."""
        identifier = self.prepare()[0]['shotId']
        source = self.generation_inputs(identifier, self.render_bytes('blue'))
        def generate(color):
            raw = self.render_bytes(color)
            with patch.object(worker, 'execute_story_card', side_effect=lambda task, card, values, head: head.upload(task, raw, 'video/mp4')):
                done = self.await_task(self.ok(f'/shots/{identifier}/video-generations', 'POST', {'appCode': '2109942725885075458', 'modelParams': {'driving_video': source}}))
            self.assertEqual(done['status'], 'SUCCEEDED', done)
            return done['result']
        takes = lambda: {t['url']: t for t in self.ok(f'/shots/{identifier}/videos?limit=100')['items']}
        first = generate('red')
        self.assertTrue(first['selected'])  # not adopted: unchanged behaviour
        self.assertEqual(self.ok('/shots/' + identifier)['selectedVideoUrl'], first['videoUrl'])
        self.assertIsNotNone(takes()[first['videoUrl']]['createdAt'])
        self.assertIsNone(takes()[source]['createdAt'])  # a take placed in the sheet has no creation time
        self.ok(f'/shots/{identifier}/adoptions', 'POST', {'videoId': takes()[first['videoUrl']]['videoId']})
        second = generate('green')
        self.assertFalse(second['selected'])
        shot = self.ok('/shots/' + identifier)
        self.assertEqual((shot['selectedVideoUrl'], shot['reviewStatus'], shot['adoption']['url']), (first['videoUrl'], 'Approved', first['videoUrl']))
        self.assertEqual(shot['takeSummary'], {'total': 3, 'newSinceAdoption': 1})
        listed = takes()[second['videoUrl']]
        self.assertFalse(listed['selected'])
        from datetime import datetime
        self.assertGreater(datetime.fromisoformat(listed['createdAt']), datetime.fromisoformat(shot['adoption']['at']))
        # Undo the adoption and the newest render previews in the cell again.
        self.ok(f'/shots/{identifier}/adoption', 'DELETE')
        third = generate('yellow')
        self.assertTrue(third['selected'])
        self.assertEqual(self.ok('/shots/' + identifier)['selectedVideoUrl'], third['videoUrl'])

    def quoting_shots(self):
        """S71 with a take in its cell (not adopted) and S72 whose prompt quotes its last frame: (S71, S72, S71's take, S72's source)."""
        one, two = self.prepare()
        self.ok('/shots/' + one['shotId'], 'PATCH', {'shotIndex': 'S71'})
        self.ok('/shots/' + two['shotId'], 'PATCH', {'shotIndex': 'S72', 'description': '@S71.end @CAST-01 leaves.'})
        upstream = self.generation_inputs(one['shotId'], self.render_bytes('red'))
        source = self.generation_inputs(two['shotId'], self.render_bytes('blue'))
        return one, two, upstream, source

    def generate_quoting(self, identifier, source, body=None):
        """Queue S72's render without running it, then run the worker here: (frozen job, worker task, finished task)."""
        import copy
        seen, raw = [], self.render_bytes('green')
        def render(task, card, values, head):
            ctx = worker.resolve_studio_context(task)
            seen.append((copy.deepcopy(task), ctx, worker._build_card_form_values(card, ctx, dict(card['engine_config'], card_values=values), task, None)))
            return head.upload(task, raw, 'video/mp4')
        with patch.object(story._POOL, 'submit'):
            queued = self.ok(f'/shots/{identifier}/video-generations', 'POST', {'appCode': '2109942725885075458', 'modelParams': {'driving_video': source}, **(body or {})})
        job = story.record(self.conn, queued['taskId'])['_job']
        self.conn.rollback()
        with patch.object(worker, 'execute_story_card', side_effect=render):
            story.execute_task(queued['taskId'])
        done = self.ok('/tasks/' + queued['taskId'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        return job, seen[0], done

    def test_a_generation_freezes_its_quoted_takes_and_the_worker_cuts_their_frames(self):
        """SPEC_19 R15 (D2, D3, D11): the tags of the prompt are frozen on submit; the worker cuts each frame from the quoted
        take with extract_frame's source_url, stores it and binds that same picture; the new take's provenance keeps it all."""
        from PIL import Image
        one, two, upstream, source = self.quoting_shots()
        job, (task, ctx, form), done = self.generate_quoting(two['shotId'], source, {'takeRefUses': {'S71.end': 'first_frame'}})
        # Frozen on submit: which take and how it is used; an untrimmed out point waits for the take's length.
        frozen = {'shotId': one['shotId'], 'shotIndex': 'S71', 'edge': 'end', 'takeUrl': upstream, 'at': None, 'frameUrl': None,
                  'use': 'first_frame', 'adopted': False, 'lastFrameAt': None}
        self.assertEqual(job['storyProvenance']['takeRefs'], [frozen])
        # The worker task names its production, so extract_frame can check the quoted take belongs to it.
        self.assertEqual(task['project_slug'], self.slug)
        [ref] = done['result']['storyProvenance']['takeRefs']
        self.assertEqual(ref, frozen | {'at': 0.375, 'lastFrameAt': 0.375, 'frameUrl': ref['frameUrl']})  # 4 frames at 8 fps
        self.assertRegex(ref['frameUrl'], rf'^/projects/api/{self.slug}/assets/pa_[0-9a-f]{{32}}$')
        with Image.open(io.BytesIO(self.request(ref['frameUrl'])[1])) as frame:
            self.assertEqual(frame.format, 'PNG')
            self.assertGreater(frame.convert('RGB').getpixel((32, 32))[0], 150)  # S71's red take
        # The frame sent to the model is the frame in the snapshot.
        self.assertEqual(task['input']['take_refs'], [{'shotIndex': 'S71', 'edge': 'end', 'use': 'first_frame', 'frameUrl': ref['frameUrl']}])
        self.assertEqual((ctx['first_frame'], ctx['anchor_keyframe'], form['1.image']), (ref['frameUrl'],) * 3)
        self.assertIn('Continue directly from the final frame of shot S71. @CAST-01 leaves.', ctx['compiled_prompt'])
        # The task and the new take keep the completed snapshot.
        self.assertEqual(story.record(self.conn, done['taskId'])['_job']['storyProvenance']['takeRefs'], [ref])
        self.conn.rollback()
        take = next(t for t in self.ok(f"/shots/{two['shotId']}/videos")['items'] if t['url'] == done['result']['videoUrl'])
        self.assertEqual(take['storyProvenance']['takeRefs'], [ref])
        # Without a quoted take, nothing is added to the provenance.
        self.ok('/shots/' + two['shotId'], 'PATCH', {'description': '@CAST-01 leaves.'})
        plain = self.generate_quoting(two['shotId'], source)[2]
        self.assertNotIn('takeRefs', plain['result']['storyProvenance'])
        # An unknown shot is refused with the tags named; a quoted shot without a take cannot be quoted.
        self.ok('/shots/' + two['shotId'], 'PATCH', {'description': '@S71.end then @S99.end'})
        code, payload = self.call(f"/shots/{two['shotId']}/video-generations", 'POST', {'appCode': '2109942725885075458', 'modelParams': {'driving_video': source}})
        self.assertEqual((code, payload['code'], payload['details']), (400, 'DRAMA_VALIDATION_FAILED', {'unknownTakeRefs': ['@S99.end']}))
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', one['rowId'], {5: ''})
        self.conn.commit()
        self.ok('/shots/' + two['shotId'], 'PATCH', {'description': '@S71.end'})
        code, payload = self.call(f"/shots/{two['shotId']}/video-generations", 'POST', {'appCode': '2109942725885075458', 'modelParams': {'driving_video': source}})
        self.assertEqual((code, payload['code']), (409, 'DRAMA_STAGE_PRECONDITION'))

    def test_the_shot_view_tells_when_a_quoted_take_changed(self):
        """SPEC_19 R16 (D4): takeRefs of the adopted take turn stale when the quoted shot adopts another take or moves its
        out point, and clear again once it is back."""
        one, two, upstream, source = self.quoting_shots()
        done = self.generate_quoting(two['shotId'], source)[2]
        ref = done['result']['storyProvenance']['takeRefs'][0]
        self.assertEqual(ref['use'], 'reference')  # no evidence of one continuous action: the default
        takes = lambda identifier: {t['url']: t['videoId'] for t in self.ok(f'/shots/{identifier}/videos?limit=100')['items']}
        self.assertEqual(self.ok('/shots/' + two['shotId'])['takeRefs'], [])  # nothing adopted yet
        self.ok(f"/shots/{two['shotId']}/adoptions", 'POST', {'videoId': takes(two['shotId'])[done['result']['videoUrl']]})
        refs = lambda: self.ok('/shots/' + two['shotId'])['takeRefs']
        current = {'shotId': one['shotId'], 'shotIndex': 'S71', 'edge': 'end', 'takeUrl': upstream, 'at': 0.375, 'use': 'reference',
                   'stale': False, 'nowTakeUrl': upstream, 'frameUrl': ref['frameUrl'], 'adopted': False}
        self.assertEqual(refs(), [current])
        listed = next(s for s in self.ok(f'/episodes/{self.ep}/shots')['items'] if s['shotId'] == two['shotId'])
        self.assertEqual(listed['takeRefs'], [current])
        # Adopting the very take that was quoted changes nothing.
        self.ok(f"/shots/{one['shotId']}/adoptions", 'POST', {'videoId': takes(one['shotId'])[upstream]})
        self.assertEqual(refs(), [current])
        # S71 adopts another take: stale, with the take it holds now.
        other = f"/projects/api/{self.slug}/assets/" + repo.put_asset(self.conn, self.slug, data=self.render_bytes('yellow'), content_type='video/mp4', actor_id=self.actor)
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', one['rowId'], {5: f'[Video]({other})'})
        self.conn.commit()
        self.ok(f"/shots/{one['shotId']}/adoptions", 'POST', {'videoId': takes(one['shotId'])[other]})
        self.assertEqual(refs(), [current | {'stale': True, 'nowTakeUrl': other}])
        # Back to the quoted take: no longer stale.
        self.ok(f"/shots/{one['shotId']}/adoptions", 'POST', {'videoId': takes(one['shotId'])[upstream]})
        self.assertEqual(refs(), [current])
        # The quoted out point moves: stale; the cut is undone: not stale.
        self.ok(f"/shots/{one['shotId']}/trim", 'PUT', {'in': 0, 'out': 0.25})
        self.assertEqual(refs(), [current | {'stale': True}])
        self.ok(f"/shots/{one['shotId']}/trim", 'PUT', {})
        self.assertEqual(refs(), [current])
        # The quoted shot is relabelled: the reference follows the shot, under its new label.
        self.ok('/shots/' + one['shotId'], 'PATCH', {'shotIndex': 'S71A'})
        self.assertEqual(refs(), [current | {'shotIndex': 'S71A'}])
        self.ok(f"/shots/{two['shotId']}/adoption", 'DELETE')
        self.assertEqual(refs(), [])

    def test_film_selection_and_fill_extend_the_rh_request_without_changing_it(self):
        from project_docs import story_trim
        one, two = self.prepare()
        url = lambda letter: f'/projects/api/{self.slug}/assets/pa_' + letter * 32
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', one['rowId'], {5: f'[Video]({url("a")})'})
        story.mutate_row(self.conn, self.me, self.slug, 'cinema-studio', two['rowId'], {5: f'[Video]({url("b")})', 8: f'[Previs]({url("c")})'})
        self.conn.commit()
        self.ok(f'/shots/{one["shotId"]}/trim', 'PUT', {'in': 0.1, 'out': 0.3})
        legacy = {key: story.film_shots(story.shots(self.conn, story.episode(self.conn, self.ep)), fill_previs=key) for key in (False, True)}
        self.conn.rollback()
        def queued(body):
            with patch.object(story._POOL, 'submit'):
                task = self.ok(f'/episodes/{self.ep}/films', 'POST', body)
            job = story.record(self.conn, task['taskId'])['_job']
            self.conn.rollback()
            return job['urls'], [(s['shotId'], s['source']) for s in job['segments']], job['trims']
        # The RH requests queue exactly the clips and cuts they queued before.
        for body, key in (({}, False), ({'fillPrevis': True}, True), ({'fillPrevis': 'yes'}, False)):
            urls, _, trims = queued(body)
            self.assertEqual((urls, trims), ([u for _, u in legacy[key]], story_trim.film_trims(legacy[key])), body)
        self.assertEqual(queued({}), queued({'selection': 'selected', 'fill': 'skip'}))
        self.assertEqual(queued({'fillPrevis': True}), queued({'fill': 'previs'}))
        self.assertEqual(queued({})[:2], ([url('a'), url('b')], [(one['shotId'], 'latest'), (two['shotId'], 'latest')]))
        video_id = next(t['videoId'] for t in self.ok(f'/shots/{one["shotId"]}/videos')['items'] if t['url'] == url('a'))
        self.ok(f'/shots/{one["shotId"]}/adoptions', 'POST', {'videoId': video_id})
        self.assertEqual(queued({})[:2], ([url('a'), url('b')], [(one['shotId'], 'adopted'), (two['shotId'], 'latest')]))
        self.assertEqual(queued({'selection': 'adopted'})[:2], ([url('a')], [(one['shotId'], 'adopted')]))
        self.assertEqual(queued({'selection': 'adopted', 'fill': 'latest'})[:2], ([url('a'), url('b')], [(one['shotId'], 'adopted'), (two['shotId'], 'latest')]))
        self.assertEqual(queued({'selection': 'adopted', 'fill': 'previs'})[:2], ([url('a'), url('c')], [(one['shotId'], 'adopted'), (two['shotId'], 'previs')]))
        for body in ({'selection': 'all'}, {'fill': 'none'}, {'fillPrevis': True, 'fill': 'latest'}):
            code, payload = self.call(f'/episodes/{self.ep}/films', 'POST', body)
            self.assertEqual((code, payload['code']), (422, 'DRAMA_VALIDATION_FAILED'), body)
        # The finished film records where every segment came from.
        with patch.object(worker, 'ffmpeg', return_value={'asset_id': 'pa_' + 'f' * 32, 'asset_url': url('f')}):
            film = self.await_task(self.ok(f'/episodes/{self.ep}/films', 'POST', {'selection': 'adopted', 'fill': 'previs'}))
        segments = [{'shotId': one['shotId'], 'source': 'adopted'}, {'shotId': two['shotId'], 'source': 'previs'}]
        named = lambda listed: [{k: s[k] for k in ('shotId', 'source')} for s in listed]  # D10 adds fields, never changes these
        self.assertEqual((film['status'], named(film['result']['segments'])), ('SUCCEEDED', segments), film)
        record = next(f for f in self.ok(f'/episodes/{self.ep}/films')['items'] if f['filmId'] == 'fl_' + film['taskId'])
        self.assertEqual((record['videoUrl'], record['segments']), (url('f'), film['result']['segments']))
        self.assertEqual([(s['takeUrl'], s['in'], s['out'], s['takeRefs']) for s in record['segments']],
                         [(url('a'), 0, None, []), (url('c'), 0, None, [])])  # adopting reset the trim; the previs plays whole
        # The cut between them is listed (shot two has no adopted take, so it cannot be checked); the last has none.
        self.assertEqual([(s['cut'] or {}).get('toShotId') for s in record['segments']], [two['shotId'], None])
        self.assertEqual(record['segments'][0]['cut']['check']['state'], 'none')
        self.ok(f'/shots/{one["shotId"]}/adoption', 'DELETE')
        code, payload = self.call(f'/episodes/{self.ep}/films', 'POST', {'selection': 'adopted'})
        self.assertEqual((code, payload['code']), (409, 'DRAMA_STAGE_PRECONDITION'))
        self.assertEqual(queued({})[0], [url('a'), url('b')])  # the RH default still exports every slate take

    def test_film_segments_name_the_take_its_cut_points_its_quotes_and_the_next_cut(self):
        """SPEC_19 D10: every segment of an export says which take plays, from where to where, what that take quoted when it
        was rendered, and the check of the cut into the next segment, as GET /episodes/{id}/cuts lists it."""
        from project_assistant import take_grader
        one, two, upstream, source = self.quoting_shots()
        done = self.generate_quoting(two['shotId'], source)[2]
        [ref] = done['result']['storyProvenance']['takeRefs']
        takes = lambda identifier: {t['url']: t['videoId'] for t in self.ok(f'/shots/{identifier}/videos?limit=100')['items']}
        self.ok(f"/shots/{one['shotId']}/adoptions", 'POST', {'videoId': takes(one['shotId'])[upstream]})
        self.ok(f"/shots/{two['shotId']}/adoptions", 'POST', {'videoId': takes(two['shotId'])[done['result']['videoUrl']]})
        self.ok(f"/shots/{one['shotId']}/trim", 'PUT', {'in': 0.125, 'out': 0.375})
        with patch.object(take_grader, 'kick'):
            self.assertEqual(self.ok(f'/episodes/{self.ep}/cut-checks', 'POST', {})['queued'], 1)
        cut = next(c for c in self.ok(f'/episodes/{self.ep}/cuts')['items'] if c['fromShotId'] == one['shotId'])
        self.assertEqual((cut['toShotId'], cut['check']['state']), (two['shotId'], 'queued'))
        def segments(body):
            with patch.object(story._POOL, 'submit'):
                task = self.ok(f'/episodes/{self.ep}/films', 'POST', body)
            job = story.record(self.conn, task['taskId'])['_job']
            self.conn.rollback()
            return job['segments']
        first, second = segments({'selection': 'adopted'})
        self.assertEqual(first, {'shotId': one['shotId'], 'source': 'adopted', 'takeUrl': upstream, 'in': 0.125, 'out': 0.375,
                                 'takeRefs': [], 'cut': {k: v for k, v in cut.items() if k != 'index'}})
        self.assertEqual(second, {'shotId': two['shotId'], 'source': 'adopted', 'takeUrl': done['result']['videoUrl'], 'in': 0,
                                  'out': None, 'takeRefs': [ref], 'cut': None})
        # The RH request keeps its segments' original fields and order; the template shots without a take stay out of it.
        self.assertEqual([(s['shotId'], s['source']) for s in segments({})], [(one['shotId'], 'adopted'), (two['shotId'], 'adopted')])

    def test_look_catalog_lists_the_options_of_a_kind(self):
        """SPEC_19 package B: GET /catalog/looks, paged like /catalog/styles; an unknown kind is a 400 with a message key."""
        from project_docs import story_look
        everything = self.ok('/catalog/looks?limit=100')
        self.assertEqual((everything['items'], everything['nextCursor']), (story_look.api_items(), None))
        first = self.ok('/catalog/looks')
        self.assertEqual((len(first['items']), first['items']), (20, story_look.api_items()[:20]))
        self.assertEqual(self.ok('/catalog/looks?cursor=' + first['nextCursor'])['items'], story_look.api_items()[20:40])
        camera = self.ok('/catalog/looks?kind=camera&limit=100')['items']
        self.assertEqual({(i['kind'], i['group']) for i in camera}, {('camera', 'body'), ('camera', 'lens'), ('camera', 'aperture')})
        self.assertEqual(camera[1], {'id': 'digital-cinema', 'kind': 'camera', 'group': 'body', 'labelKey': 'lookCatalog.camera.body.digitalCinema',
                                     'promptText': story_look.option('camera', 'digital-cinema')['promptText'],
                                     'preview': {'poster': '/projects/assets/look-samples/camera/digital-cinema.webp', 'clip': None}})
        moves = self.ok('/catalog/looks?kind=move&limit=100')['items']
        self.assertEqual([i['id'] for i in moves][:2], ['auto', 'push-in'])
        self.assertTrue(all(set(i) == {'id', 'kind', 'labelKey', 'promptText', 'preview'} for i in moves))
        # SPEC_19 package C: genre, era, tempo, palette and light, colours on the palettes.
        palettes = self.ok('/catalog/looks?kind=palette&limit=100')
        self.assertEqual((palettes['items'], palettes['nextCursor']), (story_look.api_items('palette'), None))
        self.assertEqual([('hex' in i, i['id'] == 'auto') for i in palettes['items']][:2], [(False, True), (True, False)])
        self.assertEqual(palettes['items'][1]['hex'][:2], ['#2E3A4A', '#5B6F86'])
        for kind, count in (('genre', 9), ('era', 6), ('tempo', 5), ('light', 8)):
            self.assertEqual([i['id'] for i in self.ok(f'/catalog/looks?kind={kind}&limit=100')['items']][1:],
                             [i['id'] for i in story_look.api_items(kind)][1:])
            self.assertEqual(len(story_look.api_items(kind)), count)
        code, payload = self.call('/catalog/looks?kind=colour')
        self.assertEqual((code, payload['code'], payload['message_key'], payload['message_params']['kind']),
                         (400, 'DRAMA_VALIDATION_FAILED', 'errors.unknownLookKind', 'colour'))

    def test_a_prompt_preview_is_word_for_word_what_the_worker_sends(self):
        """SPEC_19 B6: prompt-previews compiles the request with the worker's own functions (# moves and quoted takes become
        their sentences) without writing anything; the real worker then submits exactly that text to ComfyUI."""
        from unittest.mock import Mock
        one, two = self.prepare()
        upstream = self.generation_inputs(one['shotId'], self.render_bytes('red'))
        source = self.generation_inputs(two['shotId'], self.render_bytes('blue'))
        label = one['shotIndex']
        self.assertRegex(label, r'^SC\d\d-S\d\d$')  # a storyboard build's real label
        self.ok('/shots/' + two['shotId'], 'PATCH', {'description': f'[0-2s] @{label.lower()}.end @CAST-01 turns. #push-in He stops, #unknown stays.'})
        body = {'appCode': '2109942725885075458', 'modelParams': {'driving_video': source}}
        def footprint():
            self.conn.rollback()
            with self.conn.cursor() as cur:
                cur.execute('SELECT count(*), max(updated_at) FROM projectops.story_record WHERE project_slug=%s OR owner_id=%s', (self.slug, self.actor))
                records = cur.fetchone()
            return records, len(repo.revision_rows(self.conn, self.slug, tab_key='cinema-studio'))
        before = footprint()
        with patch.object(story._POOL, 'submit', side_effect=AssertionError('a preview never queues')):
            preview = self.ok(f"/shots/{two['shotId']}/prompt-previews", 'POST', dict(body, count=2))
        self.assertEqual(footprint(), before)
        self.assertEqual(sorted(preview), ['compiledPrompt', 'droppedBlocks', 'look', 'referencePlan', 'references'])  # SPEC_21 adds the last two
        text = preview['compiledPrompt']
        self.assertIn(f'Match the setting and lighting of shot {label}.', text)
        from project_docs import story_look
        self.assertIn(story_look.option('move', 'push-in')['promptText'] + ' He stops', text)
        self.assertIn('#unknown stays', text)
        self.assertNotIn('#push-in', text)
        self.assertEqual(preview['look']['moves'], ['push-in'])
        self.assertEqual(preview['look']['cameraMovement'], '')  # the #tags are the shot's movement now
        self.assertEqual(preview['look']['opticalRig'], self.ok('/shots/' + two['shotId'])['opticalRig'])
        assets = [r for r in preview['references'] if r['kind'] == 'asset']
        self.assertIn('CAST-01', [r['code'] for r in assets])
        self.assertEqual([r for r in preview['references'] if r['kind'] == 'take'],
                         [{'kind': 'take', 'shotId': one['shotId'], 'shotIndex': label, 'edge': 'end', 'takeUrl': upstream, 'at': None,
                           'frameUrl': None, 'use': 'reference', 'adopted': False, 'lastFrameAt': None}])
        # The same request through the real worker, ComfyUI replaced by a client that only records the graph it receives.
        client = Mock()
        client.upload_media.return_value = 'reference.png'
        client.submit_workflow.return_value = 'job-1'
        client.fetch_history.return_value = {'job-1': {'status': {'completed': True}, 'outputs': {'51': {'videos': [{'filename': 'take.mp4'}]}}}}
        client.download_output.return_value = (self.render_bytes('green'), 'video/mp4')
        with patch.object(story._POOL, 'submit'):
            queued = self.ok(f"/shots/{two['shotId']}/video-generations", 'POST', body)
        self.conn.rollback()
        with patch.object(worker, 'ComfyPlatformClient', return_value=client):
            story.execute_task(queued['taskId'])
        done = self.ok('/tasks/' + queued['taskId'])
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        graph = client.submit_workflow.call_args[0][0]
        self.assertEqual(graph['57']['inputs']['text'], text)
        # Read-only crew cannot preview (it is a generation request), and a bad count is refused as for a generation.
        self.assertEqual(self.call(f"/shots/{two['shotId']}/prompt-previews", 'POST', dict(body, count=5))[0], 422)
        self.assertEqual(self.call(f"/shots/{two['shotId']}/prompt-previews", 'POST', dict(body, kind='audio'))[0], 422)

    def test_a_generation_count_queues_that_many_takes_each_with_its_own_seed(self):
        """SPEC_19 B7: count 1-4 queues that many tasks; each take's seed advances by its take number."""
        import os
        identifier = self.prepare()[0]['shotId']
        self.generation_inputs(identifier)  # one video take (the source) and a first frame
        path = f'/shots/{identifier}/video-generations'
        body = {'appCode': 'LTX25_CINEMA_SHOT'}
        def seeds(answer):
            found = [story.record(self.conn, t['taskId'])['_job']['values'].get('3.seed') for t in answer['tasks']]
            self.conn.rollback()
            return found
        with patch.object(story._POOL, 'submit') as submit:
            many = self.ok(path, 'POST', dict(body, count=2))
            self.assertEqual((sorted(many), many['count'], len(many['tasks'])), (['count', 'tasks'], 2, 2))
            self.assertTrue(all(t['status'] == 'QUEUED' and t['type'] == 'SHOT_VIDEO_GENERATE' for t in many['tasks']))
            job = story.record(self.conn, many['tasks'][0]['taskId'])['_job']
            base = worker.resolve_studio_context({'input': job['input'], 'capability': 'video_gen'})['seed'] or 48291
            # One take exists: this batch is takes 1 and 2.
            self.assertEqual(seeds(many), [str(base + 1), str(base + 2)])
            # Sent while those two are still queued, the next take does not reuse their seeds.
            self.assertEqual(seeds(self.ok(path, 'POST', dict(body, count=1))), [str(base + 3)])
            # An explicit seed is where the takes start from.
            self.assertEqual(seeds(self.ok(path, 'POST', dict(body, count=2, modelParams={'3.seed': 7}))), ['11', '12'])
            # Without count the request and its answer are exactly the RH ones: one task, the card's own seed.
            single = self.ok(path, 'POST', body)
            self.assertEqual((single['type'], 'tasks' in single), ('SHOT_VIDEO_GENERATE', False))
            self.assertNotIn('3.seed', story.record(self.conn, single['taskId'])['_job']['values'])
            self.conn.rollback()
            # Images count the image takes (the first frame is one).
            images = self.ok(f'/shots/{identifier}/image-generations', 'POST', {'appCode': 'LOCAL_SDXL_SMOKE', 'count': 2})
            self.assertEqual(len(seeds(images)), 2)
            self.assertEqual(int(seeds(images)[1]) - int(seeds(images)[0]), 1)
        self.assertEqual(submit.call_count, 2 + 1 + 2 + 1 + 2)
        for count in (0, 5, -1, 2.0, '2', True, None, [2]):
            code, payload = self.call(path, 'POST', dict(body, count=count))
            self.assertEqual((code, payload['code']), (422, 'DRAMA_VALIDATION_FAILED'), count)
        # An official Router card renders one quoted take per request: several are refused before anything is queued.
        story.store(self.conn, 'policy_' + self.slug, 'production_policy', {'productionPolicy': 'hybrid_studio'}, self.slug)
        self.conn.commit()
        with patch.dict(os.environ, {'OPENBENCH_PRODUCTION_POLICY': 'hybrid_studio'}), patch.object(story._POOL, 'submit') as submit:
            code, payload = self.call(path, 'POST', {'appCode': 'router-ltx-2-5-pro', 'count': 2})
        self.assertEqual((code, payload['code'], submit.call_count), (422, 'DRAMA_VALIDATION_FAILED', 0))
        self.assertIn('Router', payload['message'])

    def test_imported_cards_are_authenticated_persisted_and_in_catalog(self):
        card_id = 'test-card-' + self.slug
        body = {'card_id': card_id, 'workflow': {'1': {'class_type': 'LoadImage', 'inputs': {'image': 'test.png'}}, '2': {'class_type': 'SaveImage', 'inputs': {'images': ['1', 0], 'filename_prefix': 'test'}}}}
        path = '/openapi/v2/cards/register'
        self.assertEqual(self.request(path, method='POST', data=body, authenticated=False)[0], 401)
        code, payload, _ = self.request(path, method='POST', data=body)
        self.assertEqual(code, 200, payload)
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS.pop(card_id, None)
        story.restore_cards(self.conn)
        self.assertTrue(any(a['card_id'] == card_id for a in self.ok('/catalog/apps?capability=IMAGE')['items']))
        body['workflow'] = 'C:/secret.json'
        self.assertEqual(self.request(path, method='POST', data=body)[0], 422)
        with worker._OPENAPI_LOCK:
            worker._OPENAPI_CARDS.pop(card_id, None)
            worker._OPENAPI_CARDS.pop(payload['webappId'], None)

    def test_multi_episode_shots_variants_patch_and_scene_rebuild(self):
        first = self.prepare()
        ep = self.ok(f'/projects/pj_{self.slug}/episodes', 'POST', {'title': 'Second Episode'})
        second_id = ep['episodeId']
        self.ok('/episodes/' + second_id + '/script', 'PUT', {'scriptContent': 'Scene 01: Second\n@CAST-02 runs.'})
        self.ok('/episodes/' + second_id + '/asset-extractions', 'POST', {})
        self.ok('/episodes/' + second_id + '/storyboards', 'POST', {})
        second = self.ok('/episodes/' + second_id + '/shots')['items']
        self.assertEqual(len(second), 1)
        self.assertFalse({s['shotId'] for s in first} & {s['shotId'] for s in second})
        self.assertEqual(self.call('/episodes/' + second_id + '/shot-video-generations', 'POST', {'appCode': 'h3-reference', 'shotIds': [first[0]['shotId']]})[0], 422)
        scene = self.ok('/episodes/' + second_id + '/scenes')['items'][0]
        self.ok('/scenes/' + scene['sceneId'], 'PATCH', {'content': '@CAST-02 stops at the door.'})
        self.assertEqual(self.call('/scenes/' + scene['sceneId'] + '/shot-rebuilds', 'POST', {})[0], 409)
        self.ok('/episodes/' + second_id + '/asset-extractions', 'POST', {})
        self.ok('/scenes/' + scene['sceneId'] + '/shot-rebuilds', 'POST', {})
        self.assertIn('stops at the door', self.ok('/shots/' + second[0]['shotId'])['description'])

    def test_webhooks_sign_exact_bytes_mask_secrets_and_bound_retries(self):
        from urllib.parse import urlsplit
        from unittest.mock import MagicMock
        import hashlib, hmac
        with patch.object(story, 'webhook_address', return_value=(urlsplit('https://example.org/hook'), '93.184.216.34')), patch.object(story._POOL, 'submit'):
            hook = self.ok('/webhooks', 'POST', {'url': 'https://example.org/hook'})
            self.assertNotEqual(self.ok('/webhooks')['items'][0]['secret'], hook['secret'])
            delivery = self.ok('/webhooks/' + hook['webhookId'] + '/test-deliveries', 'POST', {})
        transport = MagicMock(); transport.getresponse.return_value.status = 202
        with patch.object(story, 'webhook_address', return_value=(urlsplit(hook['url']), '93.184.216.34')), patch.object(story, 'HTTPSConnection', return_value=transport), patch.object(story.socket, 'create_connection'), patch.object(story.ssl, 'create_default_context'):
            story.deliver(delivery['deliveryId'])
        method, path, raw, headers = transport.request.call_args.args
        stamp = headers['X-RH-Signature'].split(',')[0][2:]
        expected = hmac.new(hook['secret'].encode(), stamp.encode() + b'.' + raw, hashlib.sha256).hexdigest()
        self.assertEqual(headers['X-RH-Signature'], f't={stamp},v1={expected}')
        self.assertEqual(self.ok('/webhooks/' + hook['webhookId'] + '/deliveries')['items'][0]['status'], 'SUCCEEDED')
        with patch.object(story._POOL, 'submit'):
            failed = self.ok('/webhooks/' + hook['webhookId'] + '/test-deliveries', 'POST', {})
        with patch.object(story, 'webhook_address', side_effect=ValueError('offline')), patch.object(story, 'retry_delivery') as retry:
            for _ in range(6):
                story.deliver(failed['deliveryId'])
            self.assertEqual(retry.call_count, 5)
        self.assertEqual(story.record(self.conn, failed['deliveryId'])['status'], 'DEAD')

    def test_script_refinement_is_configured_async_and_invalidates_baseline(self):
        from types import SimpleNamespace
        from project_assistant import providers
        self.prepare()
        path = '/episodes/' + self.ep + '/script-refinements'
        seen = []

        def turn(**kwargs):
            seen.append((kwargs['config'].base_url, kwargs['config'].model))
            return SimpleNamespace(status='ok', answer='Scene 01: Draft\\n@CAST-01 waits.')
        # SPEC_20 R2: with no OPENBENCH_* variables the refinement runs on the local default model.
        with patch.dict(os.environ, {'OPENBENCH_MODEL': '', 'OPENBENCH_API_BASE': ''}), patch.object(providers, 'run_openai_compat_turn', side_effect=turn):
            done = self.await_task(self.ok(path, 'POST', {'instruction': 'Improve pacing'}))
        self.assertEqual((done['status'], seen), ('SUCCEEDED', [(providers.DEFAULT_BASE_URL, providers.DEFAULT_MODEL)]), done)
        with patch.dict(os.environ, {'OPENBENCH_PROVIDER': 'openai_compat', 'OPENBENCH_MODEL': 'local-test', 'OPENBENCH_API_BASE': 'http://127.0.0.1:11434/v1'}), patch.object(providers, 'run_openai_compat_turn', return_value=SimpleNamespace(status='ok', answer='Scene 01: Revised\\n@CAST-01 pauses.')):
            done = self.await_task(self.ok(path, 'POST', {'instruction': 'Improve pacing'}))
        self.assertEqual(done['status'], 'SUCCEEDED', done)
        self.assertTrue(self.ok('/episodes/' + self.ep)['scriptDirty'])
        self.assertIn('Revised', self.ok('/episodes/' + self.ep)['scriptContent'])

    def test_batch_group_counts_are_strings_and_outputs_are_per_row(self):
        from PIL import Image
        data = io.BytesIO(); Image.new('RGB', (8, 8), 'green').save(data, format='PNG')
        shots = self.prepare()
        with patch.object(worker, 'execute_story_card', side_effect=lambda task, card, values, head: head.upload(task, data.getvalue(), 'image/png')):
            group = self.ok('/episodes/' + self.ep + '/shot-image-generations', 'POST', {'appCode': 'LOCAL_SDXL_SMOKE', 'shotIds': [s['shotId'] for s in shots]})
            for identifier in group['taskIds']:
                self.assertEqual(self.await_task({'taskId': identifier})['status'], 'SUCCEEDED')
        detail = self.ok('/task-groups/' + group['taskGroupId'])
        self.assertEqual(detail['counts']['succeeded'], '2')
        self.assertTrue(all(isinstance(v, str) for v in detail['counts'].values()))

    def test_cancel_preserves_new_selection_and_explicit_retry(self):
        identifier = self.prepare()[0]["shotId"]
        source = self.generation_inputs(identifier)
        queued = []
        with patch.object(story._POOL, "submit", side_effect=lambda *args: queued.append(args)):
            task = self.ok(f"/shots/{identifier}/video-generations", "POST", {"appCode": "h3-reference", "modelParams":{"driving_video":source}})
            self.ok("/tasks/" + task["taskId"] + "/cancellations", "POST", {})
            retry = self.ok("/tasks/" + task["taskId"] + "/retries", "POST", {})
        self.assertNotEqual(task["taskId"], retry["taskId"])
        self.assertEqual(self.ok("/tasks/" + task["taskId"])["status"], "CANCELED")
        self.assertEqual(len(queued), 2)
