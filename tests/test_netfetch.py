"""Host tests for proxy/tools/netfetch.py (W21, backlog B45b) and the retry inside the fetchers (W24, B62): `retry`, `ci-cache`, and
fetch_lua.py and fetch_ui.py retrying their own downloads and git fetches, removing a checkout they cannot trust, and never retrying a
wrong byte or a failed patch.

No network: tarballs are file:// URLs and the RmlUi and FreeType pins point at a local git repository in a temporary game root.
"""
import contextlib
import hashlib
import http.client
import importlib
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
# the proxy tools are imported by name from proxy/tools (not packages; the stdlib-only check reads only `import` statements)
fetch_dxvk, fetch_lua, fetch_ui, netfetch = (importlib.import_module(n) for n in ('fetch_dxvk', 'fetch_lua', 'fetch_ui', 'netfetch'))

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
        slept, out, err = [], io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            got = netfetch.retry(fn, 'lua', sleep=slept.append, jitter=random.Random(7).uniform, **kw)
        self.assertEqual(out.getvalue(), '')   # W24: build.sh discards the fetchers' stdout, so the retry lines go to stderr
        return got, slept, err.getvalue()

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

    def test_prefetch_and_clean_checkouts_are_gone(self):
        # W24 (B62): the fetchers retry themselves, so the CI-only wrapper went with the render block's third step
        self.assertFalse(hasattr(netfetch, 'prefetch'))
        self.assertFalse(hasattr(netfetch, 'clean_checkouts'))
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(netfetch.main(['prefetch']), 64)


# ------------------------------------------------------------------ a temporary game root with local sources
LUACONF = ('/* luaconf */\n#define LUA_NUMBER_DOUBLE\n#define LUA_NUMBER\tdouble\n#define LUA_NUMBER_SCAN\t\t"%lf"\n'
           '#define LUA_NUMBER_FMT\t\t"%.14g"\n#define lua_str2number(s,p)\tstrtod((s), (p))\n')


def lua_tarball(luaconf=LUACONF):
    files = {'luaconf.h': luaconf, 'ltable.c': '#define dummynode\t\t(&dummynode_)\n', 'lgc.h': 'if (G(L)->totalbytes >= G(L)->GCthreshold)\n'}
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


class FlakyUrlopen:
    """urlopen that raises a network error on its first `fail` calls, then opens the URL for real (file://)."""
    def __init__(self, fail=1):
        self.real, self.fail, self.urls = urllib.request.urlopen, fail, []

    def __call__(self, url, *a, **k):
        self.urls.append(url)
        if len(self.urls) <= self.fail:
            raise urllib.error.URLError('timed out')
        return self.real(url, *a, **k)


@unittest.skipUnless(GIT, 'git is not installed: fetch_ui.py fetches RmlUi and FreeType with git')
class Fetchers(unittest.TestCase):
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
        self.pins = pins
        (self.game / 'viewer').mkdir(parents=True)
        (self.game / 'viewer' / 'pins.json').write_text(json.dumps(pins, indent=1), encoding='utf-8')
        self.lua_pin = {'version': '5.1.1', 'url': lua.as_uri(), 'sha256': pins['lua']['sha256']}
        self.slept = []
        self.patches = [mock.patch.dict(os.environ, {'WSP_GAME_ROOT': str(self.game)}),
                        mock.patch.object(fetch_lua, 'ROOT', self.game), mock.patch.dict(fetch_lua.PIN, self.lua_pin),
                        mock.patch.object(netfetch.time, 'sleep', self.slept.append)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self._tmp.cleanup()   # TemporaryDirectory clears read-only git objects itself

    def fetch(self, urlopen=None, gitfn=None):
        """fetch_lua.fetch and fetch_ui.main as build.sh runs them: (stdout, stderr)."""
        out, err = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as st:
            if urlopen:
                st.enter_context(mock.patch.object(urllib.request, 'urlopen', urlopen))
            if gitfn:
                st.enter_context(mock.patch.object(fetch_ui, 'git', gitfn))
            st.enter_context(contextlib.redirect_stdout(out))
            st.enter_context(contextlib.redirect_stderr(err))
            fetch_lua.fetch(self.game / 'build' / 'lua')
            self.assertEqual(fetch_ui.main(['--out', str(self.game / 'build' / 'ui' / 'src')]), 0)
        return out.getvalue(), err.getvalue()

    def offline(self):
        """The fetchers with every network route raising."""
        real = fetch_ui.git

        def no_fetch(*args, cwd):
            if 'fetch' in args or 'clone' in args:
                raise AssertionError(f'network call: git {args}')
            return real(*args, cwd=cwd)

        def no_url(*a, **k):
            raise AssertionError(f'network call: urlopen {a}')
        return self.fetch(no_url, no_fetch)[0]

    def test_failing_fixture_a_flaky_download_is_retried_inside_fetch_lua_and_fetch_ui(self):
        flaky = FlakyUrlopen(1)
        with mock.patch.object(urllib.request, 'urlopen', flaky), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()) as err:
            fetch_lua.fetch(self.game / 'build' / 'lua')
        self.assertEqual(len(flaky.urls), 2)
        self.assertRegex(err.getvalue(), r'netfetch: fetch_lua .*timed out.*; retry 2 of 4')
        self.assertEqual(len(self.slept), 1)
        flaky = FlakyUrlopen(1)
        out, err = self.fetch(urlopen=flaky)
        self.assertRegex(err, r'netfetch: fetch_ui .*lua-5\.1\.1\.tar\.gz.*timed out.*; retry 2 of 4')
        self.assertNotIn('netfetch:', out)   # build.sh discards stdout: a retry line there would never be seen
        self.assertTrue((self.game / 'build' / 'ui' / 'src' / 'stb' / 'stb_image_write.h').is_file())

    def test_failing_fixture_a_flaky_git_fetch_is_retried_inside_fetch_ui(self):
        real, fails = fetch_ui.git, []

        def flaky_git(*args, cwd):
            if 'fetch' in args and not fails:
                fails.append(args)
                raise subprocess.CalledProcessError(128, ['git', *args], stderr='fatal: unable to access: Connection reset')
            return real(*args, cwd=cwd)
        out, err = self.fetch(gitfn=flaky_git)
        self.assertEqual(len(fails), 1)
        self.assertRegex(err, r'netfetch: fetch_ui rmlui: CalledProcessError.*Connection reset.*; retry 2 of 4')
        self.assertTrue((self.game / 'build' / 'ui' / 'src' / 'rmlui' / 'Include' / 'a.h').is_file())
        self.assertTrue((self.game / 'build' / 'ui' / 'src' / 'freetype' / 'README').is_file())

    def test_after_one_fetch_the_fetchers_make_no_network_call(self):
        self.fetch()
        self.assertTrue((self.game / 'build' / 'downloads' / 'lua-5.1.1.tar.gz').is_file())
        self.assertTrue((self.game / 'build' / 'lua' / 'src' / 'lapi.c').is_file())
        self.assertTrue((self.game / 'build' / 'ui' / 'src' / 'rmlui' / 'Include' / 'a.h').is_file())
        out = self.offline()
        self.assertIn('already patched', out)
        self.assertIn('rmlui 6.3 at', out)

    def test_a_restored_cache_without_the_patched_trees_needs_no_network(self):
        """What CI's fetch cache holds: the raw downloads and the git checkouts, never build/lua or build/ui/src/lua."""
        self.fetch()
        shutil.rmtree(self.game / 'build' / 'lua')
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'lua')
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'stb')
        out = self.offline()
        self.assertIn('extracted and patched', out)
        self.assertIn('fetched and patched to float numbers', out)

    def test_failing_fixture_fetch_ui_removes_a_half_restored_or_half_fetched_checkout_itself(self):
        self.fetch()
        rml = self.game / 'build' / 'ui' / 'src' / 'rmlui'
        (rml / 'Include' / 'a.h').unlink()   # a restore that stopped part way: HEAD is right, a file is missing
        out, err = self.fetch()
        self.assertIn('fetch_ui: rmlui: removed', err)
        self.assertTrue((rml / 'Include' / 'a.h').is_file())
        shutil.rmtree(self.game / 'build' / 'ui' / 'src' / 'freetype', onexc=netfetch._force_remove)
        ft = self.game / 'build' / 'ui' / 'src' / 'freetype'
        ft.mkdir()
        git(ft, 'init', '-q')   # a fetch that failed after `git init`: HEAD is unborn
        out, err = self.fetch()
        self.assertIn('fetch_ui: freetype: removed', err)
        self.assertTrue((ft / 'README').is_file())
        out, err = self.fetch()   # a good checkout is trusted and kept
        self.assertNotIn('removed', err)
        self.assertIn('freetype 2.13.3 at', out)

    def test_failing_fixture_a_sha_mismatch_or_a_failed_patch_is_never_retried(self):
        with mock.patch.dict(fetch_lua.PIN, {'sha256': '0' * 64}), self.assertRaises(SystemExit) as e, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fetch_lua.fetch(self.game / 'build' / 'lua')
        self.assertIn('refusing', str(e.exception))
        bad = dict(self.pins, stb_image=dict(self.pins['stb_image'], sha256='1' * 64))
        (self.game / 'viewer' / 'pins.json').write_text(json.dumps(bad), encoding='utf-8')
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fetch_ui.main(['--out', str(self.game / 'build' / 'ui' / 'src')])
        self.assertIn('refusing', str(e.exception))
        tb = Path(self._tmp.name) / 'srv' / 'lua-5.1.1.tar.gz'
        tb.write_bytes(lua_tarball(luaconf='/* no double here */\n'))
        with mock.patch.dict(fetch_lua.PIN, {'sha256': sha(tb.read_bytes())}), self.assertRaises(SystemExit) as e, \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            fetch_lua.fetch(self.game / 'build' / 'lua2')
        self.assertIn('did not apply', str(e.exception))
        self.assertEqual(self.slept, [])

    def test_failing_fixture_a_missing_pin_names_the_five_keys_and_the_reference_file(self):
        # C2 of the 2026-11-03 audit: the refusal said only `has no "stb_image_write" pin`
        pins = {k: v for k, v in self.pins.items() if k != 'stb_image_write'}
        (self.game / 'viewer' / 'pins.json').write_text(json.dumps(pins), encoding='utf-8')
        with self.assertRaises(SystemExit) as e, contextlib.redirect_stdout(io.StringIO()):
            fetch_ui.main(['--out', str(self.game / 'build' / 'ui' / 'src')])
        msg = str(e.exception)
        self.assertIn('has no "stb_image_write" pin', msg)
        self.assertIn('rmlui, freetype, lua, stb_image, stb_image_write', msg)
        self.assertIn('PNG dump', msg)
        self.assertIn('0.10.0', msg)
        self.assertIn('proxy/tests/null_game/viewer/pins.json', msg)
        self.assertIn('The UI pin file', msg)
        self.assertNotRegex(msg, r'(?i)napoleon|empire')

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
                mock.patch.object(netfetch.time, 'sleep', lambda s: None), contextlib.redirect_stderr(io.StringIO()) as out:
            with self.assertRaises(SystemExit):
                fetch_dxvk.fetch(t)
        self.assertEqual(calls, [fetch_dxvk.PIN['tarball_url']] * 2)
        self.assertIn('netfetch: dxvk', out.getvalue())


if __name__ == '__main__':
    unittest.main()
