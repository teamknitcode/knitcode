"""Entry annotations from the primary engine's symbols, AST and import origins."""
import ast
from collections import defaultdict

_FRAMEWORKS = {
    'flask': {'Flask':'web','Blueprint':'web'},
    'fastapi': {'FastAPI':'web','APIRouter':'web'},
    'sanic': {'Sanic':'web','Blueprint':'web'},
    'quart': {'Quart':'web','Blueprint':'web'},
    'starlette': {'Starlette':'web'}, 'bottle': {'Bottle':'web'},
    'flask_restx': {'Api':'web','Namespace':'web'}, 'flask_restful': {'Api':'web'},
    'typer': {'Typer':'cli'}, 'celery': {'Celery':'task'},
}
_HTTP = {x:x.upper() for x in ('get','post','put','delete','patch','options','head','trace','websocket')}
_HOOKS = {'before_request','after_request','teardown_request','before_first_request','errorhandler',
          'exception_handler','on_event','middleware','context_processor','template_filter','listener','before_app_request','after_app_request'}
_VIEW_BASES = {
    ('flask','MethodView'):_HTTP, ('flask','View'):{'dispatch_request':'ANY'},
    ('flask_restful','Resource'):_HTTP, ('flask_restx','Resource'):_HTTP,
    **{('django',x):_HTTP for x in ('View','TemplateView','RedirectView')},
    **{('rest_framework',x):_HTTP for x in ('APIView','GenericAPIView')},
    **{('rest_framework',x):dict(list='GET',retrieve='GET',create='POST',update='PUT',partial_update='PATCH',destroy='DELETE')
       for x in ('ViewSet','GenericViewSet','ModelViewSet','ReadOnlyModelViewSet')},
    ('starlette','HTTPEndpoint'):_HTTP, ('tornado','RequestHandler'):_HTTP,
}


def annotate_framework_entries(resolver, context, entry):
    def origin(expr, ctx):
        text=ast.unparse(expr);head,*tail=text.split('.')
        imports=resolver.imports_at(ctx)
        # Use the primary origin tracker to reject a parameter/local alias
        # hiding an imported framework name.
        bound, reasons, _=resolver.object_flow.call_origins._bound_at(ctx,head)
        if head not in imports or reasons:return ''
        return '.'.join([imports[head],*tail])

    instances={}
    # Assignment facts already belong to the shared lexical symbol table.
    for (file,scope),assignments in resolver.assignments.items():
        by_name=defaultdict(list)
        for assignment in assignments:
            for name in assignment.get('targets',[]):by_name[name].append(assignment)
        for name, rows in by_name.items():
            if len(rows)!=1:continue
            row=rows[0]
            n=resolver._source_nodes.get(file,{}).get((row['line'],row.get('column',0)))
            value=getattr(n,'value',None)
            if not isinstance(value,ast.Call):continue
            canonical=origin(value.func,context(file,value));parts=canonical.split('.')
            if parts[0] in _FRAMEWORKS and parts[-1] in _FRAMEWORKS[parts[0]]:
                instances[(row['module'],scope,name)]=(parts[0],_FRAMEWORKS[parts[0]][parts[-1]])

    def instance(expr,ctx):
        if not isinstance(expr,ast.Name):return None
        for scope in [*resolver.lexical_scopes(ctx['scope'],ctx['module']),'<module>']:
            found=instances.get((ctx['module'],scope,expr.id))
            if found:return found
        imported=resolver.imports_at(ctx).get(expr.id,'')
        mod,_,name=imported.rpartition('.')
        return instances.get((mod,'<module>',name))

    def refs(expr,ctx):
        return resolver.object_flow.refs(ast.unparse(expr),ctx,expr)

    verified=set();paths=defaultdict(list)
    click_groups=set()
    for symbol in resolver.symbols:
        if any(d.split('(',1)[0] in ('click.command','click.group') for d in symbol.get('decorators',[])):
            click_groups.add(symbol['id'])
    for file,tree in resolver.syntax_trees.items():
        for n in ast.walk(tree):
            ctx=context(file,n)
            if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                candidates=[s for s in resolver.by_id.values() if s['file']==file and s['line']==n.lineno and s['name']==n.name]
                if len(candidates)!=1:continue
                symbol=candidates[0]
                for dec in n.decorator_list:
                    target=dec.func if isinstance(dec,ast.Call) else dec
                    canonical=origin(target,ctx)
                    if canonical in ('celery.shared_task',):entry(symbol['id'],'task',canonical,confidence='inferred')
                    if not isinstance(target,ast.Attribute):continue
                    info=instance(target.value,ctx)
                    attr=target.attr
                    if info:
                        pkg,kind=info
                        args=dec.args if isinstance(dec,ast.Call) else []
                        path=args[0].value if args and isinstance(args[0],ast.Constant) and isinstance(args[0].value,str) else ''
                        if kind=='web' and (attr=='route' or attr in _HTTP):
                            if symbol['kind']=='CLASS':
                                verified.add(symbol['id']);paths[symbol['id']].append(path)
                            else:entry(symbol['id'],'route',_HTTP.get(attr,'GET')+' '+path,category='api',confidence='inferred')
                        elif kind=='web' and attr in _HOOKS:entry(symbol['id'],'web_hook',pkg+' '+attr,category='api',confidence='inferred')
                        elif kind=='cli' and attr in ('command','callback'):entry(symbol['id'],'cli_command',pkg+' '+attr,confidence='inferred')
                        elif kind=='task' and attr=='task':entry(symbol['id'],'task',pkg+' task',confidence='inferred')
                    elif attr in ('command','group') and any(r['id'] in click_groups for r in refs(target.value,ctx)):
                        entry(symbol['id'],'cli_command','click '+attr,confidence='inferred')
            if not isinstance(n,ast.Call):continue
            kws={k.arg:k.value for k in n.keywords}
            view=None;path=''
            if isinstance(n.func,ast.Attribute) and n.func.attr in ('add_url_rule','add_api_route','add_route','add_resource') and (instance(n.func.value,ctx) or ('',''))[1]=='web':
                attr=n.func.attr
                if attr=='add_resource':view=n.args[0] if n.args else None;path_node=n.args[1] if len(n.args)>1 else None
                else:
                    view=kws.get('view_func') or kws.get('endpoint') or (n.args[2] if attr=='add_url_rule' and len(n.args)>2 else n.args[1] if attr!='add_url_rule' and len(n.args)>1 else None)
                    path_node=n.args[0] if n.args else None
            elif origin(n.func,ctx) in ('django.urls.path','django.urls.re_path','django.conf.urls.url') and len(n.args)>1:
                path_node,view=n.args[:2]
            else:continue
            if isinstance(path_node,ast.Constant) and isinstance(path_node.value,str):path=path_node.value
            if view is None:continue
            if isinstance(view,ast.Call) and isinstance(view.func,ast.Attribute) and view.func.attr=='as_view':view=view.func.value
            for symbol in refs(view,ctx):
                if symbol['kind']=='CLASS':verified.add(symbol['id']);paths[symbol['id']].append(path)
                else:entry(symbol['id'],'route','GET '+path,category='api',confidence='inferred')
    for cls in resolver.classes.values():
        spec=None
        order,_=resolver._mro(cls)
        pending=[cls];seen=set()
        while pending:
            parent=pending.pop()
            if parent['canonical_name'] in seen:continue
            seen.add(parent['canonical_name'])
            pending.extend(resolver._get_bases(parent))
        for name in order or sorted(seen):
            parent=resolver.classes.get(name)
            if not parent:continue
            for base in parent.get('bases',[]):
                try:expr=ast.parse(base,mode='eval').body
                except SyntaxError:continue
                ctx=dict(file=parent['file'],module=parent['module'],scope=parent.get('scope','<module>'),line=parent['line'])
                canonical=origin(expr,ctx).split('.')
                spec=spec or _VIEW_BASES.get((canonical[0],canonical[-1]))
        if not spec and cls['id'] not in verified:continue
        for method in resolver.symbols:
            if method['kind']=='METHOD' and method['canonical_name'].rsplit('.',1)[0]==cls['canonical_name'] and method['name'] in (spec or _HTTP):
                entry(method['id'],'route',(spec or _HTTP)[method['name']]+' '+', '.join(paths[cls['id']]),category='api',confidence='inferred')
