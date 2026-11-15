# JARVIS 벤치마크 비교와 정적분석 개선 (2026-11-15)

## 결론

1. **JARVIS 벤치마크를 같은 채점기로 재현했다.** JARVIS 아티팩트에 포함된 PyCG·JARVIS 출력을 논문 채점 코드(`reproducing_RQ2/gen_table.py`)와 같은 규칙으로 다시 채점해 논문 Table V의 E.A. 평균(PyCG 0.99/0.76, JARVIS 0.99~1.00/0.82)을 그대로 얻었다. KnitCode는 같은 입력·같은 채점기로 평가한다.
2. **엔진 개선 8가지로 누락이 줄었다.** JARVIS macro 6개 합산 재현율 **69.1% → 74.7%**(JARVIS 77.6%, PyCG 72.4%), JARVIS micro 누락 **81 → 66**, PyCG micro Sound **71 → 78/112**. PyCG macro 5개는 asciinema F1 82.70 → 83.08, autojump 81.89 → 81.80, 나머지 3개는 예측 간선 집합까지 동일하다.
3. **정밀도는 JARVIS·PyCG보다 낮다(합산 87.8% vs 99.4%/99.3%).** 다만 무작위로 확인한 오탐 26개는 모두 소스상 실행될 수 있는 호출이었다. JARVIS 정답은 property 접근, `__setattr__`, `with`의 `__enter__/__exit__` 같은 암묵 호출과 리스트에 담아 부르는 함수 호출을 일관되게 표시하지 않는다(아래 "정답 감사"). **이 정밀도 차이를 KnitCode의 오류로만 해석하면 안 되지만, 정답 보정 없이 "KnitCode가 더 정확하다"고 주장할 근거도 아니다.**

PyCG·JARVIS를 전반적으로 능가했다고 결론 내리지 않는다. micro Sound(JARVIS 기준 98/138)는 JARVIS(134/138)와 PyCG(126/138)에 여전히 못 미친다.

## 1. 벤치마크와 채점

| 항목 | 내용 |
|---|---|
| 출처 | [pythonJaRvis/pythonJaRvis.github.io](https://github.com/pythonJaRvis/pythonJaRvis.github.io) `Jarvis/` (데이터·정답·PyCG/JARVIS 출력·채점 스크립트) |
| micro | 22개 범주 138개 예제. PyCG micro 112개에 `context_managers`, `new_*` 범주 추가 |
| macro | bpytop, sqlparse, TextRank4ZH, furl, rich-cli, sshtunnel (587~5,687줄) |
| 모드 | **E.A.**: 모든 함수를 진입점으로, 애플리케이션 코드만. KnitCode의 분석 방식과 같은 조건 |
| 입력 | `reproducing_RQ12_setup/macro_benchmark/pycg_EA.sh`와 같은 파일·패키지 루트. JARVIS 쪽 스크립트는 furl 결과를 sshtunnel 폴더에 쓰는 등 경로 오류가 있어 따르지 않음 |
| 채점 | `gen_table.py`와 동일: 호출자별 TP 합, FP = 예측 간선 − TP, FN = 정답 간선 − TP. micro C.=FP 없음, S.=FN 없음 |
| 실행 | `python scripts/jarvis_benchmark.py {micro,macro} --jarvis <Jarvis 폴더> --output <경로>` |

### 표기·관례 맞춤 (정답을 보지 않는 규칙)

JARVIS 정답과 KnitCode 출력은 "무엇을 호출로 세는가"의 관례가 다르다. 정답 파일을 보고 간선을 고치지 않고, 아래 규칙만 적용한다. 표에는 **원점수(raw, 표기만 맞춤)**와 **관례 맞춤 점수**를 함께 싣는다.

| 규칙 | 내용 | 적용 |
|---|---|---|
| 내장 타입 표기 | `<**PyStr**>.join` → `<str>.join`, `<**PyDict**>` → `<map>`, `<**PyList**>` → `<list>` | raw·관례 |
| 외부 라이브러리 호출 제외 | `os.path.join` 등. E.A.에서는 정답·PyCG·JARVIS 출력 모두 앱 함수와 내장 함수만 포함 | raw·관례 (`--keep-library-calls`로 끌 수 있음) |
| 클래스 본문 호출자 | 클래스 본문에서 실행되는 호출의 호출자를 모듈 대신 `mod.Cls`로 표기 | 관례 |
| 모듈 import 간선 | 프로젝트 모듈을 import하면 그 모듈 본문이 실행됨: `importer → imported`. 상대 import 포함 | 관례, **macro만** (JARVIS micro 정답은 PyCG에서 물려받아 import 간선이 없고, macro 정답에는 있다) |
| 내장 데코레이터 | `@classmethod`/`@staticmethod`/`@property` → `<builtin>.classmethod` 등 | 관례 (PyCG 정답에는 없어 PyCG 평가에는 쓰지 않음) |

## 2. 결과

### macro (E.A.) — 정밀도 / 재현율 (TP/FP/FN)

| 프로젝트 | 줄 | KnitCode 변경 전 (관례) | **KnitCode 변경 후 (관례)** | 변경 후 raw | PyCG E.A.(m) | JARVIS E.A. |
|---|---:|---|---|---|---|---|
| bpytop | 5,687 | 0.92 / 0.79 (491/43/127) | **0.92 / 0.85** (523/45/95) | 0.90 / 0.77 | 0.99 / 0.84 | 0.99 / 0.92 |
| sqlparse | 3,803 | 0.90 / 0.60 (365/39/247) | **0.90 / 0.60** (365/39/247) | 0.89 / 0.50 | 0.99 / 0.62 | 0.99 / 0.64 |
| TextRank4ZH | 587 | 0.93 / 0.88 (69/5/9) | **0.93 / 0.88** (69/5/9) | 0.92 / 0.77 | 1.00 / 0.87 | 1.00 / 0.95 |
| furl | 2,104 | 0.91 / 0.53 (169/16/150) | **0.75 / 0.76** (242/80/77) | 0.74 / 0.72 | 0.99 / 0.61 | 1.00 / 0.63 |
| rich-cli | 1,112 | 0.91 / 0.79 (48/5/13) | **0.91 / 0.79** (48/5/13) | 0.90 / 0.72 | 0.96 / 0.82 | 1.00 / 0.95 |
| sshtunnel | 1,929 | 0.88 / 0.83 (142/19/29) | **0.88 / 0.83** (142/19/29) | 0.88 / 0.81 | 1.00 / 0.80 | 1.00 / 0.85 |
| 평균 | | 0.91 / 0.74 | **0.88 / 0.78** | 0.87 / 0.72 | 0.99 / 0.76 | 1.00 / 0.82 |
| 합산 (간선 1,859) | | 0.910 / 0.691 | **0.878 / 0.747** | 0.862 / 0.676 | 0.993 / 0.724 | 0.994 / 0.776 |

- 변경 전 "관례" 열은 현재 어댑터로 변경 전 엔진(`--engine-root`)을 다시 채점한 값이다.
- PyCG E.A.(1)과 E.A.(m)은 6개 모두 같다. 논문 표의 값과 일치한다.
- KnitCode 재현율은 furl에서 JARVIS보다, bpytop·TextRank4ZH·furl·sshtunnel에서 PyCG보다 높다. sqlparse·rich-cli는 둘 다보다 낮다. 정밀도는 6개 모두 두 도구보다 낮다.

### micro — JARVIS 138개 (raw 표기 기준 TP/FP/FN)

| 도구 | C. | S. | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| PyCG (논문 표) | 113 | 126 | 317 | 27 | 27 |
| JARVIS (논문 표) | 132 | 134 | 335 | 7 | 9 |
| KnitCode 변경 전 | 130 | 92 | 263 | 9 | 81 |
| **KnitCode 변경 후** | **130** | **98** | **278** | **9** | **66** |

범주별 변화: exceptions TP 0→3 (S. 0→3), generators TP 12→16 (S. 1→4), decorators TP 3→11, classes TP 62→63. 표의 KnitCode 값은 관례 맞춤(클래스 본문·내장 데코레이터) 기준이며 raw(표기만 맞춤)는 262/9/82 → 277/9/67이다.

### PyCG 공식 벤치마크 (회귀 확인, 기존 `paper` 지표)

| | 변경 전 | 변경 후 |
|---|---|---|
| micro 112개 Complete / Sound | 111 / 71 | 111 / **78** |
| micro TP / FP / FN | 182 / 1 / 72 | **197 / 1 / 57** |
| Sublist3r F1 | 79.14 | 79.14 (간선 동일) |
| asciinema F1 | 82.70 | **83.08** (+2 TP: `pty.record`·`RecordCommand.execute`의 lambda 콜백) |
| autojump F1 | 81.89 | 81.80 (+1 FP: `map(convert, ...)`의 lambda, 아래 참고) |
| fabric F1 | 71.79 | 71.79 (간선 동일) |
| face_classification F1 | 94.86 | 94.86 (간선 동일) |

## 3. 엔진 변경

모두 "실행 시 실제로 일어나는 호출"을 추가하는 변경이며, 각 규칙에 반례 테스트를 붙였다(`tests/test_jarvis_improvements.py`, 16개).

| # | 패턴 | 파일 | 규칙과 제한 |
|---|---|---|---|
| 1 | `@dec` 적용 | `object_flow.apply_decorators` | 괄호 없는 데코레이터가 프로젝트 함수면 정의 시점에 `dec(func)` 호출을 기록하고 데코레이터 본문을 해석한다. 이때 넘어간 인자는 **장식 전 원래 함수 객체**(`ORIGINAL_DEFINITION`)라서 데코레이터 안의 `f()`는 기존 "장식된 함수는 연결하지 않음" 정책과 별개로 연결한다. 장식 후 이름(`func()`)을 연결하지 않는 정책은 그대로다. `@dec(...)`은 기존 호출 지점이라 다시 적용하지 않는다. |
| 2 | `raise A` | `object_flow.raise_class` | 괄호 없이 클래스를 raise하면 `A.__init__`을 암묵 호출로 기록한다. |
| 3 | 클래스 별칭 `l = left` | `Resolver.class_alias` | 같은 클래스 본문에서 앞서 정의한 메서드를 가리키는 단일·무조건 대입만 인정한다. 원래 이름이 다시 대입되면 인정하지 않는다. |
| 4 | f-string `__str__` | `ObjectFlow.expr` (FormattedValue) | 클래스에 `__format__`이 없으면 `object.__format__`이 `str(self)`를 부르므로 `__str__`을 기록한다. `__format__`이 있으면 `__str__`을 기록하지 않는다. |
| 5 | 반복 `__next__` | `ObjectFlow.iteration_next` | `for`·컴프리헨션에서 `__iter__`와 함께 `__next__`를 기록한다. `__iter__`가 `self` 또는 프로젝트 클래스 객체를 반환하는 경우만 따라간다. |
| 6 | `map(f, xs)`, `filter(f, xs)` | `note_builtin_callback` | 기존 `sorted(key=f)`와 같은 콜백 간선(`implicit_kind=callback`)이다. 내장 `map`·`filter` 호출 자체는 계속 외부 호출이다. |
| 7 | 사용자 정의 `__setattr__` | `ObjectFlow.assign` | `obj.x = v`에서 프로젝트 클래스가 `__setattr__`을 정의하면 그 메서드를 기록한다. property setter 기록은 그대로 유지한다. |
| 8 | `@six.add_metaclass(abc.ABCMeta)` | `Resolver._transparent_customization` | 같은 클래스 본문으로 메타클래스만 바꿔 다시 만드는 데코레이터이므로, 인자가 이미 허용된 안전 메타클래스(`abc.ABCMeta`)일 때만 계층을 확정한다. 다른 메타클래스는 계속 미확정이다. |

**가장 큰 효과는 8번이다.** furl의 기반 클래스에 이 데코레이터가 있어 `furl` 클래스 계층 전체가 미확정이었고, `self.load()` 같은 명시적 호출도 연결되지 않았다. 이 하나로 furl 재현율이 0.53 → 0.76이 됐고, 늘어난 간선 중 정답에 표시되지 않은 property·`__setattr__` 호출이 오탐으로 집계되어 정밀도가 0.91 → 0.75로 내려갔다(아래 감사).

## 4. 정답 감사

JARVIS 정답에는 실제로 실행되는 호출이 빠진 경우가 있다. 변경 후 오탐에서 무작위로 26개를 뽑아 소스와 대조했다.

| 프로젝트 | 확인 | 소스상 실행될 수 있음 | 예 |
|---|---:|---:|---|
| furl | 14 | 14 | `Fragment.__bool__`의 `bool(self.path)` → property getter, `Query.__ne__`의 `not self == other` → `__eq__`, `furl.remove`의 `self.host = None` → setter |
| sqlparse | 5 | 5 | `group()`은 `for func in [group_comments, ...]: func(stmt)`로 20여 개 함수를 호출하는데 정답은 `[]`. `_get_offset`의 `self.leading_ws` → property |
| bpytop | 4 | 4 | `with Nonblocking(sys.stdin)` → `__enter__`/`__exit__` |
| sshtunnel | 3 | 3 (조건부) | 조건에 따라 고르는 클래스 생성 |

같은 종류가 정답에 있는 경우도 있다. 예를 들어 furl 정답은 `origin → scheme`(property)과 `load → __setattr__`은 표시하지만, `__init__ → __setattr__`과 `path` property는 표시하지 않는다. 정답이 **일관되지 않다**는 근거이며, 표본 밖의 오탐까지 모두 정답 누락이라는 증명은 아니다.

그 밖에 확인한 정답 쪽 문제:
- micro `mro/basic`, `mro/basic_init`, `mro/super_call`: `super().__init__()`이 있는데 정답에는 `B.__init__ → A.__init__`이 없다. KnitCode의 micro 오탐 9개 중 4개가 이것이다.
- micro `builtins/map`: 정답은 인자 순서가 뒤바뀐 `map([1, 2, 3], func)`에서도 `func` 호출을 요구한다. 실제로는 TypeError가 나는 코드라 KnitCode는 맞추지 않는다.
- lambda 이름 표기가 프로젝트마다 다르다(`<lambda>`와 `<lambda1>`). 맞추지 않았다(누락 11, 오탐 10).

## 5. 남은 누락 (변경 후 macro, 관례 맞춤 기준)

| 원인 | 누락 | 예 |
|---|---:|---|
| 앱 함수 호출 | 381 | sqlparse: `@recurse(...)`로 장식된 `group_*` 함수가 받은 `tlist` 매개변수의 메서드(`token_next_by` 22건 등). 장식된 함수 호출을 연결하지 않는 정책 때문에 호출 문맥이 전달되지 않는다. |
| 내장 함수·타입 메서드 | 72 | 수신 객체 타입을 모르는 `x.split()` 등 |
| lambda 표기 | 11 | 위 정답 감사 참고 |
| 클래스 본문·import | 6 | |

micro에 남은 주요 누락: decorators 11(장식된 함수 `func()` 호출, 정책), dicts 11(첨자 대입 `d["a"] = f2` 추적), assignments 7(`a, *b = ...` 언패킹), new_imports 5(`import *`, 재수출).

다음 후보:
1. **항등 데코레이터 증명.** 1번 변경으로 데코레이터 본문을 해석하므로, 데코레이터가 받은 함수를 그대로 반환한다는 것이 증명되면 장식된 이름도 연결할 수 있다. micro decorators와 sqlparse에 효과가 클 것으로 본다.
2. dict 첨자 대입과 별표 언패킹.
3. `new_direct_calls`의 다른 함수에서 일어나는 필드 재대입(`change()` 안의 `c.fn = func2`). JARVIS가 내세우는 흐름 민감 분석과 strong update가 필요한 부분이다.

## 6. 시간·메모리

아래 수치는 측정 환경에 따라 달라지므로 점수와 달리 그대로 재현되지 않는다. 두 환경에서 쟀다.

| 프로젝트 | Linux (Python 3.13, 원자료 환경) 시간 / RSS | Windows (Python 3.12, 재현 환경) 시간 |
|---|---|---|
| bpytop | 4.09초 / 81MB | 9.04초 |
| sqlparse | 0.58초 / 44MB | 1.31초 |
| TextRank4ZH | 0.10초 / 24MB | 0.25초 |
| furl | 1.95초 / 31MB | 3.87초 |
| rich-cli | 0.21초 / 28MB | 0.47초 |
| sshtunnel | 0.61초 / 40MB | 1.20초 |

Windows에는 `resource` 모듈이 없어 최대 메모리(RSS)를 재지 않는다(`-`로 출력). 시간은 Windows가 약 2배 길지만 6개 사이의 상대 순서는 같다.

Linux 기준(같은 프로세스에서 분석 + 표기 변환, `ru_maxrss`): 6개 모두 4.1초 이하, 최대 RSS 81MB(bpytop). furl만 0.38초 → 1.95초로 늘었다. 확정된 클래스 계층에서 객체 흐름이 더 많은 메서드를 따라가기 때문이다. 논문 Table(RQ1)의 PyCG E.A. 0.16~1.26초·24~90MB, JARVIS E.A. 0.19~1.22초·24~61MB와 같은 규모이며, 머신이 달라 직접 비교하지 않는다.

실제 저장소(Linux 환경, 같은 머신에서 변경 전·후 비교, 분석만, `scripts` 밖 임시 스크립트로 측정):

| 대상 | 호출 지점 | 변경 전 시간 / RSS | 변경 후 시간 / RSS | 해결 지점 | 암묵 간선 |
|---|---:|---|---|---|---|
| Click (저장소 전체) | 7,084 | 6.8초 / 181MB | 7.1초 / 181MB | 3,131 → 3,131 | 129 → 209 |
| Requests (저장소 전체) | 2,687 | 4.3초 / 97MB | 4.0초 / 97MB | 1,056 → 1,056 | 147 → 147 |
| Rich (`rich/` 폴더만) | 4,366 | 4.6초 / 167MB | 4.6초 / 167MB | 807 → 807 | 182 → 185 |

- 명시적 호출의 해결 수는 세 저장소 모두 같고, 늘어난 것은 암묵 간선(Click의 `__setattr__`·`__next__`·데코레이터 등)이다. 이 늘어난 간선의 실행 검증(`trace_recall.py`)은 이번에 하지 않았다.
- **Rich 저장소 전체는 변경 전·후 모두 `graph_navigation.build_hierarchy`에서 `KeyError: None`으로 실패한다**(이번 변경과 무관한 기존 문제, `timing-realworld.txt`). 그래서 `rich/` 폴더만 분석했는데, 이 경우 모듈 이름이 `rich.`로 시작하지 않아 import 해석이 크게 줄어든다(해결 807/4,366). 시간 비교용으로만 쓴다.

## 7. 재현

```bash
# 데이터 (분석기 폴더 밖)
git clone https://github.com/pythonJaRvis/pythonJaRvis.github.io ../pythonJaRvis.github.io
# JARVIS
python3 scripts/jarvis_benchmark.py micro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/micro.json
python3 scripts/jarvis_benchmark.py macro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/macro
# 변경 전 엔진을 같은 어댑터로
git worktree add ../knitcode-before c404b3c
python3 scripts/jarvis_benchmark.py macro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/macro-before --engine-root ../knitcode-before
# PyCG 회귀 (benchmarks/pycg-evaluation, ce37eb5)
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --output out/pycg
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --output out/pycg-micro.json
# 테스트: tests/test_v24.py와 tests/jse_original/test_v24.py의 이름이 같아 폴더별로 실행
python3 -m pytest tests -q --ignore=tests/jse_original --ignore=tests/ljy_original
python3 -m pytest tests/jse_original -q
python3 -m pytest tests/ljy_original -q
```

| 환경 | 용도 | 검사 결과 (세 그룹) |
|---|---|---|
| Linux, Python 3.13.18, pytest 9 | 원자료 작성, 변경 전·후 비교 | 227 passed·1 skipped / 265 passed / 59 passed·7 skipped (변경 전 211 / 265 / 59 passed) |
| **Windows, Python 3.12 (conda), PowerShell** | 독립 재현 | 224 passed·1 skipped / 265 passed / 59 passed·7 skipped, 새 테스트 16 passed |

두 환경 모두 실패는 0개다. 첫 그룹의 수집 개수 차이(227/224)는 실패가 아니라 두 작업 트리의 `tests/` 구성 차이다.

**Windows에서 독립 재현한 결과는 아래 점수가 모두 원자료와 같았다.**
- JARVIS micro: C. 130, S. 98, TP 278, FP 9, FN 66 (raw 277/9/67)
- JARVIS macro 6개: 정밀도·재현율 전부 일치 (평균 KnitCode 0.88 / 0.78, PyCG 0.99 / 0.76, JARVIS 1.00 / 0.82)
- PyCG macro 5개: explicit internal과 all calls F1 전부 일치 (79.1 / 83.1 / 81.8 / 71.8 / 94.9)
- PyCG micro: Complete 111, Sound 78

Windows 재현 시 주의: `pycg-evaluation`의 서브모듈 받기가 네트워크 오류로 실패하면 프로젝트 폴더가 빈 채로 남고, `pycg_benchmark.py`가 오류 없이 모든 점수를 0.0%로 출력한다. 점수가 전부 0이면 `projects/<프로젝트>` 폴더에 `.py` 파일이 있는지 먼저 확인한다.

원자료(Linux 환경): `before/`, `after/` 아래 `jarvis-micro.json`(예제별 누락·오탐 간선), `jarvis-macro/<프로젝트>.json`, `jarvis-macro-summary.json`, `pycg-micro.json`, `pycg-macro/<프로젝트>.json`, `timing-realworld.txt`.
