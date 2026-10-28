import unittest

from _util import TempRepo
from warscape.registry import load_all
from warscape.repo import Ctx
from warscape.search import search


class Search(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = TempRepo()
        cls.repo.wsc('reg', 'render')
        regs = load_all(Ctx.load(cls.repo.root))
        t = regs['tools']
        base = {'kind': 'script', 'usage': 'u', 'when': 'w', 'not_a_verb': 'r', 'last_used': '2026-10-28'}
        t.rows = [dict(base, id='pc.sync', path='a/sync.py', purpose='Copy the mod to the PC with sha checks', status='live'),
                  dict(base, id='pc.sync_old', path='a/old.py', purpose='Copy the mod to the PC', status='superseded:pc.sync'),
                  dict(base, id='shots', path='a/shots.py', purpose='Contact sheets of screenshots', status='live')]
        f = regs['engine_facts']
        f.rows = [{'id': 'shadow.single_map', 'claim': 'The engine draws one shadow map per frame', 'state': 'open'},
                  {'id': 'sky.random', 'claim': 'Sky is picked from battle_sky_types', 'state': 'verified', 'date': '2026-10-23', 'evidence': 'r1'}]
        cls.regs = list(regs.values())

    @classmethod
    def tearDownClass(cls):
        cls.repo.close()

    def ids(self, text, **kw):
        hits, note = search(self.regs, text, **kw)
        return [r['id'] for _, _, r in hits], note

    def test_every_word_with_prefix_last(self):
        self.assertEqual(self.ids('copy pc')[0], ['pc.sync'])
        self.assertEqual(self.ids('shad')[0], ['shadow.single_map'])
        self.assertEqual(self.ids('contact sheet')[0], ['shots'])

    def test_superseded_hidden_unless_asked_and_ranked_last(self):
        self.assertNotIn('pc.sync_old', self.ids('copy mod')[0])
        self.assertEqual(self.ids('copy mod', include_superseded=True)[0], ['pc.sync', 'pc.sync_old'])

    def test_any_word_fallback_has_a_note(self):
        ids, note = self.ids('shadow banana')
        self.assertEqual(ids, ['shadow.single_map'])
        self.assertIn('any word', note)
        self.assertEqual(self.ids('banana'), ([], ''))

    def test_restrict_to_registries(self):
        self.assertEqual(self.ids('the', only=['engine_facts'])[0][:1], ['shadow.single_map'])
        self.assertEqual(self.ids('sky', only=['tools'])[0], [])


if __name__ == '__main__':
    unittest.main()
