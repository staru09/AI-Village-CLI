import re

HYPHENS = str.maketrans({'‐': '-', '‑': '-', '–': '-'})
HANDLE = re.compile(r'(?<![\w.])@([\w.-]+)')


def extractor(agents, humans):
    """agents: {id: name}; humans: lowercase handles. Returns mentions(text, src) -> {dst: kind}."""
    # ponytail: exact full names only; short forms ("Opus", "Gemini") are ambiguous across versions and skipped.
    lookup = {n.translate(HYPHENS).lower(): i for i, n in agents.items()}
    alt = '|'.join(re.escape(n) for n in sorted(lookup, key=len, reverse=True))  # longest name wins
    rx = re.compile(rf'(@)?(?<![\w./-])({alt})(?![\w-]|\.\d)', re.I)  # GPT-5 must not eat GPT-5.1

    def mentions(text, src):
        text, out = text.translate(HYPHENS), {}
        for m in rx.finditer(text):
            dst = lookup[m[2].lower()]
            if dst != src and out.get(dst) != 'addressed':
                out[dst] = 'addressed' if m[1] else 'named'
        if src != 'human':
            # ponytail: only single-token display names are reachable via @handle.
            if any(h.rstrip('.-').lower() in humans for h in HANDLE.findall(rx.sub(' ', text))):
                out['human'] = 'addressed'
        return out
    return mentions
