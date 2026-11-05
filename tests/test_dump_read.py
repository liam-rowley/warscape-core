"""Host tests for proxy/tools/dump_read.py on cdb's text (W39): the main module, the watch list, the frames and the cycle. No debugger needed:
the fixture has the shape of a real `cdb -z` run (a 32-bit ping.exe dump, WinDbg 1.2610.1001.0, 2026-11-04), with cdb's echo of each `.echo`."""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dump_read', ROOT / 'proxy' / 'tools' / 'dump_read.py')
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

CYCLE = ['opengl32!wglWndProc+0x1b', 'user32!_InternalCallWinProc+0x2b', 'user32!UserCallWinProcCheckWow+0x33a', 'user32!CallWindowProcW+0x7e',
         'd3d9_dxvk+0x71d06', 'user32!_InternalCallWinProc+0x2b', 'user32!UserCallWinProcCheckWow+0x33a', 'user32!CallWindowProcW+0x7e']


def cdb_text(frames, name=r'C:\Program Files (x86)\Steam\steamapps\common\Some Game\Game.EXE', mods=('Game', 'd3d9', 'd3d9_dxvk', 'opengl32')):
    main = f'.  0\tid: 7bd4\texamine\tname: {name}\n' if name else 'no process\n'
    lm = ''.join(f'0{i}400000 0{i}409000   {m}       (deferred)\n' for i, m in enumerate(mods))
    return (f'0:000> .echo @@MAIN\n@@MAIN\n{main}0:000> .echo @@ENDMAIN\n@@ENDMAIN\n'
            'esp=02edefac\n    StackBase:            02ee0000\n    StackLimit:           02eda000\n'
            '0:000> .echo @@STACK\n@@STACK\n0:000> kc 0n60000\nCall Site\n' + '\n'.join(frames) + '\n'
            f'0:000> .echo @@ENDSTACK\n@@ENDSTACK\n0:000> .echo @@MODS\n@@MODS\n0:000> lm\nstart    end        module name\n{lm}0:000> .echo @@ENDMODS\n@@ENDMODS\n')


class MainModule(unittest.TestCase):
    def test_the_name_is_the_exe_without_its_folder_or_extension(self):
        self.assertEqual(dr.main_module(cdb_text([])), 'Game')
        self.assertEqual(dr.main_module(cdb_text([], name=r'C:\Windows\SysWOW64\PING.EXE')), 'PING')

    def test_no_name_from_cdb(self):
        self.assertIsNone(dr.main_module(cdb_text([], name=None)))
        self.assertIsNone(dr.main_module(''))


class WatchList(unittest.TestCase):
    def test_the_dumps_own_main_module_by_default(self):
        self.assertEqual(dr.watch_list(None, cdb_text([])), dr.WATCH + ('Game',))

    def test_exe_wins_with_or_without_its_extension(self):
        self.assertEqual(dr.watch_list('Other', cdb_text([]))[-1], 'Other')
        self.assertEqual(dr.watch_list('Other.exe', cdb_text([]))[-1], 'Other')

    def test_no_exe_anywhere_keeps_the_graphics_list(self):
        self.assertEqual(dr.watch_list(None, cdb_text([], name=None)), dr.WATCH)

    def test_the_loaded_list_names_the_exe(self):
        r = dr.analyse('x.dmp', cdb_text(CYCLE * 4))
        self.assertTrue(r['modules']['Game'])
        self.assertTrue(r['modules']['d3d9_dxvk'])
        self.assertFalse(r['modules']['amdvlk32'])
        self.assertTrue(dr.analyse('x.dmp', cdb_text(CYCLE * 4), 'Elsewhere')['modules'].get('Elsewhere') is False)


class Frames(unittest.TestCase):
    def test_cdbs_echo_of_the_marker_is_not_a_frame(self):
        r = dr.analyse('x.dmp', cdb_text(['ntdll!NtDelayExecution+0xc', 'PING!wmain+0x1a']))
        self.assertEqual(r['frames'], 2)
        self.assertEqual(r['top'], ['ntdll!NtDelayExecution', 'PING!wmain'])
        self.assertNotIn('@@STACK', r['frame_owners'])

    def test_the_period_8_cycle_of_the_window_procs(self):
        frames = ['ntdll!KiFastSystemCallRet+0x1'] + CYCLE * 6 + ['user32!PeekMessageW+0x10', 'Game!main+0x20']
        r = dr.analyse('x.dmp', cdb_text(frames))
        self.assertEqual(r['frames'], len(frames))
        self.assertEqual(r['cycle']['period'], 8)
        self.assertEqual(r['cycle']['repeats'], 6)
        self.assertEqual(r['below_cycle'], ['user32!PeekMessageW', 'Game!main'])
        self.assertIn('repeating cycle', dr.md({**r, 'session_time': None, 'process_uptime': None, 'exception_code': None, 'exception_address': None, 'access': None, 'thread': None}))

    def test_no_cycle_in_a_plain_stack(self):
        self.assertIsNone(dr.find_cycle(['a', 'b', 'c', 'd']))


if __name__ == '__main__':
    unittest.main()
