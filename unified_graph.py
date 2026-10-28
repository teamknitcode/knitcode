"""Navigation and compatibility views of the single Resolver/ObjectFlow graph.

No independent symbol table, call collector or legacy analyzer is executed here.
"""
import ast
from collections import Counter, defaultdict
from pathlib import Path

import graph_navigation as nav
from import_resolution import canonical_import
from symbol_builder import module_name_from_file


def finish_graph(graph, symbols, resolver, *, call_policy):
    repository = symbols.get('repository') or 'project'
    nodes = {n['id']: n for n in graph['nodes']}
    modules = {n['canonical_name']: n for n in nodes.values() if n['kind'] == 'MODULE'}
    definitions = defaultdict(list)
    for s in resolver.symbols:
        definitions[s['file']].append(s)
    sources = symbols.get('analysis_sources', {})
    supplemental = []
    seen = set()

    def extra(source, target, kind, line, **evidence):
        key = source, target, kind, line
        if key in seen or source not in nodes or target not in nodes:
            return
        seen.add(key)
        supplemental.append(dict(source=source, target=target, type=kind,
            evidence=dict(file=nodes[source]['file'], line=line, producer='unified',
                          prediction_eligible=kind in ('CALLS','CALLS_OVERRIDE'), **evidence)))

    for call in resolver.calls:
        owner=call.get('caller_id') or 'MODULE:'+call['module']
        modes=['specific'] if owner in resolver.object_flow.specific else ['root','generic']
        for mode in modes:
            for target in sorted(resolver.object_flow.advisory_events.get((call['id'],mode),())):
                extra(owner,target,'CALLS',call['line'],call_id=call['id'],
                      certainty='declared_return_advisory_may_call',rule='object_flow_return_annotation')

    for (owner,line,mode),targets in resolver.object_flow.reference_events.items():
        if owner in resolver.object_flow.specific and mode!='specific':continue
        for target in sorted(targets):extra(owner,target,'REFERENCES',line,certainty='flow_reference')

    # Subtype alternatives derive from the SAME resolved annotation call site.
    for e in graph['edges']:
        if e['type'] != 'CALLS' or e.get('evidence', {}).get('certainty') != 'declared_parameter_type_may_call':
            continue
        target = resolver.by_id[e['target']]
        cls = resolver.classes.get(target['canonical_name'].rsplit('.', 1)[0])
        if not cls:
            continue
        for child in resolver._descendants(cls):
            methods, _ = resolver._find_method(child, target['name'])
            for method in methods:
                if method['id'] != target['id'] and resolver.safe_callable(method):
                    extra(e['source'], method['id'], 'CALLS_OVERRIDE', e['evidence'].get('line'),
                          certainty='declared_subtype_may_call', declared_subtype_dispatch=True)

    symbol_locations = {(s['file'],s['line'],s.get('column',0)):s for s in resolver.symbols}
    contexts = {}
    def context(file, node):
        key=(file,node)
        if key in contexts:return contexts[key]
        parents=resolver._source_parents[file]
        child=node
        ancestor=parents.get(child)
        owner=None
        while ancestor:
            if isinstance(ancestor,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef,ast.Lambda)):
                body=[ancestor.body] if isinstance(ancestor,ast.Lambda) else ancestor.body
                if child in body:
                    owner=symbol_locations.get((file,ancestor.lineno,ancestor.col_offset))
                    if owner:break
            child,ancestor=ancestor,parents.get(ancestor)
        module = module_name_from_file(file, repository, symbols.get('source_roots', []))
        result=dict(file=file, module=module, scope=owner['qualified_name'] if owner else '<module>',
                    caller_id=owner['id'] if owner else modules[module]['id'], line=getattr(node,'lineno',1),
                    column=getattr(node,'col_offset',0))
        contexts[key]=result
        return result

    dynamic = []
    entries = []
    def entry(nid, kind, detail='', category='runtime', confidence='certain'):
        if nid in nodes and not any(e['id']==nid and e['kind']==kind for e in entries):
            entries.append(dict(id=nid,kind=kind,detail=detail,category=category,confidence=confidence))

    import_edges = {}
    for file, tree in resolver.syntax_trees.items():
        module = module_name_from_file(file, repository, symbols.get('source_roots', []))
        module_id = modules[module]['id']
        parents = resolver._source_parents[file]
        ast_imports = {n.lineno:n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))}
        if file.endswith('/__main__.py'):
            entry(module_id, 'main_module')
            for edge in graph['edges']:
                if edge['source']==module_id and edge['type']=='CALLS':entry(edge['target'],'main_call')
        for n in ast.walk(tree):
            ctx = context(file,n)
            if isinstance(n, ast.If) and isinstance(n.test,ast.Compare):
                text=ast.unparse(n.test)
                if text in ("__name__ == '__main__'", "'__main__' == __name__"):
                    entry(module_id,'main_guard')
                    for e in graph['edges']:
                        if e['source']==module_id and e['type']=='CALLS' and n.lineno < (e.get('evidence',{}).get('line') or 0) <= n.end_lineno:
                            entry(e['target'],'main_call')
            if isinstance(n,ast.Call):
                imports=resolver.imports_at(ctx)
                text=ast.unparse(n.func)
                root,*tail=text.split('.')
                origin='.'.join([imports.get(root,root),*tail])
                bound, reasons, _ = resolver.object_flow.call_origins._bound_at(ctx,root)
                builtin = root not in imports and not bound and not reasons
                nonliteral = lambda value: not (isinstance(value,ast.Constant) and isinstance(value.value,str))
                kind=None
                if builtin:
                    if text in ('getattr','setattr','delattr') and len(n.args)>=2 and nonliteral(n.args[1]):kind=text
                    elif text in ('eval','exec','compile','__import__'):kind='import' if text=='__import__' else text
                    elif text=='type' and len(n.args)==3:kind='type_new'
                elif not reasons:
                    if origin in ('importlib.import_module','importlib.__import__'):kind='import'
                    elif origin in ('operator.methodcaller','operator.attrgetter') and n.args and nonliteral(n.args[0]):kind=origin.rsplit('.',1)[-1]
                    elif origin in ('builtins.eval','builtins.exec','builtins.compile'):kind=origin.rsplit('.',1)[-1]
                if kind:
                    dynamic.append(dict(**{'from':ctx['caller_id']},file=file,line=n.lineno,kind=kind,expr=ast.unparse(n)[:80]))
            if isinstance(n,ast.Subscript):
                value=n.value
                namespace=False
                if isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and value.func.id in ('globals','locals','vars'):
                    bound,reasons,_=resolver.object_flow.call_origins._bound_at(ctx,value.func.id)
                    namespace=not bound and not reasons
                elif isinstance(value,ast.Attribute) and value.attr=='__dict__':
                    namespace=not (isinstance(n.slice,ast.Constant) and isinstance(n.slice.value,str))
                if namespace:
                    dynamic.append(dict(**{'from':ctx['caller_id']},file=file,line=n.lineno,kind='namespace_lookup',expr=ast.unparse(n)[:80]))
            if isinstance(n,(ast.Name,ast.Attribute)) and isinstance(n.ctx,ast.Load):
                parent=parents.get(n)
                if isinstance(parent,ast.Attribute) or isinstance(parent,ast.Call) and parent.func is n:
                    continue
                text=ast.unparse(n); root=text.split('.')[0]
                owner=resolver.by_id.get(ctx['caller_id'],{})
                if root in (owner.get('parameters') or []):
                    continue
                if resolver._find_binding(ctx,root):
                    continue
                imports=resolver.imports_at(ctx)
                refs=[]
                if '.' not in text:
                    for scope in resolver.lexical_scopes(ctx['scope'],module):
                        refs=resolver._lookup('.'.join([module,scope,text]))
                        if refs: break
                refs=refs or resolver._resolve_reference(text,module,imports)
                for target in refs:
                    extra(ctx['caller_id'],target['id'],'REFERENCES',n.lineno,certainty='static_reference')
        # Use import facts from the shared scan, including relative resolution.
        for imp in resolver.imports[file]:
            canonical=canonical_import(imp)
            target=canonical
            while target and target not in modules:
                target=target.rpartition('.')[0]
            if not target: continue
            scope='function' if imp.get('scope') not in (None,'<module>') else 'conditional' if imp.get('control_depth') else 'top'
            ast_node=ast_imports.get(imp['line'])
            ancestor=parents.get(ast_node)
            while ancestor:
                if isinstance(ancestor,ast.If) and ast.unparse(ancestor.test) in ('TYPE_CHECKING','typing.TYPE_CHECKING'):
                    scope='type_checking';break
                ancestor=parents.get(ancestor)
            key=(module_id,modules[target]['id'])
            rec=import_edges.setdefault(key,dict(**{'from':key[0],'to':key[1]},type='imports',line=imp['line'],scope=scope,scopes=[],count=0))
            rec['count']+=1
            if scope not in rec['scopes']:rec['scopes'].append(scope)
            extra(*key,'IMPORTS',imp['line'],scope=scope,certainty='static_reference')

    for symbol in resolver.symbols:
        if symbol['kind']=='METHOD' and symbol['name'] in ('__getattr__','__getattribute__'):
            cls=resolver.classes.get(symbol['canonical_name'].rsplit('.',1)[0])
            if cls:dynamic.append(dict(**{'from':cls['id']},file=symbol['file'],line=symbol['line'],kind='getattr_hook',expr=symbol['name']))
    dynamic.sort(key=lambda d:(d['from'],d['line'],d['kind']))

    metadata = dict(getattr(symbols,'metadata_sources',{}) or symbols.get('metadata_sources',{}))
    metadata.update({file.removeprefix(repository+'/'):text for file,text in sources.items()})
    for name,module,qual,source in nav.find_console_scripts(Path('/__knitcode_snapshot__'),source_snapshot=metadata,
            syntax_trees={f.removeprefix(repository+'/'):t for f,t in resolver.syntax_trees.items()}):
        for target in resolver.origins.project_symbols(module+'.'+qual):
            entry(target['id'],'console_script',name+' ('+source+')')
    # Explicit public exports and framework decorators use existing imports.
    for file, tree in resolver.syntax_trees.items():
        for stmt in tree.body:
            if isinstance(stmt,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='__all__' for t in stmt.targets):
                for name in nav._literal_strs(stmt.value) or []:
                    ctx=context(file,stmt)
                    for target in resolver._resolve_reference(name,ctx['module'],resolver.imports_at(ctx)):
                        entry(target['id'],'public_api',category='api')
        has_all=any(isinstance(stmt,(ast.Assign,ast.AnnAssign)) and
                    any(isinstance(t,ast.Name) and t.id=='__all__' for t in (stmt.targets if isinstance(stmt,ast.Assign) else [stmt.target]))
                    for stmt in tree.body)
        if file.endswith('/__init__.py') and not has_all:
            for imp in resolver.imports[file]:
                name=imp.get('local_name') or ''
                if name.startswith('_') or name=='*' or imp.get('scope')!='<module>':continue
                for target in resolver.origins.project_symbols(canonical_import(imp)):
                    entry(target['id'],'public_api',category='api',confidence='inferred')
    for s in resolver.symbols:
        if nav._is_test_file(s['file']) and s['name'].startswith('test'):
            cls=resolver.classes.get(s['module']+'.'+s.get('scope',''))
            is_test=(s['kind']=='FUNCTION' and s.get('scope')=='<module>' or
                     s['kind']=='METHOD' and cls and (cls['name'].startswith('Test') or
                         any(b.rsplit('.',1)[-1]=='TestCase' for b in cls.get('bases',[]))))
            if is_test:entry(s['id'],'test',category='test',confidence='heuristic')
        ctx=dict(file=s['file'],module=s['module'],scope=s.get('scope') or '<module>',line=s['line'])
        imports=resolver.imports_at(ctx)
        for decorator in s.get('decorators',[]):
            text=decorator.split('(',1)[0];root,*tail=text.split('.')
            origin='.'.join([imports.get(root,root),*tail])
            if origin in ('click.command','click.group'):
                entry(s['id'],'cli_command',origin,confidence='inferred')
            elif origin in ('pytest.fixture','pytest_asyncio.fixture'):
                entry(s['id'],'fixture',origin,category='test',confidence='inferred')

    from graph_entrypoints import annotate_framework_entries
    annotate_framework_entries(resolver,context,entry)
    entries.sort(key=lambda e: (nav._ENTRY_RANK[e['category']],e['kind'],e['id']))

    # The viewer receives a projection, never independently inferred edges.
    projected={}
    definition_nodes={(file,n.lineno,n.col_offset):n for file,tree in resolver.syntax_trees.items()
                      for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    skip_functions={id(n) for n in definition_nodes.values()}
    for n in nodes.values():
        s=resolver.by_id.get(n['id'],{})
        tree=resolver.syntax_trees.get(n['file'])
        end=s.get('end_line') or (getattr(tree,'knit_total_lines',len(sources.get(n['file'],'').splitlines())) if n['kind']=='MODULE' else n.get('line',1))
        projected[n['id']]=dict(id=n['id'],type={'MODULE':'module','CLASS':'class','METHOD':'method'}.get(n['kind'],'function'),
            name=n['name'],file=n['file'],line=n.get('line',1),end_lineno=end,
            loc=max(1,end-(n.get('line') or 1)+1),parent=None,decorators=s.get('decorators',[]),
            visibility='private' if n['name'].startswith('_') else 'public',complexity=1)
    for nid,p in projected.items():
        if p['type']=='module':continue
        s=resolver.by_id[nid]
        parent=resolver._lookup(s['module']+'.'+s.get('scope','')) if s.get('scope')!='<module>' else []
        p['parent']=next((x['id'] for x in parent if x['id']!=nid),modules[s['module']]['id'])
        definition=definition_nodes.get((s['file'],s['line'],s.get('column',0)))
        if isinstance(definition,(ast.FunctionDef,ast.AsyncFunctionDef)):
            p.update(nav._func_info(definition,nid,p['file'],p['type'],p['parent'],
                                   projected[p['parent']]['type'] in ('function','method')))
            p['complexity']=nav.cyclomatic(definition,skip_functions)
        elif isinstance(definition,ast.ClassDef):
            p.update(nav._class_info(definition,nid,p['file'],p['parent'],projected[p['parent']]['type']!='module'))
            constructors,_=resolver._find_method(s,'__init__')
            p['constructor']=constructors[0]['id'] if len(constructors)==1 else None
    # Decorators execute in the enclosing scope, but navigation also records
    # which definition they decorate. Reuse primary call targets for factories.
    call_facts={c['id']:c for c in resolver.calls}
    decorator_targets=defaultdict(list)
    for edge in graph['edges']:
        call=call_facts.get(edge.get('evidence',{}).get('call_id'))
        if call and call.get('execution_phase')=='definition_decorator' and edge['type']=='CALLS':
            decorator_targets[(call['file'],call['line'])].append(resolver.by_id[edge['target']])
    for symbol in resolver.symbols:
        definition=definition_nodes.get((symbol['file'],symbol['line'],symbol.get('column',0)))
        if definition is None:continue
        for decorator in definition.decorator_list:
            expression=decorator.func if isinstance(decorator,ast.Call) else decorator
            ctx={**symbol,'scope':symbol.get('scope','<module>')}
            targets=list(resolver.object_flow.refs(ast.unparse(expression),ctx,expression))
            for line in range(decorator.lineno,decorator.end_lineno+1):
                targets.extend(decorator_targets.get((symbol['file'],line),[]))
            for target in targets:extra(symbol['id'],target['id'],'REFERENCES',decorator.lineno,certainty='decorator_reference')
    edge_types={'CALLS':'calls','CALLS_IMPLICIT':'calls_implicit','CALLS_OVERRIDE':'calls_override',
                'REFERENCES':'references','INHERITS':'extends','CONTAINS':'contains'}
    edges=[dict(**{'from':e['source'],'to':e['target']},type=edge_types[e['type']],
                line=e.get('evidence',{}).get('line'),via=e.get('evidence',{}).get('implicit_kind'),count=1)
           for e in [*graph['edges'],*graph.get('implicit_edges',[]),*supplemental] if e['type'] in edge_types]
    existing_contains={(e['from'],e['to']) for e in edges if e['type']=='contains'}
    edges += [dict(**{'from':p['parent'],'to':p['id']},type='contains') for p in projected.values()
              if p['parent'] and (p['parent'],p['id']) not in existing_contains]
    edges+=list(import_edges.values())
    cycles=nav.find_import_cycles(list(import_edges.values()))
    for c in cycles:
        for nid in c['modules']:projected[nid].setdefault('import_cycles',[]).append(c['id'])
    nav.annotate_entry_depth(projected,entries,edges)
    nav.compute_importance(projected,edges)
    reading=nav.build_reading_order(projected,entries)
    hierarchy=nav.build_hierarchy({},projected,edges)
    native=dict(schema_version=3,nodes=list(projected.values()),edges=edges,entry_points=entries,
                import_cycles=cycles,dynamic_calls=dynamic,reading_order=reading,hierarchy=hierarchy,
                external_nodes=[],external_edges=[],unresolved=graph.get('unresolved_calls',[]),skipped_files=[],
                summary=dict(files=len(modules),nodes=len(nodes)-len(modules),total_calls=len(resolver.calls),
                             internal_resolved=sum(e['type']=='CALLS' for e in graph['edges'])))
    for field in ('entry_points','reading_order','hierarchy','import_cycles','dynamic_calls'):
        graph[field]=native[field]
    for marker in dynamic:
        projected[marker['from']].setdefault('dynamic',[]).append(marker['kind'])
    for nid,p in projected.items():
        nodes[nid]['navigation_metadata']={k:v for k,v in p.items() if k not in ('id','file','name','type')}
    from ljy_integration import legacy_view
    graph.update(schema_version=3,analysis_profile='integrated',call_graph_policy=call_policy,
                 supplemental_nodes=[],supplemental_edges=supplemental,ljy_result=legacy_view(native,symbols),
                 supplemental_summary=dict(producer='unified',edges=len(supplemental),types=dict(Counter(e['type'] for e in supplemental))),
                 integration_stats=dict(shared_ast_files=sum(f in getattr(symbols,'syntax_trees',{}) for f in sources),
                                        fallback_ast_parses=sum(f not in getattr(symbols,'syntax_trees',{}) for f in sources),snapshot_file_writes=0),
                 integration_contract=dict(semantic_engine='Resolver/ObjectFlow',legacy_analyzer_executed=False,
                                           navigation_ids='Shared primary node IDs',native_export='Projection of unified graph'))
    return graph
