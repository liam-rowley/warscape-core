"""One search across every registry (the repo's, plus the core's tools when run from a game repo).

Every word must match (prefix match per token; the last word may be partial); when nothing matches all words, any-word matches are
shown with a note. Hits in id, purpose, description, claim or when weigh more; live tools rank first; superseded tools are hidden
unless asked. (Ranking rules carried from empire-remastered `assets/find.py`.)
"""
import re

WORD = re.compile(r'[^\W_]+')
STRONG = ('id', 'purpose', 'description', 'claim', 'when', 'action', 'binding')
SUMMARY = ('purpose', 'description', 'claim', 'action', 'role')


def _flat(v):
    if isinstance(v, dict):
        return ' '.join(f'{k} {_flat(x)}' for k, x in v.items())
    if isinstance(v, list):
        return ' '.join(_flat(x) for x in v)
    return '' if v is None else str(v)


def _tokens(s):
    return WORD.findall(s.casefold())


def score_row(row, words):
    """(matched word count, score)."""
    strong = set(_tokens(' '.join(_flat(row.get(k)) for k in STRONG)))
    weak = set(_tokens(_flat(row)))
    hit, score = 0, 0.0
    for w in words:
        exact_s, pre_s = w in strong, any(t.startswith(w) for t in strong)
        exact_w, pre_w = w in weak, any(t.startswith(w) for t in weak)
        if not (pre_s or pre_w):
            continue
        hit += 1
        score += (3 if pre_s else 1) * (2 if (exact_s or exact_w) else 1)
    return hit, score


def search(regs, text, only=None, include_superseded=False, limit=20):
    """regs: list of Registry. Returns (hits, note) with hits = [(score, registry label, row)], best first."""
    words = _tokens(text)
    if not words:
        return [], 'no search words'
    pool = []
    for reg in regs:
        if only and reg.name not in only and reg.label not in only:
            continue
        for r in reg.rows:
            st = str(r.get('status', ''))
            if st.startswith('superseded') and not include_superseded:
                continue
            pool.append((reg, r, st))
    def run(need_all):
        out = []
        for reg, r, st in pool:
            hit, sc = score_row(r, words)
            if hit and (hit == len(words) or not need_all):
                sc += 1.5 if st == 'live' else -3 if st.startswith('superseded') else 0
                out.append((sc + hit * 10, reg.label, r))
        return sorted(out, key=lambda x: (-x[0], x[1], str(x[2].get('id'))))
    hits, note = run(True), ''
    if not hits and len(words) > 1:
        hits = run(False)
        note = 'no row matches every word: showing rows matching any word' if hits else ''
    return hits[:limit], note


def summary(row):
    for k in SUMMARY:
        if row.get(k):
            return str(row[k])
    return next((str(v) for k, v in row.items() if k != 'id' and isinstance(v, str) and v), '')


def format_hit(label, row):
    st = row.get('status')
    head = f'{label:<14} {row.get("id")}' + (f'  [{st}]' if st else '')
    lines = [head, f'    {summary(row)[:160]}']
    if row.get('usage'):
        lines.append(f'    usage: {row["usage"][:160]}')
    if row.get('when'):
        lines.append(f'    when:  {row["when"][:160]}')
    if row.get('path') and label.endswith('tools'):
        lines.append(f'    path:  {row["path"]}')
    return '\n'.join(lines)
