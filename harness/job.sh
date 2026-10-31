#!/usr/bin/env bash
# purpose: agent helper on the PC (Git Bash): submit a watcher job, block inside ONE call until its result (or a timeout), print the output, return the job's exit code (refused 2, no answer 124); also take, refresh and release the game lock
# usage: job.sh [--adapter FILE] <owner> <file|-> [timeout_s]  |  job.sh adapter  |  job.sh [--adapter FILE] lock <owner> <session> <purpose> [hang_s]  |  touch  |  unlock <owner> [--force]  |  status  |  root  |  scratch <owner>  |  ctl <owner> '<verb args>' [wait_s]
# when: every time an agent runs something on the PC (launch, kill, profile, scripts): the watcher root comes from the adapter (state_dir + watcher_subdir), never a default path; waiting belongs here, not in repeated agent calls
# not-a-verb: a bash helper agents call directly from Git Bash (python3 only reads JSON); the PC side of the protocol is harness/core/watcher.ps1
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
if [ "${1:-}" = "scratch" ]; then
  # J18 (J5 ledger row 31): PC experiments live in <state>/_scratch/<owner>/, the one place in the state folder an agent writes by hand
  owner="${2:-}"
  printf '%s' "$owner" | grep -Eq '^[a-z0-9][a-z0-9_-]{0,31}$' || { echo "job.sh scratch: owner '$owner' must match ^[a-z0-9][a-z0-9_-]{0,31}\$ (a job id like j18)" >&2; exit 64; }
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
lock_owner() { [ -f "$ROOT/game.lock" ] && tr -d '\r' < "$ROOT/game.lock" | head -1 | sed -n 's/.*\bowner=\([^ ]*\).*/\1/p'; }
lock_age() { echo $(( $(date +%s) - $(stat -c %Y "$ROOT/game.lock") )); }
cmd="${1:-}"
case "$cmd" in
  root) printf '%s\n' "$ROOT"; exit 0;;
  ctl)
    # The proxy's dev control channel (dev.ctl=1): <state>/ctl/<id>.cmd -> <id>.done (proxy/README.md "Dev control channel").
    # Blocks inside this one call until the result; exit 0 ok, 1 failed, 3 timeout (the proxy's own), 2 refused, 124 no answer.
    owner="${2:?ctl <owner> '<verb args>' [wait_s]}"; line="${3:?ctl <owner> '<verb args>' [wait_s]}"; w="${4:-170}"
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
  lock)
    owner="${2:?lock <owner> <session> <purpose> [hang_s]}"; session="${3:?session}"; purpose="${4:?purpose}"; hang="${5:-}"
    if [ -f "$ROOT/game.lock" ]; then
      cur="$(lock_owner)"; age="$(lock_age)"
      if [ -n "$cur" ] && [ "$cur" != "$owner" ] && [ "$age" -lt 1200 ]; then echo "game.lock is held by '$cur' (refreshed ${age}s ago): refused" >&2; exit 2; fi
    fi
    line="owner=${owner//[$'\r\n']/_} session=${session//[$'\r\n']/_} purpose=${purpose//[$'\r\n']/ } started=$(utc)"
    [ -n "$hang" ] && line="$line hang_s=$hang"
    # J2 L3: an exclusive create (noclobber, O_EXCL), so two agents taking a free lock in the same second cannot both win. Our own lock is
    # rewritten in place; a stale one is first moved aside, a rename only one taker can win, then created exclusively.
    create() { ( set -o noclobber; printf '%s\n' "$line" > "$ROOT/game.lock" ) 2>/dev/null; }
    taken() { echo "game.lock taken: $line  (refresh at least every 10 min with: job.sh touch; the watcher expires it after 20 min)"; exit 0; }
    create && taken
    cur="$(lock_owner)"
    if [ -n "$cur" ] && [ "$cur" = "$owner" ]; then
      printf '%s\n' "$line" > "$ROOT/game.lock.tmp" && mv "$ROOT/game.lock.tmp" "$ROOT/game.lock" || exit 1; taken
    fi
    # someone else's lock (or one being written this instant: no owner yet) is only ever moved aside when it is stale
    if [ -f "$ROOT/game.lock" ] && [ "$(lock_age)" -lt 1200 ]; then echo "game.lock is held by '${cur:-another agent}' (just taken): refused" >&2; exit 2; fi
    mkdir -p "$ROOT/_to_delete"
    mv "$ROOT/game.lock" "$ROOT/_to_delete/game.lock.stale_${cur:-unknown}_$(date -u +%Y%m%dT%H%M%SZ)_$$" 2>/dev/null && create && taken
    echo "game.lock was taken by another agent at the same moment: refused (job.sh status, then retry)" >&2; exit 2;;
  touch)
    [ -f "$ROOT/game.lock" ] || { echo "no game.lock to refresh" >&2; exit 2; }
    touch "$ROOT/game.lock" && echo "game.lock refreshed"; exit 0;;
  unlock)
    owner="${2:?unlock <owner> [--force]}"
    [ -f "$ROOT/game.lock" ] || { echo "no game.lock held"; exit 0; }
    cur="$(lock_owner)"
    if [ "$cur" != "$owner" ] && [ "${3:-}" != "--force" ]; then echo "game.lock belongs to '$cur', not '$owner': refused (--force overrides)" >&2; exit 2; fi
    mkdir -p "$ROOT/_to_delete"
    mv "$ROOT/game.lock" "$ROOT/_to_delete/game.lock.released_${cur:-unknown}_$(date -u +%Y%m%dT%H%M%SZ)" && echo "game.lock released (the watcher restores an active profile by itself once the game is closed)"; exit 0;;
esac
owner="${1:-}"; file="${2:-}"; t="${3:-900}"
[ -n "$owner" ] && [ -n "$file" ] || { sed -n '2,4p' "$0"; exit 64; }
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
  echo "job $id: no result after ${t}s. Check: job.sh status   (heartbeat, current_job, queue). The request stays queued." >&2
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
