"""Small source-verified CPython stdlib MRO contracts; no target imports."""
import ast
import hashlib
from pathlib import Path
import sysconfig
import sys
import tokenize


def multiprocessing_contract():
    """Only admit the explicit Process -> BaseProcess -> object hierarchy.

    Members come from installed stdlib source, never from a project-specific
    absence list. Missing/unrecognized layouts fall back to unknown bases.
    External members are barriers, not fabricated project graph targets.
    """
    directory = Path(sysconfig.get_path('stdlib'))/'multiprocessing'
    specs = [('context.py', 'Process', 'process.BaseProcess', 'multiprocessing.Process'),
             ('process.py', 'BaseProcess', 'object', 'multiprocessing.process.BaseProcess')]
    result, provenance = {}, []
    try:
        for filename, classname, base, canonical in specs:
            path = directory/filename
            with tokenize.open(path) as stream:
                tree = ast.parse(stream.read())
            definitions = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name==classname]
            if len(definitions)!=1:
                return {}, []
            cls = definitions[0]
            if cls.decorator_list or cls.keywords or [ast.unparse(b) for b in cls.bases] != [base]:
                return {}, []
            attributes = set()
            for statement in cls.body:
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    attributes.add(statement.name)
                elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target]
                    if not all(isinstance(n, ast.Name) for n in targets):
                        return {}, []
                    attributes.update(n.id for n in targets)
                elif not (isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr)
                          and isinstance(statement.value, ast.Constant) and isinstance(statement.value.value, str)):
                    return {}, []
            result[canonical] = attributes
            provenance.append(dict(file=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                                   modeled_class=canonical, members=sorted(attributes),
                                   target_platform=sys.platform, python_version=sys.version))
        # Dynamic interception invalidates ordinary static member lookup.
        if any(attrs & {'__getattribute__','__getattr__','__mro_entries__','__init_subclass__'} for attrs in result.values()):
            return {}, []
    except (OSError, SyntaxError, UnicodeError):
        return {}, []
    return result, provenance
