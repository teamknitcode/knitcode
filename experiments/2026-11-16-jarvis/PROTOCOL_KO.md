# Jarvis 후속 실험 프로토콜

- 도구: PR #4 병합 후 main (`b0eaa8a`)
- 자료: 공식 `pythonJaRvis/pythonJaRvis.github.io`의 고정 snapshot
- 대상: sqlparse·furl. 둘 다 제공 소스·EA 정답·원본 테스트가 있으며 외부 서버가 필요하지 않음
- 입력 범위: 공식 `pycg_EA.sh`에 열거된 앱 Python 파일(동일 패키지 폴더의 전체 Python 파일)
- 실행: sqlparse `tests` 전체, furl `tests`에서 일반 실행부터 실패한 `TestFurl.test_hosts`, `TestFurl.test_netloc`만 제외. 정답 채점 전에 고정
- 주평가: 소스 AST로 독립적으로 열거한 `def`/`async def` 이름을 양 끝점으로 갖는 함수 간 호출. GT·정적 예측·동적 관찰에 같은 조건을 적용
- 제외 범위: 모듈 import·클래스 본문 진입·외부/내장·람다·소스에 없는 동적 생성 함수. 전체 EA 예측/GT는 별도 보존
- 결합: 정적 예측 ∪ 소스 검증 및 노드 매핑을 통과한 실행 호출. 정답에 맞춰 추가 호출을 선택하거나 제거하지 않음
- 비교: 정적 단독 / 정적+호출 중심 / 정적+전체 추적. 일반 실행도 비용 기준으로 측정
- 추적 및 일반 실행 각 3회, 순환 순서. 정적 분석 1회. 같은 Python 환경·테스트 사용
- 출력: TP·FP·FN·정밀도·재현율·F1, 실행 시간·최대 RSS·결과 크기, 미매핑 및 범위 밖 호출, 추가 관계별 정답 여부
- 해석: Jarvis 논문 전체 EA/진입점 중심 점수의 재현이 아니라, 공통 함수 호출 범위를 사용한 별도 보조 분석 평가임

실행 중 변경: furl 전체 추적 첫 실행이 240초 제한을 초과해 해당 모드의 나머지 반복은 중단했다. 완료 점수·중앙값을 추정하지 않는다. 완료한 호출 중심·일반 실행만 재사용하여 남은 반복을 이어간다. 최초 실행기의 하위 프로세스 종료 처리를 보완했으며 이 변경은 수집기·평가 범위·점수 계산을 변경하지 않는다.

공식 근거: [GT 안내](https://github.com/pythonJaRvis/pythonJaRvis.github.io/tree/master/Jarvis/ground_truth), [입력 범위 스크립트](https://github.com/pythonJaRvis/pythonJaRvis.github.io/blob/master/Jarvis/reproducing_RQ12_setup/macro_benchmark/pycg_EA.sh).
