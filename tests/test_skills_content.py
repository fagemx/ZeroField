"""SPEC_20 R32: the workflow manuals in skills/ keep a valid header, the required sections, only real tool names and no
camera brand names. The manuals are guidance; the tools enforce safety, so this checks content, not behaviour."""
import re
import unittest
from pathlib import Path

from project_assistant import tool_registry

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / 'skills'
MANUALS = ('crew-preproduction', 'shot-beats', 'previs-blocking', 'continuity-check')

# SPEC_20 section 4.7: the tools a manual may name before they exist in the registry.
SPEC_TOOLS = frozenset({
    'read_episode', 'read_scene', 'read_shot', 'read_cast', 'list_takes',
    'propose_shot_prompt', 'propose_camera', 'propose_previs_ops', 'propose_asset_description', 'propose_cast',
    'propose_look', 'request_generation', 'get_workflow'})
KNOWN_TOOLS = SPEC_TOOLS | frozenset(tool_registry.NAMES)
# snake_case words a manual may put in backticks that are not tools. Add to this on purpose, not to silence a typo.
NOT_TOOLS = frozenset()
TOOL_VERBS = ('read', 'list', 'propose', 'request', 'get', 'studio', 'report', 'search', 'spawn', 'check', 'cancel',
              'consult', 'offer', 'ask', 'trigger')

HEADER_KEYS = ['name', 'description', 'version']
SECTIONS = ['When to use', 'Hard rules', 'Intake questions', 'Steps', 'Validation', 'Human approval', 'No auto-spend',
            'Failure handling']
MIN_LINES, MAX_LINES = 60, 200  # the brief asks for roughly 80 to 160

# Camera and lens makers or models. The image models letter them onto props (Phase 2), so no manual may carry one.
BRANDS = re.compile(r'\b(?:arri|arriflex|alexa|panavision|sony|canon|nikon|blackmagic|bolex|leica|zeiss|cooke|kodak|gopro'
                    r'|panasonic|hasselblad|angenieux|aaton|fujifilm|tamron|samyang|schneider|v-raptor)\b', re.I)
UPPERCASE_BRAND = re.compile(r'\bRED\b')  # the colour is fine in lower case

# What each manual must still say, so a rewrite cannot quietly drop a rule from the spec.
COMMON = ('front-facing', 'appearance', 'proposal', 'director')
REQUIRED_PHRASES = {
    'crew-preproduction': ('SCRIPT LOCK', 'LIST LOCK', 'STORYBOARD LOCK', 'insert', 'Stage 1 - Screenwriter',
                           'Stage 2 - Art', 'Stage 3 - Cinematographer', 'Stage 4 - Continuity'),
    'shot-beats': ('contiguous', '4, 6, 8 or 10', '`@` tag', 'brand', 'insert', 'Sound:', '0-1.5s'),
    'previs-blocking': ('baseRevision', '409', 'never write code', 'place', 'camera', 'retime', 'preview'),
    'continuity-check': ('Findings and proposals', 'insert', 'adopted', 'information', 'join'),
}


def split_manual(text):
    """(header lines, body) of a manual, or raise ValueError."""
    match = re.match(r'---\n(.*?)\n---\n(.*)\Z', text.replace('\r\n', '\n'), re.S)
    if not match:
        raise ValueError('The manual must start with a --- header block.')
    return match.group(1).split('\n'), match.group(2)


def parse_header(lines):
    """The header is three single-line plain scalars, so a one-line parser and a YAML parser read it the same way."""
    fields = {}
    for line in lines:
        match = re.fullmatch(r'([a-z][a-z-]*): (\S.*)', line)
        if not match:
            raise ValueError('Header line is not "key: value" on one line: ' + line)
        key, value = match.groups()
        if key in fields:
            raise ValueError('Header key repeated: ' + key)
        if ': ' in value or ' #' in value or value[0] in '[]{}&*!|>\'"%@`,#-?:':
            raise ValueError('Header value is not a plain YAML scalar: ' + line)
        fields[key] = value
    if list(fields) != HEADER_KEYS:
        raise ValueError('Header keys must be exactly ' + ', '.join(HEADER_KEYS) + ' in that order; found ' + ', '.join(fields))
    if not re.fullmatch(r'\d+\.\d+', fields['version']):
        raise ValueError('version must look like 1.0')
    lowered = fields['description'].lower()
    if 'use when' not in lowered or 'not for' not in lowered:
        raise ValueError('description must say "Use when" and "Not for"')
    if not 60 <= len(fields['description']) <= 600:
        raise ValueError('description should be one to three sentences (60 to 600 characters)')
    return fields


def sections(body):
    return re.findall(r'^## (.+?)\s*$', body, re.M)


def section_text(body, title):
    parts = re.split(r'^## .+$', body, flags=re.M)
    names = sections(body)
    return parts[names.index(title) + 1]


def is_subsequence(wanted, found):
    it = iter(found)
    return all(item in it for item in wanted)


def prose(text):
    """The text without fenced code blocks (their JSON is checked by reading, not by the name scan)."""
    return re.sub(r'```.*?```', '', text, flags=re.S)


def tool_problems(text):
    """Tool-like names that no registry or spec lists."""
    text = prose(text)
    problems = set()
    for span in re.findall(r'`([^`\n]+)`', text):
        if re.fullmatch(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+', span) and span not in KNOWN_TOOLS | NOT_TOOLS:
            problems.add(span)
    for word in re.findall(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b', text):
        if word.split('_')[0] in TOOL_VERBS and word not in KNOWN_TOOLS | NOT_TOOLS:
            problems.add(word)
    return sorted(problems)


def brand_problems(text):
    return sorted({m.group(0) for m in BRANDS.finditer(text)} | {m.group(0) for m in UPPERCASE_BRAND.finditer(text)})


def discovered():
    return sorted(path.parent.name for path in SKILLS.glob('*/SKILL.md'))


class SkillsContentTests(unittest.TestCase):
    def read(self, name):
        return (SKILLS / name / 'SKILL.md').read_text(encoding='utf-8')

    def test_the_four_manuals_exist(self):
        self.assertTrue(set(MANUALS) <= set(discovered()), 'Missing manual(s): ' + ', '.join(sorted(set(MANUALS) - set(discovered()))))

    def test_header_is_valid_and_matches_the_folder(self):
        for name in discovered():
            with self.subTest(name=name):
                header, body = split_manual(self.read(name))
                fields = parse_header(header)
                self.assertEqual(fields['name'], name)
                self.assertRegex(name, r'^[a-z][a-z0-9-]*$')
                self.assertEqual(body.lstrip().splitlines()[0], '# ' + name)

    def test_required_sections_in_order(self):
        for name in discovered():
            with self.subTest(name=name):
                _, body = split_manual(self.read(name))
                found = sections(body)
                self.assertTrue(is_subsequence(SECTIONS, found), f'Sections must include {SECTIONS} in order; found {found}')
                self.assertEqual(len(found), len(set(found)), 'A section title is repeated')
                for title in SECTIONS:
                    self.assertGreater(len(section_text(body, title).strip()), 40, title + ' is empty')

    def test_length_is_tight(self):
        for name in discovered():
            with self.subTest(name=name):
                lines = len(self.read(name).splitlines())
                self.assertTrue(MIN_LINES <= lines <= MAX_LINES, f'{name} has {lines} lines')

    def test_only_known_tool_names(self):
        self.assertLessEqual({'read_page', 'propose_table_edit', 'search_pages'}, KNOWN_TOOLS)  # the registry loaded
        for name in discovered():
            with self.subTest(name=name):
                self.assertEqual(tool_problems(self.read(name)), [], 'Unknown tool-like names (add the tool to the registry, or fix the typo)')

    def test_each_manual_names_real_tools_and_the_spend_rule(self):
        for name in discovered():
            with self.subTest(name=name):
                text = self.read(name)
                used = {tool for tool in KNOWN_TOOLS if re.search(r'`' + tool + r'`', text)}
                self.assertGreaterEqual(len(used & SPEC_TOOLS), 3, 'A manual should name the SPEC_20 tools it uses')
                _, body = split_manual(text)
                spend = section_text(body, 'No auto-spend')
                self.assertIn('`request_generation`', spend)
                self.assertIn('requestId', spend)
                self.assertIn('closed or paid', spend.lower())
                self.assertIn('retry once', section_text(body, 'Failure handling').lower())
                self.assertIn('rule fallback', section_text(body, 'Failure handling').lower())

    def test_no_camera_brand_names(self):
        for name in discovered():
            with self.subTest(name=name):
                self.assertEqual(brand_problems(self.read(name)), [])
        self.assertEqual(brand_problems((SKILLS / 'README.md').read_text(encoding='utf-8')), [])

    def test_required_phrases_survive(self):
        for name in discovered():
            text = self.read(name)
            for phrase in COMMON:
                with self.subTest(name=name, phrase=phrase):
                    self.assertIn(phrase, text.lower())
            for phrase in REQUIRED_PHRASES.get(name, ()):
                with self.subTest(name=name, phrase=phrase):
                    self.assertIn(phrase, text)

    def test_crew_preproduction_orders_the_locks_and_points_at_its_siblings(self):
        text = self.read('crew-preproduction')
        positions = [text.index('Gate: ' + lock) for lock in ('SCRIPT LOCK', 'LIST LOCK', 'STORYBOARD LOCK')]
        self.assertEqual(positions, sorted(positions))
        for sibling in ('shot-beats', 'previs-blocking', 'continuity-check'):
            self.assertIn('`' + sibling + '`', text)
        self.assertIn('`get_workflow`', text)

    def test_readme_lists_every_manual_and_states_the_boundary(self):
        readme = (SKILLS / 'README.md').read_text(encoding='utf-8')
        for name in discovered():
            with self.subTest(name=name):
                self.assertIn(f'(./{name}/SKILL.md)', readme)
        self.assertIn('get_workflow', readme)
        self.assertIn('not a security boundary', readme)
        self.assertIn('the tool wins', readme)

    def test_skills_ship_with_the_package(self):
        self.assertIn('recursive-include skills', (ROOT / 'MANIFEST.in').read_text(encoding='utf-8'))
        self.assertIn('skills/', (ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
        self.assertIn('"skills"', (ROOT / 'setup.py').read_text(encoding='utf-8'))
        self.assertIn('skills/', (ROOT / 'scripts' / 'verify_wheel.py').read_text(encoding='utf-8'))


class CheckerSelfTests(unittest.TestCase):
    """The checks must actually catch what they claim to catch."""

    GOOD = '---\nname: x-y\ndescription: Does a thing for the crew in a few words. Use when asked. Not for other jobs.\nversion: 1.0\n---\n# x-y\n'

    def test_header_problems_are_caught(self):
        parse_header(split_manual(self.GOOD)[0])
        bad = [
            self.GOOD.replace('version: 1.0', 'version: one'),
            self.GOOD.replace('name: x-y\n', ''),
            self.GOOD.replace('Not for other jobs.', 'Skip other jobs.'),
            self.GOOD.replace('in a few words.', 'in a few words: really.'),
            self.GOOD.replace('description: Does', 'description: "Does'),
            self.GOOD.replace('version: 1.0', 'version: 1.0\nextra: yes'),
            self.GOOD.replace('description: Does a thing for the crew in a few words. Use when asked. Not for other jobs.', 'description: |\n  Use when. Not for.'),
        ]
        for text in bad:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_header(split_manual(text)[0])
        with self.assertRaises(ValueError):
            split_manual('# no header\n')

    def test_unknown_tools_are_caught(self):
        self.assertEqual(tool_problems('Call `propose_shot_prompt` then `read_shot` and `get_workflow`.'), [])
        self.assertEqual(tool_problems('Call `propose_shotprompt` and `read_everything`.'), ['propose_shotprompt', 'read_everything'])
        self.assertEqual(tool_problems('Then request_generations runs.'), ['request_generations'])
        self.assertEqual(tool_problems('```json\n{"read_nothing": 1}\n```'), [])

    def test_brands_are_caught(self):
        self.assertEqual(brand_problems('a lens look, 35mm, soft red light'), [])
        self.assertTrue(brand_problems('shot on an ARRI Alexa'))
        self.assertTrue(brand_problems('RED V-Raptor'))
        self.assertTrue(brand_problems('a Zeiss prime'))

    def test_section_helpers(self):
        body = '# t\n\n## A\none\n\n## B\ntwo\n'
        self.assertEqual(sections(body), ['A', 'B'])
        self.assertEqual(section_text(body, 'B').strip(), 'two')
        self.assertTrue(is_subsequence(['A', 'C'], ['A', 'B', 'C']))
        self.assertFalse(is_subsequence(['C', 'A'], ['A', 'B', 'C']))


if __name__ == '__main__':
    unittest.main()
