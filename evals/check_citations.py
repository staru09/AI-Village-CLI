"""Check a ground-truth file's citations against the database: does each quote really appear in the record it cites?

    python3 evals/check_citations.py FILE.json [FILE.json ...]      # reads village.db next to the repo root

A ground-truth file holds {"question", "answer", "reasoning", "findings": [{"claim", "kind", "citations":
[{"ref", "field", "quote"}]}], ...}. For every citation this looks the ref up and searches the record's text for the
quote: exactly, then with whitespace collapsed (tables print texts on one line). It writes `quote_ok` (true/false) and,
when the ref does not exist, `missing` into each citation, saves the file, and prints what failed.
"""
import json, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from village_graph.core import KINDS, REF  # noqa: E402

TEXT = {'m': ('content', 'reasoning'), 't': ('action', 'output', 'error', 'reasoning'), 's': ('short', 'goal'),
        'e': ('text', 'reasoning'), 'k': ('added',), 'r': ('content',)}
squash = lambda s: ' '.join((s or '').replace('«', '').replace('»', '').split())


def record(con, ref):
    """A ref -> the record's texts joined, or None when it does not exist (or is ambiguous)."""
    m = REF.fullmatch(ref.strip().strip('[]'))
    if not m:
        return None
    kind, h = m.groups()
    p = h if h.startswith('toolu_') else f'{h[:8]}-{h[8:]}'
    rows = con.execute(f"SELECT {', '.join(TEXT[kind])} FROM {KINDS[kind]} WHERE id >= ? AND id < ? LIMIT 2", (p, p + '~')).fetchall()
    return '\n'.join(x or '' for x in rows[0]) if len(rows) == 1 else None


def check(con, path):
    d = json.loads(Path(path).read_text())
    bad, n = [], 0
    for f in d.get('findings', []):
        for c in f.get('citations', []):
            n += 1
            text = record(con, c.get('ref', ''))
            c.pop('missing', None)
            if text is None:
                c['quote_ok'], c['missing'] = False, True
            else:
                q = c.get('quote') or ''
                c['quote_ok'] = bool(q.strip()) and (q in text or squash(q) in squash(text))
            if not c['quote_ok']:
                bad.append((c.get('ref'), 'no such record' if c.get('missing') else 'quote not in the record', (c.get('quote') or '')[:90]))
        f['verified'] = bool(f.get('citations')) and all(c['quote_ok'] for c in f['citations'])
    Path(path).write_text(json.dumps(d, ensure_ascii=False, indent=1))
    ok = sum(f['verified'] for f in d.get('findings', []))
    print(f"{Path(path).name}: {n - len(bad)} of {n} citations found in their records; {ok} of {len(d.get('findings', []))} findings fully cited")
    for b in bad:
        print('   ✗', *b)
    return not bad


def main():
    con = sqlite3.connect(f'file:{ROOT / "village.db"}?mode=ro', uri=True)
    sys.exit(0 if all([check(con, p) for p in sys.argv[1:]]) else 1)


if __name__ == '__main__':
    main()
