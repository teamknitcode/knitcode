# 이정연 기능 통합 실험 (2026-10-24)

**2026-10-25 정정:** 이 문서는 당시 기준선의 역사 기록이다. 중첩 함수 표기 오류를 수정하고 암묵 호출 포함 동일 기준으로 다시 비교한 결과는 [최신 정정 보고서](../../experiments/2026-10-24-integration-refinement/REPORT_KO.md)에 있다. 당시 일부 오탐 증가로 해석한 결과를 현재 결론으로 사용하지 않는다.

## 결정

**기본값은 `integrated` + `supported`로 선택했다.** 기존 모듈형 엔진의 예측·호출 상태를 유지하고, 이정연 분석기의 타입 추적 근거가 있는 미해결 호출과 암묵 호출을 보강한다. 넓은 다형성 후보와 참조·탐색 정보도 삭제하지 않고 별도로 제공한다.

## 기준선 보존

- Git HEAD `5e92661301daf94767bfa6a9aa9d7daf0b7dc1bc`만으로는 시작 상태를 재현할 수 없다. 당시 미커밋 수정과 보고서까지 포함해 `baseline-source.tar.gz`와 파일별 `baseline-manifest.json`으로 보존했다.
- 압축본 SHA-256: `51aad3ef319b5b9691cae8709b2f661e3309ba2caac8023c837a4e09dd421be3`. 기존 보고서·실험 결과를 지우거나 원본 브랜치에 푸시하지 않았다.
- 최종 코드·프로젝트·공식 자료의 커밋과 해시는 `selection.json`에 기록했다. 별도의 `selected-source.tar.gz`·manifest로 선택본도 보존한다.

## 통합 방법과 출력 계약

원본을 전면 재작성하지 않고 **원본 엔진 보존 + 공통 파이프라인 어댑터** 방식으로 통합했다. 각 엔진은 같은 사전 수집 소스 스냅샷을 분석하며, 대상 코드를 import하거나 실행하지 않는다. 이정연 분석기는 임시 디렉터리에 스냅샷을 복원해 분석한다. 이는 한 번의 AST 해석으로 모든 기능을 처리하는 단일 엔진 통합이 아니므로 추가 비용이 든다.

- `analyze_project.py`, `knit_viewer.py`, `viewer_template.html`, `compare_pycg.py`는 이정연 원본을 그대로 복구했다. 실행 추적 원본은 이름 충돌을 피해 `ljy_trace_recall.py`로 보존했다.
- `ljy_integration.py`가 원본 ID와 현재 엔진 ID를 파일·모듈·심볼·줄 정보로 대응시킨다. 현재 엔진에 없는 원본 범위는 `supplemental_nodes`로 구분한다.
- `edges`, `implicit_edges`, `call_statuses`, resolved/unresolved 카운트는 기존 엔진의 계약을 유지한다. 이정연의 추가 관계는 `supplemental_edges`에 producer·근거·certainty와 함께 기록한다. 참조를 실제 호출로 세지 않는다.
- 타입 컨테이너·진리값 검사·다형성 후보·함수 참조를 복구했다. 자식 호출 후보 `CALLS_OVERRIDE`와 구조 관계 `OVERRIDDEN_BY`는 서로 다르게 보존한다.
- 진입점·읽는 순서·계층·순환·동적 호출 정보는 공통 ID로 변환해 기본 JSON과 VS Code 결과에 제공한다. 현재 Flow HTML은 선택한 추가 호출을 표시한다.
- 원본 전체 정보와 기존 읽는 순서 UI는 `ljy_graph.json`·`ljy_report.html`로 출력한다. 이 두 파일의 ID는 원본 `파일::정의` 형식이다. 원본에서만 발견된 넓은 후보·메타데이터도 여기에서 확인할 수 있다.
- 호출 상태 카운트가 그대로이므로 추가 후보 수를 resolved 카운트로 해석해서는 안 된다. 기존 실행 추적기의 primary/implicit 지표도 새 보충 후보의 런타임 검증을 뜻하지 않는다.

## 비교한 정책

1. **baseline / primary:** 시작 시 보존한 기존 엔진·기존 후보만 사용한다.
2. **integrated / augmented:** 안전한 현재 callable에 대응되는 이정연 후보를 넓게 합친다. 추가 자식 후보 때문에 FP가 늘어 채택하지 않았다.
3. **integrated / supported:** 추가 명시적 호출은 원본의 타입 추적 근거(`type_hint`, `container_elem`, `local_assign`, `self_attr`, `return_type`)가 있고 같은 호출자·같은 줄에 기존 해석이 없을 때만 자동 선택한다. 원본 간선의 column 정보가 충분하지 않으므로 같은 줄에 여러 호출이 있으면 보수적으로 선택을 제한한다. 암묵 호출은 별도 간선으로 유지한다. 넓은 자식 후보는 조회용으로 보존하되 기본 예측에 합치지 않는다.

모든 정책에서 현재 엔진이 확인한 데코레이터·이름 바꿔치기 장벽을 원본 후보가 덮어쓰지 않게 했다. 이 정책은 정답의 함수 이름을 하드코딩하거나 프로젝트별 설정을 바꾸지 않는다. 전체 합집합의 오류를 본 후 설계한 탐색적 변경임을 명시한다.

채택 검사: 5개 프로젝트 각각의 P/R/F1이 기존보다 낮아지지 않을 것, micro Complete/Sound가 낮아지지 않을 것, 기존 primary 점수가 그대로 재현될 것, 통합·회귀 검사가 통과할 것. 이 조건을 선택본이 만족했다.

## 공식 PyCG macro 결과

입력은 공식 `vitsalis/pycg-evaluation`에 고정된 5개 프로젝트와 패키지 루트를 따른다. 공식 채점 함수를 변경하지 않았다. 주 지표는 앞선 평가와 같은 명시적 내부 호출 + 정적 근거가 있는 외부 호출이다. 암묵 호출 포함 값은 각 summary.json에 별도로 보존한다. PyCG 자체를 이번에 새로 실행한 것은 아니다.

| 프로젝트 | 기존 P / R / F1 (%) | 전체 합집합 P / R / F1 (%) | 선택본 P / R / F1 (%) | 선택본 TP / FP / FN |
|---|---|---|---|---|
| Sublist3r | 95.5 / 67.5 / 79.1 | 86.4 / 67.5 / 75.8 | 95.5 / 67.5 / 79.1 | 274 / 13 / 132 |
| asciinema | 96.9 / 73.0 / 83.3 | 95.4 / 73.0 / 82.7 | 96.9 / 73.0 / 83.3 | 248 / 8 / 92 |
| autojump | 96.7 / 71.1 / 82.0 | 94.3 / 71.1 / 81.1 | 96.7 / 71.1 / 82.0 | 382 / 13 / 153 |
| fabric | 95.1 / 56.4 / 70.8 | 95.3 / 58.0 / 72.1 | 95.3 / 58.0 / 72.1 | 221 / 11 / 160 |
| face_classification | 98.8 / 91.3 / 94.9 | 98.5 / 91.3 / 94.7 | 98.8 / 91.3 / 94.9 | 397 / 5 / 38 |

프로젝트별 평균 F1: 기존 82.01% → 전체 합집합 81.29% → **선택본 82.26%**.

fabric은 올바른 호출 6개를 더 찾았고 FP 11개는 유지했다. 나머지 4개 프로젝트의 주 점수는 정확히 같다. 이것은 PyCG 논문 전체를 이겼다는 뜻이 아니다. fabric F1은 논문 PyCG의 약 76.0%에 아직 못 미치고, 다른 프로젝트에서도 정밀도 차이가 남아 있다.

### 암묵 호출까지 포함한 보조 평가

| 프로젝트 | 기존 P / R / F1 (%) | 선택본 P / R / F1 (%) |
|---|---|---|
| Sublist3r | 95.2 / 67.7 / 79.1 | 95.2 / 67.7 / 79.1 |
| asciinema | 92.1 / 75.1 / 82.7 | 92.1 / 75.1 / 82.7 |
| autojump | 96.5 / 71.1 / 81.9 | 96.0 / 71.1 / 81.7 |
| fabric | 92.0 / 57.2 / 70.6 | 91.8 / 58.8 / 71.7 |
| face_classification | 98.8 / 91.3 / 94.9 | 98.8 / 91.3 / 94.9 |

autojump는 FP가 14→16으로 늘어 이 보조 평가의 F1이 약 0.18점 하락했다. fabric은 TP 218→224, FP 19→20이다. 선택은 기존과 같은 주 평가 및 기능 보존을 우선한 것으로, 시간과 암묵 호출 포함 모든 지표에서 엄격히 우월한 버전이라는 뜻은 아니다. 추가 원본 후보는 계속 별도 조회·평가할 수 있다.

### 시간 (단회, 분석·모든 출력 포함)

| 프로젝트 | 기존 초 | 선택본 초 |
|---|---:|---:|
| Sublist3r | 0.31 | 0.54 |
| asciinema | 0.23 | 0.41 |
| autojump | 0.42 | 0.72 |
| fabric | 0.29 | 0.44 |
| face_classification | 0.33 | 0.48 |

같은 머신·Python에서 측정했으나 반복 평균이 아니며, 추가 분석기·JSON·원본 뷰어 출력 비용을 포함한다. 대형 저장소 속도와 순수 분석기 성능의 우열은 이번 수치로 주장하지 않는다. 속도가 더 중요하면 `--analysis-profile baseline`을 선택할 수 있다.

## Micro 112개와 회귀 검사

| 버전 | Complete | Sound |
|---|---:|---:|
| 기존 | 111/112 | 68/112 |
| 전체 합집합 | 110/112 | 68/112 |
| 선택본 | 111/112 | 68/112 |

공식 자료의 용어 그대로 Complete는 과다 간선이 없는지, Sound는 정답 노드·간선을 모두 포함하는지 검사한다. 선택본은 암묵 호출 포함 micro 검사도 111/68로 같다. 논문 PyCG의 Sound 103/112와는 차이가 크다. 이번에는 언어 기능 전반의 성능 향상이 아니라 원본 기능 복원과 제한적인 macro 개선을 확인했다.

**최종 pytest: 496 passed, 7 skipped, 27 subtests passed.** 정세은 원본 265개를 `tests/jse_original`, 이정연 원본 66개를 `tests/ljy_original`에 복원했다. 이정연 원본 중 외부 프로젝트 기준선 6개와 브라우저 선택 검사 1개는 필요한 입력/환경이 없어 skip이다. 테스트 실행 수는 중복 기능에 대한 독립적인 정확도 증거 수와 같지 않다.

기존 `@lru_cache` 테스트 실패는 recorder 검사와 분석 정책을 혼합했던 문제였다. 정상 호출에 대한 실제 기록 검사는 recall 1.0을 계속 요구하고, 데코레이터 fixture는 실제 누락이 `test_cached → cached` 한 건인지 별도 검증한다. 기대값만 낮춰 같은 테스트를 통과시킨 것이 아니며, 불투명 데코레이터 호출을 여전히 놓친다는 사실을 숨기지 않는다.

새 통합 검사는 타입 컨테이너, 진리값 암묵 호출, 참조/호출 분리, 자식 후보/구조 관계 분리, 1차 상태 보존, 바꿔치기·이름 범위 반례, src 레이아웃, 순환·동적 표식, 원본 HTML 출력과 공유 ID 무결성을 확인한다. VSIX 번들 실행·웹뷰 검사도 전체 pytest에 포함된다.

## 재현과 버전 선택

```bash
python3 main.py <프로젝트> --analysis-profile integrated --call-policy supported --output-dir output
python3 main.py <프로젝트> --analysis-profile baseline --output-dir output_baseline
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --analysis-profile integrated --call-policy supported --output out/selected
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --analysis-profile integrated --call-policy augmented --output out/augmented
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --analysis-profile integrated --call-policy supported --output out/micro.json
python -m pytest tests -q
```

정확한 시작 버전으로 돌아가려면 `baseline-source.tar.gz`를 별도 빈 디렉터리에 풀어 실행한다. 현재 파일 위에 덮어쓰지 않고 버전을 나란히 비교하는 것을 권장한다. baseline 옵션은 기존 해석 알고리즘을 선택하고, 압축본은 미커밋 파일까지 포함한 당시의 정확한 소스 상태를 재현한다.

보존 자료: baseline/augmented/selected macro의 summary.json·프로젝트별 result.json·호출 그래프, 112개 예제별 JSON, selection.json·출처 해시, 원본 코드 압축본, 테스트 로그. 큰 AST·symbol·HTML 중간 산출물은 각 `analysis/`에 로컬로 보관하고 Git에서는 제외한다.

## 진행 기록

- 시작 작업 트리 보존 → 보존한 코드에서 공식 기준선 재실행.
- 원본 API·뷰어·테스트 복구, 공유 노드·별도 후보 어댑터 구현.
- 최초 원본 module 노드의 선택적 name 필드 처리와 추적 도구 이름 충돌을 수정.
- 전체 후보 합집합에서 정밀도 저하 확인 → 타입 근거 기반 보수적 정책을 추가해 세 정책을 비교.
- 복원한 테스트의 상대 경로 수정, recorder와 데코레이터 정책 검사 분리.
- 최종 선택본·전체 합집합을 같은 최종 코드에서 재실행하고 기준선 동일성·496개 검사 통과 확인.
- 통합평가보고서와 별도 실험 로그 갱신. 원격 푸시·배포는 하지 않음.
