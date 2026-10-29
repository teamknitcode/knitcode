"""Read saved working-tree changes against HEAD; never execute target code."""
from pathlib import Path
import subprocess
from git_validation.analyzer.git_insights import function_changes


def read_changes(root, nodes, edges):
    root = Path(root).resolve()
    result = {'available': False, 'files': [], 'warnings': [],
              'basis': 'HEAD와 저장된 작업 파일 비교(스테이징 포함). 미저장 편집은 제외.'}
    def git(*args):
        return subprocess.run(['git', '-C', str(root), *args], check=True,
                              capture_output=True, timeout=30).stdout
    try:
        if Path(git('rev-parse', '--show-toplevel').decode().strip()).resolve() != root:
            raise ValueError('Git 저장소 최상위 폴더를 열어주세요.')
        git('rev-parse', '--verify', 'HEAD')
        # Git diff includes staged+unstaged changes; untracked files are separate.
        names = set(git('diff', '--name-only', '-z', 'HEAD', '--').decode().split('\0'))
        names.update(git('ls-files', '--others', '--exclude-standard', '-z').decode().split('\0'))
        paths = sorted(p for p in names if p.endswith('.py'))
        if len(paths) > 200:
            result['warnings'].append('변경 Python 파일 200개까지만 분석합니다.')
        for name in paths[:200]:
            row = {'file': name, 'functions': [], 'error': None}
            result['files'].append(row)
            try:
                path = root / name
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    raise ValueError('프로젝트 밖 경로 또는 심볼릭 링크 제외')
                old = subprocess.run(['git', '-C', str(root), 'show', 'HEAD:' + name],
                                     capture_output=True, timeout=30)
                if old.returncode and path.exists():
                    # Missing HEAD path is normal for newly added files.
                    tracked = git('ls-tree', 'HEAD', '--', name)
                    if tracked: raise ValueError('HEAD 소스를 읽을 수 없습니다.')
                if path.exists() and path.stat().st_size > 500_000 or len(old.stdout) > 500_000:
                    raise ValueError('500KB 소스 제한 초과')
                new = path.read_bytes() if path.exists() else b''
                for change in function_changes(old.stdout if old.returncode == 0 else b'', new):
                    matches = [n for n in nodes if n['file'] == name and n['type'] in ('function', 'method')
                               and (n['name'] == change['name'] or n['name'].endswith('.' + change['name']))]
                    node = matches[0] if len(matches) == 1 and change['kind'] != 'deleted' else None
                    callers = sorted({e['source'] for e in edges if node and e['target'] == node['id']
                                      and e['type'] in ('calls', 'instantiates', 'calls_implicit')})
                    row['functions'].append({'name': change['name'], 'kind': change['kind'],
                                             'facts': change['facts'], 'node_id': node['id'] if node else None,
                                             'callers': callers})
            except (OSError, ValueError, SyntaxError, UnicodeError, LookupError, RecursionError) as exc:
                row['error'] = str(exc)
        result['available'] = True
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result['error'] = str(exc)
    return result
