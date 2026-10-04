"""village: ask the AI Village dataset. `village -h` lists the commands; README.md and USAGE.md explain them."""
import argparse, io, json, shlex, sys, time
from contextlib import redirect_stderr, redirect_stdout

from . import commands, db, evidence
from .core import connect

MENTIONS = ('pair', 'neighbors', 'top-pairs', 'hubs', 'families', 'agents', 'examples', 'ignored', 'replies')
LLM = ('label', 'labels', 'verdict', 'check', 'look', 'ask', 'eval')
SPENDS = ('label', 'check', 'look', 'ask', 'eval')  # these call a model: they cost money
EPILOG = '''Start with `goals`, then `overview --goal N`. Every row has a ref (m: chat, t: action, s: session, e: event, k: memory,
r: recap): open it with `show REF`. Trust: actions, outputs, errors and events are recorded by the system (ground truth);
chat, reasoning, session goals and memories are the agents' own words (claims); recaps are secondary. Times are Pacific.'''


def parser():
    ap = argparse.ArgumentParser(prog='village', description='Evidence from the AI Village dataset: who did, said and claimed what.',
                                 epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--json', action='store_true', help='print the result as JSON')
    sub = ap.add_subparsers(dest='cmd', required=True, metavar='command')

    b = sub.add_parser('build', help='rebuild village.db from the dataset (chat: full history; actions and memories: a window)')
    b.add_argument('--days', type=int, help='actions and memories for the last N days (default 7)')
    b.add_argument('--goal', action='append', help='… for the village goal whose text contains this (repeatable)')
    b.add_argument('--since', help='… from this Pacific date')
    b.add_argument('--until', help='… up to this Pacific date (exclusive)')
    b.add_argument('--all', action='store_true', help='… for the whole history (several GB, about an hour)')

    def scope(limit=20):  # the scope flags. A fresh parser per command: argparse shares a parent's options, defaults included
        f = argparse.ArgumentParser(add_help=False)
        g = f.add_argument_group('scope (Pacific time)')
        g.add_argument('--goal', help='one village goal: its number in `goals`, or part of its text')
        g.add_argument('--day', type=int, help='one village day by number, e.g. 407')
        g.add_argument('--date', help='one day, YYYY-MM-DD')
        g.add_argument('--since', help='from this date or "YYYY-MM-DD HH:MM"')
        g.add_argument('--until', help='up to this date or time (exclusive)')
        f.add_argument('--limit', type=int, default=limit, help='maximum rows (default %(default)s)')
        f.add_argument('--wide', action='store_true', help='whole texts instead of cut ones')
        f.add_argument('--json', action='store_true', default=argparse.SUPPRESS, help=argparse.SUPPRESS)
        return f

    def mentions(samples=5):
        m = argparse.ArgumentParser(add_help=False)
        m.add_argument('--room', help='only mentions in this chat room')
        m.add_argument('--kind', choices=['addressed', 'named'], help='only @mentions, or only plain name mentions')
        m.add_argument('--samples', type=int, default=samples, help='sample messages shown under the result (0 = off, default %(default)s)')
        return m

    who = argparse.ArgumentParser(add_help=False)
    who.add_argument('--agent', help='only this agent (any unique part of its name)')

    def add(name, help, limit=20, also=(), scoped=True):
        return sub.add_parser(name, parents=[*([scope(limit)] if scoped else []), *also], help=help, description=help)

    # orient
    add('goals', 'the village goals with their dates, days and sizes', 100)
    add('overview', 'what is in a scope: the goals, rooms, and per agent its messages, sessions, actions, failures')
    add('recap', "AI Digest's own daily recap or goal story (secondary: where to look, never evidence)", 5)
    add('schema', 'tables, columns, row counts and what part of the history is loaded')
    # search
    p = add('find', 'full-text search across chat, actions, outputs, reasoning, session goals, memory and events', also=[who])
    p.add_argument('text', help='words (all must match), "a phrase", OR, prefix*')
    p.add_argument('--in', dest='where', help=f'fields, comma-separated: {", ".join(evidence.FIELDS)} (default: all but said-why, error, recap)')
    p.add_argument('--order', choices=['rank', 'time'], default='rank', help='best match first (default) or oldest first')
    p.add_argument('--words', type=int, default=24, help='snippet length in words (default %(default)s, max 64)')
    p = add('count', 'count a regular expression per agent, model, maker, day or room, as a rate per 1,000 words', 100, [who])
    p.add_argument('pattern')
    p.add_argument('--in', dest='where', help='fields to count in (default chat)')
    p.add_argument('--by', choices=['agent', 'model', 'maker', 'day', 'room', 'all'], default='agent')
    p.add_argument('--case', action='store_true', help='match case (default: ignore case)')
    p = add('terms', 'words and names first used in chat inside the scope (coined terms), most widely adopted first', 40, [who])
    p.add_argument('--min-agents', type=int, default=2)
    p.add_argument('--min-uses', type=int, default=5)
    add('first-use', 'who used a term in chat first, and who picked it up when', 60).add_argument('text')
    # read
    p = add('show', 'one or more records in full, by ref')
    p.add_argument('refs', nargs='+')
    p.add_argument('--context', type=int, default=0, metavar='N', help='also the N records before and after')
    add('sessions', "computer sessions: each one's stated goal, actions, commands, failures", 60, [who])
    p = add('session', 'one session as a chain: goals, stated intent, every action with its result, and the self-report that closed it', 70)
    p.add_argument('ref', help='a session ref (s:…) or any action ref (t:…) inside it')
    p = add('timeline', "one agent's chat, actions, session goals, events and memory updates, interleaved in time", 80)
    p.add_argument('name', metavar='agent')
    p.add_argument('--kinds', help='comma-separated: chat, heard, intent, action (or bash, gui, other), event, memory (default: all but heard)')
    p.add_argument('--session', help='only this session (ref)')
    add('said', 'thought vs said: an agent\'s chat messages next to the reasoning recorded just before each').add_argument('name', metavar='agent')
    p = add('memory', "an agent's own notes at the end of the scope, or with --diff what each rewrite added")
    p.add_argument('name', metavar='agent')
    p.add_argument('--diff', action='store_true', help='list the versions in scope with the lines each added')
    p.add_argument('--grep', help='only the lines matching this regular expression')
    p = add('shot', "where an action's screenshot is; --save writes the PNG (see also `look`)")
    p.add_argument('ref')
    p.add_argument('--save', metavar='PATH')
    add('sql', 'one read-only SELECT over the database (see `schema`)', 100).add_argument('query')

    # who talks to whom
    p = add('pair', 'how often A and B mention each other, both directions, over time', also=[mentions()])
    p.add_argument('a'); p.add_argument('b')
    p.add_argument('--by', choices=['day', 'month'], default='day')
    add('neighbors', 'who A mentions and is mentioned by', also=[mentions()]).add_argument('a')
    add('top-pairs', 'the strongest pairs by mentions', also=[mentions()])
    add('hubs', 'agents with the most distinct partners', also=[mentions()])
    p = add('families', "do agents mention their own maker's models more than chance? per family, or per village goal", 100, [mentions(0)])
    p.add_argument('--by', choices=['family', 'goal'], default='family')
    add('agents', 'roster: model, messages sent, partners, first and last message', 100, [mentions()])
    p = add('examples', 'the messages behind A -> B, newest first', 10, [mentions()])
    p.add_argument('a'); p.add_argument('b')
    add('ignored', 'one-sided pairs: A mentions B, B rarely mentions A back', also=[mentions()])
    p = add('replies', 'when @-mentioned, how often and how fast each agent posts next', also=[mentions()])
    p.add_argument('a', nargs='?', help='break one agent down by who asked')
    p.add_argument('--within', type=int, default=10, help='minutes to count as a reply (default 10)')

    # with a model (needs ANTHROPIC_API_KEY and `uv sync --extra llm`)
    p = add('label', 'apply a rubric to every session, message or action in scope with a model; stores label, quote and evidence', also=[who])
    p.add_argument('rubric', help='a rubric name in rubrics/, or a path to a rubric file')
    p.add_argument('--match', help='only units whose text matches this search (as in `find`)')
    p.add_argument('--within', metavar='RUBRIC=LABEL', help='only units another rubric gave this label')
    p.add_argument('--refs', help='only these refs, comma-separated')
    p.add_argument('--model', help='default: $VILLAGE_LABEL_MODEL or claude-haiku-4-5')
    p.add_argument('--redo', action='store_true', help='label again what is already labelled')
    p.add_argument('--yes', action='store_true', help='allow more than 500 units in one run')
    p = add('labels', 'what a rubric found: counts per agent, model, maker or day with their base, or the labelled rows', also=[who])
    p.add_argument('rubric', nargs='?', help='omit to list the rubrics with stored labels')
    p.add_argument('--by', choices=['agent', 'model', 'maker', 'day', 'all'], default='agent')
    p.add_argument('--rows', metavar='LABEL', help='list the rows with this label (or "all") instead of counts')
    p = add('verdict', 'record your own verdict on one labelled unit: it overrides the model\'s label everywhere', scoped=False)
    p.add_argument('rubric'); p.add_argument('ref'); p.add_argument('value'); p.add_argument('note', nargs='?', default='')
    p = add('check', 'test a rubric on cases with known answers (a JSONL file: {"ref", "expect", "note"})', scoped=False)
    p.add_argument('rubric'); p.add_argument('cases')
    p.add_argument('--model')
    p = add('look', "ask a vision model one question about an action's screenshot", scoped=False)
    p.add_argument('ref'); p.add_argument('question')
    p.add_argument('--model')
    p = add('ask', 'a question in plain English, answered by an agent that runs these commands and cites refs', scoped=False)
    p.add_argument('question')
    p.add_argument('--goal', help='scope hint given to the agent')
    p.add_argument('--model', help='default: $VILLAGE_ASK_MODEL or claude-opus-5-5')
    p.add_argument('--max-steps', type=int, default=40)
    p.add_argument('--quiet', action='store_true', help="don't print each command as it runs")
    p = add('eval', 'run the agent on questions with known answers and grade it', scoped=False)
    p.add_argument('file', nargs='?', default='evals/questions.json')
    p.add_argument('--ids', help='only these question ids, comma-separated')
    p.add_argument('--model')
    p.add_argument('--agent-cmd', help='grade another agent instead: a shell command with {question} in it that prints the answer')
    p.add_argument('--jobs', type=int, default=3)
    p = add('web', 'the same commands in a browser: type one, or follow what you run in the terminal', scoped=False)
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8765)
    p.add_argument('--llm', action='store_true', help='let the page run commands that call a model, even when --host is not local')
    return ap


def command_list():
    """Every command with its own arguments and help, from the parser itself (for the agent's prompt and the web page)."""
    sub = next(x for x in parser()._actions if x.dest == 'cmd')
    shared = {'help', 'goal', 'day', 'date', 'since', 'until', 'limit', 'wide', 'json'}
    out = []
    for name, p in sub.choices.items():
        args = []
        for x in p._actions:
            if x.dest in shared:
                continue
            if not x.option_strings:
                args.append(f'<{x.metavar or x.dest}>' if x.nargs not in ('?', '*') else f'[{x.metavar or x.dest}]')
            else:
                args.append(f'[{x.option_strings[0]}' + ('' if x.nargs == 0 else f' {(x.metavar or x.dest).upper()}') + ']')
        out.append({'name': name, 'args': ' '.join(args), 'help': p.description, 'scoped': 'limit' in {x.dest for x in p._actions},
                    'limit': p.get_default('limit')})
    return out


def render(blocks, wide=False):
    out = []
    for b in blocks:
        if b[0] == 'note':
            out.append(f'! {b[1]}')
        elif b[0] == 'text':
            out.append(f'## {b[1]}\n{b[2]}')
        else:
            _, title, headers, rows = b
            rows = [['' if v is None else str(v).replace('\n', ' ') for v in r] for r in rows]
            widths = [max(map(len, col)) for col in zip(headers, *rows)] if rows else [len(h) for h in headers]
            lines = ['  '.join(v.ljust(w) for v, w in zip(r, widths)).rstrip() for r in [headers, *rows]]
            out.append(f'## {title}\n' + '\n'.join(lines) + ('' if rows else '\n(no rows)'))
    return '\n\n'.join(out)


def run(a):
    """A parsed command -> blocks: ('table', title, headers, rows) | ('text', title, body) | ('note', text)."""
    if a.cmd in LLM:
        from . import llm
        return getattr(llm, a.cmd)(a)
    con = connect()
    try:
        return commands.run(con, a) if a.cmd in MENTIONS else getattr(evidence, a.cmd.replace('-', '_'))(con, a)
    finally:
        con.close()


def run_cmd(line, deny=()):
    """A command line as text -> (blocks, error text). Never raises: a wrong command is an answer, not a crash."""
    err = io.StringIO()
    try:
        with redirect_stderr(err), redirect_stdout(err):
            a = parser().parse_args(shlex.split(line))
            if a.cmd in deny:
                return None, f'`{a.cmd}` is not available here.'
            return run(a), None
    except SystemExit as e:
        return None, (err.getvalue().strip() or str(e.code if isinstance(e.code, str) else '')).strip() or 'error'
    except Exception as e:
        return None, f'error: {type(e).__name__}: {e}'


def run_line(line):
    """A command line -> its output as text, for the agent."""
    blocks, err = run_cmd(line, deny=('build', 'ask', 'eval', 'verdict', 'check', 'web'))
    return err if blocks is None else render(blocks)


def main(argv=None):
    a = parser().parse_args(argv)
    if a.cmd == 'build':
        return db.build(a.days, a.goal, a.since, a.until, a.all)
    from . import web
    if a.cmd == 'web':
        return web.serve(a.host, a.port, a.llm)
    t = time.time()
    blocks = run(a)
    web.remember(shlex.join(sys.argv[1:] if argv is None else argv), blocks, time.time() - t, 'terminal')  # the page can follow the terminal
    if getattr(a, 'json', False):
        return print(json.dumps([dict(zip(('type', 'title', 'headers', 'rows') if b[0] == 'table' else ('type', 'title', 'text') if b[0] == 'text'
                                          else ('type', 'text'), b)) for b in blocks], ensure_ascii=False, indent=1))
    print(render(blocks))


if __name__ == '__main__':
    main()
