"""Combine process-local observations with process provenance and coverage."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import time


def _load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def collect_reports(config, *, wait_seconds=10):
    directory = Path(config['process_directory'])
    deadline = time.monotonic() + wait_seconds
    while True:
        starts = [_load(path) for path in directory.glob('started-*.json')]
        requested = [_load(path) for path in directory.glob('requested-*.json')]
        # Windows venv executables can launch a second interpreter process.
        # Popen's PID then belongs to the launcher, which forwards its status.
        aliases = {}
        for request in requested:
            matches = [item for item in starts if item['pid'] == request['pid']]
            if not matches:
                matches = [item for item in starts if item['parent_pid'] == request['pid']]
            if len(matches) == 1:
                aliases[request['pid']] = matches[0]['pid']
        reported = {item['pid'] for item in starts if Path(item['report']).is_file()}
        pending = ({item['pid'] for item in starts} |
                   {aliases.get(item['pid'], item['pid']) for item in requested}) - reported
        if not pending or time.monotonic() >= deadline:
            break
        time.sleep(0.05)
    reports = [_load(item['report']) for item in starts if Path(item['report']).is_file()]
    exits = {aliases.get(item['pid'], item['pid']): item['exit_code']
             for path in directory.glob('exit-*.json') for item in [_load(path)]}
    expected = {aliases.get(item['pid'], item['pid']) for item in requested}
    reports = [report for report in reports if report['nodes'] or report['pid'] in expected
               or str(Path(config['trace'])) == next(item['report'] for item in starts if item['pid'] == report['pid'])]
    for report in reports:
        request = next((item for item in requested if aliases.get(item['pid']) == report['pid']), None)
        if request is not None:
            report['launcher_pid'] = request['pid']
            report['parent_python_pid'] = request['parent_pid']
        status = exits.get(report['pid'], report['execution']['exit_code'])
        report['execution']['exit_code'] = status
        report['complete'] = report['complete'] and status == 0
    return reports, sorted(pending)


def summarize_coverage(files):
    possible_lines = covered_lines = paths = covered_paths = 0
    for file in files:
        executable, executed = set(file['executable_lines']), set(file['executed_lines'])
        file['missing_lines'] = sorted(executable - executed)
        file['line_coverage'] = len(executable & executed) / len(executable) if executable else None
        possible_lines += len(executable)
        covered_lines += len(executable & executed)
        for branch in file['branches']:
            destinations, taken = set(branch['destinations']), set(branch['taken'])
            branch['missing'] = sorted(destinations - taken)
            branch['unexpected_destinations'] = sorted(taken - destinations)
            paths += len(destinations)
            covered_paths += len(destinations & taken)
    return {'executable_lines': possible_lines, 'executed_lines': covered_lines,
            'line_coverage': covered_lines / possible_lines if possible_lines else None,
            'branch_paths': paths, 'executed_branch_paths': covered_paths,
            'branch_coverage': covered_paths / paths if paths else None}


def combine(primary, reports, pending):
    result = dict(primary)
    nodes, edges, files, coverage_files, variables, external = {}, {}, {}, {}, {}, {}
    variable_keys = {}
    flow_counts = defaultdict(int)
    processes = []
    for report in reports:
        pid = report['pid']
        processes.append({'pid': pid, 'parent_pid': report['parent_pid'],
                          'parent_python_pid': report.get('parent_python_pid'),
                          'launcher_pid': report.get('launcher_pid'),
                          'complete': report['complete'], 'execution': report['execution'],
                          'profile_hooks_intact': report['profile_hooks_intact'],
                          'collector_errors': report['collector_errors']})
        for file, evidence in report['files'].items():
            previous = files.setdefault(file, dict(evidence))
            if previous.get('sha256') != evidence.get('sha256') or evidence.get('changed_during_run'):
                previous['changed_during_run'] = True
        for node in report['nodes']:
            merged = nodes.setdefault(node['id'], dict(node, profile_calls=0, entry_events=0,
                                                      argument_types={}, receiver_types=set(),
                                                      return_types=set(), yield_types=set(), process_ids=set()))
            merged['profile_calls'] += node['profile_calls']
            merged['entry_events'] += node['entry_events']
            merged['process_ids'].add(pid)
            for name, types in node['argument_types'].items():
                merged['argument_types'].setdefault(name, set()).update(types)
            for field in ('receiver_types', 'return_types', 'yield_types'):
                merged[field].update(node[field])
        for edge in report['edges']:
            key = (edge['source'], edge['target'], edge['line'], edge['caller_offset'])
            merged = edges.setdefault(key, dict(edge, count=0, thread_ids=set(), process_ids=set(),
                                                receiver_types=set(), threads=set()))
            merged['count'] += edge['count']
            merged['thread_ids'].update(edge['thread_ids'])
            merged['process_ids'].add(pid)
            merged['receiver_types'].update(edge['receiver_types'])
            merged['threads'].update((pid, tid) for tid in edge['thread_ids'])
        for file in report['coverage']['files']:
            merged = coverage_files.setdefault(file['file'], {'file': file['file'], 'executable_lines': set(),
                                                               'executed_lines': set(), 'branches': {}})
            merged['executable_lines'].update(file['executable_lines'])
            merged['executed_lines'].update(file['executed_lines'])
            for branch in file['branches']:
                observed = merged['branches'].setdefault(branch['id'], dict(branch, destinations=set(), taken=set()))
                observed['destinations'].update(branch['destinations'])
                observed['taken'].update(branch['taken'])
        for event in report['variables']['events']:
            key = (event['node'], event['name'], event['operation'], event['line'], event['offset'], event['storage'])
            variable_keys[(pid, event['id'])] = key
            merged = variables.setdefault(key, dict(event, count=0, types=set(), process_ids=set()))
            merged['count'] += event['count']
            merged['types'].update(event['types'])
            merged['process_ids'].add(pid)
        for flow in report['variables']['binding_flows']:
            key = (variable_keys[(pid, flow['source'])], variable_keys[(pid, flow['target'])])
            flow_counts[key] += flow['count']
        for call in report['external_calls']:
            key = (call['source'], call['target'], call['line'], call['caller_offset'], call['kind'])
            merged = external.setdefault(key, dict(call, count=0, process_ids=set()))
            merged['count'] += call['count']
            merged['process_ids'].add(pid)
    for node in nodes.values():
        node['argument_types'] = {name: sorted(types) for name, types in node['argument_types'].items()}
        for field in ('receiver_types', 'return_types', 'yield_types', 'process_ids'):
            node[field] = sorted(node[field])
    for edge in edges.values():
        for field in ('thread_ids', 'process_ids', 'receiver_types'):
            edge[field] = sorted(edge[field])
        edge['threads'] = [{'pid': pid, 'thread_id': tid} for pid, tid in sorted(edge['threads'])]
    coverage = []
    for _, file in sorted(coverage_files.items()):
        file['executable_lines'] = sorted(file['executable_lines'])
        file['executed_lines'] = sorted(file['executed_lines'])
        file['branches'] = [dict(branch, destinations=sorted(branch['destinations']), taken=sorted(branch['taken']))
                            for _, branch in sorted(file['branches'].items())]
        coverage.append(file)
    ids = {}
    variable_events = []
    for index, (key, event) in enumerate(sorted(variables.items())):
        ids[key] = f'VARIABLE:{index}'
        variable_events.append(dict(event, id=ids[key], types=sorted(event['types']),
                                    process_ids=sorted(event['process_ids'])))
    flows = [{'source': ids[source], 'target': ids[target], 'count': count}
             for (source, target), count in sorted(flow_counts.items())]
    result.update(nodes=sorted(nodes.values(), key=lambda node: node['id']), edges=list(edges.values()), files=files,
                  processes=sorted(processes, key=lambda item: item['pid']), missing_process_ids=pending,
                  complete=not pending and all(item['complete'] for item in processes))
    result['collector_errors'] = [dict(error, pid=report['pid']) for report in reports
                                  for error in report['collector_errors']]
    result['coverage'] = dict(primary['coverage'], files=coverage, summary=summarize_coverage(coverage))
    consistent = all(not evidence.get('changed_during_run') for evidence in files.values())
    result['coverage']['source_consistent'] = consistent
    if not consistent:
        result['coverage']['summary']['line_coverage'] = None
        result['coverage']['summary']['branch_coverage'] = None
    result['variables'] = dict(primary['variables'], events=variable_events, binding_flows=flows)
    result['external_calls'] = [dict(value, process_ids=sorted(value['process_ids'])) for value in external.values()]
    result['summary'] = {'nodes': len(nodes), 'edges': len(edges), 'processes': len(processes),
                         'profile_call_events': sum(node['profile_calls'] for node in nodes.values()),
                         'local_edge_events': sum(edge['count'] for edge in edges.values()),
                         'entry_events': sum(node['entry_events'] for node in nodes.values()),
                         'variable_events': len(variable_events), 'binding_flows': len(flows),
                         'external_call_sites': len(external)}
    return result
