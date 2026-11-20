"""Symbol-level architecture regression tests without executing target projects."""
from pathlib import Path
from tempfile import TemporaryDirectory

from architecture_hierarchy import build_architecture_hierarchy
from vscode_export import export_project


def run(sources):
    with TemporaryDirectory() as t:
        root=Path(t)
        for name, body in sources.items():
            f=root/name;f.parent.mkdir(parents=True,exist_ok=True)
            f.write_text(body,encoding='utf8')
        data=export_project(root)
        return data['architecture_hierarchy'], data


def role(h,name):
    matches=[x for x in h['symbols'].values() if x['name'].split('.')[-1]==name]
    assert matches, (name,list(h['symbols']))
    return matches[0]['primary']


def test_same_file_multi_role_and_true_call_edges():
    src='''import sqlite3
from flask import Flask
app=Flask(__name__)
def create_app():
    return init_db()
@app.route('/')
def index():
    return get_db()
def init_db():
    return sqlite3.connect(':memory:')
def get_db():
    return sqlite3.connect(':memory:')
'''
    h,data=run({'flaskr/__init__.py':src})
    assert role(h,'create_app')=='setup'
    assert role(h,'index')=='server'
    assert role(h,'get_db')=='database'
    assert role(h,'init_db')=='database'
    assert len({g['id'] for g in h['groups'] if g['files']==['flaskr/__init__.py']})>=3
    assert any(e['source_group']=='cap:server' and e['target_group']=='cap:database' for e in h['edges'])
    assert 'value_flow' in data and 'architecture_roles' in data


def test_sql_parser_is_not_db_access():
    h,_=run({'sqlparse/lexer.py':'''class Lexer:
    def get_tokens(self, text):
        return text.split()
''','sqlparse/formatter.py':'''def format_sql(text):
    return text.strip()
'''})
    assert role(h,'get_tokens')=='sql_lexing'
    assert role(h,'format_sql')=='formatting'
    assert not any(g['role']=='database' for g in h['groups'])


def test_url_parsing_is_not_http_client():
    h,_=run({'furl/furl.py':'''from urllib.parse import urlsplit
class Fragment:
    def update_fragment(self, value):
        return urlsplit(value).fragment
''','furl/path.py':'''def parse_url(url):
    return url.split('/')
'''})
    assert role(h,'parse_url')=='parsing'
    assert not any(g['role']=='http_client' for g in h['groups'])


def test_remote_ssh_is_not_web_server():
    h,_=run({'sshtunnel.py':'''import paramiko
class SSHTunnelForwarder:
    def connect_ssh(self):
        return paramiko.SSHClient()
class ForwardHandler:
    def forward_local(self):
        return 1
'''})
    assert role(h,'connect_ssh')=='ssh'
    assert role(h,'forward_local')=='tunnel'
    assert 'cap:server' not in {g['id'] for g in h['groups']}


def test_network_is_a_facet_under_search_class():
    h,_=run({'sublist3r.py':'''import requests
class GoogleEnum:
    def send_req(self):
        return requests.get('https://example.com')
'''} )
    matches=[x for x in h['symbols'].values() if x['name'].endswith('GoogleEnum.send_req')]
    assert len(matches)==1
    assert matches[0]['primary']=='enumeration'
    assert 'network_http' in matches[0]['facets']


def test_read_resource_http_not_whole_file_server():
    h,_=run({'rich_cli/__main__.py':'''import requests
def read_resource(url):
    return requests.get(url).text
def render(data):
    print(data)
'''})
    assert role(h,'read_resource')=='input'
    assert role(h,'render')=='rendering'


def test_test_file_does_not_pollute_main_map():
    h,_=run({'tests/test_service.py':'''def test_save():
    assert True
'''})
    assert role(h,'test_save')=='test'
    assert all(g['test'] for g in h['groups'])


def test_generic_name_without_evidence_abstains():
    h,_=run({'alpha.py':'''def do_thing():
    return 3
'''})
    assert role(h,'do_thing')=='unclassified'
    assert h['metrics']['unclassified_symbols']>=1


def test_call_graph_no_fake_links():
    h,_=run({'app.py':'''def main():
    return 1
def save():
    return 2
'''})
    assert h['edges']==[]


def test_both_group_directions_and_evidence_ids():
    h,_=run({'app.py':'''def main():
    return parse_sql('SELECT 1')
def parse_sql(sql):
    return sql
'''})
    assert any(e['source_group']=='cap:cli' and e['target_group']=='cap:parsing' for e in h['edges'])
    assert h['edges'][0]['evidence'][0]['source'].startswith('FUNCTION:')


def test_flask_alias_route_and_http_client_separation():
    h,_=run({'api.py':'''from flask import Flask as F
import httpx as hx
app=F(__name__)
@app.get('/x')
def endpoint():
    return hx.get('https://example.org')
'''})
    assert role(h,'endpoint')=='server'
    fn=next(v for v in h['symbols'].values() if v['name'].endswith('endpoint'))
    assert 'network_http' in fn['facets']


def test_file_name_repository_does_not_prove_database():
    h,_=run({'git_validation/analyzer/repository_source.py':'''def read_repository():
    return 'git'
'''})
    assert not any(g['role']=='database' for g in h['groups'])


def test_no_call_edges_for_contains_and_cochange():
    h,_=run({'x.py':'''def parse_url(url):
    return url
''', 'y.py':'''def format_sql(text):
    return text
'''})
    assert h['edges']==[]
