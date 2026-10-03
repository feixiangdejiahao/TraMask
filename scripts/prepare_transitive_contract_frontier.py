"""Freeze the same historical failure pool with a transitive source priority."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from relation_search import transitive_contract_call_priority
from relation_search import source_frontend_refresh
from scripts.prepare_contract_call_frontier import prepare


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--limits', type=int, nargs='+', default=[8, 16, 32])
    parser.add_argument('--refresh-frontend', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.input, args.output, limits=tuple(args.limits),
                             selector=transitive_contract_call_priority,
                             frontend_refresher=source_frontend_refresh if args.refresh_frontend else None)))
