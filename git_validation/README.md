# Git Validation — KnitCode GitHub 분석 파트

이 폴더는 GitHub 분석 담당 파트의 코드만 담습니다. 상위 폴더의 팀 정적분석 엔진 파일은 변경하지 않습니다.

## 파일 구성

```text
git_validation/
├─ analyzer/
│  ├─ git_insights.py         # 커밋/작성자/함수 변경/동시 수정 집계
│  ├─ github_api.py           # 선택적 PR/Issue/CI 읽기
│  ├─ extensions.py           # 변경 핫스팟/테스트 후보
│  ├─ integration.py          # 정적 호출 그래프와 Git 이력 연결
│  ├─ change_review.py        # 변경 전후 비교, 호출 영향 후보
│  ├─ repository_source.py
│  └─ templates/             # 기존 분석 HTML 보고서
├─ tests/                     # GitHub 분석 전용 테스트
├─ static_bridge.py           # 부모 팀 엔진 main.run 연결
├─ git_insights_cli.py        # Git 이력 분석
├─ integrated_cli.py          # 정적 분석 + Git 이력 통합
├─ change_review_cli.py       # 커밋 변경 리뷰
└─ run_*.bat                  # Windows 실행 래퍼
```

## 실행 (Windows PowerShell, 프로젝트 루트 기준)

Python 3.10 이상, Git이 필요합니다. 새로운 외부 Python 패키지 설치는 필요하지 않습니다.

```powershell
# 팀원의 기존 정적 분석 실행 방식 (그대로 유지)
py main.py C:\path\to\target --output-dir output

# 1) GitHub 분석(작성자/수정 유형/동시수정/함수 핫스팟)
py git_validation\git_insights_cli.py https://github.com/aboul3la/Sublist3r --commits 50 --output git_validation/output/history
start git_validation\output\history\report.html

# 2) GitHub 이력 + 팀 최신 정적 분석 연계
py git_validation\integrated_cli.py https://github.com/aboul3la/Sublist3r --commits 50 --output git_validation/output/combined
start git_validation\output\combined\index.html

# 3) 커밋 전후 변경 영향/테스트 후보
py git_validation\change_review_cli.py https://github.com/aboul3la/Sublist3r --base HEAD~1 --head HEAD --commits 50 --output git_validation/output/change
start git_validation\output\change\index.html
```

보고서 출력 디렉터리는 새 이름을 사용하세요. 기존 보고서를 덮어쓰지 않는 검사를 수행합니다.
GitHub API에서 Issue/PR/CI를 함께 조회하려면 `--github-api`를 추가할 수 있습니다. API 토큰은 `GITHUB_TOKEN` 환경변수로 지정하고 저장소에는 올리지 마세요.

## 테스트

```powershell
# 팀 기능 회귀 테스트 (상위 프로젝트 루트에서 실행)
py -m pytest tests -q

# GitHub 파트 테스트 (별도 폴더에서 실행)
cd git_validation
py -m unittest discover -s tests -p "test_*.py" -v
cd ..
```

### 범위·주의

- 분석 대상 저장소의 Python 코드를 직접 실행하지 않고 Git blob과 AST만 읽습니다.
- 정적 분석은 실제 실행 경로/테스트 커버리지를 증명하지 않습니다. 영향 범위와 테스트 추천은 후보입니다.
- Git 동시 수정은 관측된 공변경 이력이지 확정된 코드 의존성이 아닙니다.
- 분석 대상에서 변경되지 않은 로컬 작업 파일은 보고서에 포함되지 않습니다.
- CLI의 내부 import는 이전 코드의 `analyzer` 구조를 유지하되, 실행 스크립트 경로를 `git_validation/`으로 분리했습니다.
- 이 패키지의 실제 원격 소스 조합은 `SOURCE_MANIFEST.txt`에서 확인합니다.
