# KnitCode B모드 v3 — 함수·클래스 기반 아키텍처 탐색

> **상태:** 시험용 개발본. 기존 A모드와 `value_flow` 정적 분석 결과를 유지하면서 B모드의 역할 분류·근거·지도를 개선한 코드다. Python 벤치마크 11개에 대한 정량 정확도 검증이 완료되었다는 뜻은 아니다.

## 무엇이 달라졌나

기존 B모드는 Python **파일마다 대표 역할 하나**를 추정했다. 이 방식은 `schedule/__init__.py` 같은 단일 파일 프로젝트나, 서버 라우트와 초기화 코드가 같은 파일에 있는 Flaskr에서 실제 구조를 놓친다.

이번 버전은 `architecture_hierarchy.py`를 추가해 **함수·메서드·클래스마다 기능 후보**를 찾는다. 해당 심볼이 특정 그룹에 속하고, 한 소스 파일의 서로 다른 심볼이 서로 다른 기능 그룹에 들어갈 수 있다.

예시: 같은 `app.py`의 `create_app()`은 **앱 초기화**, `@app.route`가 붙은 `index()`는 **웹 요청 처리**, `sqlite3.connect()`를 사용한 `get_db()`는 **DB 접근**으로 각각 분류할 수 있다. `create_app → init_db`와 `index → get_db` 링크는 엔진의 실제 정적 호출 간선이 있을 때만 생성한다.

## 분류 근거의 출처와 한계

1. **AST 직접 근거:** 실제 웹 라우트 데코레이터, 알려진 클라이언트 API 호출, DB 라이브러리의 사용, 클래스 상속, UI·모델 라이브러리 메서드 호출 등. `import`만으로 사용·동작을 확정하지 않는다.
2. **이름 단서:** `Lexer.get_tokens`, `TextRank`, `SSHTunnelForwarder` 등 함수·클래스 이름. 이 경우 기능 분류는 **추정**으로 표시한다.
3. **기술 동작 보조 태그:** `requests.get` 호출은 HTTP 사용 근거이지만 함수 전체의 주 역할과 별개로 기록한다. 예를 들어 검색 엔진 클래스의 요청 함수는 **검색 기능 후보**이면서 `network_http` 보조 태그를 가질 수 있다.
4. **판단 보류:** 근거가 부족하면 `unclassified`로 보류한다. 기능이 없다는 뜻은 아니다.
5. **호출 증거:** 기존 `edges`의 `calls`, `instantiates`, `calls_override`, `calls_implicit` 중 실제 간선이 있는 경우에만 영역 간 선을 만든다. `contains`, `cochange`는 호출선이 아니다. 호출선은 실행 순서, 데이터 이동, 실행 빈도를 증명하지 않는다.

특히 SQL 처리(`sqlparse`)를 DB 접근으로, URL 분석(`furl`)을 인터넷 통신으로, Git 저장소 파일명을 DB 저장으로 단정하지 않도록 분리했다. `@route`가 있는 웹 요청 처리와 SSH 소켓 포워딩도 다른 기능 그룹이다.

## 데이터 계약

최종 분석 JSON에는 기존 `nodes`, `edges`, `architecture_roles`, `value_flow`를 유지한 채 `architecture_hierarchy`가 추가된다.

`architecture_hierarchy` 구성:

- `schema_version`: 현재 `1`
- `profile`: 프로젝트 성격 **후보** (`verified: false`)
- `symbols`: A모드 원본 심볼 ID를 키로 한 함수·클래스 역할, 근거, 보조 기술 동작
- `groups`: `cap:<역할>` 그룹, 소속 `function_ids`, 파일 목록, AST 근거/이름 후보 집계
- `edges`: 그룹 간 실제 정적 호출 후보의 합계와 원본 함수 ID·호출 위치·`call_id`
- `metrics`: 연결된 심볼 수, 분류·보류 수
- `limitations`: 해석상의 한계

A모드와의 연결은 원래 함수·클래스 ID를 그대로 사용한다. `value_flow`는 이번 분류기에 의한 타입 검증 결과가 아니다.

## 화면 동작

- **B · 구조 이해:** 기능별 그룹을 `진입/핵심/연동/데이터`의 읽기용 레인으로 배치한다. 레인은 실제 실행 순서가 아니다.
- **실제 폴더:** 이전 B모드의 경로별 탐색을 유지한다.
- **무엇이 궁금한가요?:** 질문을 누르면 **가운데 가로 설명 패널**에 관련 기능 후보, 파일과 확인 근거가 나온다.
- **하단 상세:** 그룹을 클릭하면 그 그룹 소속 함수만 표시한다. 심볼을 선택하면 AST 단서와 실제 코드 위치를 볼 수 있고 A모드로 이동할 수 있다.
- **테스트 포함:** 초기 화면에서는 테스트를 숨긴다.

## 사용 방법

### VSIX만 테스트하려면

VS Code → 명령 팔레트 → `Extensions: Install from VSIX...` → 설치한 뒤 실제 Python 프로젝트를 연다. `knitcode: Open Call Flow` 실행 후 B를 선택한다.

### 이미 `feat/bmode`에 B모드 v2가 들어 있다면

제공한 `KnitCode_B_v2_to_v3_변경.patch`를 저장소 **루트**에 놓고:

```powershell
git status --short
git apply --check ".\KnitCode_B_v2_to_v3_변경.patch"
git apply ".\KnitCode_B_v2_to_v3_변경.patch"
python -m pytest -q tests/test_architecture_hierarchy_v3.py tests/test_architecture_roles_v2.py tests/test_value_flow.py
node --check vscode-extension/media/bmode.js
node --check vscode-extension/extension.js
python scripts/package_extension.py
```

**반드시 `git apply --check`부터 실행한다.** 이 패치는 제공된 v2 통합본을 기준으로 제작되었으므로, 로컬 `extension.js`나 `vscode_export.py`가 더 수정돼 있다면 적용 실패할 수 있다. 이 경우 파일 전체를 덮어쓰지 말고 diff를 선별 적용한다.

패치는 `package.json` 버전을 변경하지 않는다. 따라서 로컬 패치 방식으로 VSIX를 생성하면 버전 문자열은 현재 로컬 `package.json`을 따른다. 제공한 완성형 VSIX는 **0.4.19**로 패키징돼 있다.

## 검증 현황

- 13개 신규 역할 분류 회귀 테스트 + 기존 역할 11개 + 기존 value-flow 9개 + VS Code 어댑터 테스트 2개 = **35개 통과** (Webview의 JavaScriptCore 전용 1개는 환경이 없어 제외)
- JavaScript 문법 검사 통과
- Chromium 브라우저 테스트: 3개 역할 카드, 질문·중앙 답변, 그룹 선택, 함수 선택·A모드 이동, 브라우저 오류 없음
- 원본을 실행하지 않은 4개 파일짜리 Flask 형태의 **합성 코드**를 브라우저 시연 데이터로 사용
- 대규모 KnitCode 저장소 전체 E2E 분석은 제한 시간 내 완료되지 않음: **성공으로 보고하지 않음**
- PyCG/Jarvis **11개 벤치마크의 정확한 대상 커밋 전체에 대한 실측·전수 검증은 미완료**. 본 버전의 역할 어휘와 테스트는 해당 프로젝트 유형에 대응하도록 설계한 초기 구현임

## 다음 검증 순서

1. `sqlparse`, `furl`: 파싱/URL 처리의 DB/HTTP 오분류율
2. `Sublist3r`, `sshtunnel`, `bpytop`: 한 파일 안의 서로 다른 구성 요소 분리
3. `rich-cli`, `asciinema`, `autojump`: 입력/출력/파일 상태/외부 통신 구분
4. `fabric`, `face_classification`, `TextRank4ZH`: 원격 세션/ML 학습·추론/키워드·문장 분석
5. 실제 스크린샷과 사람이 작성한 역할 라벨을 바탕으로 심볼별 precision/recall 및 그룹 호출 근거의 정확성 별도 평가

**주의:** PyCG/Jarvis F1은 정적 호출 관계 탐지 점수이며 이 역할 분류기의 정확도 점수가 아니다. 검증하지 않은 결과를 성능 지표로 제시하면 안 된다.
