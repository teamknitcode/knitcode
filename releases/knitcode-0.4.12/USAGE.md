# knitcode 0.4.12

Python 프로젝트의 구조·함수 호출과 Git 변경 맥락을 탐색하는 VS Code 확장입니다.

- **[화면 6장과 전체 기능 사용 안내](../../vscode-extension/USER_GUIDE_KO.md)**
- **[개발·검증 안내](../../vscode-extension/VISUALIZATION_KO.md)**
- **[설치 파일](knitcode-static-0.4.12.vsix)** — GitHub에서 Download raw file로 다운로드

VS Code 확장 화면의 `… → Install from VSIX...`로 설치하고, 기존 버전이 있다면 `Developer: Reload Window`를 실행하세요. Python 프로젝트 최상위 폴더를 연 다음 명령 팔레트에서 **knitcode: Open Call Flow**를 선택합니다.

VS Code 1.85 이상, Python 3.10 이상이 필요합니다. Git 기능은 로컬 Git 저장소 이력이 필요합니다. 추가 Python 패키지 설치 없이 사용합니다.

패키지는 현재 분석 엔진과 안내서·화면 이미지를 포함합니다. 무결성은 [SHA256SUMS](SHA256SUMS)로 확인할 수 있습니다.

검증: macOS/Python 3.12에서 unittest 212개 통과, Mac 화면 동작 검사 실행. 실제 Webview 코드를 Chrome에서 화면·조작 검증했으며 VS Code 내부 GUI 확인은 팀 환경에서 추가 수행합니다.
