#!/usr/bin/env bash
# purpose: agent helper on the PC (Git Bash): submit a watcher job, block inside ONE call until its result (or a timeout), print the output, return the job's exit code (refused 2, no answer 124); also take, refresh and release the game lock
# usage: job.sh [--adapter FILE] <owner> <file|-> [timeout_s (default 100)]  |  job.sh adapter  |  job.sh [--adapter FILE] lock [--wait S] <owner|-> <session> <purpose> [hang_s]  |  touch <owner>  |  unlock <owner> [--force]  |  vdisplay-aside <owner|-> <session> <why>  |  holds <owner>  |  status  |  root  |  scratch <owner>  |  ctl <owner> '<verb args>' [wait_s (default 100)]
# when: every time an agent runs something on the PC (launch, kill, profile, scripts): the watcher root comes from the adapter (state_dir + watcher_subdir), never a default path; waiting belongs here, not in repeated agent calls
# not-a-verb: a bash helper agents call directly from Git Bash (python3 only reads JSON); the PC side of the protocol is harness/watcher.ps1
# The lock owner is the session (W10, C26): one owner rule ^[a-z0-9][a-z0-9_-]{0,39}$ for every command (a session id is a 36-character UUID; `lock -` makes the owner the session id).
# The holder is the pair (owner, session): the same owner with another session is refused like another owner, until the lock is stale. `holds <owner>` exits 0 when the lock is held,
# fresh, and its owner or session is <owner>, else 2 with the reason; `ctl` and shot.sh need it. touch/unlock act only on the holder's lock (a bare touch is refused). `lock --wait S`
# polls every 2 s up to S (capped at 100): 124 on timeout, a plain refusal is 2. The stale age is `lock_stale_min` in <root>/watcher.ini (default 20), the watcher's own setting.
# Waits stay under the Bash tool's 120 s limit (default 100); a plain job or ctl request that gets no answer is withdrawn (<id>.request.expired / .cmd.expired), or says its result will still land.
# A ps1 job's exit code is its last statement's: end the script with `exit 0` when a native tool's non-zero code means success (robocopy 1 to 7).
# scratch <owner> creates <state>/_scratch/<owner>/ and prints its Git Bash path (the only place for PC experiments; the Claude Code hook denies other writes there).
# Body: a one-line control job (launch|kill|profile <name>|restore|update kit=<id>|restart|status|noop) or a cmd/ps1 script ('#ps1' first line or '#job type=ps1').
# launch/kill/profile get ' owner=<owner>' appended when missing; a script without a '#job owner=' line gets one. Root: $WATCHER_ROOT when set (tests), else <adapter state_dir as a Git Bash path>/<watcher_subdir>.
# Adapter (J12): --adapter FILE, else $HARNESS_ADAPTER, else adapter.json beside this script (a kit), else the game repo's harness adapter
# (proxy/tools/layout.py harness-adapter: wsc.toml [harness] adapter, or the one harness/*/adapter.json); never a game name or folder.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ADAPTER="${HARNESS_ADAPTER:-}"
if [ "${1:-}" = "--adapter" ]; then ADAPTER="${2:?--adapter FILE}"; shift 2; fi
own_root() { local d="$HERE"; while [ "$d" != "/" ] && [ ! -f "$d/wsc.toml" ]; do d="$(dirname "$d")"; done; [ -f "$d/wsc.toml" ] && printf '%s' "$d"; }
find_adapter() {
  [ -n "$ADAPTER" ] && [ -f "$ADAPTER" ] && return 0
  [ -f "$HERE/adapter.json" ] && { ADAPTER="$HERE/adapter.json"; return 0; }
  local o; o="$(own_root)" && [ -f "$o/proxy/tools/layout.py" ] && ADAPTER="$(python3 "$o/proxy/tools/layout.py" harness-adapter 2>/dev/null)"
  [ -n "$ADAPTER" ] && [ -f "$ADAPTER" ]
}
resolve_root() {
  if [ -n "${WATCHER_ROOT:-}" ]; then printf '%s' "$WATCHER_ROOT"; return 0; fi
  find_adapter || { echo "job.sh: no adapter.json found (use --adapter FILE, \$HARNESS_ADAPTER or \$WATCHER_ROOT; from a repo: proxy/tools/layout.py harness-adapter says why)" >&2; return 64; }
  python3 - "$ADAPTER" <<'PY'
import json, re, sys
a = json.load(open(sys.argv[1], encoding='utf-8'))
s = a['state_dir'].replace('\\', '/').rstrip('/')
m = re.match(r'^([A-Za-z]):(/.*)?$', s)   # C:\state -> /c/state (Git Bash); a POSIX path stays
print((f'/{m.group(1).lower()}{m.group(2) or ""}' if m else s) + '/' + a['watcher_subdir'], end='')
PY
}
if [ "${1:-}" = "adapter" ]; then find_adapter && { printf '%s\n' "$ADAPTER"; exit 0; }; echo "job.sh: no adapter.json found" >&2; exit 64; fi
ROOT="$(resolve_root)" || exit 64
# W10 (H2): ONE owner rule for scratch, lock, touch, unlock, holds, ctl and plain jobs; the watcher compares owners exactly (case-sensitive)
owner_ok() { printf '%s' "$2" | grep -Eq '^[a-z0-9][a-z0-9_-]{0,39}$' || { echo "job.sh $1: owner '$2' must match ^[a-z0-9][a-z0-9_-]{0,39}\$ (lower case: a job id like j18, or the session id); the watcher compares owners case-sensitively, so lower-case it" >&2; return 64; }; }
if [ "${1:-}" = "scratch" ]; then
  # J18 (J5 ledger row 31): PC experiments live in <state>/_scratch/<owner>/, the one place in the state folder an agent writes by hand
  owner="${2:-}"
  owner_ok scratch "$owner" || exit 64
  d="$(dirname "$ROOT")/_scratch/$owner"
  mkdir -p "$d" || { echo "job.sh scratch: cannot create $d" >&2; exit 1; }
  printf '%s
' "$d"; exit 0
fi
[ -d "$ROOT" ] || { echo "job.sh: watcher root $ROOT does not exist: is the watcher installed (harness/README.md)?" >&2; exit 64; }
# The control channel's folder is the proxy's dev.ctl_dir (J3 review 5, J12 fix 1c): from the game's mod ini (the adapter's config_files
# entry `mod_ini`, [dev] ctl_dir) when it sets one, else the game repo's registered default (registries/config_keys.jsonl); never guessed.
ctl_dir() {
  find_adapter || { echo "job.sh ctl: no adapter, so no mod ini to read dev.ctl_dir from" >&2; return 64; }
  python3 - "$ADAPTER" "$(own_root)" <<'PY'
import configparser, json, os, re, sys
from pathlib import Path
a = json.load(open(sys.argv[1], encoding='utf-8'))
own = sys.argv[2]
v, where = None, ''
ini = next((c['path'] for c in a.get('config_files', []) if c.get('id') == 'mod_ini'), None)
if ini and a.get('game_dir'):
    p = Path(os.path.expandvars(a['game_dir'])) / ini.replace('\\', '/')
    if p.is_file():
        cp = configparser.ConfigParser(interpolation=None, strict=False)
        cp.read_string(p.read_text(encoding='utf-8', errors='replace'))
        v, where = cp.get('dev', 'ctl_dir', fallback=None), str(p)
if not v and own:
    try:
        sys.path.insert(0, os.path.join(own, 'proxy', 'tools')); import layout
        reg = layout.game_root(Path(own)) / 'registries' / 'config_keys.jsonl'
        for line in reg.read_text(encoding='utf-8').splitlines():
            if line.strip() and json.loads(line).get('id') == 'dev.ctl_dir':
                v, where = json.loads(line).get('default'), f'{reg} (default)'
    except Exception:
        pass
if not v:
    sys.exit(f'job.sh ctl: dev.ctl_dir is not set in the mod ini and has no registered default: nowhere to send requests')
s = v.replace('\\', '/').rstrip('/')
m = re.match(r'^([A-Za-z]):(/.*)?$', s)
print((f'/{m.group(1).lower()}{m.group(2) or ""}' if m else s), end='')
PY
}
jget() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8")); print(d.get(sys.argv[2],""))' "$1" "$2"; }
utc() { date -u +%Y-%m-%dT%H:%M:%SZ; }
# one field of game.lock's line (owner=, session=): the first token with that name
lock_field() { [ -f "$ROOT/game.lock" ] && tr -d '\r' < "$ROOT/game.lock" | head -1 | tr ' ' '\n' | sed -n "s/^$1=//p" | head -1; }
lock_owner() { lock_field owner; }
lock_session() { lock_field session; }
now_ms() { local n; n="$(date +%s%N)"; echo $(( n / 1000000 )); }   # GNU date; W81: a lock --wait deadline in whole seconds ended up to 1 s early
lock_age() { local m; m="$(stat -c %Y "$ROOT/game.lock" 2>/dev/null)" || return 1; echo $(( $(date +%s) - m )); }
# H12: the stale age is the watcher's own setting (watcher.ini lock_stale_min, key=value lines; absent, unparsable or < 1 = 20)
stale_min() {
  local v=""
  [ -f "$ROOT/watcher.ini" ] && v="$(tr -d '\r' < "$ROOT/watcher.ini" | sed -n 's/^[[:space:]]*lock_stale_min[[:space:]]*=[[:space:]]*\([^[:space:]]*\)[[:space:]]*$/\1/p' | tail -1)"
  case "$v" in ''|*[!0-9]*) v=20;; esac
  [ "$v" -ge 1 ] 2>/dev/null || v=20
  echo "$v"
}
# 0 when the lock is held, fresh, and its owner or session is $1; else 2 with the one-line reason (and the command to take it) in HOLDS_WHY
holds_check() {
  local me="$1" cur cs age lim
  HOLDS_WHY=""
  if [ ! -f "$ROOT/game.lock" ]; then HOLDS_WHY="no game.lock is held: take it first with: job.sh lock $me <session> <purpose>"; return 2; fi
  cur="$(lock_owner)"; cs="$(lock_session)"; age="$(lock_age)" || age=0; lim=$(( $(stale_min) * 60 ))
  if [ "$cur" != "$me" ] && [ "$cs" != "$me" ]; then HOLDS_WHY="game.lock is held by '${cur:-another agent}' (session '${cs:-?}'), not '$me': take it first with: job.sh lock $me <session> <purpose> (or wait for it)"; return 2; fi
  if [ "$age" -ge "$lim" ]; then HOLDS_WHY="game.lock of '$cur' is stale (${age}s since its last refresh) and the watcher expires it: take it again with: job.sh lock $me <session> <purpose>"; return 2; fi
  return 0
}
cmd="${1:-}"
case "$cmd" in
  root) printf '%s\n' "$ROOT"; exit 0;;
  ctl)
    # The proxy's dev control channel (dev.ctl=1): <state>/ctl/<id>.cmd -> <id>.done (the game's proxy/README.md "Dev control channel";
    # core rules, the stale refusal and peek: docs/PROXY_CTL.md).
    # Blocks inside this one call until the result; exit 0 ok, 1 failed, 3 timeout (the proxy's own), 2 refused, 124 no answer.
    owner="${2:?ctl <owner> '<verb args>' [wait_s]}"; line="${3:?ctl <owner> '<verb args>' [wait_s]}"; w="${4:-100}"
    owner_ok ctl "$owner" || exit 64
    holds_check "$owner" || { echo "job.sh ctl: $HOLDS_WHY" >&2; exit 2; }
    C="$(ctl_dir)" || exit 64; mkdir -p "$C"
    id="$(printf '%s' "$owner" | tr -c 'A-Za-z0-9._-' '_')-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM$RANDOM"
    printf '%s\n' "$line" > "$C/$id.tmp" && mv "$C/$id.tmp" "$C/$id.cmd" || { echo "job.sh ctl: cannot write into $C" >&2; exit 1; }
    end=$(( $(date +%s) + w ))
    while [ ! -f "$C/$id.done" ] && [ "$(date +%s)" -lt "$end" ]; do sleep 0.5; done
    if [ ! -f "$C/$id.done" ]; then
      # Withdraw an unanswered request: the proxy runs every *.cmd it finds, so one left behind would fire into the NEXT launch (a stale
      # exit or reset; J3 review). The rename races the proxy's own rename to .cmd.taken and only one wins: if ours fails, it is running.
      if mv "$C/$id.cmd" "$C/$id.cmd.expired" 2>/dev/null; then
        echo "ctl $id: no result after ${w}s: is the game running with dev.ctl=1 and dev.ctl_dir=$C? Request withdrawn ($id.cmd.expired)." >&2
      else
        echo "ctl $id: no result after ${w}s, but the proxy took the request: its result will still land in $C/$id.done" >&2
      fi
      exit 124
    fi
    sleep 0.1; cat "$C/$id.done"
    s="$(jget "$C/$id.done" status)"
    case "$s" in ok) exit 0;; failed) exit 1;; timeout) exit 3;; refused) exit 2;; *) exit 124;; esac;;
  status)
    [ -f "$ROOT/watcher.alive" ] || { echo "no watcher.alive in $ROOT: the watcher has never run here" >&2; exit 1; }
    age=$(( $(date +%s) - $(stat -c %Y "$ROOT/watcher.alive") ))
    for i in 1 2 3 4 5; do python3 -c 'import json,sys; json.load(open(sys.argv[1],encoding="utf-8"))' "$ROOT/watcher.status" 2>/dev/null && break; sleep 0.2; done   # the file is replaced every 2 s
    cat "$ROOT/watcher.status"; echo
    [ "$age" -lt 15 ] && exit 0
    echo "watcher heartbeat is ${age}s old: the watcher is not running (after a reboot Liam waits for the logon task, or double-clicks src\\watch.cmd)" >&2; exit 1;;
  holds)
    owner="${2:?holds <owner>}"; owner_ok holds "$owner" || exit 64
    holds_check "$owner" || { echo "job.sh holds: $HOLDS_WHY" >&2; exit 2; }
    echo "game.lock is held by '$(lock_owner)' (session '$(lock_session)'): $owner holds it"; exit 0;;
  lock)
    shift; wait_s=0; pos=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --wait) wait_s="${2:?--wait S}"; shift 2;;
        *) pos+=("$1"); shift;;
      esac
    done
    case "$wait_s" in ''|*[!0-9]*) echo "job.sh lock: --wait needs a number of seconds" >&2; exit 64;; esac
    [ "$wait_s" -gt 100 ] && wait_s=100   # the Bash tool gives up at 120 s
    owner="${pos[0]:?lock [--wait S] <owner|-> <session> <purpose> [hang_s]}"; session="${pos[1]:?session}"; purpose="${pos[2]:?purpose}"; hang="${pos[3]:-}"
    [ "$owner" = "-" ] && owner="$session"   # the owner is the session id
    owner_ok lock "$owner" || exit 64
    lim=$(( $(stale_min) * 60 ))
    LOCK_WHY=""
    # One attempt: 0 = taken (the lock is ours), 2 = refused (why in LOCK_WHY).
    lock_attempt() {
      local line cur cs age seen_line moved dest moved_age m
      line="owner=${owner//[$'\r\n']/_} session=${session//[$'\r\n']/_} purpose=${purpose//[$'\r\n']/ } started=$(utc)"
      [ -n "$hang" ] && line="$line hang_s=$hang"
      # J2 L3: an exclusive create (noclobber, O_EXCL), so two agents taking a free lock in the same second cannot both win.
      create() { ( set -o noclobber; printf '%s\n' "$line" > "$ROOT/game.lock" ) 2>/dev/null; }
      create && return 0
      cur="$(lock_owner)"; cs="$(lock_session)"
      if [ -n "$cur" ] && [ "$cur" = "$owner" ] && [ "$cs" = "$session" ]; then   # our own lock (the pair): rewritten in place
        printf '%s\n' "$line" > "$ROOT/game.lock.tmp" && mv "$ROOT/game.lock.tmp" "$ROOT/game.lock" || { LOCK_WHY="cannot rewrite game.lock"; return 2; }
        return 0
      fi
      age="$(lock_age)" || { LOCK_WHY="game.lock changed while it was read (just taken or released): refused"; return 2; }
      # someone else's lock (or one being written this instant: no owner yet) is only ever moved aside when it is stale
      if [ "$age" -lt "$lim" ]; then
        if [ -n "$cur" ] && [ "$cur" = "$owner" ]; then LOCK_WHY="game.lock is held by '$cur' under another session ('${cs:-?}', refreshed ${age}s ago), not '$session': refused (the holder is the pair owner+session)"
        else LOCK_WHY="game.lock is held by '${cur:-another agent}' (refreshed ${age}s ago): refused"; fi
        return 2
      fi
      # B20: both takers take the same three steps: read the lock (line), move it aside to a unique name, then check what was moved: the
      # same line AND still older than the stale limit (touch changes the mtime, not the line). If not, put it back (mv -n never overwrites).
      seen_line="$(tr -d '\r' < "$ROOT/game.lock" | head -1)"
      if [ "${JOB_SH_TEST:-}" = "1" ] && [ -n "${JOB_SH_TEST_HOOK:-}" ]; then eval "$JOB_SH_TEST_HOOK"; fi   # test seam: runs once, between the read and the move
      mkdir -p "$ROOT/_to_delete"
      dest="$ROOT/_to_delete/game.lock.stale_${cur:-unknown}_$(date -u +%Y%m%dT%H%M%SZ)_$$"
      mv "$ROOT/game.lock" "$dest" 2>/dev/null || { LOCK_WHY="game.lock was refreshed or taken at the same moment: refused (job.sh status, then retry)"; return 2; }
      moved="$(tr -d '\r' < "$dest" 2>/dev/null | head -1)"; moved_age=0
      m="$(stat -c %Y "$dest" 2>/dev/null)" && moved_age=$(( $(date +%s) - m ))   # unreadable = cannot be verified = not the stale one
      if [ ! -e "$dest" ]; then LOCK_WHY="game.lock was refreshed or taken at the same moment: refused (the lock moved aside vanished; job.sh status, then retry)"; return 2; fi
      if [ "$moved" != "$seen_line" ] || [ "$moved_age" -lt "$lim" ]; then
        mv -n "$dest" "$ROOT/game.lock" 2>/dev/null
        if [ -e "$dest" ]; then echo "job.sh lock: the lock moved aside was not the stale one read and the name game.lock was taken meanwhile: it stays in $dest" >&2
        else echo "job.sh lock: the lock moved aside was refreshed or replaced after it was read: put back" >&2; fi
        LOCK_WHY="game.lock was refreshed or taken at the same moment: refused (job.sh status, then retry)"; return 2
      fi
      create && return 0
      LOCK_WHY="game.lock was taken by another agent at the same moment: refused (job.sh status, then retry)"; return 2
    }
    end_ms=$(( $(now_ms) + wait_s * 1000 ))
    while :; do
      if lock_attempt; then
        echo "game.lock taken: $(lock_field owner) session=$session  (refresh at least every $(( ($(stale_min) + 1) / 2 )) min with: job.sh touch $owner; the watcher expires it after $(stale_min) min)"; exit 0
      fi
      left_ms=$(( end_ms - $(now_ms) ))
      if [ "$left_ms" -le 0 ]; then
        echo "$LOCK_WHY" >&2
        [ "$wait_s" -gt 0 ] && { echo "job.sh lock: no lock after ${wait_s}s" >&2; exit 124; }
        exit 2
      fi
      [ "$left_ms" -gt 2000 ] && left_ms=2000   # poll every 2 s while time remains; the last sleep is only what is left
      sleep "$(printf '%d.%03d' $(( left_ms / 1000 )) $(( left_ms % 1000 )))"
    done;;
  touch)
    owner="${2:-}"
    [ -n "$owner" ] || { echo "job.sh touch: needs the owner: touch <owner> (a bare touch would refresh anyone's lock)" >&2; exit 64; }
    owner_ok touch "$owner" || exit 64
    [ -f "$ROOT/game.lock" ] || { echo "no game.lock to refresh" >&2; exit 2; }
    cur="$(lock_owner)"; cs="$(lock_session)"
    if [ "$cur" != "$owner" ] && [ "$cs" != "$owner" ]; then echo "game.lock belongs to '$cur' (session '$cs'), not '$owner': not refreshed" >&2; exit 2; fi
    touch "$ROOT/game.lock" && echo "game.lock refreshed"; exit 0;;
  vdisplay-aside)
    # W35 (C35): move a stale vdisplay_restore.json aside (the one-off ask of the first consumer's J10 and J44 reports), only when the
    # files say the watcher cannot restore it: it exists; the lock is free or <owner>'s (holds_check); the watcher runs and its status
    # lists no game process; and its own restore failed or dropped it (the last "vdisplay: " line of watcher.log, at or after the file's
    # time) or the file is older than the lock's stale limit. Prints the saved mode; never deletes, never writes the display mode (only
    # the watcher's pump does) and overwrites nothing (a unique name, mv -n, checked as lock expiry is). No watcher change.
    owner="${2:-}"; session="${3:-}"; why="${4:-}"
    { [ -n "$owner" ] && [ -n "$session" ]; } || { echo "job.sh vdisplay-aside: usage: vdisplay-aside <owner|-> <session> <why>" >&2; exit 64; }
    [ "$owner" = "-" ] && owner="$session"
    owner_ok vdisplay-aside "$owner" || exit 64
    [ -n "${why// /}" ] || { echo "job.sh vdisplay-aside: refused: say why (the third argument): the record keeps it" >&2; exit 64; }
    F="$ROOT/vdisplay_restore.json"
    [ -f "$F" ] || { echo "job.sh vdisplay-aside: refused: no vdisplay_restore.json in $ROOT: nothing to move (the watcher restored or dropped it)" >&2; exit 2; }
    if [ -f "$ROOT/game.lock" ]; then holds_check "$owner" || { echo "job.sh vdisplay-aside: refused: $HOLDS_WHY" >&2; exit 2; }; fi
    alive=99; [ -f "$ROOT/watcher.alive" ] && alive=$(( $(date +%s) - $(stat -c %Y "$ROOT/watcher.alive") ))
    [ "$alive" -lt 15 ] || { echo "job.sh vdisplay-aside: refused: the watcher is not running (job.sh status), so its status cannot say no game runs: start the watcher, which then restores the mode itself" >&2; exit 2; }
    games=""
    for _ in 1 2 3 4 5; do   # watcher.status is replaced every 2 s: a read mid-swap is retried
      games="$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1],encoding="utf-8-sig")); g=d.get("game_state") or {}; print(len(d.get("processes") or []) + (1 if g.get("pid") else 0))' "$ROOT/watcher.status" 2>/dev/null)" && break
      games=""; sleep 0.2
    done
    [ -n "$games" ] || { echo "job.sh vdisplay-aside: refused: watcher.status is unreadable, so whether a game runs is unknown: retry, or job.sh status" >&2; exit 2; }
    [ "$games" = 0 ] || { echo "job.sh vdisplay-aside: refused: a game process runs (watcher.status): kill it through the watcher first; its exit lets the watcher restore the mode" >&2; exit 2; }
    fmt=$(stat -c %Y "$F"); age=$(( $(date +%s) - fmt )); lim=$(( $(stale_min) * 60 )); because=""
    last="$(grep -a 'vdisplay: ' "$ROOT/watcher.log" 2>/dev/null | tail -1 | tr -d '\r')"
    case "$last" in
      *"vdisplay: RESTORE FAILED"*|*"the RESTORE FAILED above repeated"*|*"vdisplay: pending restore dropped"*)
        ts="$(printf '%s' "$last" | sed -n 's/^\[\([^]]*\)\].*/\1/p')"; t="$(date -u -d "$ts" +%s 2>/dev/null || echo 0)"
        [ "$t" -ge $(( fmt - 2 )) ] && because="the watcher's last vdisplay line: $last";;
    esac
    [ -z "$because" ] && [ "$age" -ge "$lim" ] && because="the file is ${age}s old (the lock's stale limit is ${lim}s)"
    [ -n "$because" ] || { echo "job.sh vdisplay-aside: refused: the watcher's restore is still pending (the file is ${age}s old and the last vdisplay line of watcher.log is not a failure): let the watcher restore it (release the lock; it retries every 60 s), or wait for the stale limit (${lim}s)" >&2; exit 2; }
    mode="$(tr -d '\r' < "$F" | tr '\n' ' ' | sed 's/  */ /g; s/ $//')"
    stamp="$(date -u +%Y%m%dT%H%M%SZ)"; mkdir -p "$ROOT/_to_delete"; dest=""
    for i in "" $(seq 2 50 | sed 's/^/_/'); do
      d="$ROOT/_to_delete/vdisplay_restore_${stamp}${i}.json.aside"
      [ -e "$d" ] && continue
      mv -n "$F" "$d" 2>/dev/null
      if [ -e "$d" ] && [ ! -e "$F" ]; then dest="$d"; break; fi
      [ -e "$F" ] || { echo "job.sh vdisplay-aside: refused: vdisplay_restore.json vanished meanwhile (the watcher restored or dropped it): nothing moved" >&2; exit 2; }
    done
    [ -n "$dest" ] || { echo "job.sh vdisplay-aside: refused: no free name in _to_delete for $stamp: nothing moved, retry" >&2; exit 2; }
    rec="job.sh vdisplay-aside: moved vdisplay_restore.json to _to_delete\\$(basename "$dest") (owner $owner, session $session): $why; because $because; saved mode: $mode"
    printf '[%s] %s\r\n' "$(utc)" "$rec" >> "$ROOT/watcher.log" 2>/dev/null || echo "job.sh vdisplay-aside: watcher.log could not be appended: the record is this output" >&2
    echo "vdisplay_restore.json moved aside (never deleted) to $dest"
    echo "saved mode: $mode"
    echo "because: $because"
    echo "the next launch that needs another size saves the mode again; the display itself was not changed"; exit 0;;
  unlock)
    owner="${2:?unlock <owner> [--force]}"; owner_ok unlock "$owner" || exit 64
    [ -f "$ROOT/game.lock" ] || { echo "no game.lock held"; exit 0; }
    cur="$(lock_owner)"; cs="$(lock_session)"
    if [ "$cur" != "$owner" ] && [ "$cs" != "$owner" ] && [ "${3:-}" != "--force" ]; then echo "game.lock belongs to '$cur' (session '$cs'), not '$owner': refused (--force overrides)" >&2; exit 2; fi
    mkdir -p "$ROOT/_to_delete"
    mv "$ROOT/game.lock" "$ROOT/_to_delete/game.lock.released_${cur:-unknown}_$(date -u +%Y%m%dT%H%M%SZ)" && echo "game.lock released (the watcher restores an active profile by itself once the game is closed)"; exit 0;;
esac
owner="${1:-}"; file="${2:-}"; t="${3:-100}"
[ -n "$owner" ] && [ -n "$file" ] || { sed -n '2,4p' "$0"; exit 64; }
owner_ok job "$owner" || exit 64
safe="$(printf '%s' "$owner" | tr -c 'A-Za-z0-9._-' '_')"
J="$ROOT/jobs"; mkdir -p "$J"
id="$safe-$(date -u +%Y%m%dT%H%M%SZ)-$RANDOM$RANDOM"
body="$(mktemp)"; trap 'rm -f "$body"' EXIT
if [ "$file" = "-" ]; then cat > "$body"; else cp "$file" "$body" || exit 1; fi
nonempty="$(grep -c '[^[:space:]]' "$body" || true)"
first="$(grep -m1 '[^[:space:]]' "$body" | tr -d '\r' | sed 's/^[[:space:]]*//')"
case "$first" in
  launch*|kill*|profile*)
    if [ "$nonempty" -eq 1 ] && ! printf '%s' "$first" | grep -q 'owner='; then printf '%s owner=%s\n' "$first" "$owner" > "$body"; fi;;
  *)
    if [ "$nonempty" -ne 1 ] || ! printf '%s' "$first" | grep -Eq '^(launch|kill|profile|restart|update|status|noop)\b'; then
      grep -q '^[[:space:]]*#job\b.*\bowner=' "$body" || { { printf '#job owner=%s\n' "$owner"; cat "$body"; } > "$body.new" && mv "$body.new" "$body"; }
    fi;;
esac
cp "$body" "$J/$id.tmp" && mv "$J/$id.tmp" "$J/$id.request" || { echo "job.sh: cannot submit into $J" >&2; exit 1; }
end=$(( $(date +%s) + t ))
while [ ! -f "$J/$id.done" ] && [ "$(date +%s)" -lt "$end" ]; do sleep 1; done
if [ ! -f "$J/$id.done" ]; then
  # H11: withdraw an unanswered request as the ctl path does (the watcher lists *.request only, so a .request.expired is never run). The rename
  # races the watcher's own pickup and only one wins: if ours fails, the watcher took it and the result will still land.
  if mv "$J/$id.request" "$J/$id.request.expired" 2>/dev/null; then
    echo "job $id: no result after ${t}s. Check: job.sh status   (heartbeat, current_job, queue). Request withdrawn ($id.request.expired); resubmit with a longer wait, run in the background, if the job is slow." >&2
  else
    echo "job $id: no result after ${t}s, but the watcher took the request: its result will still land in $J/$id.done (and $id.out)" >&2
  fi
  exit 124
fi
sleep 0.2   # .done is written last and atomically; .out is already complete
[ -f "$J/$id.out" ] && cat "$J/$id.out"
s="$(jget "$J/$id.done" status)"; e="$(jget "$J/$id.done" exit)"; reason="$(jget "$J/$id.done" reason)"
echo "[job $id: $s exit=$e${reason:+ - $reason}]" >&2
case "$s" in
  ok) exit 0;;
  failed) if [ "$e" -ge 1 ] 2>/dev/null && [ "$e" -le 255 ]; then exit "$e"; else exit 1; fi;;
  refused) exit 2;;
  *) exit 124;;
esac
