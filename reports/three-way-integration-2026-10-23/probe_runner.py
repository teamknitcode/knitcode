"""Run identical, hand-authored feature probes against an isolated engine root.

python probe_runner.py --engine-root PATH --kind modular|ljy --output PATH
This is an audit tool; analyzed fixture sources are never executed.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

PROBES = {
    'direct_call': ('def target(): pass\ndef go(): target()\n', [('app.go', 'app.target')]),
    'c3_mro': ('class A:\n    def run(self): pass\nclass B(A): pass\n'
               'class C(A):\n    def run(self): pass\nclass D(B,C): pass\n'
               'def go(): D().run()\n', [('app.go', 'app.C.run')]),
    'property_return': ('class Item:\n    def run(self): pass\nclass Box:\n'
                        '    @property\n    def item(self): return Item()\n'
                        'def go(): Box().item.run()\n', [('app.go', 'app.Box.item'), ('app.go', 'app.Item.run')]),
    'with_as': ('class Item:\n    def run(self): pass\nclass Box:\n'
                '    def __enter__(self): return Item()\n'
                '    def __exit__(self,*args): pass\n'
                'def go():\n    with Box() as item: item.run()\n', [('app.go', 'app.Item.run')]),
    'operator': ('class Item:\n    def __add__(self,other): return self\n'
                 'def go():\n    item=Item()\n    item+item\n', [('app.go', 'app.Item.__add__')]),
    'typed_truth': ('class Flag:\n    def __bool__(self): return True\n'
                    'def go(flag: Flag):\n    if flag: pass\n', [('app.go', 'app.Flag.__bool__')]),
    'typed_container': ('class Item:\n    def run(self): pass\n'
                        'class Box:\n    items: list[Item]\n'
                        'def go(box: Box):\n    for item in box.items: item.run()\n', [('app.go', 'app.Item.run')]),
    'annotated_factory': ('class Item:\n    def run(self): pass\n'
                          'def factory() -> Item: return unknown()\n'
                          'def go(): factory().run()\n', [('app.go', 'app.Item.run')]),
    'subclass_dispatch_candidates': ('class Base:\n    def run(self): pass\n'
                                     'class Child(Base):\n    def run(self): pass\n'
                                     'def go(obj: Base): obj.run()\n',
                                     [('app.go', 'app.Base.run'), ('app.go', 'app.Child.run')]),
    'sorted_callback': ('def key(x): return x\ndef go(values): return sorted(values,key=key)\n',
                        [('app.go', 'app.key')]),
    'default_factory': ('class Item:\n    def run(self): pass\n'
                        'def factory(cls=Item): return cls()\n'
                        'def go(): factory().run()\n', [('app.go', 'app.Item.run')]),
    'lexical_scope': ('def work(): pass\nclass Box:\n    def work(self): pass\n'
                      '    def go(self): work()\n', [('app.Box.go', 'app.work')]),
    'method_patch_abstention': ('class Box:\n    def run(self): pass\n'
                                'Box.run=unknown\ndef go(): Box().run()\n', []),
    'thread_target_reference': ('import threading\ndef work(): pass\n'
                                'def go(): threading.Thread(target=work)\n', []),
}


def modular(root):
    from ast_parser import scan_repository
    from symbol_builder import build_symbol_result
    from graph_builder import build_graph
    from unresolved_classifier import reclassify_graph
    from call_status import annotate_call_statuses
    symbols = build_symbol_result(scan_repository(root))
    return annotate_call_statuses(reclassify_graph(build_graph(symbols), symbols), symbols)


def execute(kind):
    if kind == 'ljy':
        from analyze_project import analyze
        analyze = lambda root, original=analyze: original(root)[1]
    else:
        analyze = modular
    records = {}
    for label, (source, expected) in PROBES.items():
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'app.py').write_text(source)
            result = analyze(root)
        if kind == 'ljy':
            def name(node_id):
                file, sep, qual = node_id.partition('::')
                module = file.removesuffix('.py').replace('/', '.')
                if module.endswith('.__init__'):
                    module = module[:-9]
                return module + ('.' + qual if sep else '')
            edges = [(name(e['from']), name(e['to']), e['type']) for e in result['edges']]
            calls = {(a,b) for a,b,t in edges if t in ('calls','calls_override','calls_implicit')}
        else:
            names = {n['id']: n['canonical_name'] for n in result['nodes']}
            edges = [(names[e['source']], names[e['target']], e['type'])
                     for e in [*result['edges'], *result.get('implicit_edges', [])]]
            calls = {(a,b) for a,b,t in edges if t in ('CALLS','CALLS_IMPLICIT')}
        forbidden = [('app.go', 'app.Box.run')] if label == 'method_patch_abstention' else []
        references = [(a,b) for a,b,t in edges if t == 'references']
        records[label] = dict(expected_pairs=expected, forbidden_pairs=forbidden,
                              all_expected_found=set(map(tuple, expected)) <= calls,
                              forbidden_pairs_absent=not bool(set(forbidden) & calls),
                              thread_target_reference_found=('app.go', 'app.work') in references,
                              call_pairs=sorted(calls), edges=edges,
                              result_keys=sorted(result),
                              original_method_connected=('app.go', 'app.Box.run') in calls)
    # Metadata-specific features need an actual import cycle and a real entry point.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / 'app.py').write_text('import helper\ndef go(obj,name): getattr(obj,name)()\nif __name__=="__main__": go(helper,"work")\n')
        (root / 'helper.py').write_text('import app\ndef work(): pass\n')
        result = analyze(root)
    records['metadata'] = {k: result.get(k) for k in
                           ('schema_version','entry_points','reading_order','hierarchy','import_cycles','dynamic_calls')}
    if kind == 'modular' and importlib.util.find_spec('external_bases'):
        # New external-base implementation must also abstain if no contract is available.
        with patch('external_bases.ExternalClassIndex.attributes', return_value=None):
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp)
                (root/'app.py').write_text('from multiprocessing import Process\nclass Internal:\n'
                                           '    def work(self): pass\nclass Worker(Process,Internal): pass\n'
                                           'def go(): Worker().work()\n')
                result=analyze(root)
        records['unknown_external_contract'] = [r['target_ids'] for r in result['call_statuses']
                                                 if r['callee_text']=='Worker().work']
    return records


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine-root', type=Path, required=True)
    parser.add_argument('--kind', choices=('modular','ljy'), required=True)
    parser.add_argument('--output', type=Path, required=True)
    args=parser.parse_args()
    sys.path.insert(0,str(args.engine_root.resolve()))
    result=execute(args.kind)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
