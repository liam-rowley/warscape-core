"""Host tests for proxy/tools/netfetch.py (W21, backlog B45b): the retry around the fetchers, `prefetch` and `ci-cache`.

No network: tarballs are file:// URLs and the RmlUi and FreeType pins point at a local git repository in a temporary game root.
"""
import contextlib
import hashlib
import http.client
import io
import json
import os
import random
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'proxy' / 'tools'))
import fetch_dxvk  # noqa: E402
import fetch_lua  # noqa: E402
import fetch_ui  # noqa: E402
import netfetch  # noqa: E402

GIT = shutil.which('git')


class Flaky:
    """Raises each error in turn, then returns 'ok'."""
    def __init__(self, *errors):
        self.errors, self.calls = list(errors), 0

    def __call__(self):
        self.calls += 1
        if self.errors:
            raise self.errors.pop(0)
        return 'ok'


def http_error(code):
    return urllib.error.HTTPError('https://x.invalid/f', code, 'msg', {}, io.BytesIO(b''))


class Retry(unittest.TestCase):
    def go(self, fn, **kw):
        slept, out = [], io.StringIO()
        with contextlib.redirect_stdout(out):
            got = netfetch.retry(fn, 'lua', sleep=slept.append, jitter=random.Random(7).uniform, **kw)
        return got, slept, out.getvalue()

    def test_transient_errors_are_retried_with_the_delay_schedule_and_one_line_each(self):
        fn = Flaky(urllib.error.URLError('timed out'), ConnectionResetError(104, 'reset'), TimeoutError('connect'))
        got, slept, out = self.go(fn)
        self.assertEqual((got, fn.calls), ('ok', 4))
        rng = random.Random(7)
        self.assertEqual(slept, [d * rng.uniform(0.8, 1.2) for d in (5, 15, 45)])
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertRegex(lines[0], r'^netfetch: lua: .*timed out.*; retry 2 of 4 in \d+ s$')
        self.assertIn('retry 4 of 4', lines[2])

    def test_every_transient_class(self):
        import ssl
        for e in (OSError('x'), urllib.error.URLError('x'), TimeoutError(), ConnectionError(), ssl.SSLError('x'),
                  http.client.RemoteDisconnected('x'), http.client.IncompleteRead(b''),
                  subprocess.CalledProcessError(128, ['git', 'fetch'], stderr='fatal: unable to access'),
                  http_error(408), http_error(429), http_error(500), http_error(503)):
            self.assertTrue(netfetch.transient(e), repr(e))
            self.assertEqual(self.go(Flaky(e))[0], 'ok', repr(e))

    def test_never_retried_other_http_errors_and_system_exit(self):
        for e in (http_error(404), http_error(403), http_error(400), ValueError('x'), KeyError('x')):
            self.assertFalse(netfetch.transient(e), repr(e))
            fn = Flaky(e)
            with self.assertRaises(type(e)):
                self.go(fn)
            self.assertEqual(fn.calls, 1)
        fn = Flaky(SystemExit('fetch_lua: x has sha256 y, pinned z: refusing'))   # a wrong byte is never a flake
        with self.assertRaises(SystemExit):
            self.go(fn)
        self.assertEqual(fn.calls, 1)

    def test_the_last_try_raises_the_error(self):
        fn = Flaky(*[TimeoutError('connect')] * 4)
        with self.assertRaises(TimeoutError):
            self.go(fn)
        self.assertEqual(fn.calls, 4)
        fn = Flaky(*[TimeoutError('connect')] * 2)
        with self.assertRaises(TimeoutError):
            self.go(fn, tries=2)
        self.assertEqual(fn.calls, 2)


# ------------------------------------------------------------------ a temporary game root with local sources
LUACONF = ('/* luaconf */\n#define LUA_NUMBER_DOUBLE\n#define LUA_NUMBER\tdouble\n#define LUA_NUMBER_SCAN\t\t"%lf"\n'
           '#define LUA_NUMBER_FMT\t\t"%.14g"\n#define lua_str2number(s,p)\tstrtod((s), (p))\n')


def lua_tarball():
    files = {'luaconf.h': LUACONF, 'ltable.c': '#define dummynode\t\t(&dummynode_)\n', 'lgc.h': 'if (G(L)->totalbytes >= G(L)->GCthreshold)\n'}
    for n in fetch_lua.CORE:
        files.setdefault(n, f'/* {n} */\n')
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:gz') as t:
        for n, text in sorted(files.items()):
            data = text.encode()
            info = tarfile.TarInfo(f'lua-5.1.1/src/{n}')
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@t', 'GIT_COMMITTER_NAME': 't', 'GIT_COMMITTER_EMAIL': 't@t'})
    return subprocess.run(['git', '-c', 'core.autocrlf=false', '-c', 'commit.gpgsign=false', '-c', 'core.hooksPath=/dev/null', *args],
                          cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def sha(b):
    return hashlib.sha256(b).hexdigest()


@unittest.skipUnless(GIT, 'git is not installed: prefetch fetches RmlUi and FreeType with git')
class Prefetch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        t = Path(self._tmp.name)
        self.game = t / 'game'
        src = t / 'srv'
        src.mkdir()
        (src / 'lua-5.1.1.tar.gz').write_bytes(lua_tarball())
        (src / 'stb_image.h').write_bytes(b'/* stb_image */\n')
        (src / 'stb_image_write.h').write_bytes(b'/* stb_image_write */\n')
        repo = t / 'upstream'
        repo.mkdir()
        git(repo, 'init', '-q')
        (repo / 'README').write_bytes(b'upstream\n')
        (repo / 'Include').mkdir()
        (repo / 'Include' / 'a.h').write_bytes(b'int a;\n')
        git(repo, 'add', '-A')
        git(repo, 'commit', '-q', '-m', 'one')
        commit = git(repo, 'rev-parse', 'HEAD')
        lua = src / 'lua-5.1.1.tar.gz'
        pins = {'rmlui': {'version': '6.3', 'repo': repo.as_uri(), 'commit': commit},
                'freetype': {'version': '2.13.3', 'repo': repo.as_uri(), 'commit': commit},
                'lua': {'version': '5.1.1', 'url': lua.as_uri(), 'sha256': sha(lua.read_bytes())}}
        for k in ('stb_image', 'stb_image_write'):
            f = src / f'{k}.h'
            pins[k] = {'version': '1', 'url': f.as_uri(), 'sha256': sha(f.read_bytes())}
        (self.game / 'viewer').mkdir(parents=True)
        (self.game / 'viewer' / 'pins.json').write_text(json.dumps(pins, indent=1), encoding='utf-8')
        self.lua_pin = {'version': '5.1.1', 'url': lua.as_uri(), 'sha256': pins['lua']['sha256']}
        self.patches = [mock.patch.dict(os.environ, {'WSP_GAME_ROOT': str(self.game)}),
                        mock.patch.object(fetch_lua, 'ROOT', self.game), mock.patch.dict(fetch_lua.PIN, self.lua_pin)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()   # TemporaryDirectory clears read-only git objects itself

    def prefetch(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            netfetch.prefetch(sleep=lambda s: None)
        return out.getvalue()

    def offline(self):
        """fetch_lua.fetch and fetch_ui.main as build.sh runs them, with every network route raising."""
        real = fetch_ui.git

        def no_fetch(*args, cwd):
            if 'fetch' in args or 'clone' in args:
                raise AssertionError(f'network call: git {args}')
            return real(*args, cwd=cwd)

        def no_url(*a, **k):
            raise AssertionError(f'network call: urlopen {a}')

        out = io.StringIO()
        with mock.patch.object(urllib.request, 'urlopen', no_url), mock.patch.object(fetch_ui, 'git', no_fetch), contextlib.redirect_stdout(out):
            fetch_lua.fetch(self.game / 'build' / 'lua')
            self.assertEqual(fetch_ui.main(['--out', str(self.game / 'build' / 'ui' / 'src')]), 0)
        return out.getvalue()

    def test_after_prefetch_the_fetchers_make_no_network_call(self):
        self.prefetch()
        self.assertTrue((self.game / 'build' / 'downloads' / 'lua-5.1.1.tar.gz').is_file())
        self.assertTrue((self.game / 'build' / 'lua' / 'src' / 'lapi.c').is_file())
        self.assertTrue((self.game / 'build' / 'ui' / 'src' / 'rmlui' / 'Include' / 'a.h').is_file())
        out = self.offline()
        self.assertIn('already patched', out)
        self.assertIn('rmlui 6.3 at', out)

    def test_a_restored_cache_without_the_patched_trees_needs_no_network(self):
        """What CI's fetch cache holds: the raw downloads and the git checkouts, never build/lua or build/ui/src/lua."""
        self.prefetch()
        shutil.rmtree(self.game / 'build' / 'lua')
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'lua')
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'stb')
        out = self.offline()
        self.assertIn('extracted and patched', out)
        self.assertIn('fetched and patched to float numbers', out)

    def test_a_half_restored_or_half_fetched_checkout_is_removed_and_fetched_again(self):
        self.prefetch()
        rml = self.game / 'build' / 'ui' / 'src' / 'rmlui'
        (rml / 'Include' / 'a.h').unlink()   # a restore that stopped part way: HEAD is right, a file is missing
        out = self.prefetch()
        self.assertIn('rmlui: removed', out)
        self.assertTrue((rml / 'Include' / 'a.h').is_file())
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'freetype', onexc=netfetch._force_remove)
        ft = self.game / 'build' / 'ui' / 'src' / 'freetype'
        ft.mkdir()
        git(ft, 'init', '-q')   # a fetch that failed after `git init`: HEAD is unborn, and fetch_ui's own check would fail on every try
        out = self.prefetch()
        self.assertIn('freetype: removed', out)
        self.assertTrue((ft / 'README').is_file())

    def test_a_sha_mismatch_is_never_retried(self):
        with mock.patch.dict(fetch_lua.PIN, {'sha256': '0' * 64}):
            slept = []
            with self.assertRaises(SystemExit), contextlib.redirect_stdout(io.StringIO()):
                netfetch.prefetch(sleep=slept.append)
        self.assertEqual(slept, [])

    def test_ci_cache_prints_a_pin_key_and_the_raw_download_paths(self):
        text = netfetch.ci_cache(cwd=self.game.parent)
        lines = text.splitlines()
        self.assertRegex(lines[0], r'^key=[0-9a-f]{64}$')
        self.assertEqual(lines[1], 'paths<<NETFETCH_EOF')
        self.assertEqual(lines[-1], 'NETFETCH_EOF')
        self.assertEqual(lines[2:-1], ['game/build/downloads', 'game/build/ui/src/downloads', 'game/build/ui/src/rmlui', 'game/build/ui/src/freetype'])
        for patched in ('build/lua', 'build/ui/src/lua'):
            self.assertFalse(any(l.endswith(patched) for l in lines), patched)
        key = lines[0]
        self.assertEqual(netfetch.ci_cache(cwd=self.game.parent).splitlines()[0], key)   # stable
        pins = self.game / 'viewer' / 'pins.json'
        pins.write_bytes(pins.read_bytes() + b'\n')
        self.assertNotEqual(netfetch.ci_cache(cwd=self.game.parent).splitlines()[0], key)   # a UI pin edit
        pins.write_bytes(pins.read_bytes()[:-1])
        for mod in (fetch_lua, fetch_dxvk):
            with mock.patch.dict(mod.PIN, {'version': 'other'}):
                self.assertNotEqual(netfetch.ci_cache(cwd=self.game.parent).splitlines()[0], key, mod.__name__)
        self.assertEqual(netfetch.ci_cache(cwd=self.game).splitlines()[2], 'build/downloads')


class Dxvk(unittest.TestCase):
    def test_fetch_dxvk_retries_its_downloads_and_keeps_its_sha_check(self):
        calls = []

        def get(url, want):
            calls.append(url)
            if len(calls) == 1:
                raise urllib.error.URLError('timed out')
            raise SystemExit('fetch_dxvk: sha mismatch')

        with tempfile.TemporaryDirectory() as t, mock.patch.object(fetch_dxvk, 'get', get), \
                mock.patch.object(netfetch.time, 'sleep', lambda s: None), contextlib.redirect_stdout(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                fetch_dxvk.fetch(t)
        self.assertEqual(calls, [fetch_dxvk.PIN['tarball_url']] * 2)
        self.assertIn('netfetch: dxvk', out.getvalue())


if __name__ == '__main__':
    unittest.main()
