# W18 evidence, 2026-11-06 (run id 20261106_w18host): host tests and a scratch build only; NO PC proof ran

- `core_host_tests.txt`: `build.sh --docker all` on this branch with the null game (WSP_GAME_ROOT=proxy/tests/null_game), 2026-11-06: `test_display_guard` 328 passed, 0 failed;
  17 core host tests and 1 game test pass; the DLL compiles (build c8935ee831e7-dirty, a dirty tree: uncommitted at that moment).
- `scratch_napoleon_build.txt`: a scratch napoleon tree (main at 95e72d6a, core pin 0.30.0) with core at 45e5fe6 (this branch). First build: `test_config` and
  `test_guard` failed because napoleon's `registries/config_keys.jsonl` lacks `proxy.file_rules` and `proxy.dxvk_wndproc_fix` (the pin-bump edit of 0.33/0.40); with the two
  rows (copied from the null game) and `gen_tables.py`: all host tests pass, DLL build a005f6cccc17-dirty, sha256 a588edd7d05ef0f8029e75c39cf471620f66ccef922bc0898598629ecb7081d2.
  The scratch tree was removed; nothing from it is committed or pushed.
- `pc_deploy_status_before.txt`: the game folder before any sitting: nothing installed, exe vanilla, no .git, and the stray `napoleon_remastered.ini` (10957 bytes) that waits on Liam.

## Not run, and why
Proofs a (B19), b (B23 and the 100 % own move), d (no regression) need `pc_deploy.py install`, which refuses while the stray `napoleon_remastered.ini` is in the game
folder; the only way past it is `--move-stray`, and Liam said to leave that file. No lock was taken, no launch was made, the game folder and the watcher were not touched.
Proof c (scaled DPI) needs Liam's opt-in and was not asked for here.
