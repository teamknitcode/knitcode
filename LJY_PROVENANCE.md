# 이정연 분석기 원본 보존

`knit_viewer.py`, `viewer_template.html`, `compare_pycg.py`는 Lee-jeongyeon/KnitCode의 main `d3a9da6`에서 변경 없이 가져왔다. 원본 API·JSON·오프라인 뷰어를 보존한다. 원본 `trace_recall.py`도 변경 없이 보존하되 현재 추적 도구와 충돌하지 않도록 파일 이름은 `ljy_trace_recall.py`로 정했다.

`tests/ljy_original`의 원본 테스트는 저장 위치에 맞춰 ROOT 경로를 조정하고 위 추적 도구의 import·CLI 경로만 새 이름으로 변경했다. 호출 정답은 변경하지 않았다. `tests/jse_original`은 정세은 기반 원본 테스트를 보존하며, 재배치된 CLI 경로와 fixture 수집 제외만 조정했다.

2026-10-24 통합 어댑터는 `ljy_integration.py`다. 기존 모듈형 엔진의 호출 상태와 이정연의 보충 후보를 구분한다. 기본 `supported` 정책은 기존 해석을 유지하고 타입 추적 근거가 있는 미해결 호출만 예측에 추가한다. 전체 원본 결과·다형성 후보·참조·탐색 메타데이터는 별도로 유지한다.


2026-10-25 최적화에서 `analyze_project.py`에는 기존 독립 실행 API를 유지하면서 사전 파싱 AST·스냅샷 기반 import/console-script 메타데이터를 받을 수 있는 선택적 입력을 추가했다. 원본 의미 분석을 임시 파일로 재구성하지 않고 공유 AST에서 실행하기 위한 변경이다. 원본 상태는 이전 실험 소스 압축본에 보존했고, 디스크 분석·스냅샷·JSON fallback의 결과 동일성을 회귀 검사로 확인했다.

기본 `supported` 정책은 이제 선언된 부모 타입 매개변수에 한해 C3 계층으로 증명되는 자식 후보도 선택한다. 구체 객체의 임의 자식 확장은 계속 제외한다.

## 2026-10-25 단일 엔진 이식

현재 기본 경로는 `analyze_project.analyze`를 호출하지 않는다. `ljy_integration.py`의 별도 실행 어댑터를 제거했고 출력·정책 선택만 남겼다. `graph_navigation.py`는 원본의 순수 그래프 집계·표시·설정 파싱 함수를 추출한 파일이며, `graph_entrypoints.py`와 `unified_graph.py`는 기존 Resolver의 심볼·import·AST·호출 결과를 사용한다. 타입·컨테이너·클래스 값·암묵 호출은 `object_flow.py`에 이식했다.

`analyze_project.py`와 원본 CLI·회귀 검사는 독립 API의 재현용으로 유지한다. 이 파일의 존재를 기본 경로에서 두 엔진을 실행한다는 의미로 해석하지 않는다. 기존 JSON·HTML은 통합 결과를 원래 ID 형식으로 변환해 생성한다. 과거 독립 분석기의 모든 추정 후보·분류 수치를 그대로 반환한다는 계약은 아니다.

정세은 원본 `tests/jse_original/test_v24.py`의 union 미지원 검사 한 건은 `baseline`의 기존 기대값을 유지하고, 통합 모드의 정확한 may-call 대상도 확인하도록 확장했다. 이번 변경의 동결 버전·기능 대조·검사 기록은 [단일 엔진 보고서](experiments/2026-10-25-single-engine/REPORT_KO.md)에 남겼다.
