"""Host tests for the proxy and harness tools that moved here from napoleon-remastered (J12): where they find the game
(proxy/tools/layout.py), the DLL build id in either layout (proxy/tools/build_id.py), the exclusive game lock (harness/job.sh), and
that nothing in the moved code names a game. The tools' fuller host tests run here too, one file per tool against the null game or temp
folders (tests/test_pc_deploy.py, test_ctl.py, test_acceptance.py, test_saves.py, test_job_sh.py, test_gitbash.py; B17); the proxy's C++
host tests and the harness PowerShell tests run in CI's proxy and harness-windows jobs against the null game (proxy/tests/null_game)."""
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from warscape import gitbash  # noqa: E402


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def git(*a, cwd):
    return subprocess.run(['git', '-c', 'core.autocrlf=false', *a], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def init(d):
    d.mkdir(parents=True, exist_ok=True)
    git('init', '-q', '-b', 'main', cwd=d)
    git('config', 'user.email', 't@example.invalid', cwd=d)
    git('config', 'user.name', 'test', cwd=d)


def write(p, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data if isinstance(data, bytes) else data.encode())


class Env(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.saved = {k: os.environ.pop(k) for k in ('WSP_GAME_ROOT', 'WSP_PROXY_ADAPTER', 'HARNESS_ADAPTER') if k in os.environ}

    def tearDown(self):
        os.environ.update(self.saved)
        self.tmp.cleanup()


class Layout(Env):
    def setUp(self):
        super().setUp()
        self.lay = _load('layout', 'proxy/tools/layout.py')

    def test_one_adapter_is_found_and_none_or_two_are_named(self):
        g = self.t / 'game'
        write(g / 'proxy/x/adapter.cpp', '')
        write(g / 'harness/x/adapter.json', '{}')
        self.assertEqual(self.lay.proxy_adapter(g), g / 'proxy/x')
        self.assertEqual(self.lay.harness_adapter(g), g / 'harness/x/adapter.json')
        write(g / 'proxy/y/adapter.cpp', '')
        with self.assertRaises(self.lay.LayoutError) as e:
            self.lay.proxy_adapter(g)
        self.assertIn('proxy/x/adapter.cpp, proxy/y/adapter.cpp', str(e.exception))
        write(g / 'wsc.toml', '[proxy]\nadapter = "proxy/y"\n')                  # the game names it (core 0.4.0 accepts the key)
        self.assertEqual(self.lay.proxy_adapter(g), g / 'proxy/y')
        with self.assertRaises(self.lay.LayoutError):
            self.lay.harness_adapter(self.t / 'empty')

    def test_the_game_root_is_the_superproject_or_the_env(self):
        self.assertEqual(self.lay.game_root(ROOT), ROOT)                          # standalone: the core is its own game (the null one)
        os.environ['WSP_GAME_ROOT'] = str(self.t)
        self.assertEqual(self.lay.game_root(ROOT), self.t.resolve())
        self.assertEqual(self.lay.proxy_src(ROOT), ROOT / 'proxy' / 'src')


TOOLS = ('build.sh', 'build_id.py', 'fetch_lua.py', 'fetch_ui.py', 'layout.py', 'toolchain.py')   # the files the roles name, and their imports


class BuildId(Env):
    """The id hashes role names and object ids, so the proxy sources and tools keep it when they move into a submodule (J12)."""
    def flat(self):
        g = self.t / 'flat'
        init(g)
        write(g / 'proxy/core/a.cpp', 'int a;\n')
        write(g / 'proxy/game/adapter.cpp', 'int b;\n')
        write(g / 'viewer/pins.json', '{}\n')   # the UI pin file (J30: a DLL input, it stays in the game repo)
        for n in TOOLS:
            write(g / 'proxy/tools' / n, (ROOT / 'proxy/tools' / n).read_bytes())
        write(g / 'wsc.toml', '# marker\n')
        git('add', '-A', cwd=g); git('commit', '-q', '-m', 'flat', cwd=g)
        return g

    def moved(self, flat):
        core = self.t / 'core'
        init(core)
        write(core / 'proxy/src/a.cpp', (flat / 'proxy/core/a.cpp').read_bytes())
        for n in TOOLS:
            write(core / 'proxy/tools' / n, (flat / 'proxy/tools' / n).read_bytes())
        write(core / 'wsc.toml', '# marker\n')
        git('add', '-A', cwd=core); git('commit', '-q', '-m', 'core', cwd=core)
        g = self.t / 'game'
        subprocess.run(['git', '-c', 'core.autocrlf=false', 'clone', '-q', flat.as_uri(), str(g)], check=True, capture_output=True)
        git('config', 'user.email', 't@example.invalid', cwd=g); git('config', 'user.name', 'test', cwd=g)
        git('rm', '-q', '-r', 'proxy/core', 'proxy/tools', cwd=g)
        git('-c', 'protocol.file.allow=always', 'submodule', 'add', '-q', core.as_uri(), 'core', cwd=g)
        git('commit', '-q', '-m', 'move', cwd=g)
        return g

    def test_failing_fixture_the_moved_layout_keeps_the_id_and_sees_a_change(self):
        bi = _load('build_id', 'proxy/tools/build_id.py')
        f = self.flat()
        flat_id = bi.build_id(f)
        g = self.moved(f)
        self.assertEqual(bi.build_id(g), flat_id)
        paths = {r: p for r, p, _ in bi.object_ids(g)}
        self.assertEqual((paths['core'], paths['build_sh']), ('core/proxy/src', 'core/proxy/tools/build.sh'))
        write(g / 'core/proxy/src/a.cpp', 'int a2;\n')
        self.assertEqual(bi.build_id(g), flat_id + '-dirty')

    def test_failing_fixture_the_toolchain_pin_is_the_last_role_and_moves_the_id(self):
        # W24 (C24): the toolchain is a committed build-id input, never a measured one; editing the pin is a new DLL
        bi = _load('build_id', 'proxy/tools/build_id.py')
        self.assertEqual([r for r, _ in bi.INPUTS][-1], 'toolchain')
        self.assertEqual(dict(bi.INPUTS)['toolchain'], ('proxy/tools/toolchain.py',))
        f = self.flat()
        before = bi.build_id(f)
        g = self.moved(f)
        self.assertEqual({r: p for r, p, _ in bi.object_ids(g)}['toolchain'], 'core/proxy/tools/toolchain.py')
        pin = f / 'proxy/tools/toolchain.py'
        pin.write_bytes(pin.read_bytes().replace(b"'mingw-w64-common': '", b"'mingw-w64-common': '9:"))
        self.assertEqual(bi.build_id(f), before + '-dirty')
        git('commit', '-q', '-am', 'bump the pin', cwd=f)
        self.assertNotIn(bi.build_id(f), (before, before + '-dirty'))
        self.assertEqual(len(bi.build_id(f)), 12)


class Sources(Env):
    """W24 (C24): the DLL compiles the core sources folder's tracked top-level *.cpp, byte-sorted; an untracked or ignored source file under the
    core sources or the adapter folder refuses the build (`build_id.py --sources`, exit 2), before any compile."""
    def repo(self):
        g = self.t / 'flat'
        init(g)
        for n in ('b.cpp', 'a.cpp', 'Z.cpp', 'ui_lua.cpp', 'x.h', 'sub/nested.cpp'):
            write(g / 'proxy/core' / n, f'// {n}\n')
        write(g / 'proxy/game/adapter.cpp', 'int b;\n')
        write(g / 'viewer/pins.json', '{}\n')
        for n in TOOLS:
            write(g / 'proxy/tools' / n, (ROOT / 'proxy/tools' / n).read_bytes())
        write(g / 'wsc.toml', '# marker\n')
        write(g / '.gitignore', '*.gen.h\n')
        git('add', '-A', cwd=g); git('commit', '-q', '-m', 'flat', cwd=g)
        return g

    def test_failing_fixture_the_tracked_top_level_cpp_files_in_byte_order(self):
        bi = _load('build_id', 'proxy/tools/build_id.py')
        g = self.repo()
        names, note = bi.sources(g / 'proxy/core', g / 'proxy/game')
        self.assertEqual(names, ['Z.cpp', 'a.cpp', 'b.cpp', 'ui_lua.cpp'])   # LC_ALL=C ls order; nested and headers are not compiled by name
        self.assertEqual(note, '')

    def test_failing_fixture_an_untracked_cpp_and_an_ignored_header_refuse_naming_each(self):
        bi = _load('build_id', 'proxy/tools/build_id.py')
        g = self.repo()
        write(g / 'proxy/core/stray.cpp', 'int s;\n')            # a forgotten git add: the DLL would silently lack it, or link a stray copy
        write(g / 'proxy/core/sub/shadow.gen.h', '#pragma once\n')   # ignored, and -I"$S" would let it shadow a tracked header
        write(g / 'proxy/game/extra.inc', '\n')
        write(g / 'proxy/core/notes.txt', 'not a source\n')
        with self.assertRaises(ValueError) as e:
            bi.sources(g / 'proxy/core', g / 'proxy/game')
        msg = str(e.exception)
        self.assertIn('untracked source', msg)
        self.assertIn('ignored source', msg)
        for part in ('proxy/core/stray.cpp', 'proxy/core/sub/shadow.gen.h', 'proxy/game/extra.inc', 'git add'):
            self.assertIn(part, msg)
        self.assertNotIn('notes.txt', msg)
        r = subprocess.run([sys.executable, str(g / 'proxy/tools/build_id.py'), '--sources'], cwd=g, capture_output=True, text=True,
                           env={k: v for k, v in os.environ.items() if not k.startswith('GIT_')})
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn('proxy/core/stray.cpp', r.stderr)
        self.assertEqual(r.stdout, '')

    def test_failing_fixture_a_staged_new_file_is_listed_and_the_id_is_dirty(self):
        bi = _load('build_id', 'proxy/tools/build_id.py')
        g = self.repo()
        clean = bi.build_id(g)
        write(g / 'proxy/core/c.cpp', 'int c;\n')
        git('add', 'proxy/core/c.cpp', cwd=g)
        names, _ = bi.sources(g / 'proxy/core', g / 'proxy/game')
        self.assertIn('c.cpp', names)
        self.assertEqual(bi.build_id(g), clean + '-dirty')

    def test_outside_git_every_cpp_is_listed_and_said_so(self):
        bi = _load('build_id', 'proxy/tools/build_id.py')
        d = self.t / 'nogit'
        for n in ('b.cpp', 'a.cpp', 'x.h'):
            write(d / 'src' / n, '\n')
        names, note = bi.sources(d / 'src', d / 'adapter')
        self.assertEqual(names, ['a.cpp', 'b.cpp'])
        self.assertIn('not in a git checkout', note)

    def test_failing_fixture_build_sh_refuses_an_untracked_cpp_before_any_compile(self):
        bash = gitbash.bash_or_skip(self)
        g = self.repo()
        marker = g / 'gen_tables_ran'
        # gen_tables.py --check runs after the sources check: a stub that leaves a marker proves the refusal came first
        write(g / 'proxy/tools/gen_tables.py', f'open({str(marker)!r}, "w").close()\n')
        git('add', '-A', cwd=g); git('commit', '-q', '-m', 'stub', cwd=g)
        write(g / 'proxy/core/stray.cpp', 'int s;\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith(('GIT_', 'WSP_'))}
        r = subprocess.run([bash, 'proxy/tools/build.sh', 'dll'], cwd=g, capture_output=True, text=True, env=env, timeout=120)
        out = r.stdout + r.stderr
        self.assertEqual(r.returncode, 2, out)
        self.assertIn('proxy/core/stray.cpp', out)
        self.assertFalse(marker.exists(), out)


class Toolchain(unittest.TestCase):
    """W24 (C24): toolchain.py pins the image and the mingw-w64 packages; `check` reads dpkg with an injected runner."""
    @classmethod
    def setUpClass(cls):
        cls.tc = _load('toolchain', 'proxy/tools/toolchain.py')

    def fake(self, have=None, owner='g++-mingw-w64-i686-win32', dpkg=True):
        """A runner that plays dpkg-query, dpkg -S, readlink -f and the version lines; `have` = {pkg: version} installed (default: the pin)."""
        have = dict(self.tc.PIN['apt']) if have is None else have
        calls = []

        def run(argv):
            calls.append(argv)
            if argv[0] in ('dpkg-query', 'dpkg') and not dpkg:
                raise FileNotFoundError(argv[0])
            if argv[0] == 'dpkg-query':
                lines = [f'{p}\t{v}\tii ' for p, v in have.items() if v] + [f'{p}\t\tun ' for p, v in have.items() if not v]
                return (0 if all(have.values()) else 1), ''.join(l + '\n' for l in lines)
            if argv[0] == 'readlink':
                return 0, argv[-1] + '\n'
            if argv[0] == 'dpkg':
                return (0, f'{owner}: {argv[-1]}\n') if owner else (1, '')
            if argv[-1] == '--version':
                return 0, ('i686-w64-mingw32-g++-win32 (GCC) 13-win32\nCopyright\n' if 'g++' in argv[0] else 'GNU ld (GNU Binutils) 2.41.90.20240122\n')
            raise AssertionError(argv)
        return run, calls

    CXX = '/usr/bin/i686-w64-mingw32-g++-win32'

    def test_apt_and_image_print_the_pin(self):
        line = self.tc.apt_line()
        self.assertEqual(line.split(), sorted(line.split()))
        self.assertEqual(dict(x.split('=', 1) for x in line.split()), self.tc.PIN['apt'])
        self.assertIn('g++-mingw-w64-i686-win32=', line)
        self.assertIn('mingw-w64-i686-dev=', line)   # the headers, CRT and import libraries linked into the DLL
        self.assertRegex(self.tc.PIN['image'], r'^ubuntu@sha256:[0-9a-f]{64}$')
        for p in self.tc.PIN['apt'].values():
            self.assertRegex(p, r'^[0-9][0-9A-Za-z.+~:-]*$')

    def test_failing_fixture_all_at_the_pin_is_one_line(self):
        run, calls = self.fake()
        ok, lines = self.tc.check(self.CXX, run=run)
        self.assertTrue(ok, lines)
        self.assertEqual(lines, [f'toolchain: pinned: {len(self.tc.PIN["apt"])} packages at their pins; i686-w64-mingw32-g++-win32 (GCC) 13-win32; '
                                 'GNU ld (GNU Binutils) 2.41.90.20240122'])
        self.assertIn(['/usr/bin/i686-w64-mingw32-ld', '--version'], calls)   # the linker next to the compiler, as build.sh's ${CXX%%g++*}
        self.assertIn(['dpkg', '-S', self.CXX], calls)

    def test_failing_fixture_one_version_off_one_missing(self):
        have = dict(self.tc.PIN['apt'], **{'mingw-w64-i686-dev': '12.0.0-1', 'binutils-mingw-w64-i686': None})
        ok, lines = self.tc.check(self.CXX, run=self.fake(have)[0])
        self.assertFalse(ok)
        text = '\n'.join(lines)
        self.assertIn(f"toolchain: mingw-w64-i686-dev 12.0.0-1 installed, pinned {self.tc.PIN['apt']['mingw-w64-i686-dev']}", text)
        self.assertIn(f"toolchain: binutils-mingw-w64-i686 not installed, pinned {self.tc.PIN['apt']['binutils-mingw-w64-i686']}", text)
        self.assertEqual(len(lines), 3, text)
        self.assertIn('--docker', lines[-1])
        self.assertIn('WSP_TOOLCHAIN=any', lines[-1])
        self.assertIn('toolchain.py apt', lines[-1])

    def test_failing_fixture_a_compiler_no_pinned_package_owns_is_refused(self):
        for owner in ('', 'g++-13'):
            ok, lines = self.tc.check('/opt/other/i686-w64-mingw32-g++', run=self.fake(owner=owner)[0])
            self.assertFalse(ok)
            self.assertIn('not by a pinned package', lines[0])
            self.assertIn(owner or 'no package', lines[0])

    def test_failing_fixture_no_dpkg_query(self):
        ok, lines = self.tc.check(self.CXX, run=self.fake(dpkg=False)[0])
        self.assertFalse(ok)
        self.assertEqual(lines[0], 'toolchain: no dpkg-query: the pin cannot be checked')
        self.assertEqual(len(lines), 2)

    def test_the_cli_exit_codes(self):
        import contextlib
        import io
        one_missing = dict(self.tc.PIN['apt'], **{'mingw-w64-common': None})
        for have, code in ((None, 0), (one_missing, 2)):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.tc.main(['check', self.CXX], run=self.fake(have)[0]), code)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(self.tc.main(['installed'], run=self.fake(one_missing)[0]), 0)
        self.assertIn('mingw-w64-common=none', out.getvalue())
        self.assertIn('mingw-w64-i686-dev=' + self.tc.PIN['apt']['mingw-w64-i686-dev'], out.getvalue())
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.tc.main(['bogus']), 64)


class GameLock(Env):
    def test_failing_fixture_of_racing_takers_exactly_one_wins(self):
        bash = gitbash.bash_or_skip(self)
        state = self.t / 'state'
        (state / 'watcher').mkdir(parents=True)
        ad = self.t / 'adapter.json'
        ad.write_text(json.dumps({'state_dir': str(state), 'watcher_subdir': 'watcher'}))
        env = {k: v for k, v in os.environ.items() if k not in ('WATCHER_ROOT', 'HARNESS_ADAPTER')}
        procs = [subprocess.Popen([bash, str(ROOT / 'harness/job.sh'), '--adapter', str(ad), 'lock', f'a{i}', 's', 'p'], env=env,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for i in range(4)]
        codes = [p.wait(60) for p in procs]
        self.assertEqual(sorted(codes), [0, 2, 2, 2], codes)


class NoGameNames(unittest.TestCase):
    """The code that came from a game repo (proxy/, harness/, saves/; J12; discovery/, W4) names no game: a path, an exe or a mod folder would carry the
    game into the core (CLAUDE.md). Provenance links to the earlier remaster's repository ("empire-remastered ...") are allowed. The
    rest of the core cites its consumer's job ids as provenance in comments, which this does not police. A module that cannot be made name-free gets an entry in ALLOW with its reason and a
    backlog row, never a blanket exemption (none today). The moved tools' host tests ported from the game repo (B17, B18) are scanned too:
    PORTED, never an ALLOW entry for a test file."""
    GAME = re.compile(r'napoleon|empire(?!-remastered)', re.I)
    ALLOW = {}   # tracked path -> why it may name a game (and its backlog row)
    PORTED = ('tests/test_pc_deploy.py', 'tests/test_ctl.py', 'tests/test_acceptance.py', 'tests/test_saves.py', 'tests/test_job_sh.py',
              'tests/test_gitbash.py')

    def test_no_tracked_file_names_a_game(self):
        files = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], capture_output=True, text=True).stdout.splitlines()
        self.assertEqual([f for f in self.PORTED if f not in files], [], 'a ported host test is not tracked')
        bad = []
        for f in files:
            moved = f.startswith(('proxy/', 'harness/', 'saves/', 'discovery/')) or f in self.PORTED
            if not moved or f in self.ALLOW or not (ROOT / f).is_file():
                continue
            for n, line in enumerate((ROOT / f).read_bytes().decode('utf-8', 'replace').splitlines(), 1):
                if self.GAME.search(line):
                    bad.append(f'{f}:{n}: {line.strip()[:100]}')
        self.assertEqual(bad, [], '\n'.join(bad))


class NoOldLayoutPaths(unittest.TestCase):
    """B24: the trees that moved into the core (proxy/, harness/, saves/, discovery/) have no `core/` folder any more; a comment, a docstring or a
    `usage:` line that names `harness/core/job.sh` sends the reader to a path that is gone. (`viewer/core/` is still a consumer's folder and is not
    matched.) A match that must stay has an entry in ALLOW: (path, matched text) -> (how many times, why); no blanket exemption. The count makes a
    new match in an allowed file fail, and a stale entry fail once its strings are re-stamped."""
    OLD = re.compile(r'(?:proxy|harness|saves|discovery)/core/')
    TREES = ('proxy/', 'harness/', 'saves/', 'discovery/')
    RESULT = ('written into a committed result of a game (a generator or provenance string, or a line of a generated README): changing it moves the '
              "game's committed bytes; backlog B55 re-stamps them in one regeneration commit on the game")
    ALLOW = {
        ('discovery/README.md', 'discovery/core/'): (None, 'documents the old-to-new paths on purpose (the table of moved tools)'),
        ('discovery/assets.py', 'discovery/core/'): (1, RESULT),
        ('discovery/db.py', 'discovery/core/'): (2, RESULT),
        ('discovery/engine_api.py', 'discovery/core/'): (3, RESULT),
        ('discovery/gate.py', 'discovery/core/'): (2, RESULT),
        ('discovery/loc.py', 'discovery/core/'): (1, RESULT),
        ('discovery/lua_api.py', 'discovery/core/'): (1, RESULT),
        ('discovery/ron2json.py', 'discovery/core/'): (1, RESULT),
        ('discovery/shader_catalog.py', 'discovery/core/'): (1, RESULT),
        ('discovery/ui_atlas.py', 'discovery/core/'): (5, RESULT),
        ('proxy/tools/gen_tables.py', 'discovery/core/'): (1, 'written into the generated console_table.h, a DLL input of every game: changing it changes their build ids'),
        ('proxy/src/camera.h', 'harness/core/'): (1, 'a comment in a DLL input: fix it with the next DLL change'),
        ('proxy/tools/pc_deploy.py', 'harness/core/'): (1, 'code that still supports the old layout on purpose (a game that has not bumped its pin)'),
        ('harness/watcher.ps1', 'harness/core/'): (2, 'the watcher kit: fixed with the next watcher change (W10), so its version and the consumer rule-79 streak move once'),
    }

    def test_no_moved_file_names_a_path_that_is_gone(self):
        files = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], capture_output=True, text=True).stdout.splitlines()
        found, bad = {}, []
        for f in files:
            if not f.startswith(self.TREES) or not (ROOT / f).is_file():
                continue
            for n, line in enumerate((ROOT / f).read_bytes().decode('utf-8', 'replace').splitlines(), 1):
                for m in self.OLD.finditer(line):
                    found[(f, m.group(0))] = found.get((f, m.group(0)), 0) + 1
                    if (f, m.group(0)) not in self.ALLOW:
                        bad.append(f'{f}:{n}: names {m.group(0)}, which no longer exists in the core: {line.strip()[:100]}')
        for key, (count, why) in self.ALLOW.items():
            if count is not None and found.get(key, 0) != count:
                bad.append(f'ALLOW entry {key} expects {count} match(es), found {found.get(key, 0)}: update or remove the entry ({why[:40]}...)')
        self.assertEqual(bad, [], '\n'.join(bad))


if __name__ == '__main__':
    unittest.main()
