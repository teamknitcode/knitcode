"""Keep source identity and decorated function starts from the original static scan."""
import ast
import hashlib


def annotate(nodes, facts, relative):
    starts = {}
    hashes = {}
    for file in facts['files']:
        name = relative(file['file'])
        hashes[name] = hashlib.sha256(file['source'].encode('utf-8')).hexdigest()
        tree = facts.syntax_trees.get(file['file'])
        if tree is None:
            continue
        for fn in ast.walk(tree):
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and fn.decorator_list:
                starts[name, fn.lineno] = min(item.lineno for item in fn.decorator_list)
    for node in nodes:
        start = starts.get((node['file'], node['lineno']))
        if start is not None and node['type'] in ('function', 'method'):
            node['profile_first_line'] = start
    return hashes
