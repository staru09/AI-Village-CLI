# AI Village CLI

`village-graph` builds a who-talks-to-whom graph of the [AI Village](https://theaidigest.org/village) agents from the [`aidigestorg/ai-village`](https://huggingface.co/datasets/aidigestorg/ai-village) dataset. You can query it from a CLI or a small web UI. It uses only the Python standard library and stores the graph in a local SQLite file.

## Setup

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

1. Request access to the gated dataset on its Hugging Face page, then log in and download the five files it needs (about 360 MB):

   ```bash
   uvx --from huggingface_hub hf auth login
   uvx --from huggingface_hub hf download aidigestorg/ai-village --repo-type dataset \
     agents.jsonl.gz chat_rooms.jsonl.gz village_goals.jsonl.gz events.jsonl.gz chat_messages.jsonl.gz
   ```

   The tool reads the latest snapshot from the Hugging Face cache. To use a folder of `.jsonl.gz` files instead, set `VILLAGE_DATA=/path/to/folder`.

2. Install the project and run the self-check:

   ```bash
   git clone https://github.com/staru09/AI-Village-CLI.git && cd AI-Village-CLI
   uv sync
   uv run python test_village_graph.py   # prints "ok"
   ```

## Run

```bash
uv run village-graph build                            # build village.db from the last 7 days (--days 0 = full history)
uv run village-graph top-pairs                        # strongest agent pairs
uv run village-graph pair "opus 4.8" "gemini 2.5"     # how two agents interact over time
uv run village-graph web                              # interactive graph at http://127.0.0.1:8765
uv run village-graph -h                               # all commands
```

`village.db` is generated locally and is not part of the repo. See [USAGE.md](USAGE.md) for every command and filter, how interactions are defined, and the SQLite schema.
