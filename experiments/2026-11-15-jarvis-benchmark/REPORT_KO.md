# JARVIS 벤치마크 비교와 정적분석 개선 (2026-11-15)

## 결론

1. **JARVIS 벤치마크를 같은 채점기로 재현했다.** JARVIS 아티팩트에 포함된 PyCG·JARVIS 출력을 논문 채점 코드(`reproducing_RQ2/gen_table.py`)와 같은 규칙으로 다시 채점해 논문 Table V의 E.A. 평균(PyCG 0.99/0.76, JARVIS 0.99~1.00/0.82)을 그대로 얻었다. KnitCode는 같은 입력·같은 채점기로 평가한다.
2. **엔진 개선 12가지로 누락이 크게 줄었다.** 모든 수치는 `main`(`c404b3c`) 엔진을 같은 채점기로 다시 잰 값과 비교한다.
   - JARVIS macro 6개 합산 재현율: **0.748 → 0.837**(JARVIS 0.776, PyCG 0.724)
   - 관례 맞춤 없는 원점수 재현율: 0.621 → 0.709
   - JARVIS micro 놓친 호출: 81 → 56, PyCG micro Sound: 71 → 82/112
   - PyCG macro 5개: asciinema·autojump F1이 오르고, 나머지 3개는 예측 간선 집합까지 동일하다.
3. **정밀도는 JARVIS·PyCG보다 낮다(합산 0.878 vs 0.994/0.993).** 다만 오탐 50개(무작위 26개, 단계별 신규 24개)는 모두 소스상 실행될 수 있는 호출이었다. JARVIS 정답은 property 접근, `with`의 `__enter__/__exit__`, 리스트에 담아 부르는 함수 호출 등을 일관되게 표시하지 않는다(4절). **이 정밀도 차이를 KnitCode의 오류로만 해석하면 안 되지만, 오탐 전체를 검수하기 전에는 "KnitCode가 더 정확하다"고 주장하지 않는다.**

**JARVIS보다 높은 재현율은 채점 관례를 맞춘 점수 기준이다**(1절 표의 관례 맞춤 규칙 포함). micro Sound(JARVIS 기준 104/138)는 JARVIS(134/138)와 PyCG(126/138)에 여전히 못 미친다. PyCG·JARVIS를 전반적으로 능가했다고 결론 내리지 않는다.

## 1. 벤치마크와 채점

| 항목 | 내용 |
|---|---|
| 출처 | [pythonJaRvis/pythonJaRvis.github.io](https://github.com/pythonJaRvis/pythonJaRvis.github.io) `Jarvis/` (데이터·정답·PyCG/JARVIS 출력·채점 스크립트) |
| micro | 22개 범주 138개 예제. PyCG micro 112개에 `context_managers`, `new_*` 범주 추가 |
| macro | bpytop, sqlparse, TextRank4ZH, furl, rich-cli, sshtunnel (587~5,687줄) |
| 모드 | **E.A.**: 모든 함수를 진입점으로, 애플리케이션 코드만. KnitCode의 분석 방식과 같은 조건 |
| 입력 | `reproducing_RQ12_setup/macro_benchmark/pycg_EA.sh`와 같은 파일·패키지 루트. JARVIS 쪽 스크립트는 furl 결과를 sshtunnel 폴더에 쓰는 등 경로 오류가 있어 따르지 않음 |
| 채점 | `gen_table.py`와 동일: 호출자별 TP 합, FP = 예측 간선 − TP, FN = 정답 간선 − TP. micro C.=FP 없음, S.=FN 없음 |
| 실행 | `python scripts/jarvis_benchmark.py {micro,macro} --jarvis <Jarvis 폴더> --output <경로>` (`--engine-root`로 다른 커밋의 엔진을 같은 어댑터로 채점) |

### 표기·관례 맞춤 (정답을 보지 않는 규칙)

JARVIS 정답과 KnitCode 출력은 "무엇을 호출로 세는가"의 관례가 다르다. 정답 파일을 보고 간선을 고치지 않고, 아래 규칙만 적용한다. 결과 표에는 **원점수(raw, 표기만 맞춤)**와 **관례 맞춤 점수**를 함께 싣는다.

| 규칙 | 내용 | 적용 |
|---|---|---|
| 내장 타입 표기 | `<**PyStr**>.join` → `<str>.join`, `<**PyDict**>` → `<map>`, `<**PyList**>` → `<list>` | raw·관례 |
| 외부 라이브러리 호출 제외 | `os.path.join` 등. E.A.에서는 정답·PyCG·JARVIS 출력 모두 앱 함수와 내장 함수만 포함 | raw·관례 (`--keep-library-calls`로 끌 수 있음) |
| 클래스 본문 호출자 | 클래스 본문에서 실행되는 호출의 호출자를 모듈 대신 `mod.Cls`로 표기 | 관례 |
| 내장 데코레이터 | `@classmethod`/`@staticmethod`/`@property` → `<builtin>.classmethod` 등 | 관례 (PyCG 정답에는 없어 PyCG 평가에는 쓰지 않음) |
| 모듈 import 간선 | 프로젝트 모듈을 import하면 그 모듈 본문이 실행됨: `importer → imported`. 상대 import 포함 | 관례, **macro만** |
| 클래스 정의 간선 | 클래스 문을 실행하면 본문이 실행됨: `정의한 scope → 클래스`. JARVIS macro 정답은 클래스 106개 **전부**에 이 간선이 있고, PyCG·JARVIS 출력에도 있다 | 관례, **macro만** |

macro만 적용하는 두 규칙은 JARVIS micro 정답(PyCG에서 물려받음)에는 없고 macro 정답에는 있는 관례다. 정답 자체가 micro와 macro에서 기준이 다르다.

## 2. 결과

### macro (E.A.) — 정밀도 / 재현율 (TP/FP/FN)

| 프로젝트 | 줄 | `main` 엔진 (관례) | **개선 후 (관례)** | 개선 후 raw | PyCG E.A.(m) | JARVIS E.A. |
|---|---:|---|---|---|---|---|
| bpytop | 5,687 | 0.92 / 0.85 (524/43/94) | **0.93 / 0.90** (556/45/62) | 0.90 / 0.77 | 0.99 / 0.84 | 0.99 / 0.92 |
| sqlparse | 3,803 | 0.91 / 0.66 (406/39/206) | **0.91 / 0.73** (445/45/167) | 0.88 / 0.57 | 0.99 / 0.62 | 0.99 / 0.64 |
| TextRank4ZH | 587 | 0.94 / 0.96 (75/5/3) | **0.94 / 0.96** (75/5/3) | 0.92 / 0.77 | 1.00 / 0.87 | 1.00 / 0.95 |
| furl | 2,104 | 0.92 / 0.56 (180/16/139) | **0.76 / 0.84** (269/87/50) | 0.74 / 0.77 | 0.99 / 0.61 | 1.00 / 0.63 |
| rich-cli | 1,112 | 0.92 / 0.89 (54/5/7) | **0.92 / 0.89** (54/5/7) | 0.90 / 0.72 | 0.96 / 0.82 | 1.00 / 0.95 |
| sshtunnel | 1,929 | 0.89 / 0.88 (151/19/20) | **0.84 / 0.92** (157/30/14) | 0.83 / 0.84 | 1.00 / 0.80 | 1.00 / 0.85 |
| 평균 | | 0.92 / 0.80 | **0.88 / 0.87** | 0.86 / 0.74 | 0.99 / 0.76 | 1.00 / 0.82 |
| **합산 (간선 1,859)** | | 0.916 / 0.748 | **0.878 / 0.837** | 0.854 / 0.709 (`main` 0.897 / 0.621) | 0.993 / 0.724 | 0.994 / 0.776 |

- PyCG E.A.(1)과 E.A.(m)은 6개 모두 같다. 논문 표의 값과 일치한다.
- 재현율은 furl·sshtunnel·TextRank4ZH·sqlparse에서 JARVIS보다, bpytop·TextRank4ZH·furl·sqlparse·sshtunnel에서 PyCG보다 높다. rich-cli는 JARVIS보다 낮다. 정밀도는 6개 모두 두 도구보다 낮다.
- 정밀도가 가장 많이 내려간 furl(0.92 → 0.76)은 클래스 계층이 확정되면서 property·`__setattr__` 호출을 새로 찾은 결과다. 이 호출들은 정답에 표시되지 않았다(4절).

### micro — JARVIS 138개 (관례 맞춤 기준)

| 도구 | C. | S. | TP | FP | FN |
|---|---:|---:|---:|---:|---:|
| PyCG (논문 표) | 113 | 126 | 317 | 27 | 27 |
| JARVIS (논문 표) | 132 | 134 | 335 | 7 | 9 |
| KnitCode `main` | 130 | 92 | 263 | 9 | 81 |
| **KnitCode 개선 후** | **130** | **104** | **288** | **9** | **56** |

- raw(표기만 맞춤)는 262/9/82 → 287/9/57이다.
- 범주별 변화: decorators TP 3→20 (S. 0→5), exceptions 0→3 (S. 0→3), generators 12→16 (S. 1→4), new_direct_calls 15→16.

### PyCG 공식 벤치마크 (회귀 확인, 기존 `paper` 지표)

| | `main` | 개선 후 |
|---|---|---|
| micro 112개 Complete / Sound | 111 / 71 | 111 / **82** |
| micro TP / FP / FN | 182 / 1 / 72 | **205 / 1 / 49** |
| Sublist3r F1 | 79.14 | 79.14 (간선 동일) |
| asciinema F1 | 82.70 | **83.08** (`pty.record`·`RecordCommand.execute`의 lambda 콜백 +2 TP) |
| autojump F1 | 81.89 | **82.05** (+2 TP, `map(convert, ...)`의 lambda +1 FP) |
| fabric F1 | 71.79 | 71.79 (간선 동일) |
| face_classification F1 | 94.86 | 94.86 (간선 동일) |

## 3. 엔진 변경

모두 "실행 시 실제로 일어나는 호출"을 추가하는 변경이며, 각 규칙에 반례 테스트를 붙였다(`tests/test_jarvis_improvements.py`, 35개). 진단 → 수정 → 반례 테스트 → JARVIS·PyCG 회귀 확인 순서로 하나씩 진행했다.

### 1차: 개별 호출 패턴

| # | 패턴 | 파일 | 규칙과 제한 |
|---|---|---|---|
| 1 | `@dec` 적용 | `object_flow.apply_decorators` | 정의 시점에 데코레이터 호출을 기록하고 데코레이터 본문을 해석한다. 넘어간 인자는 **장식 전 원래 함수 객체**(`ORIGINAL_DEFINITION`)라서, 데코레이터 안의 `f()`는 "장식된 함수는 연결하지 않음" 정책과 별개로 연결한다. |
| 2 | `raise A` | `object_flow.raise_class` | 괄호 없이 클래스를 raise하면 `A.__init__`을 암묵 호출로 기록한다. |
| 3 | 클래스 별칭 `l = left` | `Resolver.class_alias` | 같은 클래스 본문에서 앞서 정의한 메서드를 가리키는 단일·무조건 대입만 인정한다. 원래 이름이 다시 대입되면 인정하지 않는다. |
| 4 | f-string `__str__`, 반복 `__next__` | `ObjectFlow.expr`, `iteration_next` | `__format__`이 없으면 `object.__format__`이 `str(self)`를 부르므로 `__str__`을 기록한다. `for`·컴프리헨션에서 `__iter__`가 `self` 또는 프로젝트 클래스 객체를 반환하면 `__next__`를 기록한다. |
| 5 | `map(f, xs)`, `filter(f, xs)` | `note_builtin_callback` | 기존 `sorted(key=f)`와 같은 콜백 간선이다. `map`·`filter` 호출 자체는 계속 외부 호출이다. |
| 6 | 사용자 정의 `__setattr__` | `ObjectFlow.assign` | `obj.x = v`에서 프로젝트 클래스가 `__setattr__`을 정의하면 그 메서드를 기록한다. |
| 7 | `@six.add_metaclass(abc.ABCMeta)` | `Resolver._transparent_customization` | 같은 클래스 본문으로 메타클래스만 바꿔 다시 만드는 데코레이터이므로, 인자가 안전 메타클래스(`abc.ABCMeta`)일 때만 계층을 확정한다. **furl 재현율 0.53 → 0.76**의 대부분이 이 변경이다. |

### 2차: 데코레이터와 클로저

| # | 패턴 | 파일 | 규칙과 제한 |
|---|---|---|---|
| 8 | 항등 데코레이터 | `Resolver.identity_decorator` | 데코레이터의 **모든 `return`이 받은 첫 인자를 그대로 돌려준다**고 소스로 증명되면 장식된 이름도 원래 함수로 연결한다. 별칭(`a = dec`), 지역 정의, 팩토리(`@static_vars(...)`의 안쪽 함수)를 포함한다. 부수효과(`setattr`, 등록)는 허용한다. `return None`, 일부 경로의 다른 반환, 인자 재대입, 제너레이터, 외부 패키지 데코레이터는 인정하지 않는다. |
| 9 | 클로저와 데코레이터 연쇄 | `ObjectFlow.capture_closure`, `apply_decorators` | 함수 안의 `def`가 실행될 때 바깥 변수 값을 기록해 두었다가, 안쪽 함수를 해석할 때 넣는다. 값이 나중에 생긴 클로저는 마지막에 다시 해석한다(최대 3회). `@a @b`는 `a(b(f))`로, `@factory(...)`는 팩토리가 돌려준 함수로 적용한다. sqlparse `@recurse(...)`의 `wrapped_f → group_*` 6개가 연결된다. |

### 3차: 진단으로 찾은 누락 원인

| # | 패턴 | 파일 | 규칙과 제한 |
|---|---|---|---|
| 10 | property·staticmethod 본문 | `ObjectFlow.run` | 모든 메서드를 진입점으로 해석하던 단계에서 `@property`(내장 property로 확인된 것)와 `@staticmethod` 메서드가 빠져 있었다. 이제 함께 해석한다. 프로젝트가 `property`라는 이름을 정의하면 적용하지 않는다. |
| 11 | `getattr` 접두사 디스패치 | `ObjectFlow.dynamic_getattr` | `getattr(self, '_process_' + ..., 기본값)`처럼 이름식에서 **고정 접두사**를 뽑을 수 있으면 그 접두사로 시작하는 메서드들과 기본값으로 연결한다. `+`, f-string, `str.format`, `.lower()/.upper()`, 같은 함수에서 한 번 대입한 변수를 인정한다. 접두사가 2글자 미만이거나 수신 클래스·계층이 미확정이면 적용하지 않는다. **sqlparse 0.67 → 0.72**. |
| 12 | 목록 내용과 제너레이터 | `ObjectFlow.list_mutation`, `invoke` | 내용을 아는 목록의 `append`/`insert`/`extend`/`pop`을 원소로 기록한다. 내용을 모르는 값으로 `extend`하거나, 알 수 없는 함수에 목록을 넘기거나, 원소가 64개를 넘으면 지금처럼 "알 수 없음"으로 둔다. `yield`가 있는 함수도 호출한 쪽 문맥으로 본문을 해석하고, 반환값은 알 수 없는 반복자로 둔다. sqlparse `FilterStack.run → 각 필터.process` 7개, **sshtunnel 0.88 → 0.92**. |

### 시도했지만 넣지 않은 것

| 후보 | 측정한 효과 | 넣지 않은 이유 |
|---|---|---|
| 장식된 이름을 감싼 함수로 연결 (`func()` → `dec.inner`) | 마이크로 오탐이 늘 것으로 예상 | 실행 의미상 맞지만, micro 정답(PyCG 관례: `main → func`)과 macro 정답이 충돌. 해석 순서를 바꾸는 큰 수정 필요 |
| 메서드 이름이 프로젝트에 하나뿐이면 그 메서드로 연결 | JARVIS: 추가 104개 중 88개 정답. PyCG: 추가 45개 중 18개 정답(fabric 28개 중 4개) | 이름 기반 추정이라 프로젝트에 따라 정밀도를 크게 떨어뜨림. 기본값으로 부적합 |
| 제너레이터 원소 타입 + 진입점별 예산 6,000 → 30,000 | sqlparse 0.73 → 0.80, 평균 0.87 → 0.88 | bpytop 분석 시간 +40%. Rich는 기존 측정에서 72초 → 105초. 동적 분석 통합으로 보완하는 쪽을 먼저 검토 |
| 내장 타입(`str`·`list`) 메서드 추론 | 누락 74개 중 타입 힌트 근거가 분명한 것 16~30개 | 정답이 내장 메서드를 일관되게 표시하지 않아(현재 내장 메서드 "오탐" 79개) 효과가 불확실 |

## 4. 정답 감사

JARVIS 정답에는 실제로 실행되는 호출이 빠진 경우가 있다. 오탐을 두 가지 방식으로 소스와 대조했다.

1. **1차 개선 후 무작위 26개:** 모두 소스상 실행될 수 있는 호출

| 프로젝트 | 확인 | 소스상 실행될 수 있음 | 예 |
|---|---:|---:|---|
| furl | 14 | 14 | `Fragment.__bool__`의 `bool(self.path)` → property getter, `Query.__ne__`의 `not self == other` → `__eq__`, `furl.remove`의 `self.host = None` → setter |
| sqlparse | 5 | 5 | `group()`은 `for func in [group_comments, ...]: func(stmt)`로 20여 개 함수를 호출하는데 정답은 `[]`. `_get_offset`의 `self.leading_ws` → property |
| bpytop | 4 | 4 | `with Nonblocking(sys.stdin)` → `__enter__`/`__exit__` |
| sshtunnel | 3 | 3 (조건부) | 조건에 따라 고르는 클래스 생성 |

2. **2·3차 단계별 신규 24개:** 유형별로 소스를 확인했다.
   - property 안의 property 접근: sshtunnel `local_bind_address`가 `self.local_bind_addresses[0]`를 읽는다.
   - setter 안의 대입: furl `origin` setter의 `self.scheme = ...` → `__setattr__`·setter.
   - `getattr`의 기본값 메서드: `_stripws → _stripws_default`.
   - `run()`이 순회하는 `self.preprocess` 필터들의 `process`.
   - TCP·유닉스 스트림 두 종류 서버의 property: sshtunnel `_ForwardServer`와 `_StreamForwardServer`가 각자 property를 정의하는데, 정답은 `_ForwardServer` 쪽만 적었고 그중 `local_address`도 빠뜨렸다.

같은 종류가 정답에 있는 경우도 있다. 예를 들어 furl 정답은 `origin → scheme`(property)과 `load → __setattr__`은 표시하지만 `__init__ → __setattr__`과 `path` property는 표시하지 않는다. 정답이 **일관되지 않다**는 근거이며, 표본 밖의 오탐까지 모두 정답 누락이라는 증명은 아니다. **다음 단계로 오탐 217개 전체를 검수해 보정 정답을 만들고, 원래 정답과 보정 정답 두 기준으로 정밀도를 보고할 계획이다.**

그 밖에 확인한 정답 쪽 문제:
- micro `mro/basic`, `mro/basic_init`, `mro/super_call`: `super().__init__()`이 있는데 정답에는 `B.__init__ → A.__init__`이 없다. KnitCode의 micro 오탐 9개 중 4개가 이것이다.
- micro `builtins/map`: 정답은 인자 순서가 뒤바뀐 `map([1, 2, 3], func)`에서도 `func` 호출을 요구한다. 실제로는 TypeError가 나는 코드라 KnitCode는 맞추지 않는다.
- lambda 이름 표기가 프로젝트마다 다르다(`<lambda>`와 `<lambda1>`). 맞추지 않았다(누락 46 중 상당수).
- furl 정답의 `<list>.allitems`처럼 존재하지 않는 내장 메서드가 있다.

## 5. 남은 누락 (개선 후 macro, 관례 맞춤 기준, 303개)

| 원인 | 누락 | 예와 방향 |
|---|---:|---|
| 메서드 수신 객체의 타입을 모름 | 146 | sqlparse `tlist.token_next_by()` 등. `tlist`는 파서가 만든 객체가 `getattr`·데코레이터·제너레이터를 여러 번 거쳐 들어온다. PyCG(0.62)·JARVIS(0.64)도 sqlparse에서 낮다. **동적 분석 통합으로 보완하는 방향을 검토한다.** |
| 내장 타입 메서드 | 74 | `color: str`의 `color.split()`(힌트 근거 16개), 필드 힌트, 지역 변수. 3절 보류 참고 |
| lambda 이름 표기 | 46 | 정답 표기 불일치 |
| 장식된 함수 호출·데코레이터 문맥 | 29 | 3절 보류 참고 |
| 기타 | 8 | |

micro에 남은 주요 누락: dicts 11(첨자 대입 `d["a"] = f2` 추적), assignments 7(`a, *b = ...` 언패킹), new_imports 5(`import *`, 재수출), decorators 2, new_direct_calls 3(다른 함수에서 일어나는 필드 재대입, JARVIS가 내세우는 흐름 민감 분석과 strong update가 필요한 부분).

## 6. 시간·메모리

아래 수치는 측정 환경에 따라 달라지므로 점수와 달리 그대로 재현되지 않는다.

**JARVIS macro**(같은 프로세스에서 분석 + 표기 변환, Linux `ru_maxrss`)

| 프로젝트 | `main` 시간 | 개선 후 시간 / RSS |
|---|---:|---|
| bpytop | 5.5초 | 5.7초 / 81MB |
| sqlparse | 0.8초 | 1.3초 / 45MB |
| TextRank4ZH | 0.15초 | 0.15초 / 24MB |
| furl | 0.5초 | 2.8초 / 31MB |
| rich-cli | 0.2초 | 0.3초 / 28MB |
| sshtunnel | 0.9초 | 0.9초 / 39MB |

- furl은 클래스 계층이 확정되면서 객체 흐름이 더 많은 메서드를 따라가 늘었다.
- 1차 결과는 Windows(Python 3.12)에서도 쟀는데 Linux의 약 2배였고, 프로젝트 사이의 상대 순서는 같았다. Windows에는 `resource` 모듈이 없어 RSS를 재지 않는다(`-`로 출력).
- 논문 Table(RQ1)의 PyCG E.A. 0.16~1.26초·24~90MB, JARVIS E.A. 0.19~1.22초·24~61MB와 같은 규모이며, 머신이 달라 직접 비교하지 않는다.

**실제 저장소**(Linux, 같은 머신에서 `main`·개선 후 비교, 분석만, `timing-realworld.txt`)

| 대상 | 호출 지점 | `main` 시간 / RSS | 개선 후 시간 / RSS | 해결 지점 | 암묵 간선 |
|---|---:|---|---|---|---|
| Click (저장소 전체) | 7,084 | 6.8초 / 181MB | 12.0~12.5초 / 192MB | 3,131 → 3,141 | 129 → 785 |
| Requests (저장소 전체) | 2,687 | 4.3초 / 97MB | 7.1~7.3초 / 98MB | 1,056 → 1,057 | 147 → 152 |
| Rich (`rich/` 폴더만) | 4,366 | 4.6초 / 167MB | 6.8초 / 168MB | 807 → 831 | 182 → 203 |

- Click 암묵 간선 증가분의 대부분(652개)은 테스트·예제의 `@click.command()`, `@click.option(...)` 같은 팩토리 데코레이터 적용 간선이다. 실제로 실행되는 호출이다.
- 시간이 늘어난 주된 원인은 데코레이터 본문과 제너레이터 본문을 문맥별로 해석하는 비용이다.
- 늘어난 간선의 실행 검증(`trace_recall.py`)은 이번에 하지 않았다.
- **Rich 저장소 전체는 `main`·개선 후 모두 `graph_navigation.build_hierarchy`에서 `KeyError: None`으로 실패한다**(이번 변경과 무관한 기존 문제). 그래서 `rich/` 폴더만 분석했고, 이 경우 모듈 이름이 `rich.`로 시작하지 않아 import 해석이 크게 줄어든다. 시간 비교용으로만 쓴다.

## 7. 재현

```bash
# 데이터 (분석기 폴더 밖)
git clone https://github.com/pythonJaRvis/pythonJaRvis.github.io ../pythonJaRvis.github.io
# JARVIS
python3 scripts/jarvis_benchmark.py micro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/micro.json
python3 scripts/jarvis_benchmark.py macro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/macro
# main 엔진을 같은 어댑터로
git worktree add ../knitcode-main c404b3c
python3 scripts/jarvis_benchmark.py macro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/macro-main --engine-root ../knitcode-main
python3 scripts/jarvis_benchmark.py micro --jarvis ../pythonJaRvis.github.io/Jarvis --output out/jarvis/micro-main.json --engine-root ../knitcode-main
# PyCG 회귀 (pycg-evaluation, ce37eb5, macro 프로젝트 5개 서브모듈)
python3 pycg_benchmark.py --benchmark ../pycg-evaluation --output out/pycg
python3 scripts/evaluate_pycg_micro.py --benchmark ../pycg-evaluation --output out/pycg-micro.json
# 테스트: tests/test_v24.py와 tests/jse_original/test_v24.py의 이름이 같아 폴더별로 실행
python3 -m pytest tests -q --ignore=tests/jse_original --ignore=tests/ljy_original
python3 -m pytest tests/jse_original -q
python3 -m pytest tests/ljy_original -q
```

| 환경 | 용도 | 검사 결과 (세 그룹) |
|---|---|---|
| Linux, Python 3.13.18, pytest 9 | 원자료 작성, `main`·개선 후 비교 | 246 passed·1 skipped / 265 passed / 59 passed·7 skipped (`main` 211 / 265 / 59 passed, 증가분은 새 테스트 35개) |
| **Windows, Python 3.12 (conda), PowerShell** | 단계마다 독립 재현 | 새 테스트 35 passed. 기존 그룹은 `test_project_intro.py`의 심볼릭 링크 테스트 1개만 권한 문제(WinError 1314)로 실패. 이번 변경과 무관 |

**Windows에서 독립 재현한 결과는 아래 점수가 모두 원자료와 같았다.**
- JARVIS micro (최종): C. 130, S. 104, TP 288, FP 9, FN 56
- JARVIS macro 6개 (최종): 프로젝트별 정밀도·재현율 일치, 평균 KnitCode 0.88 / 0.87
- PyCG macro 5개, PyCG micro: 1차 결과(Sound 78)까지 Windows에서 일치를 확인했다. 최종값(Sound 82, asciinema·autojump F1)은 Linux에서만 쟀다.

**재현 시 주의**
- `pycg-evaluation`의 서브모듈 받기가 네트워크 오류로 실패하면 프로젝트 폴더가 빈 채로 남고, `pycg_benchmark.py`가 오류 없이 모든 점수를 0.0%로 출력한다. 점수가 전부 0이면 `projects/<프로젝트>` 폴더에 `.py` 파일이 있는지 먼저 확인한다.
- Python 3.10 이상이 필요하다(`sys.stdlib_module_names`, `ast.Match`).

원자료(Linux 환경): `before/`(`main` 엔진), `after/`(최종) 아래
- `jarvis-micro.json`(예제별 누락·오탐 간선)
- `jarvis-macro/<프로젝트>.json`, `jarvis-macro-summary.json`
- `pycg-micro.json`, `pycg-macro/<프로젝트>.json`
- `timing-realworld.txt`

JARVIS 결과는 모두 현재 어댑터(관례 맞춤 6가지)로 채점했다.
