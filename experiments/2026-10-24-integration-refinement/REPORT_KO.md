# 통합 손실 개선·평가 정정 실험

시작 2026-10-24 / 완료 2026-10-25 (Asia/Seoul). 직전 선택본을 보존한 뒤 같은 데이터·변환 기준으로 비교했다.

## 결과와 정정

**직전 통합본과 같은 검출 결과를 유지하면서 중복 처리 비용을 줄였다. 이전에 통합 때문에 늘었다고 설명한 오탐 3건은 평가 이름 변환 오류였다.** 해당 간선을 삭제하지 않았고, 보존한 이전 예측도 같은 변환기로 재채점했다. 이번 코드 변경으로 macro 정확도가 새로 높아졌다고 주장하지 않는다.

- 암묵 호출을 포함한 선택된 전체 호출을 기본 평가(`paper`)로 사용한다. 명시적 호출만 센 값은 진단용으로 남긴다. 이것은 논문이 주/보조 평가를 나누었다는 의미가 아니다.
- PyCG의 중첩 함수 이름에는 CPython의 `<locals>` 표식이 없다. 공통 어댑터에서 일반적인 `.<locals>.` 표기만 제거한다. 정답을 보고 특정 함수명을 바꾸는 규칙을 추가하지 않았다.
- 실제 예제는 autojump의 중첩 `take_action`, `consume_optional`에서 `ArgumentError(...)`를 생성하는 호출과 fabric의 중첩 `callback`에서 `Tunnel(...)`을 생성하는 호출이다. 소스에 존재하며 공식 정답에도 해당 어휘 범위의 호출이 있다. 잘못된 표기 때문에 같은 의미의 간선이 별도 오탐처럼 집계됐다.
- autojump의 보고 FP 16은 같은 예측을 올바르게 표기하면 **14**이고, fabric의 FP 20은 **19**다. 수정 전·후 실제 엔진을 같은 변환기로 평가하면 동일하다. 세부 수치는 `evaluation-correction.json`에 보존했다.

## 구현 개선

1. **프로젝트 소스·AST 공유:** 최초 스캔의 AST를 `SourceSnapshot`으로 두 분석기에 전달한다. AST는 프로세스 내부 속성이므로 JSON에는 직렬화하지 않는다. 기존처럼 JSON에서 다시 시작할 때는 소스 파싱으로 돌아가며, 같은 결과임을 검사한다.
2. **임시 파일 재구성 제거:** 매번 임시 디렉터리에 소스를 쓰고 다시 읽던 단계를 제거했다. 이정연 분석기에 선택적인 parsed-files 입력을 추가하고, 원본 독립 실행 경로는 유지했다. 패키지·import 별칭 처리는 기존 공통 함수를 재사용한다.
3. **출력 비용 감소:** 원본 뷰어의 소스 발췌는 함수마다 파일 전체를 split하지 않고 파일당 한 번 계산한다. ObjectFlow도 파일마다 전체 심볼을 순회하지 않도록 파일별로 인덱싱한다.
4. **필요한 다형성 후보 보존:** 부모 타입을 선언한 매개변수에 자식 객체가 들어올 수 있고 C3 계층이 확인되는 경우 자식 호출 후보를 선택한다. `obj = Base()`처럼 구체적으로 만든 객체에 임의의 자식 메서드는 추가하지 않는다. 바꿔치기·데코레이터 장벽도 유지한다.
5. **평가 코드 분리:** `pycg_adapter.py`는 분석 엔진과 독립적인 표기·채점 어댑터다. 동결한 엔진과 현재 엔진을 서로 다른 프로세스에서 같은 어댑터로 평가해 기준 변경과 모델 변경을 구분한다.

## 암묵 호출 포함 동일 기준 결과

| 프로젝트 | 통합 전 단일 엔진 F1 (%) | 직전 통합본 재채점 F1 (%) | 개선본 P / R / F1 (%) | 개선본 TP / FP / FN |
|---|---:|---:|---|---|
| Sublist3r | 79.14 | 79.14 | 95.16 / 67.73 / 79.14 | 275 / 14 / 131 |
| asciinema | 82.70 | 82.70 | 92.06 / 75.07 / 82.70 | 255 / 22 / 85 |
| autojump | 81.89 | 81.89 | 96.46 / 71.14 / 81.89 | 382 / 14 / 153 |
| fabric | 70.55 | 71.79 | 92.18 / 58.79 / 71.79 | 224 / 19 / 157 |
| face_classification | 94.86 | 94.86 | 98.76 / 91.26 / 94.86 | 397 / 5 / 38 |

5개 프로젝트 모두 직전 통합본과 개선본의 P/R/F1·TP/FP/FN이 정확히 같다. 원래 단일 엔진과 비교하면 fabric의 추가 검출 이점도 유지된다. 직전 통합본의 잘못된 이름 변환으로 생긴 손해를 새로운 엔진 개선 성과로 계산하지 않는다.

공식 micro 112개도 동결한 이전 엔진과 현재 엔진을 공통 어댑터로 각각 실행했다. 둘 다 **Complete 111 / Sound 68**, 간선 기준 TP 182 / FP 1 / FN 72다. 이전 보고의 TP 178과의 차이도 이름 변환 수정에 따른 것이며 알고리즘 향상으로 해석하지 않는다. 엔진과 어댑터의 실제 파일 경로를 각 JSON에 남겼다.

## 처리 시간

같은 머신에서 5개 프로젝트의 전체 파이프라인(프로세스 시작·두 분석기·모든 JSON/HTML 출력)을 전후 교차 순서로 **5회씩** 실행했다. 중앙값은 **2.460초 → 2.362초**, 약 **4.0% 감소**다.

작은 차이이며 실행 환경·I/O 캐시·스케줄링 영향을 받는다. 모든 환경에서 같은 속도 개선을 보장하거나 기존 단일 분석기 수준의 비용으로 복구됐다고 주장하지 않는다. 원본과 현재의 모든 출력은 그대로 생성했다. `timing-selected.json`에 각 실행값과 프로젝트별 시간을 보존했다. `timing.json`, `timing-final.json`은 중간 단계 측정 이력이다.

## 검증과 남은 한계

- **501 passed, 7 skipped, 30 subtests passed.** 기존 정세은·이정연 원본 회귀 검사와 번들 VSIX·웹뷰 검사를 포함한다.
- 새 검사는 nested scope와 lambda의 공통 이름 변환, 공유 AST/디스크 분석/JSON fallback의 동일성, 패키지·src 레이아웃·console script 메타데이터 보존, 발췌 출력 비용, 선언 타입의 자식 후보와 구체 객체의 반례를 확인한다.
- 기본 엔진의 명시적 호출 상태 집계는 그대로다. 보충 후보는 `supplemental_edges`에서 provenance와 선택 근거를 유지한다.
- 두 의미 분석기는 여전히 별도로 유지한다. 이번에는 소스·AST·이름 변환·패키지 보정을 공유했으며, 전체 알고리즘을 하나로 재작성한 것은 아니다.
- micro Sound 68/112는 논문 PyCG의 103/112에 못 미친다. 데코레이터·고차 함수·제너레이터 등의 기존 누락과 별도 검증 프로젝트에 대한 일반화 문제는 남아 있다.

## 재현

```bash
python3 scripts/rescore_pycg_outputs.py --source experiments/2026-10-24-ljy-integration/selected-macro --benchmark benchmarks/pycg-evaluation --output out/before-rescored
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --output out/refined
python3 scripts/evaluate_pycg_micro.py --engine-root benchmarks/refinement-before --benchmark benchmarks/pycg-evaluation --output out/before-micro.json
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --output out/after-micro.json
python3 scripts/benchmark_integration_latency.py --before benchmarks/refinement-before --benchmark benchmarks/pycg-evaluation --repeat 5 --output out/timing.json
python -m pytest tests -q
```

이전 엔진은 `baseline-source.tar.gz`를 별도 빈 디렉터리에 풀어 `--engine-root`/`--before`에 지정한다. 재채점용 원시 analysis 파일을 로컬에서 정리했다면 해당 동결 소스로 같은 공식 입력을 분석해 재생성할 수 있다. source archive·manifest·selection.json에 버전과 해시를 보존한다. 큰 중간 `analysis/`는 로컬 보관·Git 제외이며, 점수·정정 내역·테스트·반복 측정 결과는 별도로 남겼다. 원격 푸시·배포는 하지 않았다.
