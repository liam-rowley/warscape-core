"""discovery/core/engine_api.py: probe-line parsing, the last-block rule for a state probed twice, kinds and J6 answers (synthetic logs)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'discovery' / 'core'))
import engine_api  # noqa: E402

T = '2026-11-01T16:24:13.170Z [INFO ] [t1] lua: '


class Parse(unittest.TestCase):
    def write(self, d, name, lines):
        p = Path(d) / name
        p.write_text(''.join(T + l + '\n' for l in lines), encoding='utf-8')
        return str(p)

    def test_last_block_wins_and_kinds(self):
        with tempfile.TemporaryDirectory() as d:
            log = self.write(d, 'a_proxy.log', [
                'api land@frontend G FrontEnd:table',                     # a stale request run in the front end
                'api land@frontend G.FrontEnd StartCampaign:function',
                'api land@frontend __end total=2',
                'api land@battle G BattleUI:table CampaignUI:nil',
                'api land@battle G.BattleUI CameraZoomTo:function OnUpdate:function',
                'api land@battle R.UIComponent TriggerAnimation:function',
                'api land@battle __end total=5',
            ])
            seen, totals, dropped = engine_api.parse_logs([log])
            self.assertEqual(totals, {'land': 5})
            self.assertEqual(dropped, [{'state': 'land@frontend', 'log': 'a_proxy.log', 'probe_total': 2}])
            self.assertNotIn('G.FrontEnd', seen['land'])
            names = engine_api.merge(seen)
            self.assertEqual(names['G.BattleUI:CameraZoomTo']['kind'], 'function')
            self.assertEqual(names['G.BattleUI:OnUpdate']['kind'], 'event')
            self.assertEqual(names['R.UIComponent:TriggerAnimation']['kind'], 'method')
            self.assertEqual(names['G:BattleUI']['states'], ['land'])

    def test_logs_without_probe_lines_are_not_listed(self):
        # a proof launch's proxy log added to the run later must not change the table (J9 review round 1: the committed table went stale)
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / 'raw'
            raw.mkdir()
            self.write(raw, 'a_proxy.log', ['api land G BattleUI:table', 'api land __end total=1'])
            self.write(raw, 'b_proxy.log', ['loaded probe file other.lua'])
            doc = engine_api.build([d])
            self.assertEqual([Path(p).name for p in doc['logs']], ['a_proxy.log'])

    def test_state_note(self):
        # a state whose launch did not reach what its label says carries a note (J9 review round 2: campaign_show_prestige)
        with tempfile.TemporaryDirectory() as d:
            raw = Path(d) / 'raw'
            raw.mkdir()
            self.write(raw, 'a_proxy.log', ['api campaign_show_prestige G CampaignUI:table', 'api campaign_show_prestige __end total=1',
                                            'api land G BattleUI:table', 'api land __end total=1'])
            doc = engine_api.build([d])
            self.assertIn('not the prestige panel', doc['states']['campaign_show_prestige']['note'])
            self.assertNotIn('note', doc['states']['land'])

    def test_j6_answers(self):
        with tempfile.TemporaryDirectory() as d:
            diff = Path(d) / 'lua_api.json'
            diff.write_text(json.dumps({'detail': {'names': {
                'BattleUI.*': {'BattleUI.CameraZoomTo': 'new', 'BattleUI.Gone': 'gone', 'BattleUI.Same': 'same'},
                'component methods': {'Component.TriggerAnimation': 'new', 'Component.Missing': 'new'}}}}), encoding='utf-8')
            names = {'G.BattleUI:CameraZoomTo': {'owner': 'G.BattleUI', 'name': 'CameraZoomTo', 'states': ['land']},
                     'R.UIComponent:TriggerAnimation': {'owner': 'R.UIComponent', 'name': 'TriggerAnimation', 'states': ['land']}}
            a = engine_api.j6_answers(names, str(diff))
            self.assertEqual(a['BattleUI.*']['new']['at_runtime'], ['BattleUI.CameraZoomTo'])
            self.assertEqual(a['BattleUI.*']['gone']['not_at_runtime'], ['BattleUI.Gone'])
            self.assertEqual(a['component methods']['found'], ['TriggerAnimation'])
            self.assertEqual(a['component methods']['not_found'], ['Missing'])


class Samples(unittest.TestCase):
    def test_samples_and_impl(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / 'g_proxy.log'
            p.write_text(''.join(T + l + '\n' for l in [
                'api campaign@campaign G.CampaignUI CurrentTurn:function PlayerFactionId:function',
                'api campaign@campaign S OnShortcut:function',
                'api campaign@campaign __end total=3',
                'sample campaign G.CampaignUI CurrentTurn number 1',
                'sample campaign G.CampaignUI PlayerFactionId error attempt to call a nil value',
            ]), encoding='utf-8')
            seen, _, _ = engine_api.parse_logs([str(p)])
            names = engine_api.merge(seen)
            names['G.CampaignUI:CurrentTurn']['va'] = '0x9e0000'
            engine_api.add_impl_and_samples(names, engine_api.parse_samples([str(p)]))
            self.assertEqual(names['G.CampaignUI:CurrentTurn']['impl'], 'C')
            self.assertEqual(names['G.CampaignUI:CurrentTurn']['samples'], {'campaign': {'type': 'number', 'value': '1'}})
            self.assertEqual(names['G.CampaignUI:PlayerFactionId']['samples']['campaign'], {'error': 'attempt to call a nil value'})
            self.assertEqual(names['S:OnShortcut']['impl'], 'Lua')
            self.assertNotIn('impl', names['G.CampaignUI:PlayerFactionId'])


class ProbeSafe(unittest.TestCase):
    def test_rule(self):
        with tempfile.TemporaryDirectory() as d:
            cf = Path(d) / 'cf.json'
            e = lambda n, a=0, m=0, doc='Out: a value': {'name': n, 'va': '0x1', 'static_args': a, 'static_args_min': m, 'doc': doc}
            cf.write_text(json.dumps({'tables': {'CampaignUI': {'entries': [
                e('CurrentTurn'), e('CampaignKey'), e('EndTurn'), e('CurrentSelection', 1, 1), e('Current_Selection_Halt'),
                e('GetHealthStatus', doc='Update the killometer bar'), e('MPCanCancel'), e('Valid')]}}}), encoding='utf-8')
            names = [r['name'] for r in engine_api.probe_safe(str(cf))['getters']]
            self.assertEqual(names, ['CampaignKey', 'CurrentTurn'])

    def test_committed_list_current(self):
        self.assertEqual(engine_api.main(['probe-safe', '--check']), 0, 'discovery/napoleon/probe_safe.json is stale: rerun probe-safe')


class Committed(unittest.TestCase):
    def test_table_current(self):
        out = Path(engine_api.OUT)
        if not out.exists():
            self.skipTest('no committed engine_api.json')
        doc = json.loads(out.read_text(encoding='utf-8'))
        runs = [Path(engine_api.REPO) / r for r in doc['runs']]
        missing = [str(r) for r in runs if not (r / 'raw').is_dir()]
        if missing:
            self.skipTest(f'{missing} not present')
        args = ['build'] + [x for r in runs for x in ('--run', str(r))] + ['--check']
        self.assertEqual(engine_api.main(args), 0, 'discovery/napoleon/engine_api.json is stale: rebuild it')


if __name__ == '__main__':
    unittest.main()
