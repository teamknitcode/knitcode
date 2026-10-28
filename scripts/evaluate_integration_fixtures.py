"""Compare frozen supported integration features without running fixture code."""
import argparse
import json
from pathlib import Path
import sys

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--engine-root',type=Path,default=Path(__file__).resolve().parents[1])
parser.add_argument('--fixtures',type=Path,default=Path(__file__).resolve().parents[1]/'tests/ljy_original/fixtures')
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
sys.path.insert(0,str(args.engine_root.resolve()))
from ast_parser import scan_repository
from symbol_builder import build_symbol_result
from graph_builder import build_graph
from pycg_adapter import to_pycg

results={}
for root in sorted(args.fixtures.iterdir()):
    if not root.is_dir() or root.name=='__pycache__':continue
    symbols=build_symbol_result(scan_repository(root,source_roots=['.']))
    graph=build_graph(symbols)
    calls,_,_=to_pycg(symbols,graph,include_implicit=True)
    names={n['id']:n['canonical_name'].replace('.<locals>.','.') for n in graph['nodes']+graph.get('supplemental_nodes',[])}
    results[root.name]=dict(calls=sorted(calls),
        references=sorted({(names[e['source']],names[e['target']]) for e in graph.get('supplemental_edges',[]) if e['type']=='REFERENCES'}),
        entries=sorted({(names[e['id']],e['kind']) for e in graph['entry_points']}),
        dynamic=sorted({(names[d['from']],d['kind']) for d in graph['dynamic_calls']}),
        cycles=sorted((c['kind'],sorted(names.get(n,n) for n in c['modules'])) for c in graph['import_cycles']))
import graph_builder
args.output.parent.mkdir(parents=True,exist_ok=True)
args.output.write_text(json.dumps(dict(engine_module=str(Path(graph_builder.__file__).resolve()),fixtures=results),indent=2)+'\n')
