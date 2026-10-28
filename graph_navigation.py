"""Pure graph navigation algorithms extracted from Lee Jeongyeon's implementation.

Consumes the unified engine's graph; does not discover symbols or resolve calls.
"""
import ast
from pathlib import Path
from collections import Counter, defaultdict, deque
IMPORT_SCOPES = ("top", "conditional", "function", "type_checking")
_IMPORT_TIME_SCOPES = {"top", "conditional"}
CYCLE_LEVELS = (("import_time", _IMPORT_TIME_SCOPES), ("deferred", _IMPORT_TIME_SCOPES | {"function"}), ("type_only", set(IMPORT_SCOPES)))
CALL_LIKE = ("calls", "calls_override", "calls_implicit", "references")
READING_NODES = 40
_ENTRY_RANK = {"runtime": 0, "api": 1, "test": 2}
HIERARCHY_LEVELS = ("package", "module", "class", "function")


def _literal_strs(node):
    if isinstance(node, (ast.List, ast.Tuple)) and all(isinstance(e, ast.Constant) and isinstance(e.value, str)
                                                         for e in node.elts):
        return [e.value for e in node.elts]
    return None

def _tarjan_sccs(graph):
    """강연결 요소 (반복형 Tarjan).  graph: 노드 -> 정렬된 이웃 리스트.  크기 2 이상인 것만 돌려준다"""
    index, low, on, stack, out, counter = {}, {}, set(), [], [], [0]
    for start in sorted(graph):
        if start in index:
            continue
        work = [(start, 0)]
        index[start] = low[start] = counter[0]
        counter[0] += 1
        stack.append(start)
        on.add(start)
        while work:
            v, i = work[-1]
            nbrs = graph.get(v, [])
            if i < len(nbrs):
                work[-1] = (v, i + 1)
                w = nbrs[i]
                if w not in index:
                    index[w] = low[w] = counter[0]
                    counter[0] += 1
                    stack.append(w)
                    on.add(w)
                    work.append((w, 0))
                elif w in on:
                    low[v] = min(low[v], index[w])
            else:
                work.pop()
                if work:
                    low[work[-1][0]] = min(low[work[-1][0]], low[v])
                if low[v] == index[v]:
                    comp = []
                    while True:
                        w = stack.pop()
                        on.discard(w)
                        comp.append(w)
                        if w == v:
                            break
                    if len(comp) > 1:
                        out.append(sorted(comp))
    return out

def _shortest_cycle(start, graph, members):
    """start 에서 출발해 start 로 돌아오는 가장 짧은 경로 [start, ..., start]"""
    prev, dq = {start: None}, deque([start])
    while dq:
        v = dq.popleft()
        for w in graph.get(v, []):
            if w not in members:
                continue
            if w == start:
                path = []
                while v is not None:
                    path.append(v)
                    v = prev[v]
                return path[::-1] + [start]
            if w not in prev:
                prev[w] = v
                dq.append(w)
    return [start]

def find_import_cycles(import_edges):
    """모듈 import 간선에서 순환(강연결 요소)을 찾는다.  더 약한 조건에서 이미 보고된 같은 모듈 묶음은 다시 보고하지 않는다"""
    reported, cycles = set(), []
    for kind, allowed in CYCLE_LEVELS:
        use = [e for e in import_edges if set(e["scopes"]) & allowed]
        graph = defaultdict(set)
        for e in use:
            graph[e["from"]].add(e["to"])
        graph = {k: sorted(v) for k, v in graph.items()}
        for comp in _tarjan_sccs(graph):
            key = frozenset(comp)
            if key in reported:
                continue
            reported.add(key)
            members = set(comp)
            cycles.append({"kind": kind, "modules": comp, "size": len(comp),
                           "path": _shortest_cycle(comp[0], graph, members),
                           "edges": [{"from": e["from"], "to": e["to"], "scope": e["scope"], "line": e["line"]}
                                     for e in sorted(use, key=lambda e: (e["from"], e["to"]))
                                     if e["from"] in members and e["to"] in members]})
    order = {k: i for i, (k, _) in enumerate(CYCLE_LEVELS)}
    cycles.sort(key=lambda c: (order[c["kind"]], c["size"], c["modules"]))
    for i, c in enumerate(cycles, 1):
        c["id"] = f"cycle:{i}"
    return [{"id": c["id"], **{k: v for k, v in c.items() if k != "id"}} for c in cycles]

def _split_target(target):
    target = target.split("[")[0].strip().strip("'\"")
    if ":" not in target:
        return None
    m, _, f = target.partition(":")
    m, f = m.strip(), f.strip()
    return (m, f) if m and f else None

def find_console_scripts(root, source_snapshot=None, syntax_trees=None):
    """setup.py / setup.cfg / pyproject.toml 에 적힌 실행 명령 -> [(명령 이름, 모듈, 함수, 출처 파일)]
    분석 폴더에서 시작해 설정 파일이 있는 폴더(또는 .git 이 있는 폴더)까지 최대 3단계 위로 찾는다"""
    import configparser
    import re
    root = Path(root)
    def exists(path):
        if source_snapshot is None:
            return path.exists()
        try:
            return path.relative_to(root).as_posix() in source_snapshot
        except ValueError:
            return False
    def read(path):
        return (path.read_text(encoding='utf-8') if source_snapshot is None
                else source_snapshot[path.relative_to(root).as_posix()])
    dirs, d = [], root
    for _ in range(4):
        dirs.append(d)
        if exists(d / ".git") or any(exists(d / f) for f in ("setup.py", "setup.cfg", "pyproject.toml")) \
                or d.parent == d:
            break
        d = d.parent
    out = []

    def add(name, target, src):
        tm = _split_target(target)
        if tm:
            out.append((name, tm[0], tm[1], src))

    for d in dirs:
        sp = d / "setup.py"
        if exists(sp):
            try:
                tree = (syntax_trees or {}).get(sp.relative_to(root).as_posix())
                if tree is None:
                    tree = ast.parse(read(sp))
            except (SyntaxError, UnicodeDecodeError, ValueError, OSError):
                tree = None
            for c in (n for n in ast.walk(tree) if isinstance(n, ast.Call)) if tree else ():
                fname = c.func.id if isinstance(c.func, ast.Name) else (c.func.attr if isinstance(c.func, ast.Attribute) else None)
                if fname != "setup":
                    continue
                for kw in c.keywords:
                    if kw.arg == "entry_points" and isinstance(kw.value, ast.Dict):
                        for k, v in zip(kw.value.keys, kw.value.values):
                            if isinstance(k, ast.Constant) and k.value in ("console_scripts", "gui_scripts"):
                                for spec in _literal_strs(v) or []:
                                    name, _, tgt = spec.partition("=")
                                    add(name.strip(), tgt or name, "setup.py")
        cfg = d / "setup.cfg"
        if exists(cfg):
            cp = configparser.RawConfigParser(strict=False)
            try:
                if source_snapshot is None:
                    cp.read(cfg, encoding="utf-8")
                else:
                    cp.read_string(read(cfg))
            except (configparser.Error, UnicodeDecodeError, OSError):
                pass
            if cp.has_section("options.entry_points"):
                for key in ("console_scripts", "gui_scripts"):
                    for line in cp.get("options.entry_points", key, fallback="").splitlines():
                        if "=" in line:
                            name, _, tgt = line.partition("=")
                            add(name.strip(), tgt, "setup.cfg")
        pp = d / "pyproject.toml"
        if exists(pp):
            try:
                text = read(pp)
            except (UnicodeDecodeError, OSError):
                text = ""
            section = None
            for line in text.splitlines():
                s = line.strip()
                m = re.match(r"^\[([^\[\]]+)\]\s*(#.*)?$", s)
                if m:
                    section = m.group(1).strip()
                elif section in ("project.scripts", "project.gui-scripts", "tool.poetry.scripts"):
                    m2 = re.match(r"""^["']?([\w.\-]+)["']?\s*=\s*["']([^"']+)["']""", s)
                    if m2:
                        add(m2.group(1), m2.group(2), "pyproject.toml")
    return out

def _is_test_file(rel):
    parts = rel.split("/")
    return parts[-1].startswith("test_") or parts[-1].endswith("_test.py") or any(p in ("tests", "test") for p in parts[:-1])

def annotate_entry_depth(nodes, entries, edges):
    """노드에 entry(어떤 진입점인지)와 entry_depth(가장 가까운 진입점에서 호출 간선으로 몇 걸음인지)를 기록한다.
    테스트 진입점은 출발점에서 뺀다 (테스트가 부르는 코드와 실제 실행 경로를 섞지 않기 위해).
    도달할 수 없으면 None, 진입점이 아예 없는 프로젝트는 모두 None"""
    kinds = defaultdict(list)
    for e in entries:
        if e["kind"] not in kinds[e["id"]]:
            kinds[e["id"]].append(e["kind"])
    adj = defaultdict(set)
    for e in edges:
        if e["type"] in CALL_LIKE:
            adj[e["from"]].add(e["to"])
    depth = {}
    dq = deque()
    for e in entries:
        if e["category"] != "test" and e["id"] not in depth:
            depth[e["id"]] = 0
            dq.append(e["id"])
    while dq:
        v = dq.popleft()
        for w in sorted(adj.get(v, ())):
            if w not in depth:
                depth[w] = depth[v] + 1
                dq.append(w)
    for nid, n in nodes.items():
        if nid in kinds:
            n["entry"] = kinds[nid]
        if n["type"] != "module":
            n["entry_depth"] = depth.get(nid)
    return sum(1 for nid, n in nodes.items() if n["type"] != "module" and n["entry_depth"] is not None)

def compute_importance(nodes, edges, damping=0.85, iters=100):
    ids = sorted(nid for nid, n in nodes.items() if n["type"] != "module")
    idx = {nid: i for i, nid in enumerate(ids)}
    out = defaultdict(lambda: defaultdict(float))
    for e in edges:
        if e["type"] not in CALL_LIKE and e["type"] != "extends":
            continue
        a, b = e["from"], e["to"]
        if a not in idx or b not in idx or a == b or _is_test_file(nodes[a]["file"]):
            continue
        out[a][b] += e.get("count", 1)
    n = len(ids)
    if not n:
        return 0
    rank = [1.0 / n] * n
    for _ in range(iters):
        nxt = [(1 - damping) / n] * n
        dangling = 0.0
        for nid in ids:
            i = idx[nid]
            tot = sum(out[nid].values()) if nid in out else 0
            if not tot:
                dangling += rank[i]
                continue
            for b, w in out[nid].items():
                nxt[idx[b]] += damping * rank[i] * w / tot
        share = damping * dangling / n
        nxt = [x + share for x in nxt]
        done = sum(abs(x - y) for x, y in zip(nxt, rank)) < 1e-10
        rank = nxt
        if done:
            break
    top = max(rank) or 1.0
    per_file = Counter()
    for nid in ids:
        nodes[nid]["importance"] = round(rank[idx[nid]] / top, 4)
        per_file[nodes[nid]["file"]] += rank[idx[nid]]
    ftop = max(per_file.values()) or 1.0
    for nid, nd in nodes.items():
        if nd["type"] == "module":
            nd["importance"] = round(per_file[nd["file"]] / ftop, 4)
    return n

def build_reading_order(nodes, entries, limit=READING_NODES):
    """처음 읽을 파일(modules)과 함수·클래스(nodes)를 순서대로 돌려준다.  테스트 파일은 뺀다"""
    best_entry = {}                                                   # 노드 -> (가장 앞선 category 순위, 종류들)
    for e in entries:
        if e["category"] == "test":
            continue
        rank, kinds = best_entry.get(e["id"], (9, []))
        best_entry[e["id"]] = (min(rank, _ENTRY_RANK[e["category"]]), kinds + ([e["kind"]] if e["kind"] not in kinds else []))
    INF = 10 ** 6
    syms = [n for n in nodes.values() if n["type"] != "module" and not _is_test_file(n["file"])]

    def depth(n):
        return n["entry_depth"] if n.get("entry_depth") is not None else INF

    def why(n):
        out = []
        if n["id"] in best_entry:
            out.append("진입점: " + ", ".join(best_entry[n["id"]][1]))
        elif n.get("entry_depth") is not None:
            out.append(f"진입점에서 {n['entry_depth']}걸음")
        else:
            out.append("진입점에서 호출로 닿지 않음")
        if n.get("importance", 0) >= 0.5:
            out.append("많은 코드가 기대는 핵심")
        return out

    by_file = defaultdict(list)
    for n in syms:
        by_file[n["file"]].append(n)
    mods = []
    for m in nodes.values():
        if m["type"] != "module":
            continue
        inside = by_file.get(m["file"], [])
        mod_entry = m["id"] in best_entry
        if not inside and not mod_entry:
            continue                                                  # 내용 없는 파일(빈 __init__.py 등)
        d = min([depth(n) for n in inside] + ([0] if mod_entry else [INF]))
        first = sorted(inside, key=lambda n: (depth(n), best_entry.get(n["id"], (9,))[0], -n.get("importance", 0), n["id"]))[:3]
        reasons = []
        kinds = sorted({k for n in inside for k in best_entry.get(n["id"], (9, []))[1]} |
                       set(best_entry.get(m["id"], (9, []))[1]))
        if kinds:
            reasons.append("진입점: " + ", ".join(kinds))
        elif d < INF:
            reasons.append(f"진입점에서 {d}걸음")
        else:
            reasons.append("진입점에서 호출로 닿지 않음")
        if m.get("importance", 0) >= 0.5:
            reasons.append("많은 코드가 기대는 핵심 파일")
        if m.get("import_cycles"):
            reasons.append("순환 import 에 포함")
        mods.append({"id": m["id"], "min_depth": None if d >= INF else d, "importance": m.get("importance", 0),
                     "entry": kinds, "read_first": [n["id"] for n in first], "reasons": reasons})
    mods.sort(key=lambda x: (x["min_depth"] is None, x["min_depth"] or 0, -x["importance"], x["id"]))
    for i, x in enumerate(mods, 1):
        x["rank"] = i
    ordered = sorted(syms, key=lambda n: (depth(n), best_entry.get(n["id"], (9,))[0], -n.get("importance", 0), n["id"]))
    picked = [{"rank": i, "id": n["id"], "depth": n.get("entry_depth"), "importance": n.get("importance", 0),
               "entry": best_entry.get(n["id"], (9, []))[1], "reasons": why(n)} for i, n in enumerate(ordered[:limit], 1)]
    return {"strategy": "진입점에서 가까운 순서, 같은 거리에서는 중요도(PageRank) 순서. 테스트 파일은 제외",
            "modules": mods, "nodes": picked}

def _pkg_of(rel):
    d = rel.rpartition("/")[0]
    return d + "/" if d else "./"

def _pkg_parent(pid):
    if pid == "./":
        return None
    return _pkg_of(pid.rstrip("/"))

def _graph_metrics(unit_ids, edges, internal):
    """단위별 결합도 지표를 계산해 {uid: {...}} 로 돌려준다"""
    w_in, w_out, n_in, n_out = Counter(), Counter(), defaultdict(set), defaultdict(set)
    for e in edges:
        w_out[e["from"]] += e["weight"]
        w_in[e["to"]] += e["weight"]
        n_out[e["from"]].add(e["to"])
        n_in[e["to"]].add(e["from"])
    out = {}
    for u in unit_ids:
        fi, fo = len(n_in[u]), len(n_out[u])
        out[u] = {"in_weight": w_in[u], "out_weight": w_out[u], "internal_weight": internal.get(u, 0),
                  "fan_in": fi, "fan_out": fo, "instability": round(fo / (fi + fo), 3) if fi + fo else None}
    return out

def _edge_list(acc):
    out = []
    for (a, b), v in acc.items():
        e = {"from": a, "to": b, "weight": v["weight"], "by_type": dict(sorted(v["by_type"].items()))}
        if v["extends"]:
            e["extends"] = v["extends"]
        if v["import_weight"]:
            e["import_weight"] = v["import_weight"]
        out.append(e)
    out.sort(key=lambda e: (-e["weight"], -e.get("import_weight", 0), e["from"], e["to"]))
    return out

def build_hierarchy(files, nodes, edges):
    """edges: calls·extra·structure 간선 전부.  반환: {"levels", "units", "edges": {층: [...]}}"""
    def top_unit(nid):                                            # 모듈 바로 아래(최상위 클래스·함수)까지 올라간다
        while nid and nodes[nid]["type"] != "module":
            p = nodes[nid]["parent"]
            if p is None or nodes[p]["type"] == "module":
                return nid
            nid = p
        return None

    def unit_of(level, nid):
        n = nodes[nid]
        if level == "function":
            return nid if n["type"] in ("function", "method") else None
        if level == "class":
            return top_unit(nid)
        if level == "module":
            return n["file"]
        return _pkg_of(n["file"])

    acc = {lv: defaultdict(lambda: {"weight": 0, "by_type": Counter(), "extends": 0, "import_weight": 0})
           for lv in HIERARCHY_LEVELS}
    internal = {lv: Counter() for lv in HIERARCHY_LEVELS}
    for e in edges:
        t = e["type"]
        if t in CALL_LIKE:
            w, levels = e.get("count", 1), HIERARCHY_LEVELS
        elif t == "extends":
            w, levels = 1, ("package", "module", "class")
        elif t == "imports":
            w, levels = e.get("count", 1), ("package", "module")
        else:
            continue
        for lv in levels:
            a, b = unit_of(lv, e["from"]), unit_of(lv, e["to"])
            if a is None or b is None:
                continue
            if a == b:
                if t in CALL_LIKE:
                    internal[lv][f"{lv}:{a}"] += w
                continue
            rec = acc[lv][(f"{lv}:{a}", f"{lv}:{b}")]
            if t in CALL_LIKE:
                rec["weight"] += w
                rec["by_type"][t] += w
            elif t == "extends":
                rec["extends"] += w
            else:
                rec["import_weight"] += w

    units = {}                                                    # uid -> 단위

    def unit(level, uid_id, name, kind, parent_uid):
        u = units.setdefault(f"{level}:{uid_id}", {"uid": f"{level}:{uid_id}", "level": level, "id": uid_id,
                                                   "name": name, "kind": kind, "parent": parent_uid,
                                                   "loc": 0, "modules": 0, "functions": 0, "classes": 0,
                                                   "complexity": 0})
        return u

    for n in sorted((n for n in nodes.values() if n["type"] == "module"), key=lambda x: x["file"]):
        rel = n["file"]
        pid = _pkg_of(rel)
        while pid:                                                # 폴더 사슬
            par = _pkg_parent(pid)
            unit("package", pid, pid.rstrip("/").rpartition("/")[2] or ".", "package", f"package:{par}" if par else None)
            pid = par
        pu = units[f"package:{_pkg_of(rel)}"]
        pu["loc"] += n["loc"]
        pu["modules"] += 1
        mu = unit("module", rel, rel.rpartition("/")[2], "module", f"package:{_pkg_of(rel)}")
        mu["loc"] = n["loc"]
        mu["modules"] = 1
    for nid, n in sorted(nodes.items()):
        if n["type"] == "module":
            continue
        mod_rel = n["file"]
        tu = top_unit(nid)
        is_func = n["type"] in ("function", "method")
        if tu == nid:                                             # 최상위 클래스·함수
            cu = unit("class", nid, n["name"], "class" if n["type"] == "class" else "function", f"module:{mod_rel}")
            cu["loc"] = n["loc"]
        if is_func:
            parent = nodes[n["parent"]]
            if parent["type"] == "module":
                par_uid = f"class:{nid}"
            elif parent["type"] == "class":
                par_uid = f"class:{tu}"
            else:
                par_uid = f"function:{n['parent']}"
            fu = unit("function", nid, n["name"], n["type"], par_uid)
            fu["loc"], fu["functions"], fu["complexity"] = n["loc"], 1, n.get("complexity", 0)
            for lv_uid in (f"module:{mod_rel}", f"package:{_pkg_of(mod_rel)}", f"class:{tu}"):
                if lv_uid in units:
                    units[lv_uid]["functions"] += 1
                    units[lv_uid]["complexity"] += n.get("complexity", 0)
        else:
            for lv_uid in (f"module:{mod_rel}", f"package:{_pkg_of(mod_rel)}"):
                units[lv_uid]["classes"] += 1
            if tu == nid:
                units[f"class:{nid}"]["classes"] = 1
    # 폴더 단위의 loc 등은 '그 폴더에 직접 들어 있는 파일' 기준이고, 하위 폴더까지 합친 값은 total_* 로 따로 둔다
    for lv in ("package",):
        for u in units.values():
            if u["level"] == lv:
                u["total_loc"], u["total_modules"] = u["loc"], u["modules"]
        for u in sorted((x for x in units.values() if x["level"] == lv), key=lambda x: -len(x["id"])):
            if u["parent"]:
                units[u["parent"]]["total_loc"] += u["total_loc"]
                units[u["parent"]]["total_modules"] += u["total_modules"]

    out_edges = {lv: _edge_list(acc[lv]) for lv in HIERARCHY_LEVELS}
    for lv in HIERARCHY_LEVELS:
        ids = [u["uid"] for u in units.values() if u["level"] == lv]
        m = _graph_metrics(ids, out_edges[lv], internal[lv])
        for uid in ids:
            units[uid].update(m[uid])
    kids = Counter(u["parent"] for u in units.values() if u["parent"])
    for u in units.values():
        u["children"] = kids[u["uid"]]
    ordered = sorted(units.values(), key=lambda u: (HIERARCHY_LEVELS.index(u["level"]), u["id"]))
    return {"levels": list(HIERARCHY_LEVELS), "units": ordered, "edges": out_edges}

def rollup_packages(hierarchy, depth):
    """폴더 층을 경로 깊이 `depth` 까지만 남기고 합친다 (depth=0 은 프로젝트 전체, 1 은 최상위 폴더 단위).
    반환: {"depth", "units", "edges"}  — 합쳐지며 같은 단위 안이 된 호출은 internal_weight 로 옮겨진다"""
    def cut(pid):
        parts = [p for p in pid.split("/") if p]
        return "/".join(parts[:depth]) + "/" if parts[:depth] else "./"

    pk = {u["uid"]: u for u in hierarchy["units"] if u["level"] == "package"}
    units, internal = {}, Counter()
    for u in pk.values():
        c = cut(u["id"])
        r = units.setdefault(f"package:{c}", {"uid": f"package:{c}", "level": "package", "id": c, "loc": 0,
                                              "modules": 0, "functions": 0, "classes": 0, "complexity": 0})
        for k in ("loc", "modules", "functions", "classes", "complexity"):
            r[k] += u[k]
        internal[r["uid"]] += u["internal_weight"]
    acc = defaultdict(lambda: {"weight": 0, "by_type": Counter(), "extends": 0, "import_weight": 0})
    for e in hierarchy["edges"]["package"]:
        a, b = f"package:{cut(pk[e['from']]['id'])}", f"package:{cut(pk[e['to']]['id'])}"
        if a == b:
            internal[a] += e["weight"]
            continue
        rec = acc[(a, b)]
        rec["weight"] += e["weight"]
        for t, v in e["by_type"].items():
            rec["by_type"][t] += v
        rec["extends"] += e.get("extends", 0)
        rec["import_weight"] += e.get("import_weight", 0)
    edges = _edge_list(acc)
    m = _graph_metrics(list(units), edges, internal)
    for uid, u in units.items():
        u.update(m[uid])
    return {"depth": depth, "units": sorted(units.values(), key=lambda u: u["id"]), "edges": edges}

FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)
_BRANCH_NODES = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.IfExp, ast.ExceptHandler)

def _decorator_names(n):
    out = []
    for d in n.decorator_list:
        out.append(_short(ast.unparse(d), 60))
    return out

def _dec_base(d):
    """데코레이터 표현식의 마지막 이름: @a.b(x) -> 'b'"""
    if isinstance(d, ast.Call):
        d = d.func
    return d.id if isinstance(d, ast.Name) else (d.attr if isinstance(d, ast.Attribute) else None)

def _visibility(name):
    if name.startswith("__") and name.endswith("__"):
        return "dunder"
    return "private" if name.startswith("_") else "public"

def _doc_first_line(n):
    doc = ast.get_docstring(n, clean=True)
    if not doc:
        return None
    first = doc.strip().splitlines()[0].strip() if doc.strip() else ""
    return _short(first, 120) or None

def cyclomatic(fn, skip_ids=frozenset()):
    """순환 복잡도 = 1 + 분기 수 (if / for / while / except / 삼항 / and·or / 컴프리헨션의 for·if / match case).
    별도 노드로 수집된 중첩 함수의 본문은 세지 않는다"""
    c = 1
    for n in own_walk(fn, skip_ids):
        if isinstance(n, _BRANCH_NODES):
            c += 1
        elif isinstance(n, ast.BoolOp):
            c += len(n.values) - 1
        elif isinstance(n, ast.comprehension):
            c += 1 + len(n.ifs)
        elif type(n).__name__ == "match_case":
            c += 1
    return c

def own_walk(fn, skip_ids=frozenset()):
    """fn 자신의 코드만 너비 우선으로 훑는다. skip_ids 에 있는 함수 정의(= 별도 노드가 된 중첩 함수·메서드)는 들어가지 않는다"""
    todo = deque([fn])
    while todo:
        node = todo.popleft()
        yield node
        for child in ast.iter_child_nodes(node):
            if isinstance(child, FUNC_TYPES) and id(child) in skip_ids:
                continue
            todo.append(child)

def _method_kind(n):
    bases = {_dec_base(d) for d in n.decorator_list}
    if "staticmethod" in bases:
        return "static"
    if "classmethod" in bases:
        return "class"
    if bases & {"property", "cached_property", "setter", "getter", "deleter"}:
        return "property"
    return "instance"

def _func_info(n, nid, rel, ntype, parent, nested, skip_ids=frozenset()):
    end = getattr(n, "end_lineno", None) or n.lineno
    info = {"id": nid, "type": ntype, "file": rel, "line": n.lineno, "end_lineno": end, "loc": end - n.lineno + 1,
            "name": n.name, "signature": f"({ast.unparse(n.args)})" + (f" -> {ast.unparse(n.returns)}" if n.returns else ""),
            "docstring": _doc_first_line(n), "decorators": _decorator_names(n),
            "is_async": isinstance(n, ast.AsyncFunctionDef), "visibility": _visibility(n.name),
            "parent": parent}
    if ntype == "method":
        info["kind"] = _method_kind(n)
    if nested:
        info["nested"] = True
    return info

def _class_info(n, cid, rel, parent, nested):
    end = getattr(n, "end_lineno", None) or n.lineno
    info = {"id": cid, "type": "class", "file": rel, "line": n.lineno, "end_lineno": end, "loc": end - n.lineno + 1,
            "name": n.name, "bases": [_short(ast.unparse(b), 60) for b in n.bases],
            "docstring": _doc_first_line(n), "decorators": _decorator_names(n),
            "visibility": _visibility(n.name), "parent": parent}
    if nested:
        info["nested"] = True
    return info

def _short(text, n=80):
    return text if len(text) <= n else text[:n - 3] + "..."
