## Round 1 (2026-11-04, branch job/W35 at 758f039)

**Verdict: merge after fixes.**

Machines: `wsc gates --fast` 12 ok, 2 warn (hooks path, an old W23 policy.yml.in note), 0 failed; CI on 758f039 green (2 checks); `wsc policy` refuses only on the
missing review and row (expected before this round). main has not moved (VERSION 0.33.0 on main, 0.35.0 here, C29 free on main), so no merge of main was needed.
The 14 `test_agent_settings` tests pass. Risk-first reading: `warscape/verbs/agent_settings.py` (edits an agent's permissions) and the `vdisplay-aside` case in
`harness/job.sh` (moves PC state). Crash/minidump/map parts were skimmed against the CI evidence (artifact, `lua_gettop` named under wine) and look sound.
Probed `agent-settings` on temp files only (`probe.py` in the job tmp dir); no real settings file was touched.

### Blockers (agent-settings can be made to add a broad or write-capable rule, or write outside its repo)
1. **A "narrower" rule can be a write primitive.** `warscape/verbs/agent_settings.py:46-54` `covers` accepts any rule whose text starts with a safe prefix.
   With safe `Bash(git diff:*)`, `allow 'Bash(git diff --output=C:/x/y:*)'` exits 0 and is added (git diff/log/show `--output=<file>` writes any file; `--ext-diff`
   runs a configured program). Also `Bash(git diffx:*)` is accepted (no word boundary: a different command). Both reproduced. Fix: a rule must equal a safe
   pattern or extend it by whole words; refuse `--output`, `--ext-diff`, `--textconv`, `-c`/`--exec` style flags (a small deny-flag list in the code), and add
   an optional `[agent_settings] exact_only` or document that a narrower rule is only a longer word-boundary prefix without those flags. Test each.
2. **Symlinks are not refused reliably; a junction is followed.** `agent_settings.py:86` checks `f.is_symlink() or f.parent.is_symlink()` only. A Windows
   junction `repo/.claude -> elsewhere` is not a symlink: the verb wrote `settings.json` through it (reproduced: `out/settings.json` changed). The `.bak`
   path (`agent_settings.py:106`, `shutil.copyfile(f, f + '.bak')`) is never checked, so a `settings.json.bak` symlink is written through. The temp file is created
   by `mkstemp` in the folder (fine) but nothing resolves the folder. Fix: resolve the target (`os.path.realpath`) and require it to equal
   `<root>/.claude/<name>` after resolution; refuse `is_junction()`, a link at `.bak`, and a hard-link count above 1 on the file; open the `.bak` with `O_EXCL`
   or write it as a unique temp then replace.
3. **`--file` may name any `.claude` folder anywhere** (`agent_settings.py:84`): `--file C:/Users/x/.claude/settings.json` or another repo's was written
   (reproduced, exit 0). The brief says never outside `.claude/`; the safe reading is the repo's own `<root>/.claude`. Fix: require the resolved parent to be
   `<root>/.claude`. Test it with a second `.claude` folder outside the root.
4. **The tests do not prove each refusal the brief asks for.** `tests/test_agent_settings.py` has no test for a symlink, a junction, a link at `.bak`, a
   `.claude` outside the root, a write-capable flag, or `deny`/hook byte-identity after `allow` beyond a dict compare (that last one is present; the rest are not).
   Add tests that fail on 1-3 above before the fix (a symlink test may skip where `os.symlink` raises, but the junction/realpath test must run on Windows).

### Should-fix
5. `agent_settings.py:72-77`: a `deny` rule with a mid-string glob (`Bash(git * --force)`) is only compared as a literal, so an allow it would cover is not seen.
   Treat any deny containing `*` as overlapping when its non-wildcard prefix and the rule share a prefix, or refuse when the deny has a glob and the tool matches.
6. `.bak` is overwritten on every writing run (report deviation 6), so two runs lose the first original. Fine if said; say it in the verb's help.

### job.sh `vdisplay-aside` (checked, no finding)
`harness/job.sh` case `vdisplay-aside` moves only `$ROOT/vdisplay_restore.json`, to a new `_to_delete/*.json.aside` name, with `mv -n` and a check that the
destination exists and the source is gone; it never deletes and writes nothing else but a `watcher.log` record. It refuses unless all hold: usage and
`owner_ok`; non-empty why; the file exists; `holds_check` passes when `game.lock` exists (free = no file); `watcher.alive` is under 15 s old; `watcher.status`
is readable and lists no process and no game pid; and either the last `vdisplay:` log line is RESTORE FAILED/repeated/dropped and not older than the file
(2 s slack), or the file is older than the stale limit. A vanished file or a name collision is a refusal. Matches decision 10. 5 `TestJobSh.VdisplayAside`
tests cover it. Later (not required): a test where `watcher.status` shows a process, if absent.

### Claims against evidence
Report claims on the map, repro, CI artifact and the `lua_gettop` symbolisation are backed by CI run 41890834438 and the host tests; not re-run (needs wine/CI).
The report's statement that `agent-settings` "never follows a symlink" and "writes only directly inside `.claude/`" is not true as probed (blockers 2, 3).

### Round 2 ask
Fix 1-4 (and 5 if cheap), add the tests, bump nothing else; append `## Fix round 1` to `report.md` and set the row to `review`.
