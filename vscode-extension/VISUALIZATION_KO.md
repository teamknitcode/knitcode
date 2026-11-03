# knitcode 시각화 (2026-11)

이 문서는 VS Code 확장의 시각화 작업을 이어받는 분을 위한 안내입니다.
교수님 중간 발표 전 피드백 중 **함수 노드 그래프, 줌인·줌아웃, 함수 간 전달값**을 반영한 상태까지 정리했습니다.

## 1. 브랜치

모든 작업은 아래 브랜치에 차례로 쌓여 있습니다. **`feat/call-args` 하나에 전부 들어 있습니다.**

```
main
 └ feat/hotspot-chart     함수 핫스팟 막대 차트
   └ feat/card-change-heat  호출 흐름 카드에 변경 횟수
     └ feat/test-callers      테스트 호출자 분리
       └ feat/type-chips        수정 유형 칩
         └ feat/project-map       프로젝트 지도 (첫 화면)
           └ feat/map-zoom          줌·이동
             └ feat/file-graph        파일 화면을 함수 그래프로
               └ feat/call-args         함수 간 전달값 표시   ← 이어받을 브랜치
```

`main`에는 Git 심층 분석 속도 개선(627초 → 38.5초, PR #1)만 반영되어 있습니다.

## 2. 이번에 바뀐 것과 교수님 피드백

| 교수님 피드백 | 반영 내용 | 상태 |
|---|---|---|
| 함수를 노드로, 파일명은 함께 표시 | 파일을 누르면 그 파일의 함수가 노드인 그래프. 다른 파일 함수에는 파일명 표시 | 완료 |
| 함수 간 흐름 | 파일 안 호출 순서대로 왼쪽→오른쪽 배치, 양옆에 이 파일을 부르는/이 파일이 부르는 다른 파일 함수 | 완료 |
| 줌인·줌아웃 (가독성 = HCI 문제) | 지도와 파일 그래프에서 휠 확대·축소, 끌어서 이동, `− + 전체 보기` | 완료 |
| 함수 간 어떤 값을 전달받는지 | 호출 근거 목록에 "넘기는 값 → 받는 매개변수(선언된 타입 힌트)" 표 | 1차 완료 (선언 타입만) |
| data flow, 타입이 알맞게 넘어가는지 | - | 다음 과제 |
| 메모리 효율 | - | 다음 과제 (측정부터) |
| 자연어 설명 (프롬프트 엔지니어링) | - | 다음 과제 |
| REA | 약자 의미 확인 필요 | 확인 필요 |

## 3. 화면 구조

```
① 프로젝트 지도 (첫 화면)
   칸 = 파일, 색 = 변경 빈도, 열 = 진입점에서의 거리
   회색 화살표 = 호출, 주황 파선 = 함께 변경, 주황 점선 = 코드 연결 없이 함께 변경
        │ 파일 클릭
        ▼
② 파일 그래프
   노드 = 함수, 가운데 = 이 파일의 함수(파일 안 호출 순서), 양옆 = 다른 파일 함수(점선, 파일명 표시)
   주황 테두리 + "변경 N회" = 최근 50커밋에서 자주 바뀐 함수
        │ 함수 클릭
        ▼
③ 호출 흐름 (기존 화면)
   호출자 ← 함수 → 호출 대상, 1~3단계
   아래 "호출 후보와 근거"에 넘기는 값 → 받는 매개변수 표
```

상단 `프로젝트 지도` / `함수 화면 보기` 버튼으로 ①과 ②③을 오갑니다.

## 4. 코드 지도

### `vscode-extension/extension.js`

| 바뀐 곳 | 내용 |
|---|---|
| 상단 버튼 | `#toggle-map` (지도 ↔ 함수 화면) |
| 가운데 영역 | `<section id="project-map">` 추가, 단계 버튼 줄에 `id="flow-controls"` |

### `vscode-extension/media/map.js`

**① 지도**

| 이름 | 역할 |
|---|---|
| `mapMode`, `showMap(on)` | 지도 ↔ 함수 화면 전환. 분석 직후 지도가 먼저 보임 |
| `buildProjectMap(limit)` | 함수 단위 분석을 **파일 단위로 합침**. 파일별 변경·함수 수·열(depth)·순서(rank), 파일 간 호출, 함께 변경 쌍, 숨은 결합 여부 |
| `OTHER_FILE`, `CALL_TYPES`, `LINK_TYPES` | 기타 파일 판별, 호출로 셀 간선 종류, "코드 연결"로 셀 간선 종류 |
| `MAP_COLUMNS` | 열 정의 `[제목, 부제, 조건, 선택 표시 여부]`. 열을 바꾸려면 여기만 수정 |
| `HEAT`, `heatOf(n)` | 변경 횟수 5단계 색 구간 |
| `renderMap()` | 지도 그리기, 설정(테스트·기타 파일, 함께 변경 집계 6/50) |
| `mapEdgePath`, `focusMap` | 선 모양, 마우스 올림 강조 (class만 바꾸고 다시 그리지 않음) |

**줌**

| 이름 | 역할 |
|---|---|
| `setupZoom(zoom, svg, view, width, height, controls)` | 휠 확대(커서 기준), 끌기 이동, 버튼. 상태는 넘겨받은 객체에 저장 |
| `mapZoom`, `fileZoom` | 지도용, 파일 그래프용 줌 상태. `dragged`로 끌기 후 클릭 무시 |
| `zoomControls(parent)` | `− + 전체 보기` 버튼 생성. **반드시 `parent`에 붙임** |

**② 파일 그래프**

| 이름 | 역할 |
|---|---|
| `renderFileGraph(file, box)` | 파일의 함수 그래프. `flow()`에서 선택이 파일일 때 호출 |
| 열 계산 | 파일 안에서 아무도 안 부르는 함수 = 0단계, 거기서 너비 우선 탐색으로 단계 (최대 5) |
| 열 안 순서 | 자기를 부르는 함수들의 평균 위치 (선 꼬임 감소) |
| `GMAX` | 양옆 다른 파일 함수 최대 개수 (기본 12) |

**③ 전달값**

| 이름 | 역할 |
|---|---|
| `bindArguments(edge, callee)` | 호출 원문의 인자와 받는 함수의 매개변수를 짝지음 |
| `callArguments` | 연쇄 호출 `a(x).b(y)`에서 **마지막 호출** `y`를 읽음 |
| `parseParams`, `splitDefault`, `splitTop`, `insideParens` | 시그니처·인자 문자열 파싱 |
| `argumentTable` | `evidence()`의 각 호출 아래에 표 그리기 |

짝짓기 규칙: 위치 인자는 순서대로, 키워드는 이름으로. 메서드(instance/class)는 `self`/`cls` 제외, **staticmethod는 제외 안 함**. 클래스 생성은 `__init__` 시그니처 사용. `*args`/`**kwargs`로 펼쳐 넘기면 "불확실"로 표시.

**이전 작업 (같은 파일)**

| 이름 | 역할 |
|---|---|
| `functionChanges()`, `changeCounts` | 함수 → 최근 50커밋 변경 횟수 표 (카드 배지, 그래프 주황 테두리) |
| `isTest(node)` | 테스트 파일 판별 (pytest 관례: `tests/`, `test_*.py`, `*_test.py`) |
| `layers(id, incoming, limit, skip)` | ③ 호출 흐름 단계 계산, `skip`으로 테스트 탐색 제외 |
| `COMMIT_TYPES` | 수정 유형 한국어 라벨 |

### `vscode-extension/media/map.css`

맨 아래에 작업 순서대로 추가했습니다. 색은 모두 VS Code 테마 변수(`--vscode-charts-blue`, `--vscode-charts-orange` 등)를 써서 라이트·다크 테마 모두 대응합니다. `--heat`(주황) = Git 변경, `--heat-0` ~ `--heat-4`(파랑 단계) = 지도 칸 색입니다.

### `tests/flow_webview_smoke.js`

지도 그리기, 파일 클릭 → 파일 그래프, 전달값 표, 테스트 판별, 카드 변경 배지 확인을 추가했습니다. 가짜 DOM에 `createElementNS`를 추가했습니다.
**이 테스트는 JavaScriptCore가 있는 Mac에서만 실행됩니다** (Windows에서는 skipped). Mac에서 한 번 확인 부탁드립니다.

## 5. 사용하는 데이터 필드

Python 쪽(`vscode_export.py`, 분석 엔진)을 고칠 때 아래 필드가 바뀌면 화면이 깨집니다.

| 필드 | 쓰는 곳 |
|---|---|
| `nodes[].id, type, file, name, lineno` | 전체 |
| `nodes[].navigation_metadata.signature`, `.kind` | 전달값 (시그니처, staticmethod 구분) |
| `edges[].type, source, target` | 호출 관계 (`calls`, `instantiates`, `calls_implicit`, `calls_override`, `imports`, `inherits`, `references`) |
| `edges[].evidence.source` | 전달값 (호출 원문) |
| `history.changes` | 파일 변경 횟수 (칸 색) |
| `history.commits[].files` | 함께 변경 집계 |
| `reading_order.modules[].id, min_depth, rank, entry` | 지도 열·순서·진입점 ★ |
| (Git 심층 분석) `files[path].events[].functions, type, author` | 함수 변경 횟수, 핫스팟, 수정 유형 |

## 6. 실행과 확인

```bash
code --extensionDevelopmentPath="<knitcode 경로>/vscode-extension" <분석할 프로젝트 경로>
```

- 확인용 프로젝트는 `psf/requests`를 추천합니다 (파일 37개, 커밋 이력 풍부).
- 설정: `knitcodeStatic.pythonPath` = Python 3.10 이상, `knitcodeStatic.historyDays` = 3650
- `map.js`·`map.css` 수정 후에는 **Developer: Reload Window**, `extension.js` 수정 후에는 개발 창을 닫고 다시 열기
- 화면이 "분석 준비 중…"에서 멈추면 `map.js` 문법 오류입니다. **Developer: Open Webview Developer Tools** → Console의 빨간 줄(`map.js:줄번호`)을 확인하세요.

```bash
python -m unittest discover -s tests
```

**requests 기준 기대값** (확인용)

| 화면 | 기대값 |
|---|---|
| ① 지도 | 코드 파일 19개, 열 `진입점 6 / 1걸음 4 / 2걸음 2 / 3걸음 이상 2 / 호출로 닿지 않음 5`, 선 44개 |
| ① 집계 50개로 변경 + 테스트·기타 표시 | 파일 37개, 선 213개 (대량 커밋 잡음 비교용) |
| ② `models.py` | 노드 63개, 선 79개, 연결 없는 함수 9개, 테스트 119개 제외 |
| ② `api.py` | `get/post/...` → `api.request` → `Session.request` 흐름 (발표 예시로 좋음) |
| ③ `prepare_body` → `_encode_files` | `raw_data → data: _t.RawDataType \| None` |
| 전달값 짝짓기 | 호출 1,361개 중 1,297개(95.3%) 성공, 64개는 시그니처 없음 |

## 7. 다음 과제 (우선순위 순)

1. **파일 그래프 가독성**: 선이 많은 파일(`models.py` 79개)은 전체 보기에서 빽빽함. 예: 기본은 파일 안 선만, 다른 파일로 가는 선은 마우스를 올렸을 때만 표시
2. **`**kwargs` 타입 펼치기**: `Unpack[_t.RequestKwargs]` 같은 TypedDict를 따라가 `data`, `json`의 실제 선언 타입 표시
3. **data flow / 타입 검사** (교수님 피드백): 지금은 선언된 힌트만 보여 줌. "타입이 알맞게 넘어가는지"는 엔진의 객체 흐름(ObjectFlow) 확장 필요
4. **메모리** (교수님 피드백): requests(파일 37개) 분석 결과 JSON이 약 4.5MB. 큰 프로젝트(click, rich)에서 크기와 확장 메모리부터 측정. `evidence.source`, `trace` 등 중복 필드 축소, 파일별 지연 로딩 검토
5. **자연어 설명** (교수님 피드백): 선택한 함수의 호출 흐름 + 전달값 + 변경 이력을 프롬프트로 만들어 LLM이 설명하는 데모
6. **큰 프로젝트 지도**: 파일 수백 개에서는 선이 엉킴. 폴더 단위 묶기 또는 트리맵 검토
7. 작은 정리: ③ 카드와 근거 목록의 긴 이름을 짧게(모듈 이름 생략), 파일 화면 상단의 "서로 다른 호출자 0개" 숨기기

## 8. 알려진 한계와 팀 결정 대기

- **함께 변경 집계 기준**: 지도 기본값은 파일 6개 이하 커밋, Git 패널 "함께 변경" 탭은 50개 이하. 통일 여부는 팀 결정 필요 (requests에서 대량 커밋 4개가 함께 변경 쌍 대부분을 만듦)
- **테스트 판별**은 pytest 관례 기준이라, 관례를 따르지 않는 프로젝트에서는 놓칠 수 있음
- **함수 변경 횟수**는 Git 심층 분석(최근 50커밋)이 끝난 뒤(약 40초) 반영됨
- **전달값**은 정적 분석 결과라 실제 실행 시 값과 다를 수 있음. 펼쳐 넘기는 인자는 "불확실"로 표시
- 작성자는 이메일로 표시
