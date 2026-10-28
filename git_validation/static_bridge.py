"""Bridge Git history reports to the team's current KnitCode static analyzer.

The target snapshot is read-only source. No target code is imported or executed.
The team's main.py and other modules are imported from the parent directory.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

TEAM_ROOT = Path(__file__).resolve().parent.parent
if str(TEAM_ROOT) not in sys.path:
    sys.path.insert(0, str(TEAM_ROOT))


def run(snapshot, output, commit, source_roots=None):
    from main import run as team_static_run
    from symbol_builder import save_json

    out = Path(output)
    ast_data, symbols, graph = team_static_run(
        str(snapshot), out, source_roots=source_roots
    )
    # The source is materialized from immutable Git blobs (no .git in snapshot).
    # Explicitly annotate the known commit and replace JSON metadata consistently.
    for filename, data in (
        ('ast_result.json', ast_data),
        ('symbol_result.json', symbols),
        ('graph_result.json', graph),
    ):
        data['commit'] = commit
        save_json(data, out / filename)
    return ast_data, symbols, graph


def main():
    parser = argparse.ArgumentParser(description='KnitCode current integrated engine adapter')
    parser.add_argument('snapshot')
    parser.add_argument('output')
    parser.add_argument('commit')
    parser.add_argument('--source-root', action='append', default=None)
    args = parser.parse_args()
    run(args.snapshot, args.output, args.commit, args.source_root)

if __name__ == '__main__':
    main()
