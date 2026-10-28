# 단일 엔진 통합 실험 (2026-10-25)

## 결론과 버전 선택

**기본 분석 경로를 `Resolver/ObjectFlow` 하나로 통합했다.** 이전의 “기존 엔진 실행 → 이정연 분석기 별도 실행 → 간선 합치기”를 제거했다. PyCG macro 5개 프로젝트의 예측 간선 집합을 유지하면서 전체 처리 중앙값은 **2.313초 → 1.906초, 17.6% 감소**했다. 최종 선택은 단일 엔진의 `integrated` + `supported`다.

직전 버전은 [소스 압축본](baseline-source.tar.gz)과 [SHA-256 목록](baseline-manifest.json)으로 보존했다. 원본은 이전 refinement 실험에서 선택한 버전이며, 실행용으로 `benchmarks/single-engine-before/`에 풀었다. 이번 선택본은 `selected-source.tar.gz`, `selected-manifest.json`, `selection.json`으로 별도 보존한다.

## 무엇을 합쳤나

| 기능 | 이전 구현 | 현재 구현 |
|---|---|---|
| 심볼·호출·타입·객체 흐름 | 모듈형 엔진과 이정연 분석기가 각각 해석 | 공통 심볼·import·AST를 사용하는 `Resolver/ObjectFlow` |
| 타입 컨테이너·필드 | 별도 분석기의 보충 호출 | 같은 추상 값·힙에서 list/dict/tuple 원소, `get/values/items`, `enumerate/sorted`, `ContextVar`를 전달 |
| 클래스 값 factory | 별도 타입 추론 결과를 합침 | `type[T]`, 클래스 속성에 담긴 클래스, 상속 생성자를 같은 호출 해석기로 추적 |
| 진리값·포맷 암묵 호출 | 두 분석기의 결과를 합침 | 기존 `implicit_events`에 `__bool__/__len__/__format__/__repr__` 등을 기록 |
| 선언 반환 타입의 보충 후보 | 이정연 분석기의 결과 | 같은 인터프리터가 `advisory_events`로 기록; 실제 `None` 반환을 덮어쓰지 않음 |
| 자식 메서드 후보 | 두 결과의 ID와 계층을 대조 | 주 엔진에서 선언 타입으로 해석한 호출과 같은 C3 계층에서 생성 |
| 참조·진입점·import 순환·계층·읽는 순서·동적 표식 | 별도 분석기가 만든 그래프를 변환 | 같은 AST·심볼·import 사실과 통합 호출 그래프에서 계산 |
| 기존 JSON·HTML | 별도 분석기의 원본 결과 | 통합 결과의 출력용 projection; `file::qualified_name` 형식은 호환 출력에서만 사용 |

`graph_navigation.py`는 이정연 코드의 순환 탐지·PageRank·계층 집계·표시 메타데이터 같은 순수 함수를 분리한 파일이다. 심볼이나 호출을 다시 해석하지 않는다. `graph_entrypoints.py` 역시 기존 import 출처와 심볼을 이용해 Web/CLI 진입점을 표시한다. `ljy_integration.py`에는 정책 선택과 출력 변환만 남겼고, `analyze_snapshot`·`augment_graph`는 제거했다.

`analyze_project.py`와 옛 도구는 원본 API 재현을 위한 호환 자료로 남겼다. **기본 CLI(`main.py`)와 VS Code(`vscode_export.py`)의 통합 분석은 이를 실행하지 않는다.** 파일이 남아 있다는 사실과 제품 경로에서 두 분석기를 돌리는 것은 구분한다.

## PyCG 동일 기준 비교

공식 artifact 커밋은 `ce37eb5668465b0c17371914e863d699826447ee`다. 공통 `pycg_adapter.py`를 그대로 사용했고, 정답을 이용한 이름 변환·간선 삭제 규칙을 추가하지 않았다. 기본 지표는 선택된 명시적 호출 + 암묵 호출 + 정적 출처가 있는 외부 호출(`paper`)이다. 참조·구조 간선은 호출 점수에 포함하지 않는다. PyCG 프로그램 자체를 이번에 다시 실행한 비교는 아니다.

| 프로젝트 | 이전 F1 (%) | 단일 엔진 P / R / F1 (%) | 단일 엔진 TP / FP / FN |
|---|---:|---|---|
| Sublist3r | 79.14 | 95.16 / 67.73 / 79.14 | 275 / 14 / 131 |
| asciinema | 82.70 | 92.06 / 75.07 / 82.70 | 255 / 22 / 85 |
| autojump | 81.89 | 96.46 / 71.14 / 81.89 | 382 / 14 / 153 |
| fabric | 71.79 | 92.18 / 58.79 / 71.79 | 224 / 19 / 157 |
| face_classification | 94.86 | 98.76 / 91.26 / 94.86 | 397 / 5 / 38 |

5개 모두 이전과 **예측 간선 집합까지 동일**하다. 점수만 우연히 같은 경우가 아니다. [간선 차이와 점수](comparison.json), [macro 원자료](macro/summary.json)를 남겼다.

| micro 112개 | 이전 | 단일 엔진 |
|---|---:|---:|
| Complete | 111 | 111 |
| Sound | 68 | 71 |
| TP / FP / FN | 182 / 1 / 72 | 182 / 1 / 72 |

Sound 3개 증가는 호출 추론 증가가 아니라 **빈 모듈·import 전용 모듈 노드의 누락 복구** 때문이다. 공식 scorer는 나가는 호출이 없는 노드도 요구한다. 바뀐 사례는 `imports/parent_import`, `imports/relative_import_with_name`, `imports/submodule_import_from`이다. 다른 4개 예제에서도 모듈 노드는 복구됐지만 호출 누락이 남아 Sound는 늘지 않았다. 간선 TP/FP/FN과 예측 호출은 그대로다. [이전 micro](before-micro.json), [현재 micro](micro.json)에 실제 엔진·어댑터 경로를 기록했다.

## 기능 보존과 검사

**513 passed, 7 skipped, 41 subtests passed.** [검사 원문](tests.txt). 7개 skip은 기존과 같이 외부 프로젝트 기준선 6개와 선택적 브라우저 검사 1개다. 원본 테스트에는 호환 CLI 검사도 있으므로 이 숫자 전체를 새 엔진만의 기능 검증 수라고 부르지 않는다.

- 별도 `analyze_project` 모듈을 사용할 수 없는 상태에서 `Resolver.build` 1회·`ObjectFlow.run` 1회로 분석되는지 검사했다. 공유 AST 객체의 동일성, JSON fallback에서 파일당 한 번 파싱, 임시 소스 쓰기 없음도 검사했다.
- 이전 통합본과 이정연 원본 fixture **11개 묶음**을 같은 입력으로 대조했다. 이전에 선택하던 내부 호출 **182개 모두 유지**했다. `tests/single_engine_expected_calls.json`에 동결해 회귀 검사한다. 기존 정적 참조 18개도 모두 보존하고 `tests/single_engine_expected_references.json`에 고정했다. 콜백으로 전달한 bound method와 데코레이터 참조도 포함한다. 진입점의 `(노드, 종류)` 집합, 동적 호출 표식, import 순환 결과도 이 예제 범위에서 일치한다. 이는 모든 입력에서 원본과 동치라는 증명은 아니다.
- fixture에 새로 생긴 후보 3개는 `Service.ambiguous_union → Child.ping`, `use.overloaded → Item.run`, `tpkg.use.use → App.run`이다. union·반환 타입·명시적인 Protocol 타입의 근거에서 나온 may-call이며, 이 예제에는 공식 정답 점수가 없어 정확도 향상 수치로 계산하지 않는다. [기능 대조 원자료](features-comparison.json).
- 정세은 원본의 “union 타입은 해석하지 않는다” 검사 한 건은 과거 `baseline`에서 기존 기대값을 유지하고, 통합 모드에서 정확한 대상과 `MAY_CALL`을 함께 검사하도록 확장했다. 정답을 삭제하거나 실패를 skip하지 않았다. `Optional`/union 타입을 해석하는 의도된 정책 확장이다.
- 필드 재대입·클래스 factory 바꿔치기·가려진 framework 이름·테스트가 아닌 클래스·정적 참조와 실제 호출의 구분도 반례로 검사했다. HTML, VS Code 내보내기와 VSIX 번들 검사도 전체 검사에 포함한다.

## 시간 측정

같은 머신·Python 3.12.2에서 5개 프로젝트 전체를 전후 교차 순서로 **5회씩** 실행했다. 프로세스 시작, 선택된 엔진 파이프라인, 모든 JSON·HTML 출력을 포함한다. **순수 추론 시간만의 측정은 아니다.**

중앙값 **2.313179초 → 1.906174초**, 약 **17.60% 감소**. [최종 반복 측정](timing-selected.json)에 모든 실행값과 프로젝트별 시간을 남겼다. `timing.json`·`timing-final.json`·`timing-before-references.json`은 보완 전 중간 측정이며 버전 선택 수치는 아니다.

## 출력 계약과 남은 한계

- 통합 그래프 schema는 3이다. 내부 심볼과 탐색 정보는 공통 노드 ID를 쓴다. `ljy_result`라는 호환 키와 `ljy_graph.json` 파일명은 남지만, 두 번째 분석 결과가 아니다.
- 같은 엔진 안에서도 확실한 본문 흐름과 선언 타입에 근거한 보충 후보는 구분한다. `supported`는 근거 있는 보충 후보를 고른다. 이를 실제 실행이 보장된 호출이라고 표현하지 않는다. `primary`는 보충 후보를 제외하며, 타입 컨테이너처럼 본 엔진으로 옮긴 기능 자체를 끄는 옵션은 아니다.
- `augmented`는 현재 엔진이 만든 모든 보충 관계를 선택한다. 과거 별도 분석기의 모든 휴리스틱 후보를 재현하는 모드가 아니다. 그 과거 결과가 필요하면 보존한 이전 버전을 실행해야 한다. 원본의 모든 추정 규칙을 기본 경로로 무조건 옮기지는 않았다.
- 원본 호환 JSON의 외부 분류도 통합 엔진의 최종 `call_statuses`를 출력 형식으로 바꾼 것이다. 과거 독립 분석기의 휴리스틱 분류 수치와 동일하다고 보장하지 않는다.
- 재귀·분석 예산, 동적인 재바인딩, 데코레이터·고차 함수·제너레이터 등의 기존 한계는 남는다. micro Sound 71/112는 앞서 인용한 논문 PyCG의 103/112에 못 미친다. 이번 결과로 PyCG를 전반적으로 이겼다고 결론 내리지 않는다.

## 재현 명령

```bash
# 이전 버전 실행용 복원
mkdir -p benchmarks/single-engine-before
tar -xzf experiments/2026-10-25-single-engine/baseline-source.tar.gz -C benchmarks/single-engine-before
python3 -m pytest tests -q
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --output out/single-macro
python3 scripts/rescore_pycg_outputs.py --source experiments/2026-10-24-integration-refinement/final-macro --benchmark benchmarks/pycg-evaluation --output out/before-rescored
python3 scripts/evaluate_pycg_micro.py --engine-root benchmarks/single-engine-before --benchmark benchmarks/pycg-evaluation --output out/before-micro.json
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --output out/single-micro.json
python3 scripts/evaluate_integration_fixtures.py --engine-root benchmarks/single-engine-before --output out/features-before.json
python3 scripts/evaluate_integration_fixtures.py --output out/features-after.json
python3 scripts/benchmark_integration_latency.py --before benchmarks/single-engine-before --benchmark benchmarks/pycg-evaluation --repeat 5 --output out/single-timing.json
```

이번 실행은 `/private/tmp/knitcode-review-venv/bin/python`을 사용했다. 원격 저장소에 커밋하거나 푸시하지 않았다.
