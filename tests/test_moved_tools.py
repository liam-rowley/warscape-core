"""Host tests for the proxy and harness tools that moved here from napoleon-remastered (J12): where they find the game
(proxy/tools/layout.py), the DLL build id in either layout (proxy/tools/build_id.py), the exclusive game lock (harness/job.sh), and
that nothing in this repo names a game. The tools' fuller tests run in the game repo against its real adapter; the proxy's C++ host
tests and the harness PowerShell tests run in CI's proxy and harness-windows jobs against the null game (proxy/tests/null_game)."""
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


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


class BuildId(Env):
    """The id hashes role names and object ids, so the proxy sources and tools keep it when they move into a submodule (J12)."""
    def flat(self):
        g = self.t / 'flat'
        init(g)
        write(g / 'proxy/core/a.cpp', 'int a;\n')
        write(g / 'proxy/game/adapter.cpp', 'int b;\n')
        for n in ('build.sh', 'build_id.py', 'fetch_lua.py', 'layout.py'):
            write(g / 'proxy/tools' / n, (ROOT / 'proxy/tools' / n).read_bytes())
        write(g / 'wsc.toml', '# marker\n')
        git('add', '-A', cwd=g); git('commit', '-q', '-m', 'flat', cwd=g)
        return g

    def moved(self, flat):
        core = self.t / 'core'
        init(core)
        write(core / 'proxy/src/a.cpp', (flat / 'proxy/core/a.cpp').read_bytes())
        for n in ('build.sh', 'build_id.py', 'fetch_lua.py', 'layout.py'):
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


def git_bash():
    """bash for the job.sh test: Git Bash on Windows (never the WSL launcher in System32), any bash elsewhere."""
    if os.name != 'nt':
        return shutil.which('bash')
    for c in (r'C:\Program Files\Git\bin\bash.exe', r'C:\Program Files\Git\usr\bin\bash.exe'):
        if Path(c).is_file():
            return c
    b = shutil.which('bash')
    return b if b and 'system32' not in b.lower() else None


class GameLock(Env):
    def test_failing_fixture_of_racing_takers_exactly_one_wins(self):
        bash = git_bash()
        if not bash:
            self.skipTest('no bash to run harness/job.sh (Git Bash on Windows)')
        if not shutil.which('python3'):
            self.skipTest('job.sh calls python3, which is not on PATH here')
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
    """The code that came from a game repo (proxy/, harness/, saves/; J12) names no game: a path, an exe or a mod folder would carry the
    game into the core (CLAUDE.md). Provenance links to the earlier remaster's repository ("empire-remastered ...") are allowed. The
    rest of the core cites its consumer's job ids as provenance in comments, which this does not police."""
    GAME = re.compile(r'napoleon|empire(?!-remastered)', re.I)

    def test_no_tracked_file_names_a_game(self):
        files = subprocess.run(['git', '-C', str(ROOT), 'ls-files'], capture_output=True, text=True).stdout.splitlines()
        bad = []
        for f in files:
            if not f.startswith(('proxy/', 'harness/', 'saves/')) or not (ROOT / f).is_file():
                continue
            for n, line in enumerate((ROOT / f).read_bytes().decode('utf-8', 'replace').splitlines(), 1):
                if self.GAME.search(line):
                    bad.append(f'{f}:{n}: {line.strip()[:100]}')
        self.assertEqual(bad, [], '\n'.join(bad))


if __name__ == '__main__':
    unittest.main()
