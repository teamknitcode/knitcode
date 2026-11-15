# 동적 분석 실행 안내

정적 그래프를 유지하면서 실제 실행에서 관찰한 호출을 별도 결과로 보강합니다.
대상 코드를 실제 실행하므로 대상 프로젝트의 의존성이 설치된 Python을 사용하세요.

## 호출 중심 실행

저장소 루트에서 실행합니다. `PROJECT`는 대상 프로젝트 경로입니다.

```bash
python3 main.py PROJECT --output-dir out/static
python3 dynamic_analysis.py record PROJECT --script app.py --calls-only --out out/trace.json
python3 dynamic_analysis.py compare --static-dir out/static --trace out/trace.json --out out/hybrid_graph.json
```

- 파일 대신 모듈 실행: `--script app.py`를 `--module package`로 변경합니다.
- pytest 실행 예: `--module pytest --calls-only --out out/trace.json -- tests/test_example.py`
- 실행 환경 선택: `--python /path/to/venv/bin/python`
- `--calls-only`는 호출·타입을 수집하고 줄·opcode 추적은 끕니다. 생략하면 커버리지와 변수 접근도 수집해 비용이 증가합니다.
- 기본적으로 자식 Python 프로세스도 수집합니다. `--no-children`은 진입 프로세스로 수집 범위를 제한합니다.

## 결과 해석

- `confirmed`: 호출자·호출 대상·호출 줄이 정적 결과와 일치
- `additional`: 정적 결과에서 찾지 못한 실행 관찰 관계
- `unmapped`: 소스 불일치 또는 표현되지 않은 실행 범위 등으로 연결 불가
- `scope_entry`: 모듈·클래스 본문 진입

미관찰 간선을 잘못된 호출로 판단하거나 삭제하지 않습니다. 결과는 실행한 입력과 경로에 한정됩니다.
`profile_calls`와 간선 `count`는 프로파일 이벤트 수이며 제너레이터·코루틴 재개를 포함합니다.
`complete`는 수집 상태이며 모든 코드 경로를 실행했다는 뜻이 아닙니다.
소스 해시가 일치하지 않으면 정적 노드 연결을 차단합니다. VS Code 화면 연동은 별도 작업입니다.

## 검증

```bash
python3 -m unittest discover -s tests -p test_dynamic_analysis.py -v
```

Python 3.12에서는 opcode 추적을 켜기 전에 기존 프레임의 `f_trace_opcodes`를 설정해야 합니다.
수집기는 설정 후 프레임 플래그를 원복합니다. [Python 공식 문서](https://docs.python.org/3.12/library/sys.html#sys.settrace)
