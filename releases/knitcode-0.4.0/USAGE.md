# knitcode 0.4.0 사용 안내

Python 코드를 실행하지 않고 함수 호출 관계와 Git 변경 이력을 함께 탐색하는 VS Code 확장입니다.

## 설치와 시작

1. 이 폴더의 `knitcode-static-0.4.0.vsix`를 다운로드합니다. GitHub 파일 화면의 **Download raw file**을 사용하세요.
2. VS Code 확장 화면에서 `…` → **Install from VSIX...**를 선택하고 설치합니다.
3. 분석할 Python 프로젝트의 **Git 저장소 최상위 폴더**를 엽니다. Git이 없어도 호출 흐름은 사용할 수 있습니다.
4. 프로젝트 폴더를 신뢰한 상태에서 macOS는 `Cmd + Shift + P`, Windows/Linux는 `Ctrl + Shift + P`를 누릅니다.
5. `knitcode`를 입력하고 **knitcode: Open Call Flow**를 선택합니다.

VS Code 1.85+, Python 3.10+, Git이 필요합니다. Python 패키지를 추가로 설치할 필요는 없습니다. 설치 파일명과 내부 확장 ID는 이전 설치와의 업데이트 호환성을 위해 `knitcode-static`을 유지하며, 표시 이름은 `knitcode`입니다.

## 호출 흐름 탐색

- 왼쪽에서 파일·함수를 검색하고 함수를 선택합니다.
- 가운데는 선택한 코드, 왼쪽 열은 호출자, 오른쪽 열은 호출 대상입니다.
- `+ 단계 / − 단계`로 1~3단계를 탐색하고 `이전 선택`으로 돌아갑니다.
- `코드 ↗`는 편집기의 해당 정의로 이동합니다. 아래 근거 영역에서는 호출 위치와 분석 규칙을 확인합니다.
- 좌우 패널 경계선을 드래그하거나 경계선에 Tab으로 이동한 뒤 방향키로 너비를 조절합니다.
- 상단 `Git 패널 접기 / 열기`로 공간을 확보합니다. 너비·접힘 상태·선택 탭은 유지됩니다.
- 좁은 화면에서는 Git 패널이 아래로 이동합니다.

## Git 패널

선택한 함수가 있는 파일을 기준으로 표시합니다.

### 함께 변경

관찰 범위에서 2회 이상 같은 커밋에 수정된 현재 Python 파일을 표시합니다. 파일을 선택해 탐색하거나 공동 변경 커밋을 펼쳐 확인할 수 있습니다. 50개 파일을 초과하는 대량 변경은 기본 공동 변경 집계에서 제외합니다.

### 변경 이력

선택 파일의 커밋을 확인합니다. 커밋을 클릭하면 VS Code에서 diff가 열립니다. 기본 범위는 최근 90일, 최대 300개 비병합 커밋입니다.

### 심층 분석: 작성자와 함수 핫스팟

- 기본 최대 50개 커밋에서 파일별 작성자·수정 유형·함수 변경·공동 변경을 분석합니다.
- `작성자별 함수·커밋 보기`에서 작성자를 선택하면 **함수 핫스팟과 커밋 목록**이 해당 작성자 기준으로 좁혀집니다. 파일 전체 통계·수정 유형·공동 변경은 전체 작성자 기준입니다.
- 함수 핫스팟을 펼치고 함수 버튼을 누르면 호출 흐름의 중심으로 선택하고 해당 소스 정의를 엽니다.
- 삭제·이름 변경·중복 정의 등으로 현재 함수와 유일하게 연결되지 않으면 위치 확인 불가로 표시합니다.
- 작성자는 Git 메타데이터 기준이며 GitHub 계정 인증을 의미하지 않습니다. 수정 유형은 커밋 메시지 규칙에 따른 추정입니다.

### 심층 분석: 미커밋 변경 영향 후보

1. 수정한 Python 파일을 **저장**합니다.
2. 상단 **재분석**을 누릅니다.
3. `심층 분석` 탭 맨 위의 **미커밋 변경 영향 후보**를 펼칩니다.
4. 변경된 함수, 현재 그래프의 직접 호출자, 함께 변경된 파일을 확인하고 코드로 이동합니다.

기준은 **HEAD 대비 저장된 작업 파일**입니다. 스테이징·미스테이징·추적되지 않은 Python 파일을 포함합니다. 커밋 전의 전체 저장 상태를 비교하며, 미저장 편집과 Git이 무시하는 새 파일은 포함하지 않습니다. `Git 상세 분석 다시 실행`은 과거 이력만 갱신하므로 현재 수정 내용을 반영하려면 상단 `재분석`을 사용하세요.

함수 변경은 AST 기준이므로 주석·공백만 바뀌면 함수 변경으로 표시하지 않습니다. 모듈 수준 변경도 함수 영향으로 임의 추정하지 않습니다. 삭제 함수의 이전 호출자는 현재 그래프에서 복원하지 않습니다. 이름 변경은 추가/삭제로 표시될 수 있습니다. 변경 파일은 최대 200개, 파일별 소스는 최대 500KB이며 제외·파싱 오류는 화면에 표시합니다. 최초 커밋이 없는 저장소는 먼저 커밋이 필요합니다.

직접 호출자와 공동 변경은 **함께 검토할 후보**입니다. 실제 실행 영향, 모든 호출 관계, 전이 영향 범위를 보장하지 않습니다.

### 정적분석 + Git 통합 보고서

`정적분석 + Git 통합 보고서 ↗` 버튼을 누르면 같은 커밋의 소스와 이력을 분석한 HTML을 브라우저에서 엽니다. 이 보고서는 **커밋된 소스 기준**이므로 위 미커밋 변경 화면과 범위가 다릅니다. 미커밋 변경은 포함하지 않습니다.

## 설정

VS Code 설정에서 `knitcodeStatic`을 검색합니다.

| 설정 | 기본값 | 설명 |
|---|---|---|
| `knitcodeStatic.pythonPath` | 자동 | macOS/Linux는 python3, Windows는 python. 필요하면 Python 실행 파일의 절대 경로 지정 |
| `knitcodeStatic.historyDays` | 90 | 기본 변경 이력 관찰 기간(일) |
| `knitcodeStatic.commitLimit` | 300 | 기본 변경 이력 최대 커밋 수 |
| `knitcodeStatic.gitValidationAutoRun` | true | 정적 분석 후 심층 Git 분석 자동 실행 |
| `knitcodeStatic.gitValidationCommitLimit` | 50 | 심층 분석 최대 커밋 수(1~300) |

## 문제 해결과 분석 범위

- 명령이 안 보이면 VS Code 창을 다시 로드하고 확장 설치 상태와 프로젝트 신뢰 상태를 확인하세요.
- Python 실행 오류가 나면 `pythonPath`를 Python 3.10+ 실행 파일로 설정하세요.
- Git 정보가 없으면 ZIP 다운로드 대신 Git clone한 프로젝트의 최상위 폴더를 여세요.
- 이력 조회는 로컬 Git 기준입니다. 원격 새 커밋 자동 fetch, PR·Issue·CI 조회는 이 화면에 연결되어 있지 않습니다.
- 파싱 오류, 재귀·계산 한도, 동적 호출 등으로 관계가 누락될 수 있습니다. 미확정 호출은 내부 호출 누락을 확정하는 수치가 아닙니다.
- 신뢰된 로컬 파일 시스템 워크스페이스를 지원합니다. 분석 대상 Python 소스를 import하거나 실행하지 않습니다.

## 배포 및 검증

이 폴더는 VSIX와 사용 안내를 묶은 배포 폴더입니다. 개발 소스는 저장소의 원래 경로에 함께 반영되어 있습니다.

- 버전: 0.4.0
- 전체 검사: 462개 실행, 460개 통과, 2개 건너뜀.
- VSIX 외부 경로 실행, Git 이력 JSON·통합 HTML 생성, 번들 엔진의 미커밋 변경 처리 검증 통과.
- UI 동작 검사: 작성자 필터, 핫스팟·호출자 소스 이동, 탭 전환, 패널 접기·너비 조절.
- 실제 VS Code GUI에서 신규 기능의 클릭·시각 검증은 별도로 수행하지 않았습니다.
- SHA-256: `7a5f5f9c3a94e18d363b4d96ed896e84df8dc1dfee0133e2c073a9cb3dddc452`

## 팀원용 수정·빌드 안내

전체 저장소를 clone한 뒤 저장소 최상위에서 실행합니다.

```bash
code --extensionDevelopmentPath="$PWD/vscode-extension" .
python3 scripts/package_extension.py
python3 -m unittest discover -s tests
```

첫 명령으로 연 개발 창에서 `knitcode: Open Call Flow`를 실행합니다. 화면 파일 수정 후 개발 창을 다시 로드하고 명령을 다시 실행하세요. Python 파일 수정 후에는 저장하고 재분석합니다. 빌드 결과는 `dist/knitcode-static-0.4.0.vsix`이며 새 버전 배포 시 `package.json`의 version을 올립니다.

| 수정 대상 | 파일 |
|---|---|
| 화면 구성·VS Code 연결 | `vscode-extension/extension.js` |
| 시각화·탭·필터·패널 동작 | `vscode-extension/media/map.js` |
| 여백·색상·글자·반응형 배치 | `vscode-extension/media/map.css` |
| 이름·버전·명령·설정 | `vscode-extension/package.json` |
| 확장 설명 | `vscode-extension/README.md` |
| 분석 결과 변환 | `vscode_export.py` |
| 미커밋 변경·직접 호출자 후보 | `vscode_changes.py` |
| 기존 Git 이력 | `vscode_history.py` |
| 작성자·함수 변경 JSON | `git_validation/vscode_json_cli.py` |
| Git 분석 및 보고서 모듈 | `git_validation/analyzer/` |
| 통합 보고서 실행 | `git_validation/integrated_cli.py` |
| VSIX 빌드 | `scripts/package_extension.py` |
| 화면 동작 검사 | `tests/flow_webview_smoke.js`, `tests/test_vscode_extension.py` |
| 미커밋 변경·번들 검사 | `tests/test_vscode_changes.py`, `tests/test_git_validation_package.py` |

`tests/test_v24.py`는 최신 엔진의 Optional 타입 후보·불확실성 표시와 맞춘 회귀 기대값을 포함합니다. JavaScriptCore가 없는 환경에서는 화면 동작 검사가 건너뛰어지므로 실제 VS Code 개발 창에서도 확인하세요. 분석 엔진과 Git 보고서는 저장소의 다른 Python 모듈과 HTML 템플릿에도 의존합니다.

개발 소스 업로드 시 원격 저장소 기준 재검증: 209개 실행, 207개 통과, 2개 건너뜀. 재빌드한 VSIX의 모든 파일 내용이 배포본과 동일함을 확인했습니다. 기존 배포본에 포함된 호환 보조 파일 `stdlib_mro.py`도 반영했습니다.
