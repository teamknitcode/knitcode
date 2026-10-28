"""Optional read-only GitHub REST enrichment, with bounded requests and partial states."""
import json
import os
import re
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs): return None


class Client:
    def __init__(self, token=None, budget=120):
        self.token = token if token is not None else os.environ.get('GITHUB_TOKEN', '')
        self.budget, self.requests, self.cache = budget, 0, {}
        self.warnings = []
        self.stopped = False

    def get(self, path):
        if path in self.cache: return self.cache[path]
        if self.stopped or self.requests >= self.budget:
            self.warnings.append('API 요청 상한 또는 인증/호출 제한으로 일부 데이터 미수집')
            return None
        self.requests += 1
        headers={'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28','User-Agent':'Knitcode-Git-Insights'}
        if self.token: headers['Authorization']='Bearer '+self.token
        try:
            with build_opener(NoRedirect()).open(Request('https://api.github.com'+path, headers=headers), timeout=20) as response:
                result=json.load(response)
        except HTTPError as exc:
            self.warnings.append(f'API HTTP {exc.code}: {path}')
            if exc.code in (401,429) or (exc.code==403 and (exc.headers.get('X-RateLimit-Remaining')=='0' or exc.headers.get('Retry-After'))): self.stopped=True
            result=None
        except (URLError, TimeoutError, OSError, ValueError):
            self.warnings.append('API 연결/응답 오류: '+path); result=None
        self.cache[path]=result
        return result

    def pages(self, path, key=None, limit=3):
        rows=[]
        for page in range(1,limit+1):
            result=self.get(path+('&' if '?' in path else '?')+f'per_page=100&page={page}')
            if result is None: return {'items':rows,'complete':False}
            items=result.get(key,[]) if key else result
            rows.extend(items)
            if len(items)<100: return {'items':rows,'complete':True}
        self.warnings.append('페이지 상한 적용: '+path)
        return {'items':rows,'complete':False}


def issue_refs(text, repo):
    # A text reference is not proof that an issue was fixed or formally linked.
    refs={(repo,int(n)) for n in re.findall(r'(?<![\w/])#(\d+)\b',text)}
    refs.update((r,int(n)) for r,n in re.findall(r'https://github.com/([\w.-]+/[\w.-]+)/issues/(\d+)',text))
    refs.update((r,int(n)) for r,n in re.findall(r'\b([\w.-]+/[\w.-]+)#(\d+)\b',text))
    return sorted(refs)


def enrich_github(data, max_commits=20, client=None):
    client=client or Client()
    repo=data['repository']; base='/repos/'+repo
    records=[]
    for c in data['commits'][:max_commits]:
        sha=c['sha']; prs=client.pages(base+'/commits/'+sha+'/pulls')
        pulls=[]; texts=[c['message']]
        for p in prs['items']:
            pulls.append({k:p.get(k) for k in ('number','title','body','state','html_url','merged_at')})
            texts.append((p.get('title') or '')+'\n'+(p.get('body') or ''))
        refs=issue_refs('\n'.join(texts),repo); issues=[]
        for target,number in refs[:20]:
            issue=client.get(f'/repos/{target}/issues/{number}')
            if issue and not issue.get('pull_request'):
                issues.append(dict(repository=target, evidence='커밋/PR 텍스트 참조 · 해결 확정 아님', **{k:issue.get(k) for k in ('number','title','body','state','html_url')}))
        checks=client.pages(base+'/commits/'+sha+'/check-runs', 'check_runs')
        statuses=client.pages(base+'/commits/'+sha+'/status','statuses')
        records.append(dict(sha=sha, pulls=pulls, pulls_complete=prs['complete'], issues=issues,
            issue_refs_count=len(refs), issues_lookup_limited=len(refs)>20,
            checks=[{k:r.get(k) for k in ('name','status','conclusion','html_url','head_sha')} for r in checks['items']], checks_complete=checks['complete'],
            statuses=[{k:r.get(k) for k in ('context','state','description','target_url')} for r in statuses['items']], statuses_complete=statuses['complete']))
        if client.stopped or client.requests>=client.budget: break
    data['github'] = dict(enabled=True, records=records, requests=client.requests, commit_limit=max_commits,
        selected_commits=min(max_commits,len(data['commits'])), warnings=list(dict.fromkeys(client.warnings)),
        note='수집 시점의 커밋 SHA별 Checks/Status입니다. PR head의 검사와 다를 수 있으며 빈 결과는 통과를 뜻하지 않습니다. Issue는 텍스트 참조 후보이며 자동 종료/해결 관계를 확정하지 않습니다.')
