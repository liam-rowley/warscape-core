# W18 PC proofs a, b, d on the fixed DLL: run 20261106_w18pc2 (2026-11-06)

The re-run review round 1 asked for (findings 2 and 3): the fix changes `proxy/src`, so the proofs must name the new DLL.

**The DLL:** sha256 `5d646e47eff9414f94234d995876b2c4aef79e08acab31dd268993e91e25b1c9`, 4454400 bytes, from core c67d801 (`job/W18`) in a scratch clone of napoleon main e0ac1d8a07ad with the two `config_keys` rows its pin lacks; kit `kit_20261106T142836Z_e0ac1d8a07ad`. All three logs carry this sha on their `self_hash` line. The installed file no longer contains the name of the old conversion call.

**The build id does not name it.** The logs say `a005f6cccc17-dirty`, the same id as run 20261106_w18pc's different DLL (`a588edd7...`). `build_id.py` hashes the inputs at the commit the superproject's gitlink pins, so a scratch tree with a newer core reports the pin's id plus `-dirty`. Use the sha256 and the core commit.

Lock `w18`, session aac2fd3f-d9f9-409f-8143-3df8abdde693, taken only when the watcher showed it free, released between launches for the profile restore. Launches, kills and display moves only through the watcher. CI at c67d801 (run 42232966335) was green before the sitting. Installed watcher 1.4.0. Sequence: install, set, a, kill, unlock, lock, set, b (discarded), restore, kill, b, kill, unlock, lock, set, d, kill, unlock, lock, uninstall, unlock.

## a. B19 (`headless.test_dll_window_ms=15000`): PASS
- `a_proxy.log.txt`: `14:35:15.787Z ... unguarded window 0173069c shown at 0,0 640x480: hidden at show (winevent)`, then the `TEST HOOK` line at `.799`. That line is written after `CreateWindowExW` returns, so the order is a bound, not a measurement of the delay (review, Later).
- The measurement is the probe, `a_winprobe.json`: window `173069C` (Static) first seen at 17314 ms already cloaked, `visible_ms` 11 = `cloaked_ms` 11, `visible_on_real_ms` **0**; `longest_visible_on_real_ms` 0 (limit 25; J12's sweep-only run 109); game window 0.
- `a_headless_status.json`: `on_virtual`, `relocations` 0.

## b. B23 and the own move (`headless.test_off_thread=1`): PASS
- `-Origin 3840,0` at 61.9 s, at the front end, then `-Restore` at 89.0 s. (3840,0 as in the first sitting: the layout has no 2560,0 slot.)
- `b_proxy.log.txt`: both moves `relocated and verified`, uncloaked at 62.530 s and 89.585 s; no `matches neither` line, no `own move armed` line (a 96 DPI target: nothing to arm).
- `b_headless_status_after1.json`, committed this time: `"relocations": 1`, `target.rect` `[3840, 0, 7680, 2160]`, `state` `on_virtual`. `b_headless_status_after2.json`: `"relocations": 2`, `[3839, 2160, 7679, 4320]`, `state` `on_virtual`.
- `b1_shot_output.txt`: `from 3840 x 2160 at 3840,0`; `b2_shot_output.txt`: `at 3839,2160`, with `b1_shot_3840_0.jpg` and `b2_shot_3839_2160.jpg`.
- `b_winprobe.json`: `longest_visible_on_real_ms` **0**, total 0, off-target 0, `cloaked_ms` 1307, 2 monitor changes.

**One launch discarded.** The first b launch moved the origin 5.2 s after start, during loading, not at the front end the brief names (a wait of mine was refused and the next call ran at once). It relocated correctly, but it does not count: `b0_discarded_early_proxy.log.txt`, `b0_discarded_early_status.json`. The display was restored and the game killed before the real launch. Its save file `vd_saved2.json` is why the real launch used `vd_saved3.json`: the tool refuses to overwrite one, and its first `-Origin` attempt was refused for that reason, changing nothing.

## d. No regression (plain launch): PASS
`d_proxy.log.txt`: `on_virtual` at 1.3 s; the one WARN is the existing `crash: top-level filter` line; no `winevent`, `matches neither`, `own move armed` or `TEST HOOK` line. `d_winprobe.json`: `longest_visible_on_real_ms` 0, total 0, off-target 0, cloaked 0. `d_headless_status.json`: `on_virtual`, `relocations` 0.

## The PC put back
`pc_deploy uninstall`: "game folder identical to the pre-install snapshot (1564 files)". `pc_deploy_status_after.txt` is identical to `pc_deploy_status_before.txt`: not installed, exe vanilla. No `d3d9.dll`, no `napoleon_remastered.ini`, no `vdisplay_restore.json`; the virtual display is at 3839,2160; lock released; scratch clone removed.

## c. B22 at a scaled display: NOT RUN
Needs Liam's opt-in. These proofs run at 96 DPI, so they show the fix did not regress; they do not exercise the logical arm with the game. That rests on the host tests and the probe, `jobs/W18/runs/20261106_w18fix/`.
