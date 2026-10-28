# PyCG 논문 데이터셋 평가 — KnitCode 통합본

**2026-10-25 정정:** 이 문서는 당시 기준선의 역사 기록이다. 중첩 함수 표기 오류를 수정하고 암묵 호출 포함 동일 기준으로 다시 비교한 결과는 [최신 정정 보고서](../../experiments/2026-10-24-integration-refinement/REPORT_KO.md)에 있다. 당시 일부 오탐 증가로 해석한 결과를 현재 결론으로 사용하지 않는다.

평가일: 2026-10-23 (Asia/Seoul). 대상: `merge`의 `5e92661` + 외부 호출 내보내기의 null 이름 방어 수정.

2026-10-24 이정연 기능 통합 후 재평가는 [별도 실험 보고서](../../experiments/2026-10-24-ljy-integration/REPORT_KO.md)에 기록했다. 이 문서의 점수는 당시 기준선으로 보존한다.

## 결론

**아직 PyCG를 전반적으로 이겼다고 말할 수 없다.** 실제 프로젝트 5개 중 4개에서 재현율·F1이 높지만 정밀도는 5개 모두 낮다. `fabric`에서는 재현율·F1도 낮고, 작은 예제 112개의 호출 누락 방지 능력은 PyCG보다 상당히 낮다.

## 근거와 비교 조건

- [논문: PyCG, ICSE 2021](https://arxiv.org/html/2103.00587), Table III·IV. PyCG는 학습 모델이 아니라 정적 호출 그래프 분석기다.
- [공식 평가 자료](https://github.com/vitsalis/pycg-evaluation), commit `ce37eb5668465b0c17371914e863d699826447ee`. 실제 프로젝트는 최신 버전이 아닌 이 자료에 고정된 커밋을 사용했다.
- PyCG 비교값은 공식 자료의 `data/results/table3.txt`, `table4.txt`에 실린 논문 측정값이다. 이번 환경에서 PyCG를 새로 실행한 결과로 표기하지 않는다.
- macOS / Python 3.12.2. 대상 코드는 실행하거나 의존성을 설치하지 않고 AST로 분석했다.
- Macro 입력 파일과 패키지 루트는 공식 `generate_pycg_cgs.sh`와 일치한다. fabric은 `tests` 또는 `setup.py`가 경로에 있는 파일을 제외하며, 공식 범위에 남는 integration 파일은 포함한다.
- 공식 `measure_precision` / `measure_recall`을 그대로 호출한다. 함수 단위의 중복 없는 caller → callee 쌍이 단위다. 클래스 생성 자체는 함수 간선과 구분하고, 실제 `__init__` 호출은 센다. 외부 호출은 정적 근거가 있는 `KNOWN_NON_INTERNAL`만 포함한다.
- 내장 함수·타입 메서드·람다 이름의 표현을 PyCG 형식으로 변환한다. 정답에 맞춰 특정 간선을 삭제하거나 이름을 추측해 연결하지 않았다. 문장 설명형 외부 origin과 `__init__` 없는 클래스 생성의 제외 수는 결과 JSON에 보존했다.
- 주 비교는 기존 README와 같은 명시적 호출+외부 호출(`full`). 암묵 호출까지 합친 별도 결과도 아래 공개한다. 두 설정 중 프로젝트마다 유리한 값만 고르지 않는다.
- 논문 PyCG F1은 발표된 소수점 한 자리 P/R에서 계산한 파생값이며 논문 자체의 별도 측정값이 아니다. 실행 시간은 같은 머신의 PyCG 측정이 없어 우열 판단에 사용하지 않는다.

## Macro: 실제 프로젝트 5개

| 프로젝트 | 파일 | KnitCode P / R / F1 (%) | 논문 PyCG P / R / F1 (%) | ΔF1 (점) | TP / FP / FN |
|---|---:|---|---|---:|---|
| Sublist3r | 4 | 95.5 / 67.5 / 79.1 | 98.8 / 61.6 / 75.9 | +3.2 | 274 / 13 / 132 |
| asciinema | 24 | 96.9 / 73.0 / 83.3 | 100.0 / 68.0 / 81.0 | +2.3 | 248 / 8 / 92 |
| autojump | 4 | 96.7 / 71.1 / 82.0 | 99.5 / 68.2 / 80.9 | +1.0 | 382 / 13 / 153 |
| fabric | 20 | 95.1 / 56.4 / 70.8 | 98.3 / 61.9 / 76.0 | -5.1 | 215 / 11 / 166 |
| face_classification | 20 | 98.8 / 91.3 / 94.9 | 99.5 / 89.7 / 94.3 | +0.5 | 397 / 5 / 38 |

프로젝트별 단순 평균: KnitCode **P 96.59% / R 71.87% / 평균 F1 82.01%**. 논문 PyCG의 발표 평균은 P 99.2% / R 69.9%다. 평균 F1은 프로젝트별 F1의 평균으로 계산하며 평균 P/R의 조화평균과 다르다. 전체 5개에서 파싱 오류는 0개였다.

### 암묵 호출 포함 결과 (보조 비교)

| 프로젝트 | P / R / F1 (%) | TP / FP / FN |
|---|---|---|
| Sublist3r | 95.2 / 67.7 / 79.1 | 275 / 14 / 131 |
| asciinema | 92.1 / 75.1 / 82.7 | 255 / 22 / 85 |
| autojump | 96.5 / 71.1 / 81.9 | 382 / 14 / 153 |
| fabric | 92.0 / 57.2 / 70.6 | 218 / 19 / 163 |
| face_classification | 98.8 / 91.3 / 94.9 | 397 / 5 / 38 |

암묵 호출 추가는 재현율을 조금 높이지만 FP도 늘린다. 예를 들어 asciinema는 TP 248→255, FP 8→22다. 이 결과만으로 암묵 호출이 실제로 틀렸다고 단정하지 않으며, 공식 정답과 불일치한 간선으로 기록한다.

## Micro: 언어 기능별 112개 예제

공식 `equal_complete`와 `equal_sound`를 그대로 사용했다. **이 자료에서 Complete는 과다 간선이 없는지, Sound는 정답 노드·간선을 모두 포함하는지**를 뜻한다. 용어를 일반적인 직관과 혼동하지 않아야 한다. Complete 함수는 정답에 없는 caller를 건너뛰는 구현이므로 strict 간선 집합 결과도 JSON에 함께 남겼다.

노드는 엔진이 발견한 함수·메서드·모듈·람다 및 추출한 간선의 목적지에서만 구성한다. 정답에만 있는 노드를 결과에 채워 넣지 않는다. 호출이 없는 namespace 노드의 표현 차이도 Sound에 영향을 준다.

| 범주 | 개수 | KnitCode Complete / Sound | 논문 PyCG Complete / Sound |
|---|---:|---|---|
| assignments | 4 | 4 / 2 | 4 / 3 |
| builtins | 3 | 3 / 2 | 3 / 1 |
| classes | 22 | 22 / 21 | 22 / 22 |
| decorators | 7 | 7 / 0 | 6 / 5 |
| dicts | 12 | 11 / 5 | 12 / 11 |
| direct_calls | 4 | 4 / 0 | 4 / 4 |
| exceptions | 3 | 3 / 0 | 3 / 3 |
| functions | 4 | 4 / 4 | 4 / 4 |
| generators | 6 | 6 / 1 | 6 / 6 |
| imports | 14 | 14 / 8 | 14 / 14 |
| kwargs | 3 | 3 / 2 | 3 / 3 |
| lambdas | 5 | 5 / 4 | 5 / 5 |
| lists | 8 | 8 / 4 | 8 / 7 |
| mro | 7 | 7 / 6 | 7 / 5 |
| parameters | 6 | 6 / 6 | 6 / 6 |
| returns | 4 | 4 / 3 | 4 / 4 |
| **합계** | **112** | **111 / 68** | **111 / 103** |

암묵 호출 포함 결과도 **111 / 68**로 같았다. 간선만 기준으로 정답을 모두 찾은 예제는 71/112개이며, 노드 포함 공식 Sound와 구분한다.

## 이기기 위한 우선순위

1. **반환 함수·클로저·고차 함수 전달.** direct_calls 0/4 Sound, lambdas 4/5, returns 3/4다. `func()()`처럼 반환값을 다시 호출하는 흐름과 중첩 함수 환경을 우선 점검한다.
2. **데코레이터의 증명 가능한 경우.** decorators 0/7. 모든 데코레이터를 무시하는 대신, 함수 치환·래퍼·클로저 반환을 정적으로 추적할 수 있는 경우만 연결한다. 지금 남아 있는 실행 추적 테스트 실패와도 관련 있다.
3. **컨테이너 원소·인덱스·구조 분해.** dicts 5/12, lists 4/8, assignments 2/4. 별도 일반화 예제와 반례로 개선을 검증한다.
4. **제너레이터·예외의 암묵 실행.** generators 1/6, exceptions 0/3. `__iter__`, `__next__`, raise 시 예외 생성 호출을 추적한다.
5. **fabric의 외부 부모·객체 반환.** 누락 예시는 `invoke.config.Config._set`, `Config.clone`, `paramiko.config.SSHConfig.parse`. 이들은 정답과 불일치한 사례이며 원인별 확정 진단은 별도 소스 검토가 필요하다. 외부 수신 객체의 근거를 강화해 재현율을 높이면서 정밀도를 유지해야 한다.

같은 벤치마크를 반복해 보며 수정하면 평가 자료에 맞춘 과적합 위험이 있다. 개선 후에는 별도 프로젝트·새 예제를 검증 세트로 남기고, FP/FN·기존 회귀·실행 시간도 같이 비교해야 한다. 이번 결과는 개선 전 기준선이며 분석 정확도를 높이는 알고리즘 변경은 하지 않았다.

## 통합 검증

**3자 원본 대조에 따른 정정:** 이 절은 최초 통합본 자체 검사 요약이다. 이후 GreatJung1·Jeff_Park·Lee-jeongyeon 원본을 대조한 결과, 기반 회귀 검사는 보존되지만 LJY의 일부 타입·참조·다형성·탐색 기능이 미이식된 것을 확인했다. 최종 통합 판단은 [재작성한 통합 평가](../../INTEGRATION_REVIEW_KO.md)를 따른다. 아래 PyCG 점수 자체는 이번 재검토에서 변경하지 않았다.

CLI를 중단시키던 `external_calls.imported()`의 None 처리만 수정했다. constructed 이름이 문자열이 아니거나 비어 있으면 근거 없는 외부 연결을 생략한다. 회귀 테스트를 추가했고, 실제 저장소 분석도 JSON·HTML 생성까지 완료했다. 이 방어는 벤치마크 채점 대상인 내부 호출·call_statuses를 바꾸지 않는다.

최종 전체 pytest는 **163개 통과 / 1개 실패**, 추가 subtest 25개 통과. 남은 실패는 `test_record_with_pytest`: 실제 관찰 호출 7개 중 `test_cached → cached`를 놓쳐 recall이 6/7=0.8571인데 1.0을 요구한다. `@lru_cache` 연결을 제한하는 통합 정책과 기대값이 충돌한다. 테스트를 통과시키려고 기대값을 낮추거나 분석 정책을 무조건 완화하지 않았다.

세부 판단은 [INTEGRATION_REVIEW_KO.md](../../INTEGRATION_REVIEW_KO.md)에 남겼다. 원격에는 푸시하지 않았다.

## 재현

```bash
python3 pycg_benchmark.py --benchmark benchmarks/pycg-evaluation --output out/pycg-20261023
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --output out/pycg-20261023/micro.json
python3 scripts/evaluate_pycg_micro.py --benchmark benchmarks/pycg-evaluation --include-implicit --output out/pycg-20261023/micro-with-implicit.json
python -m pytest tests -q
```

자료 최초 준비는 `git clone https://github.com/vitsalis/pycg-evaluation.git benchmarks/pycg-evaluation` 후 위 metadata의 artifact 커밋으로 체크아웃하고, `data/macro-benchmark/projects/` 아래 5개 프로젝트 submodule을 `update --init`하면 된다.

## 보존한 산출물

- [summary.json](summary.json): 5개 프로젝트 P/R/F1, TP/FP/FN, 파일 수, 파싱 오류, 암묵 호출 보조 비교.
- [micro.json](micro.json), [micro-with-implicit.json](micro-with-implicit.json): 112개 예제별 누락·과다 간선과 공식 점수.
- [metadata.json](metadata.json): 도구·자료·대상 프로젝트 커밋, 환경, 엔진·정답·평가 스크립트 SHA-256.
- 상세 호출 그래프·분석 로그는 `out/pycg-20261023/`에 생성했다(Git 제외). 최종 평가 기준선 요약은 이 디렉터리에 별도로 보존했다.
