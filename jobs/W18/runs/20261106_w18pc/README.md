# W18 PC proofs a, b, d: run 20261106_w18pc (2026-11-06)

Build: napoleon main 95e72d6a (scratch tree, never committed) with core at 82cdce4 (this branch merged with origin/main); DLL build `a005f6cccc17-dirty`,
sha256 `a588edd7d05ef0f8029e75c39cf471620f66ccef922bc0898598629ecb7081d2`; kit `kit_20261106T133718Z_95e72d6a6f1d`. Installed watcher 1.4.0 (core has 1.5.0): it did not stop
any proof. The stray `napoleon_remastered.ini` was moved aside by Liam before the sitting, so `pc_deploy install` ran without `--move-stray`.
Display layout (changed 2026-11-05): DISPLAY1 (the MSI) 0,0 3840x2160 primary, DISPLAY2 -2560,327, virtual DISPLAY10 3839,2160 3840x2160; no foreign-window observer was needed.
Game lock `w18`, taken and released between launches (the watcher's profile restore needs the release before `pc_deploy set`). Launches only through the watcher.
Sequence: lock, install, set, launch a, kill, unlock, lock, set, launch b (origin move, shot, restore, shot), kill, unlock, lock, set, launch d, kill, unlock, uninstall
("game folder identical to the pre-install snapshot (1564 files)"), `pc_deploy status`: not installed, exe vanilla, no lock, no `vdisplay_restore.json`.

## a. B19 (`headless.test_dll_window_ms=15000`): PASS
- `a_proxy.log.txt`: `13:38:46.091Z ... unguarded window 01980018 shown at 0,0 640x480: hidden at show (winevent)` precedes `13:38:46.143Z ... TEST HOOK headless.test_dll_window_ms:
  window 01980018 shown at 0,0 640x480 through the proxy's own import`. The hide is logged by the guard thread from the hook; the test line is logged after the test thread's
  show call returns, so the hide came first (0 ms after the show, limit 15 ms; the sweep alone would be up to 250 ms).
- `a_winprobe.json`: window `1980018` (Static) `visible_ms` 54, `visible_on_real_ms` **0**; `longest_visible_on_real_ms` 0 (limit 25; J12's sweep-only run: 109); game window 0 ms; off-target 0.
  The 54 ms of `visible_ms` is the window cloaked-then-hidden by the hook as the probe sees it, on no real monitor.
- `a_headless_status.json`: `on_virtual`, `relocations` 0.

## b. B23 and the own move (`headless.test_off_thread=1`): PASS
- `vdisplay_probe.ps1 -Origin 3840,0` (the layout has no 2560,0 slot; 3840,0 is right of the MSI, no overlap) then `-Restore`.
- `b_proxy.log.txt`: first move `CLOAKED ... relocation queued ... relocated and verified on \\.\DISPLAY10 3840,0 ... uncloaked ... at 37.095 s`; the restore the same, uncloaked at 75.340 s.
  No `matches neither armed own-move rect` line (100 % DPI, the physical rect matched).
- Status after the first move (read live, quoted from the run): `"relocations": 1`, `target.rect` `[3840, 0, 7680, 2160]`, `detail` `relocated to \\.\DISPLAY10 3840,0 3840x2160 at 36.6 s`, `state` still `on_virtual`.
  `b_headless_status_after2.json` (after the restore): `"relocations": 2`, `target.rect` `[3839, 2160, 7679, 4320]`.
- Shots through `harness/shot.sh`: `b1_shot_3840_0.jpg` reports "from 3840 x 2160 at 3840,0" (the new rect), `b2_shot_3839_2160.jpg` "at 3839,2160" (the restored rect).
- `b_winprobe.json`: `longest_visible_on_real_ms` **0**, `visible_on_real_ms_total` 0, off-target 0, `cloaked_ms` 1304 (the two settles), 2 monitor changes.

## d. No regression (plain launch): PASS
- `d_proxy.log.txt`: `on_virtual` at 1.3 s, no `winevent` line, no `neither` line; the only WARN is `crash: top-level filter ... REPLACED` (present in every launch, a and b too, before this change).
- `d_winprobe.json`: `longest_visible_on_real_ms` 0, total 0, off-target 0, cloaked 0. `d_headless_status.json`: `on_virtual`, `relocations` 0.

## c. B22 at a scaled display: NOT RUN (needs Liam to set the virtual display to 125 or 150 %; the report recommends not).
