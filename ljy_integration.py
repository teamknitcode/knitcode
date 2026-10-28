"""Compatibility selectors and exports for the unified graph (no analysis)."""
from pathlib import Path


def selected_supplemental_edges(graph):
    policy = graph.get('call_graph_policy', 'primary')
    edges = graph.get('supplemental_edges', [])
    if policy == 'augmented':
        return edges
    if policy == 'supported':
        return [e for e in edges if e.get('evidence', {}).get('prediction_eligible')]
    return []


def write_legacy_outputs(graph, symbols, out):
    """Export the unified graph through the preserved viewer format."""
    import knit_viewer
    from symbol_builder import save_json
    native = graph.get('ljy_result')
    if native is None:
        return
    out = Path(out)
    save_json(native, out / 'ljy_graph.json')
    data = knit_viewer.slim(native, with_source=False, project=symbols.get('repository'))
    sources = symbols.get('analysis_sources') or {}
    repository = symbols.get('repository')
    data['source'] = {}
    source_lines = {}
    for n in native['nodes']:
        file = n.get('file', '')
        if file not in sources:
            file = repository + '/' + file
        text = sources.get(file)
        if text and n['type'] in ('class', 'function', 'method'):
            if file not in source_lines:
                source_lines[file] = text.splitlines()
            lines = source_lines[file]
            start = max(0, n['line'] - 1)
            data['source'][n['id']] = '\n'.join(lines[start:min(n.get('end_lineno') or n['line'], start+40)])
    (out / 'ljy_report.html').write_text(knit_viewer.build_html(data), encoding='utf-8')


def legacy_view(native, symbols):
    """Convert shared IDs to the original viewer/comparison-tool namespace."""
    repository = symbols.get('repository') or 'project'
    definitions = {s['id']: s for s in symbols.get('symbols', [])}
    ids = {}
    for node in native['nodes']:
        file = node['file'].removeprefix(repository + '/')
        symbol = definitions.get(node['id'])
        ids[node['id']] = file + ('::' + symbol['qualified_name'] if symbol else '')

    def convert(value):
        if isinstance(value, str):
            if value in ids:
                return ids[value]
            for prefix in ('package:', 'module:', 'class:', 'function:'):
                if value.startswith(prefix):
                    suffix = value[len(prefix):]
                    return prefix + ids.get(suffix, suffix.removeprefix(repository + '/'))
            return value.removeprefix(repository + '/')
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    return convert(native)


def refresh_legacy_classification(graph, symbols):
    """Project final boundary statuses into the compatibility JSON, without resolving again."""
    native = graph.get('ljy_result')
    if native is None:
        return
    from collections import Counter
    repository = symbols.get('repository') or 'project'
    definitions = {s['id']: s for s in symbols.get('symbols', [])}
    modules = {n['id']: n for n in graph['nodes'] if n['kind'] == 'MODULE'}
    def owner(call):
        nid = call.get('caller_id')
        symbol = definitions.get(nid)
        if symbol:
            return symbol['file'].removeprefix(repository+'/')+'::'+symbol['qualified_name']
        return modules.get(nid, {}).get('file',call['file']).removeprefix(repository+'/')
    categories = {'BUILTIN':'builtin', 'STDLIB':'stdlib', 'EXTERNAL_IMPORT':'third_party'}
    external, unresolved = [], []
    for call in graph.get('call_statuses', []):
        if call['status'] == 'KNOWN_NON_INTERNAL':
            category = categories[call['origin_kind']]
            origin = call.get('evidence', {}).get('origin_name') or call['callee_text']
            external.append(dict(**{'from':owner(call),'to':'EXTERNAL::'+category},
                type='calls_external',category=category,package=origin.split('.')[0],detail=origin,
                confidence='certain',count=1,line=call['line']))
        elif call['status'] == 'UNKNOWN':
            unresolved.append(dict(**{'from':owner(call)},expr=call['callee_text'],category='unknown',line=call['line']))
    native['external_nodes'] = [dict(id='EXTERNAL::'+c,type='external',category=c) for c in categories.values()]
    native['external_edges'] = external
    native['unresolved'] = unresolved
    native['summary'].update(external=dict(Counter(e['category'] for e in external)),
                             unresolved={'unknown':len(unresolved)},
                             classification_source='unified call_statuses; static origins only')
