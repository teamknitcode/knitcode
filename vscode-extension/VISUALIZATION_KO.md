# knitcode 시각화 개발 안내 — 0.4.12

사용 순서와 화면별 기능은 **[팀원 사용 안내](USER_GUIDE_KO.md)**를 참고하세요. 이 문서는 후속 개발을 위한 구조·데이터 계약·검증 방법입니다.

## 1. 작업 기준

- 팀원 시각화 PR #2는 merge commit `4235ee2`로 합쳐졌습니다. 함수 노드 프로젝트 지도, 파일 그래프, 줌·이동, 인자 대응, Git 차트가 기반입니다.
- 이번 후속 작업은 `feat/visualization-next`에서 진행했습니다. 프로젝트 소개와 후보 근거, 선택 범위, 탐색 경로, 전체 함수 정보, 스크롤 유지와 배치 개선을 포함합니다.
- [PR #2 당시 안내 원본](https://github.com/teamknitcode/knitcode/blob/fd9ee694ed34d2456b8f38e42c54451f08dc5419/vscode-extension/VISUALIZATION_KO.md)은 해당 커밋에 보존됩니다.
- 이어서 작업할 때는 병합된 main을 갱신하고 새 브랜치를 만듭니다. 후속 PR은 최종적으로 검토·병합된 상태인지 GitHub에서 확인하세요.

## 2. 코드 구조

| 파일/함수 | 역할 |
|---|---|
| `extension.js` | 명령 등록, Webview HTML/CSP, Python 분석 실행, Git 추가 분석, 소스·커밋 이동, HTML 보고서 |
| `../vscode_export.py` | 통합 엔진 결과를 Webview JSON으로 변환 |
| `../project_intro.py` | 제한된 크기의 README에서 제목·소개·출처 발췌. 외부 symlink는 읽지 않음 |
| `media/map.js` / `renderIntroduction`, `entryReason` | 설명 접기, 탐색 후보 분류·근거, 최대 5개 함수의 정적 호출 한 갈래 |
| `buildProjectMap`, `renderMap`, `mapFocus` | 파일 집계·배치, 함수 상자, 경로·호버 강조 |
| `expandedFiles`, `onlySelection`, `selectionScope`, `selectedCallEdges` | 파일별 펼침 상태와 선택 범위. 필터는 지도·파일·함수·근거에 공통 적용 |
| `setupZoom`, `zoomControls`, `GESTURE_SPEEDS` | 이동·핀치·Ctrl+휠, 배율 표시, 전체 보기, 조작 감도 |
| `renderBreadcrumbs`, `renderFunctionInfo` | 지도·파일·함수 위치와 전체 이름·시그니처·정의 이동 |
| `tree` | 검색, 파란 함수 테두리, 파일 목록 내부 자동 스크롤 |
| `renderFileGraph`, `flow`, `layers`, `anchorFlowFocus` | 파일 그래프, 호출 1~3단계, 선택 카드 위치 유지 |
| `bindArguments`, `parseParams`, `callArguments`, `argumentTable` | 선언 시그니처와 호출 문자열의 인자 대응 |
| `renderGitValidation`, `functionChanges`, `renderWorkingChanges` | 작성자 필터·차트, 함수 변경 횟수, 저장된 미커밋 영향 후보 |
| `media/map.css` | 테마, 패널 배치, 독립 스크롤, 파일 그룹 제목 고정, 좁은 창 배치 |
| `tests/flow_webview_smoke.js` | JavaScriptCore 가짜 DOM 기반 동작 검사. 실제 레이아웃 검사는 아님 |

프로젝트 데이터는 `textContent`로 표시합니다. README·파일명·함수명·Git 메시지를 HTML로 삽입하거나 분석 대상 스크립트를 실행하지 마세요.

## 3. 데이터 계약

| JSON 필드 | 사용 위치 |
|---|---|
| `project.name, description, source, line` | README 소개. 과거 JSON에서 없으면 안내로 대체 |
| `nodes[].id, type, file, name, lineno` | 검색·선택·배치·코드 이동 |
| `nodes[].navigation_metadata.signature, kind` | 시그니처와 staticmethod/instance/class 구분 |
| `edges[].type, source, target, evidence.source` | 호출·관계·전달값 |
| `entry_points[].id, kind, detail, confidence` | 탐색 후보와 선정 이유. 실행 보장과 구분 |
| `reading_order.modules[].id, min_depth, rank, entry` | 지도 열·정렬. 전체 후보 집합 기준 |
| `history.changes, commits[].files, pairs` | 파일 색, 공동 변경, 커밋 이력 |
| `working_changes` | HEAD 대비 저장된 Python 변경과 직접 호출자 후보 |
| Git 심층 결과 `files[path].events[].functions, author, type` | 함수 변경 수·핫스팟·작성자별 커밋 |

`certain`은 근거가 되는 코드 표기를 찾았다는 뜻입니다. 실행 관측 결과나 분석의 완전성을 뜻하지 않습니다. `public_api`의 명시적 `__all__`와 `__init__.py` 노출 추정을 같은 설명으로 합치지 마세요.

소개 경로는 일반 명시 호출을 따라가는 휴리스틱입니다. 같은 이름, 비공개가 아닌 이름, 후속 호출 수를 우선하며 최대 5개 노드와 순환 방지를 적용합니다. 생성자·특수 메서드는 제외합니다. 다형성 후보가 실제 실행 대상과 다를 수 있습니다.

## 4. 스크롤·상태를 바꿀 때 지킬 점

- 바깥 본문 대신 `#tree`, `.workspace`, `.history`가 각자 스크롤합니다. 검색창은 파일 목록 스크롤과 분리하고 파일 그룹 제목은 목록 안에서만 고정합니다.
- 지도 화면의 필터 줄은 지도 제목 옆에 둡니다. 상세 화면 탐색 경로는 고정하지 않습니다.
- `renderMap()`은 DOM을 다시 그린 뒤 본문 스크롤을 복원합니다. 파일 접기를 문서 맨 위로 이동시키는 동작으로 바꾸지 마세요.
- `anchorFlowFocus()`는 호출 단계 변경 뒤 선택 카드의 가로 위치를 유지합니다. `scrollIntoView()`로 본문과 다른 패널까지 움직이지 않도록 주의하세요.
- 트랙패드 일반 wheel은 이동, 핀치/Ctrl+wheel은 커서 중심 확대입니다. deltaMode 정규화·배율 상하한·프레임 단위 반영을 유지합니다. 드래그는 손가락/포인터 이동과 일대일 대응합니다.
- 경로 강조 토글은 선택 함수와 필터 범위를 바꾸지 않습니다. 호버 강조는 별도입니다.
- Webview 상태로 패널 너비·상세 패널 접힘·Git 탭·감도·선택 흐름 필터·소개 접힘을 보관합니다. 모든 탐색 상태가 VS Code 재시작 뒤 복구되는 것은 아닙니다.

## 5. 실행과 검증

```bash
# 프로젝트 루트: Python 3.10 이상
python3 scripts/package_extension.py
python3 -m unittest discover -s tests -v

# 개발용 VS Code 창
code --extensionDevelopmentPath="$PWD/vscode-extension" /path/to/requests
```

`map.js`·`map.css` 수정 후 개발 창에서 `Developer: Reload Window`를 실행합니다. `extension.js`의 HTML 구조 변경은 개발 창을 닫고 다시 열어 확인하세요.

최종 macOS/Python 3.12 검사 결과는 212 tests, OK입니다. `test_flow_webview_behavior`가 skipped가 아니라 실행됐는지 확인하세요. Windows 등에서 JavaScriptCore가 없으면 이 검사만 건너뛸 수 있습니다.

Chrome 미리보기로 레이아웃·제스처·스크롤을 검증했지만 VS Code 내부의 전체 GUI 검증을 대신하지는 않습니다. 팀 환경에서 [사용 안내 9장](USER_GUIDE_KO.md#9-팀원이-확인할-순서와-검증-범위)을 따라 확인하세요.

requests `3c7baaa`의 참고 수치: Python 파일 37개, 기본 지도 파일 상자 19개. 모두 펼치면 함수·클래스 노드 232개. `models.py` 기본 파일 그래프는 노드 63개·선 79개, 미연결 9개·테스트 호출자 119개 분리. `get`의 소개 경로만 표시하면 파일 상자는 3개입니다. 기본은 상자가 접혀 있으므로 함수 노드 232개가 처음부터 나타나지는 않습니다. 저장소 버전·선택·필터에 따라 달라집니다.

## 6. 남은 과제

| 우선 검토 | 현재 한계 |
|---|---|
| 다른 호출 갈래 선택 | 소개 경로는 자동 선택한 한 갈래이며 사용자가 중간 분기를 직접 고르지는 못함 |
| TypedDict/Unpack | `**kwargs`의 선언을 따라 개별 키의 타입을 펼치지 않음 |
| 데이터 흐름·타입 적합성 | 인자 문자열과 선언 타입의 대응만 제공. 실제 값 추적·타입 검사 아님 |
| 큰 프로젝트 성능 | JSON 크기·메모리·전체 펼침의 DOM 비용 측정, 캐시·지연 렌더링 검토 필요 |
| 폴더 단위 지도 | 파일이 아주 많으면 상자 수가 많아짐. 폴더 접기 미구현 |
| 공동 변경 기준 | 지도 기본 6파일/커밋, Git 패널 50파일/커밋. 통일 여부는 팀 결정 필요 |
| Git 자동 분석 | 최초 분석과 별도로 심층 분석 시간 소요. 환경·커밋 수에 따라 달라짐 |
| 테스트 판별 | pytest 파일명·폴더 관례 기준. 비표준 구조에서는 누락 가능 |
| 자연어 설명·REA | README 발췌 외 LLM 설명은 미구현. REA의 요구 의미는 팀 확인 필요 |

다음 수정은 기능과 표시 의미를 먼저 합의한 뒤 작은 단위로 진행하고, 공용 데이터 필드 변경 시 패키지 외부 실행 검사도 함께 확인하세요.
