"""R44-4, R44-5 and the doubled scene number: a standard screenplay gives cast cards, one set per location and
"Scene 01: INT. ..." titles.

Pure checks run anywhere (the paste goes through the real ui/src/writing/writingStartHandoff.js in Node); the Story
API case needs OPENBENCH_TEST_DB_URI. No model, provider or GPU.
"""
import os
import unittest

from project_docs import scene_headings, story_adaptation as adaptation, story_openapi as story
from project_docs.doc_schema import doc_text
from project_assistant import crew_writing
import test_story_openapi as story_http
from test_scene_headings import EP, start_document

# The R44 walk's shape: numbered headings, cues alone on their line over unquoted dialogue, extensions, transitions,
# shot directions, a sound word, and scene 3 back in scene 1's control room.
SPILLWAY = """SPILLWAY

FADE IN:

1. INT. SPILLWAY CONTROL ROOM - NIGHT

Rain hammers the glass. NORA VESK (40s) faces the gauges, jaw tight.

BOOM
The whole room shudders.

NORA
The gate is jammed. Get Eli up here.

CLOSE ON
The pressure dial climbs into the red.

ELI (O.S.)
I'm already here.

CUT TO:

2. EXT. DAM WALKWAY - NIGHT

Wind. Eli grips the rail and looks straight at us.

ELI (CONT'D)
(shouting)
Then we open it by hand!

SMASH CUT TO:

3. INT. SPILLWAY CONTROL ROOM - LATER

NORA
Eli? Eli!

THE END
"""
TITLES = ['1. INT. SPILLWAY CONTROL ROOM - NIGHT', '2. EXT. DAM WALKWAY - NIGHT', '3. INT. SPILLWAY CONTROL ROOM - LATER']
OURS = ['Scene 01: INT. SPILLWAY CONTROL ROOM - NIGHT', 'Scene 02: EXT. DAM WALKWAY - NIGHT',
        'Scene 03: INT. SPILLWAY CONTROL ROOM - LATER']


def pasted_scenes():
    """The scenes the crew and the storyboard build read after the screenplay is pasted in New Production."""
    return story.scenes_of_doc(EP, start_document(SPILLWAY))


class ScreenplayCueTests(unittest.TestCase):
    def test_standard_cues_become_cast_once_without_extensions(self):
        self.assertEqual(adaptation.character_details(SPILLWAY), [('Nora', '', None), ('Eli', '', None)])
        self.assertEqual([(name, code) for name, _, code in adaptation.allocated_characters(SPILLWAY)],
                         [('Nora', 'CAST-01'), ('Eli', 'CAST-02')])
        doc = start_document(SPILLWAY)
        self.assertEqual(adaptation.character_details(doc_text(doc)), [('Nora', '', None), ('Eli', '', None)])
        for line, name in [("ELI (O.S.)", 'Eli'), ("NORA (V.O.)", 'Nora'), ("ELI (CONT'D)", 'Eli'), ("NORA (CONT’D)", 'Nora'),
                           ('MR. VESK', 'Mr. Vesk'), ('GUARD 2', 'Guard 2'), ('NORA ^', 'Nora'), ("DR. O'NEIL", "Dr. O'neil")]:
            with self.subTest(line=line):
                self.assertEqual(adaptation.cue_name(line, 'We have to go.'), name)
                self.assertEqual(adaptation.cue_name(line, '(quietly)'), name)

    def test_headings_transitions_directions_and_sound_words_are_no_one(self):
        for line in ['FADE IN:', 'CUT TO:', 'SMASH CUT TO:', 'DISSOLVE TO:', 'FADE OUT.', 'FADE TO BLACK.', 'THE END', 'CLOSE ON',
                     'ANGLE ON NORA', 'INSERT - THE DIAL', 'POV', 'BACK TO SCENE', 'INTERCUT', 'MONTAGE', 'SUPER', 'BOOM', 'CRASH!',
                     'SILENCE.', 'WHAAAM', 'KNOCK KNOCK', 'INT. SPILLWAY CONTROL ROOM - NIGHT', '1. INT. DAM - NIGHT', 'EST. DAM',
                     'I/E CAR - NIGHT', 'CHAPTER ONE', 'MOMENTS LATER', 'ALL', 'Nora', 'nora', 'N']:
            with self.subTest(line=line):
                self.assertIsNone(adaptation.cue_name(line, 'The whole room shudders.'))
        self.assertIsNone(adaptation.cue_name('NORA', ''), 'a cue needs its dialogue on the next line')
        self.assertIsNone(adaptation.cue_name('NORA', 'ELI'), 'two caps lines are not a cue and its line')
        self.assertIsNone(adaptation.cue_name('NORA', 'INT. DAM - NIGHT'))
        text = 'FADE IN:\n\nINT. DAM - NIGHT\n\nBOOM\nThe room shudders.\n\nCUT TO:\nThe crest.\n\nTITLE: "Spillway"'
        self.assertEqual(adaptation.character_details(text), [])

    def test_cue_lines_survive_story_import_and_the_crew_breakdown(self):
        imported = story.script_doc(EP['slug'], SPILLWAY)
        self.assertIn({'type': 'hardBreak'}, imported['content'][7]['content'], 'the cue keeps its own line in one block')
        self.assertEqual(adaptation.character_details(doc_text(imported)), [('Nora', '', None), ('Eli', '', None)])
        scenes = pasted_scenes()
        self.assertEqual([s['title'] for s in scenes], TITLES)
        data = [(scene, *crew_writing.scene_units(scene)) for scene in scenes]
        units, paragraphs = data[0][1], data[0][2]
        self.assertEqual(units[3:5], ['NORA\nThe gate is jammed.', 'Get Eli up here.'])
        self.assertEqual(paragraphs[2], [4, 5])
        self.assertIn('4. NORA: The gate is jammed.', crew_writing.breakdown_prompt(
            {'episode': {'id': 'ep', 'title': ''}, 'scenes': [{'sceneId': 's', 'title': TITLES[0], 'units': units}]}))
        # The model cuts inside Nora's speech and joins it with the next paragraphs: the cue repeats for the second
        # shot and every cue keeps its own line, so the adopted script still names who speaks in each shot.
        answer = {'scenes': [{'sceneId': data[0][0]['sceneId'], 'shots': [{'from': 1, 'to': 4}, {'from': 5, 'to': len(units)}]},
                             {'sceneId': data[1][0]['sceneId'], 'shots': [{'from': 1, 'to': len(data[1][1])}]},
                             {'sceneId': data[2][0]['sceneId'], 'shots': [{'from': 1, 'to': len(data[2][1])}]}]}
        self.assertEqual(crew_writing.validate_breakdown(answer | {'scenes': [{**s, 'shots': [{**x, 'reason': 'r'} for x in s['shots']]}
                                                                             for s in answer['scenes']]},
                                                         {'scenes': [{'sceneId': s['sceneId'], 'units': u} for s, u, _, _ in data]}), [])
        text = crew_writing.reblocked_script(data, answer)
        self.assertEqual([line for line in text.splitlines() if line.startswith('## ')], ['## ' + title for title in OURS])
        adopted = story.scenes_of_doc(EP, story.script_doc(EP['slug'], text))
        beats = adaptation.scene_shot_beats(adopted[0]['content'], 'auto')
        self.assertEqual(len(beats), 2)
        self.assertTrue(beats[0].endswith('The whole room shudders.\nNORA\nThe gate is jammed.'), beats[0])
        self.assertTrue(beats[1].startswith('NORA\nGet Eli up here.\nCLOSE ON'), beats[1])
        self.assertIn("\nELI (O.S.)\nI'm already here.", beats[1])
        self.assertEqual(adaptation.character_details(doc_text(story.script_doc(EP['slug'], text))),
                         [('Nora', '', None), ('Eli', '', None)])

    def test_cinematic_cuts_and_dialogue_keep_the_speaker(self):
        scene = pasted_scenes()[0]
        beats = adaptation.scene_shot_beats(scene['content'], 'cinematic')
        self.assertIn('NORA\nThe gate is jammed.', beats)
        self.assertIn('NORA\nGet Eli up here.', beats)
        self.assertEqual(adaptation.beat_sentences('MR. VESK\nStop. Now.'), ['MR. VESK\nStop.', 'Now.'], 'a cue is never cut')
        dialogue = adaptation.infer_shot_grammar("ELI (CONT'D)\n(shouting)\nThen we open it by hand!", 1, 3)['dialogue']
        self.assertEqual([(d['speaker'], d['line']) for d in dialogue], [('Eli', 'Then we open it by hand!')])
        self.assertEqual(adaptation.infer_shot_grammar('NORA\n"The gate is jammed."', 1, 3)['dialogue'][0]['line'], 'The gate is jammed.')


class SceneTitleTests(unittest.TestCase):
    def test_our_headings_never_repeat_the_scenes_own_number(self):
        for title, ours in [(TITLES[0], OURS[0]), ('#3 INT. STAIRWELL - NIGHT', 'Scene 01: INT. STAIRWELL - NIGHT'),
                            ('Scene 07: Dawn', 'Scene 01: Dawn'), ('Scene 07', 'Scene 01: Scene'), ('12 Angry Men', 'Scene 01: 12 Angry Men'),
                            ('1. Nora runs toward the gate.', 'Scene 01: 1. Nora runs toward the gate.')]:
            with self.subTest(title=title):
                self.assertEqual(scene_headings.numbered_title(1, title), ours)
        adapted = adaptation.adapt_source_to_script(SPILLWAY, 'script')
        self.assertEqual([line[3:] for line in adapted.splitlines() if line.startswith('## ')], OURS)
        compiled = crew_writing.compile_scenes([{'title': t, 'content': 'Nora waits.'} for t in TITLES])
        self.assertEqual([line[3:] for line in compiled.splitlines() if line.startswith('## ')], OURS)


class SceneSetTests(unittest.TestCase):
    def test_untagged_scenes_at_one_location_share_one_set(self):
        scenes = pasted_scenes()
        self.assertEqual(adaptation.scene_set_codes(scenes), [['SET-01'], ['SET-02'], ['SET-01']])
        for title, place in [(TITLES[0], 'SPILLWAY CONTROL ROOM'), (TITLES[2], 'SPILLWAY CONTROL ROOM'), ('EXT. DAM CREST - CONTINUOUS', 'DAM CREST'),
                             ('INT./EXT. CAR - MOVING', 'CAR'), ('INT. HOUSE - KITCHEN - DAY', 'HOUSE - KITCHEN'),
                             ('EXT. SPILLWAY - NIGHT (FLASHBACK)', 'SPILLWAY'), ('Scene 02: Dawn', '')]:
            with self.subTest(title=title):
                self.assertEqual(scene_headings.scene_location(title), place)

    def test_a_new_set_never_takes_another_sets_code_and_stays_put(self):
        scenes = pasted_scenes()
        template = [('SET-01', 'Observatory'), ('CAST-01', 'Kael')]
        chosen = {}
        details = adaptation.extract_asset_details(doc_text(start_document(SPILLWAY)), scenes, template, None, chosen)
        self.assertEqual(adaptation.scene_set_codes(scenes, template), [['SET-02'], ['SET-03'], ['SET-02']])
        self.assertNotIn('SET-01', details, 'the template Observatory is never given scene-1 text')
        self.assertEqual((details['SET-02']['name'], details['SET-03']['name']), ('Spillway Control Room', 'Dam Walkway'))
        self.assertIn('Rain hammers the glass', details['SET-02']['traits'], 'the first scene at the location describes it')
        self.assertEqual({code: details[code]['name'] for code in details if code.startswith('CAST')},
                         {'CAST-02': 'Nora', 'CAST-03': 'Eli'}, 'Kael keeps CAST-01')
        self.assertEqual(chosen, {'cast:nora': 'CAST-02', 'cast:eli': 'CAST-03', 'set:spillway control room': 'SET-02',
                                  'set:dam walkway': 'SET-03'})
        # After the extraction the cards exist: the build finds them by name, or by the kept choice after a rename.
        cards = template + [('SET-02', 'Spillway Control Room'), ('SET-03', 'Dam Walkway')]
        self.assertEqual(adaptation.scene_set_codes(scenes, cards), [['SET-02'], ['SET-03'], ['SET-02']])
        renamed = template + [('SET-02', 'Control room in the rain'), ('SET-03', 'Dam Walkway')]
        self.assertEqual(adaptation.scene_set_codes(scenes, renamed, chosen), [['SET-02'], ['SET-03'], ['SET-02']])
        # An old extraction named the card by its numbered heading: still the same place.
        self.assertEqual(adaptation.scene_set_codes(scenes, template + [('SET-05', '1. INT. SPILLWAY CONTROL ROOM - NIGHT')])[0], ['SET-05'])

    def test_explicit_tags_still_win(self):
        tagged = [{'title': TITLES[0], 'content': 'Environment: @SET-07, rain.'}, {'title': TITLES[1], 'content': 'Wind.'},
                  {'title': TITLES[2], 'content': 'NORA\nEli?'}, {'title': 'Scene 04: Coda', 'content': '@LOC-02 at dawn.'}]
        self.assertEqual(adaptation.scene_set_codes(tagged, [('SET-01', 'Observatory')]), [['SET-07'], ['SET-02'], ['SET-07'], ['LOC-02']])


@unittest.skipUnless(os.environ.get('OPENBENCH_TEST_DB_URI'), 'set OPENBENCH_TEST_DB_URI for Story HTTP tests')
class SpillwayStoryAPITests(unittest.TestCase):
    """PUT script -> asset extraction -> storyboard build on a production whose template already has cards."""
    # The Story HTTP fixture's helpers, borrowed (not inherited, so its own tests do not run again here).
    setUp, tearDown = story_http.StoryHTTPTests.setUp, story_http.StoryHTTPTests.tearDown
    request, call, ok = story_http.StoryHTTPTests.request, story_http.StoryHTTPTests.call, story_http.StoryHTTPTests.ok

    def test_cues_cast_and_shared_sets_through_the_story_api(self):
        before = {a['assetCode']: a['name'] for a in self.ok(f'/episodes/{self.ep}/assets?limit=100')['items']}
        self.ok(f'/episodes/{self.ep}/script', 'PUT', {'scriptContent': SPILLWAY})
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        after = {a['assetCode']: a for a in self.ok(f'/episodes/{self.ep}/assets?limit=100')['items']}
        people = {a['name']: code for code, a in after.items() if a['type'] == 'CHARACTER' and a['isDefault'] and code not in before}
        self.assertEqual(set(people), {'Nora', 'Eli'})
        for code, name in before.items():
            self.assertEqual(after[code]['name'], name, 'an existing card keeps its name and code')
        sets = {a['name']: code for code, a in after.items() if code.startswith('SET-') and code not in before}
        self.assertEqual(set(sets), {'Spillway Control Room', 'Dam Walkway'})
        self.assertNotIn('assetCodeMap', self.ok(f'/episodes/{self.ep}'))
        self.ok(f'/episodes/{self.ep}/storyboards', 'POST', {})
        shots = [s for s in self.ok(f'/episodes/{self.ep}/shots?limit=100')['items'] if s.get('sceneId')]
        by_scene = {}
        for shot in shots:
            by_scene.setdefault(shot['sceneId'][-3:], []).append(shot['description'])
        room, walkway = '@' + sets['Spillway Control Room'], '@' + sets['Dam Walkway']
        self.assertTrue(all(room in d for d in by_scene['S01'] + by_scene['S03']), by_scene)
        self.assertTrue(all(walkway in d and room not in d for d in by_scene['S02']), by_scene)
        spoken = [d for d in shots if d['description'].startswith(('NORA\n', 'ELI'))]
        self.assertTrue(spoken)
        for shot in spoken:
            self.assertIn('@' + people['Nora' if shot['description'].startswith('NORA') else 'Eli'], shot['description'])
        # A rebuild finds the same codes again.
        self.ok(f'/episodes/{self.ep}/asset-extractions', 'POST', {})
        again = {a['assetCode'] for a in self.ok(f'/episodes/{self.ep}/assets?limit=100')['items']}
        self.assertEqual(again, set(after))


if __name__ == '__main__':
    unittest.main()
