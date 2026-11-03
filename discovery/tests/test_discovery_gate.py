"""Host tests for the discovery gate (J11): discovery/core/gate.py and `wsc discovery gate`, and the brief found-path rule (discovery/core/briefpaths.py, row 80).

Every rule has a bad fixture that fails and the matching good one that passes. Fixtures are small synthetic indexes and rows; the one
test that reads the real 88,415-row index runs the gate and the brief rule on this repo (that is what puts them in the `tests` gate).
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'discovery' / 'core'))
sys.path.insert(0, str(ROOT / 'tools' / 'verbs'))

import assets  # noqa: E402
import briefpaths as bp  # noqa: E402
import discovery  # noqa: E402
import gate  # noqa: E402
import tsvgz  # noqa: E402

sys.path.insert(0, str(ROOT / 'core'))
from warscape import jobq  # noqa: E402  (the brief shape rules are warscape-core's since J62; the found-path hook is tools/jobs_hooks.py)

LEGACY_BRIEFS = frozenset(json.loads((ROOT / 'jobs' / 'legacy.json').read_text(encoding='utf-8'))['brief_hooks'])   # exempt from the brief hooks only

BS = chr(92)
EXE = 'ab' * 20


def cfg(**kw):
    c = {'index': {'built': '2026-01-01', 'rows': 2, 'sha256': 'x'}, 'floors': {n: 2 for n in gate.REGISTRIES},
         'ui_context_floors': {'battle': 1, 'engine': 1}, 'config_key_owners': ['proxy'],
         'ratchet': {'a.b': 5}}
    c.update(kw)
    return c


def ui(i, **kw):
    r = {'id': i, 'description': 'd', 'status': 'atlas', 'vanilla_source': {'layout': 'battle ui' + BS + 'a'}, 'interactions': [{'name': 'none: display only'}]}
    r.update(kw)
    return r


def good_rows():
    rows = {n: [{'id': f'{n}.{i}'} for i in range(2)] for n in gate.REGISTRIES}
    rows['ui_elements'] = [ui('battle.a'), ui('engine.r', description='route: render_target. x', vanilla_source={}, interactions=[])]
    rows['engine_sites'] = [{'id': f's{i}', 'exe': 'sha1:' + EXE, 'verified': {'date': '2026-10-30', 'run': 'r'}} for i in range(2)]
    rows['jobs'] = [{'id': 'J1'}, {'id': 'J2'}]
    rows['config_keys'] = [{'id': 'a.b', 'owner': 'J1'}, {'id': 'a.c', 'owner': 'proxy'}]
    rows['scenarios'] = [{'id': f'sc{i}', 'launch': 'ctl autostart'} for i in range(2)]
    rows['engine_facts'] = [{'id': 'f1', 'state': 'open', 'claim': 'x', 'notes': 'Owner: J2'}, {'id': 'f2', 'state': 'verified', 'claim': 'y'}]
    return rows


class Floors(unittest.TestCase):
    def test_good_rows_pass(self):
        self.assertEqual(gate.floor_problems(good_rows(), cfg()), [])

    def test_a_registry_below_its_floor_fails(self):
        r = good_rows()
        r['hotkeys'] = r['hotkeys'][:1]
        self.assertEqual(gate.floor_problems(r, cfg()), ['hotkeys: 1 rows, below its floor 2'])

    def test_an_empty_ui_context_fails(self):
        r = good_rows()
        r['ui_elements'] = [ui('engine.r', description='route: x')]   # no battle row
        self.assertTrue(any('context "battle" has 0 rows' in x for x in gate.floor_problems(r, cfg())))

    def test_a_context_without_a_floor_fails(self):
        r = good_rows()
        r['ui_elements'].append(ui('frontend.x'))
        self.assertTrue(any('context "frontend" has no floor' in x for x in gate.floor_problems(r, cfg())))

    def test_a_registry_without_a_floor_fails(self):
        c = cfg()
        del c['floors']['scenarios']
        self.assertTrue(any('scenarios: no floor' in x for x in gate.floor_problems(good_rows(), c)))


class Shapes(unittest.TestCase):
    def check(self, r, c=None):
        return gate.shape_problems(r, c or cfg(), EXE)

    def test_good_rows_pass(self):
        self.assertEqual(self.check(good_rows()), [])

    def test_ui_row_before_atlas_fails(self):
        r = good_rows()
        r['ui_elements'][0]['status'] = 'sketch'
        self.assertTrue(any('not atlas or later' in x for x in self.check(r)))

    def test_ui_row_without_source_or_interactions_fails(self):
        r = good_rows()
        r['ui_elements'][0]['vanilla_source'] = {}
        r['ui_elements'][0]['interactions'] = []
        got = ' '.join(self.check(r))
        self.assertIn('no layout or script', got)
        self.assertIn('no interactions entry', got)

    def test_engine_row_needs_route(self):
        r = good_rows()
        r['ui_elements'][1]['description'] = 'Battle radar'
        self.assertTrue(any('"route:" (D39)' in x for x in self.check(r)))

    def test_engine_site_for_another_exe_fails(self):
        r = good_rows()
        r['engine_sites'][0]['exe'] = 'sha1:' + 'cd' * 20
        self.assertTrue(any('stale by definition' in x for x in self.check(r)))

    def test_engine_site_without_verified_fails(self):
        r = good_rows()
        r['engine_sites'][1]['verified'] = {'date': '2026-10-30'}
        self.assertTrue(any('no verified date and run' in x for x in self.check(r)))

    def test_config_key_owner_must_resolve(self):
        r = good_rows()
        r['config_keys'][0]['owner'] = 'J99'
        self.assertTrue(any("owner 'J99'" in x for x in self.check(r)))
        r['config_keys'][0]['owner'] = 'liam'
        self.assertEqual(self.check(r), [])
        r['config_keys'][1]['owner'] = 'proxy'
        self.assertTrue(any("owner 'proxy'" in x for x in self.check(r, cfg(config_key_owners=[]))))

    def test_scenario_without_launch_fails(self):
        r = good_rows()
        r['scenarios'][0]['launch'] = ''
        self.assertTrue(any('no launch recipe' in x for x in self.check(r)))

    def test_open_fact_without_owner_fails_and_with_owner_passes(self):
        r = good_rows()
        r['engine_facts'][0]['notes'] = 'next: try it'
        self.assertTrue(any('f1: open' in x for x in self.check(r)))
        r['engine_facts'][0]['notes'] = 'Owner: liam (no job yet)'
        self.assertEqual(self.check(r), [])
        r['engine_facts'][0]['notes'] = 'Owner: J77'   # a job id that is not a row
        self.assertTrue(self.check(r))


def write_index(path, rows):
    tsvgz.write(str(path), assets.COLUMNS, rows)


def irow(pack, path, size, sha='a' * 64):
    return (pack, path, size, sha, 'tga', 'ui', '1', '4', '4', '', 'bgr8')


class Currency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for d in ('discovery/assets', 'discovery/napoleon', 'registries'):
            (self.root / d).mkdir(parents=True)
        self.rows = [irow('data.pack', 'ui' + BS + 'a.tga', 10), irow('data.pack', 'ui' + BS + 'b.tga', 20), irow('loose', 'ui' + BS + 'c.tga', 5)]
        self.index = self.root / 'discovery' / 'assets' / 'index.tsv.gz'
        write_index(self.index, self.rows)
        self.roles = {'note': '', 'rules': [{'role': 'art', 'paths': ['*']}]}
        (self.root / 'discovery' / 'napoleon' / 'asset_roles.json').write_text(json.dumps(self.roles))
        (self.root / 'discovery' / 'assets' / 'refs.json').write_text(json.dumps({'refs': {}}))
        self.write_registry()

    def tearDown(self):
        self.tmp.cleanup()

    def write_registry(self):
        idx = assets.load_index(str(self.index))
        rules = assets.load_roles(str(self.root / 'discovery' / 'napoleon' / 'asset_roles.json'))
        assets.write_registry(assets.registry_rows(idx, {}, rules, []), str(self.root / 'registries' / 'assets.jsonl'))

    def summary(self):
        return {'index_rows': 3, 'pack_fingerprint': assets.pack_fingerprints(assets.load_index(str(self.index)))}

    def test_assets_registry_in_step_passes_and_a_changed_index_fails(self):
        self.assertEqual(discovery.j7_problems(self.root), [])
        write_index(self.index, self.rows + [irow('data.pack', 'ui' + BS + 'd.tga', 7)])
        got = discovery.j7_problems(self.root)
        self.assertTrue(any('not in step with index.tsv.gz' in x for x in got), got)

    def test_index_pin_good_and_a_replaced_index_fails(self):
        c = cfg(index={'built': '2026-01-01', 'rows': 3, 'sha256': gate.index_sha256(self.index)})
        self.assertEqual(gate.index_problems(str(self.index), self.summary(), c), [])
        write_index(self.index, self.rows + [irow('data.pack', 'ui' + BS + 'd.tga', 7)])   # a newer index, results not rebuilt
        got = gate.index_problems(str(self.index), self.summary(), c)
        self.assertTrue(got and 'older index' in got[0], got)

    def test_fingerprint_must_be_the_indexs_own(self):
        c = cfg(index={'built': '2026-01-01', 'rows': 3, 'sha256': gate.index_sha256(self.index)})
        s = self.summary()
        s['pack_fingerprint']['data.pack']['bytes'] += 1
        self.assertTrue(any('pack_fingerprint is not what' in x for x in gate.index_problems(str(self.index), s, c)))
        del s['pack_fingerprint']
        self.assertTrue(any('no pack_fingerprint' in x for x in gate.index_problems(str(self.index), s, c)))

    def test_fingerprints_leave_loose_files_out(self):
        self.assertEqual(assets.pack_fingerprints(assets.load_index(str(self.index))), {'data.pack': {'entries': 2, 'bytes': 30}})

    def test_stale_readme_fails_on_a_copy_of_the_committed_results(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copytree(ROOT / 'discovery', Path(d) / 'discovery')
            self.assertEqual(discovery.readme_problems(d), [])
            with open(Path(d) / 'discovery' / 'assets' / 'README.md', 'a', encoding='utf-8') as f:
                f.write('hand edit\n')
            self.assertTrue(any('stale' in x for x in discovery.readme_problems(d)))


class Install(unittest.TestCase):
    """--install on a synthetic install tree: fake packs whose indexes the fake reader returns (the real game folder is not read here)."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()
        (self.root / 'Napoleon.exe').write_bytes(b'exe')
        self.sha = __import__('hashlib').sha1(b'exe').hexdigest()
        for n in ('data.pack', 'boot.pack'):
            (self.root / 'data' / n).write_bytes(b'')
        self.entries = {'data.pack': [{'size': 10}, {'size': 20}], 'boot.pack': [{'size': 5}]}
        self.summary = {'pack_order': ['boot.pack', 'data.pack'],
                        'pack_fingerprint': {'boot.pack': {'entries': 1, 'bytes': 5}, 'data.pack': {'entries': 2, 'bytes': 30}}}

    def tearDown(self):
        self.tmp.cleanup()

    def run_install(self, sha=None):
        return gate.install_problems(self.summary, self.root, 'data', 'Napoleon.exe', sha or self.sha,
                                     lambda p: ({}, self.entries[Path(p).name]))

    def test_matching_install_passes(self):
        self.assertEqual(self.run_install(), [])

    def test_exe_sha_mismatch_fails(self):
        self.assertTrue(any('not the pinned identity' in x for x in self.run_install('0' * 40)))

    def test_a_changed_pack_fails(self):
        self.entries['data.pack'].append({'size': 1})
        self.assertTrue(any('data.pack has 3 entries' in x for x in self.run_install()))

    def test_a_missing_and_an_extra_pack_fail(self):
        (self.root / 'data' / 'boot.pack').unlink()
        (self.root / 'data' / 'new.pack').write_bytes(b'')
        got = ' '.join(self.run_install())
        self.assertIn('boot.pack (in pack_order) is not installed', got)
        self.assertIn('new.pack are not in the index', got)

    def test_offline_run_says_install_not_compared_and_is_never_ok(self):
        lines, _, _ = discovery.gate_run(ROOT)
        self.assertTrue(any(x.startswith('warn install not compared') for x in lines))
        self.assertFalse(any(x.startswith('ok   install') for x in lines))


class Ratchet(unittest.TestCase):
    def test_growth_fails_and_shrink_is_a_note(self):
        g = [{'key': 'a.b', 'count': 6}]
        self.assertTrue(ratchet(g)[0])
        bad, notes = ratchet([{'key': 'a.b', 'count': 4}])
        self.assertEqual((bad, len(notes)), ([], 1))
        self.assertEqual(ratchet([{'key': 'a.b', 'count': 5}]), ([], []))
        self.assertTrue(ratchet([{'key': 'new', 'count': 0}])[0])


def ratchet(found):
    return gate.ratchet_problems(found, cfg())


KNOWN = bp.make_known(
    folders={'ui', 'db', 'fx', 'profiling_scripts'},
    asset_ids={'ui/flags/a.tga'},
    ui_units={'battle.deploy': {'layout': 'battle ui' + BS + 'deploy', 'script': 'battle ui/deploy_scripts/deploy.luac, battle ui/deploy_scripts/b.luac'},
              'template.card': {'layout': 'data' + BS + 'ui' + BS + 'templates' + BS + 'uied.templates#card'}},
    repo_files={'tools/x.py', 'proxy/napoleon/a.cpp', 'ui/viewer.html'})


def check(text):
    return bp.found_path_problems(text, KNOWN)


class FoundPaths(unittest.TestCase):
    def test_shape_1_the_extract_store(self):
        self.assertTrue(any('extract store' in x for x in check('Read `/extract/napoleon/db/x.tsv` for it.')))
        self.assertTrue(any('extract store' in x for x in check('see extract/napoleon/loc/ now')))

    def test_shape_2_pack_form_path(self):
        got = check('The picture is `ui' + BS + 'flags' + BS + 'a.tga` in the pack.')
        self.assertTrue(got and 'pack-form' in got[0], got)

    def test_shape_3_path_under_a_game_folder_that_is_not_an_id(self):
        self.assertTrue(any('not a registry id' in x for x in check('Use `ui/flags/missing.tga` here.')))
        self.assertTrue(any('not a registry id' in x for x in check('Use fx/shader.fx here.')))

    def test_shape_4_layout_and_script_paths_name_the_unit_id(self):
        for text in ('Open `battle ui' + BS + 'deploy`.', 'Open `battle ui/deploy`.', 'The script battle ui/deploy_scripts/b.luac sets it.',
                     'Open `ui' + BS + 'deploy`.'):
            got = check(text)
            self.assertTrue(got and 'battle.deploy' in got[0], (text, got))
        self.assertIn('template.card', check('The template data' + BS + 'ui' + BS + 'templates' + BS + 'uied.templates#card holds it.')[0])

    def test_ids_are_accepted(self):
        self.assertEqual(check('Cite `ui/flags/a.tga` and `battle.deploy` and `template.card`.'), [])

    def test_a_layout_cited_by_unit_id_is_accepted_and_by_path_refused(self):
        self.assertEqual(check('Rebuild `battle.deploy` first.'), [])
        self.assertTrue(check('Rebuild `battle ui' + BS + 'deploy` first.'))

    def test_repo_paths_and_other_names_are_accepted(self):
        text = ('Run `python3 core/wsc.py find x`; edit `tools/x.py` and `proxy/napoleon/a.cpp`, `ui/viewer.html`, `data.pack`, '
                '`units_tables`, `rml_mod/foo/bar.lua`, `C:' + BS + 'napoleon_remastered_pc' + BS + '_scratch`, https://example.com/ui/x.')
        self.assertEqual(check(text), [])

    def test_placeholders_and_globs_are_patterns_not_citations(self):
        self.assertEqual(check('Look for `ui/<name>.luac` and `fx' + BS + '*.fx`.'), [])

    def test_quoted_line_exempts_a_fence_and_a_bullet(self):
        fence = 'Quoted, not a citation:\n```\nfx/old.fx\n/extract/napoleon/x/\n```\nAfter.\n'
        self.assertEqual(check(fence), [])
        self.assertTrue(check('Not marked:\n```\nfx/old.fx\n```\n'))
        bullet = '- Quoted, not a citation: the old brief said `fx/old.fx`\n  and `ui/more.tga`.\n- Cite `fx/other.fx`.\n'
        got = check(bullet)
        self.assertEqual(len(got), 1)
        self.assertIn('line 3', got[0])

    def test_evidence_base_paragraph_is_not_a_game_path(self):
        self.assertEqual(check('Evidence base `empire-remastered` holds `ui/legacy_note.md`.\n'), [])
        self.assertTrue(check('Other `ui/legacy_note.md`.\n'))

    def test_registry_gaps_with_owner_pass_and_without_fail(self):
        good = 'Use `fx/new.fx`.\n\n## Registry gaps\n- path: fx/new.fx; owner: J77; reason: no row yet\n'
        self.assertEqual(check(good), [])
        for bullet, why in (('- path: fx/new.fx; reason: no row', 'owner'), ('- path: fx/new.fx; owner: J77', 'reason'),
                            ('- path: fx/new.fx; owner: nobody; reason: r', 'owner')):
            got = check('Use `fx/new.fx`.\n\n## Registry gaps\n' + bullet + '\n')
            self.assertTrue(any(why in x for x in got), (bullet, got))
        self.assertEqual(bp.registry_gaps(good)[0], [{'path': 'fx/new.fx', 'owner': 'J77', 'reason': 'no row yet'}])
        self.assertTrue(check('Use `fx/other.fx`.\n\n## Registry gaps\n- path: fx/new.fx; owner: liam; reason: r\n'))

    def test_errors_name_line_token_and_what_to_cite(self):
        got = check('ok\n\nUse `ui/flags/missing.tga` here.')
        self.assertTrue(got[0].startswith('line 3: `ui/flags/missing.tga`'))
        self.assertIn('python3 core/wsc.py find', got[0])


SHAPE = '''# J77: thing

Model: Sonnet, medium. Budget about 100 tool calls.

## Kill criteria
- It breaks twice: stop.

## Finish
Then `wsc reg set jobs J77 status=review report=jobs/J77/report.md`.
'''


class BriefRule(unittest.TestCase):
    def errs(self, jid, text, known=KNOWN):
        """What `wsc jobs check` reports for a brief: the hook's found-path rule (not for a legacy id), then the core's shape rules."""
        found = [f'found path: {e}' for e in bp.found_path_problems(text, known)] if known is not None and jid not in LEGACY_BRIEFS else []
        return found + jobq.brief_problems(jid, {'model': 'sonnet'}, text)

    def test_a_clean_new_brief_passes(self):
        self.assertEqual(self.errs('J77', SHAPE + '\nCite `battle.deploy`.\n'), [])

    def test_a_legacy_brief_is_exempt_and_a_new_one_with_the_same_text_is_refused(self):
        bad = SHAPE.replace('J77', 'J10') + '\nOpen `battle ui' + BS + 'deploy`.\n'
        self.assertEqual(self.errs('J10', bad), [])
        got = self.errs('J77', bad.replace('J10', 'J77'))
        self.assertTrue(got and got[0].startswith('found path: line') and 'battle.deploy' in got[0], got)

    def test_the_rule_is_off_without_known(self):
        self.assertEqual(self.errs('J77', SHAPE + '\nOpen `battle ui' + BS + 'deploy`.\n', known=None), [])

    def test_shape_rules_still_apply_to_legacy_briefs(self):
        self.assertTrue(self.errs('J10', '# J10: x\n'))

    def test_the_legacy_set_is_every_brief_on_main_at_j11s_base(self):
        out = subprocess.run(['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', 'c674fb1', 'jobs'], capture_output=True, text=True)
        if out.returncode != 0:
            self.skipTest('J11 base commit not in this clone')
        on_main = {p.split('/')[1] for p in out.stdout.split() if p.endswith('/brief.md')}
        self.assertEqual(on_main | {'J24', 'J37'}, set(LEGACY_BRIEFS))   # J24 and J37 merged before J11 did


class ThisRepo(unittest.TestCase):
    def test_the_gate_passes_on_the_real_registries_and_is_deterministic(self):
        lines, fails, doc = discovery.gate_run(ROOT)
        self.assertEqual(fails, [], '\n'.join(lines))
        self.assertEqual(gate.summary_text(doc), gate.summary_text(discovery.gate_run(ROOT)[2]))
        self.assertEqual((ROOT / 'discovery' / 'gate' / 'summary.json').read_text(encoding='utf-8'), gate.summary_text(doc))

    def test_every_committed_brief_passes_the_found_path_rule_or_is_legacy(self):
        known = bp.load_known(ROOT)
        bad = []
        for p in sorted((ROOT / 'jobs').glob('*/brief.md')):
            if p.parent.name not in LEGACY_BRIEFS:
                bad += [f'{p.parent.name}: {e}' for e in bp.found_path_problems(p.read_text(encoding='utf-8'), known)]
        self.assertEqual(bad, [])

    def test_the_four_cases_the_rule_exists_for_fail_on_the_real_registries(self):
        known = bp.load_known(ROOT)
        unit = next(u for u in known.ui_ids if u.startswith('battle.'))
        path = next(k for k, v in known.ui_paths.items() if unit in v and ' ' in k)
        self.assertTrue(bp.found_path_problems(f'Open `{path}`.', known))
        self.assertEqual(bp.found_path_problems(f'Open `{unit}`.', known), [])


if __name__ == '__main__':
    unittest.main()
