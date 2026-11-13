"""Source-verified overlay of profile observations on saved static graphs."""
from __future__ import annotations

import ast
from collections import defaultdict
import json
from pathlib import Path

from symbol_builder import module_name_from_file
from runtime_validation.profile_collector import source_digest, write_json_atomic


def _relative(file, repository):
    file = file.replace('\\', '/')
    prefix = f'{repository}/'
    return file[len(prefix):] if repository and file.startswith(prefix) else file


def _definitions(source):
    """Index real definition starts, including decorator code-object starts."""
    result = {}

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                qualified = '.'.join([*prefix, child.name])
                first = min([d.lineno for d in child.decorator_list] + [child.lineno])
                kind = 'CLASS_BODY' if isinstance(child, ast.ClassDef) else 'FUNCTION'
                for line in {first, child.lineno}:
                    result[(line, child.name, kind)] = (qualified, child.lineno)
                walk(child, [*prefix, child.name])
            else:
                walk(child, prefix)

    walk(ast.parse(source), [])
    return result


def compare(static_dir, trace_path, out=None):
    static_dir, trace_path = Path(static_dir), Path(trace_path)
    trace = json.loads(trace_path.read_text(encoding='utf-8'))
    if trace.get('format') != 'knitcode-profile-1':
        raise ValueError('Expected a knitcode-profile-1 trace from dynamic_analysis.py record')
    symbols = json.loads((static_dir / 'symbol_result.json').read_text(encoding='utf-8'))
    graph = json.loads((static_dir / 'graph_result.json').read_text(encoding='utf-8'))
    repository = symbols.get('repository')
    sources = {_relative(file, repository): source
               for file, source in symbols.get('analysis_sources', {}).items()}
    if not sources and (static_dir / 'ast_result.json').exists():
        ast_data = json.loads((static_dir / 'ast_result.json').read_text(encoding='utf-8'))
        sources = {_relative(f['file'], repository): f['source']
                   for f in ast_data.get('files', []) if 'source' in f}
    by_location = defaultdict(list)
    for symbol in symbols['symbols']:
        key = (_relative(symbol['file'], repository), symbol['qualified_name'], symbol['line'])
        by_location[key].append(symbol)
    graph_ids = {node['id'] for node in graph['nodes']}
    definitions = {}
    file_status = {}
    for file, evidence in trace['files'].items():
        if evidence.get('changed_during_run'):
            file_status[file] = 'source_changed_during_run'
        elif file not in sources:
            file_status[file] = 'static_source_missing'
        elif evidence.get('sha256') != source_digest(sources[file]):
            file_status[file] = 'source_mismatch'
        else:
            file_status[file] = 'verified'
            definitions[file] = _definitions(sources[file])

    mapping = {}
    for node in trace['nodes']:
        file = node['file']
        static_id = None
        reason = file_status.get(file, 'runtime_source_missing')
        if reason == 'verified':
            reason = 'definition_unrepresented'
            if node['kind'] == 'MODULE':
                module = module_name_from_file(file, None, symbols.get('source_roots', []))
                candidate = f'MODULE:{module}'
                if candidate in graph_ids:
                    static_id = candidate
            elif node['kind'] in ('FUNCTION', 'CLASS_BODY'):
                definition = definitions[file].get((node['first_line'], node['name'], node['kind']))
                if definition is not None:
                    qualified, line = definition
                    runtime_qualified = node.get('qualified_name')
                    if runtime_qualified:
                        runtime_qualified = runtime_qualified.replace('.<locals>.', '.')
                    candidates = by_location.get((file, qualified, line), [])
                    expected = {'CLASS'} if node['kind'] == 'CLASS_BODY' else {'FUNCTION', 'METHOD'}
                    candidates = [s for s in candidates if s['kind'] in expected and s['id'] in graph_ids]
                    if len(candidates) == 1 and runtime_qualified in (None, qualified):
                        static_id = candidates[0]['id']
            else:
                reason = 'synthetic_scope'
        mapping[node['id']] = {'static_id': static_id,
                               'reason': 'matched' if static_id else reason}

    static_relations = defaultdict(list)
    for collection in ('edges', 'implicit_edges'):
        for index, edge in enumerate(graph.get(collection, [])):
            if edge['type'] not in ('CALLS', 'CALLS_IMPLICIT', 'CALLS_OVERRIDE'):
                continue
            line = (edge.get('evidence') or {}).get('line')
            key = (edge['source'], edge['target'], line)
            static_relations[key].append({'collection': collection, 'index': index})

    runtime_edges = []
    comparable, confirmed = set(), set()
    function_relations, confirmed_function_relations = set(), set()
    static_kinds = {node['id']: node['kind'] for node in graph['nodes']}
    runtime_kinds = {node['id']: node['kind'] for node in trace['nodes']}
    unmapped = 0
    scope_entries = 0
    for edge in trace['edges']:
        source = mapping[edge['source']]['static_id']
        target = mapping[edge['target']]['static_id']
        key = (source, target, edge['line'])
        references = static_relations.get(key, [])
        if source is None or target is None:
            status = 'unmapped'
            unmapped += 1
        elif runtime_kinds[edge['target']] in ('MODULE', 'CLASS_BODY'):
            status = 'scope_entry'
            scope_entries += 1
        else:
            comparable.add(key)
            status = 'confirmed' if references else 'additional'
            if references:
                confirmed.add(key)
            if static_kinds[source] in ('FUNCTION', 'METHOD') and static_kinds[target] in ('FUNCTION', 'METHOD'):
                function_relations.add(key)
                if references:
                    confirmed_function_relations.add(key)
        runtime_edges.append({
            **edge, 'source': source or edge['source'], 'target': target or edge['target'],
            'provenance': 'sys.setprofile', 'status': status,
            'runtime_source': edge['source'], 'runtime_target': edge['target'],
            'static_edge_refs': references,
        })
    result = {
        'format': 'knitcode-hybrid-1', 'static_directory': str(static_dir.resolve()),
        'trace_path': str(trace_path.resolve()), 'trace_complete': trace['complete'],
        'comparison_granularity': 'caller + callee + caller line',
        'file_verification': file_status, 'node_mapping': mapping,
        'static_graph': graph,
        'runtime_nodes': [node for node in trace['nodes'] if mapping[node['id']]['static_id'] is None],
        'runtime_edges': runtime_edges,
        'runtime_observations': [dict(node, static_id=mapping[node['id']]['static_id']) for node in trace['nodes']],
        'coverage': trace.get('coverage'),
        'variables': (dict(trace['variables'], events=[
            dict(event, static_node_id=mapping[event['node']]['static_id'])
            for event in trace['variables']['events']]) if trace.get('variables') else None),
        'processes': trace.get('processes', []),
        'external_calls': [dict(call, source=mapping[call['source']]['static_id'] or call['source'])
                           for call in trace.get('external_calls', [])],
        'summary': {
            'mapped_nodes': sum(m['static_id'] is not None for m in mapping.values()),
            'unmapped_nodes': sum(m['static_id'] is None for m in mapping.values()),
            'runtime_edges': len(runtime_edges),
            'static_call_relations': len(static_relations),
            'observed_mapped_relations': len(comparable),
            'confirmed_relations': len(confirmed),
            'additional_relations': len(comparable - confirmed),
            'unmapped_runtime_edges': unmapped,
            'scope_entry_edges': scope_entries,
            'observed_relation_recall': len(confirmed) / len(comparable) if comparable else None,
            'observed_function_relations': len(function_relations),
            'confirmed_function_relations': len(confirmed_function_relations),
            'observed_function_relation_recall': (len(confirmed_function_relations) / len(function_relations)
                                                 if function_relations else None),
        },
    }
    if out is not None:
        out = Path(out).resolve()
        protected = {trace_path.resolve(), (static_dir / 'symbol_result.json').resolve(),
                     (static_dir / 'graph_result.json').resolve(), (static_dir / 'ast_result.json').resolve()}
        if out in protected:
            raise ValueError('Comparison output must differ from trace and static inputs')
        write_json_atomic(out, result)
    return result
