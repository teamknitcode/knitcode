# 동적 보조 분석 실험 자료

**[노션 업로드용 전체 요약](2026-11-16_EXPERIMENT_SUMMARY_NOTION_KO.md)** 에서 실험 흐름과 결과표를 먼저 확인하세요.

## 범위와 기여

동적 수집기와 `--calls-only`, 정적 그래프 비교 기능은 팀원이 구현한 [PR #4](https://github.com/teamknitcode/knitcode/pull/4)의 기여입니다. 이 자료는 해당 구현의 호환성 수정·검증 기록과 이후 수행한 성능·정답 기반 평가를 보존합니다. 수집기 수정은 이미 main에 병합되어 있으며, 이 PR은 실험 스크립트와 문서·결과를 추가합니다.

| 자료 | 내용 |
|---|---|
| [초기 비용 실험](2026-11-15-pr4-handoff/BENCHMARK_KO.md) | Requests 27개 테스트·동적 호출 예제의 일반/호출 중심/전체 추적 비교 |
| [PR 처리 기록](2026-11-15-pr4-handoff/MERGE_RESULT_KO.md) | opcode·가상환경 경로 수정과 병합 이력 |
| [PyCG 정답 평가](2026-11-16-groundtruth/REPORT_NOTION_KO.md) | autojump·asciinema·Fabric 평가 및 범위·환경 한계 |
| [Jarvis 평가](2026-11-16-jarvis/REPORT_NOTION_KO.md) | 독립된 앱 함수 범위로 정적/호출 중심/전체 추적 비교 |
| [Jarvis 공개 예측 비교](2026-11-16-jarvis/JARVIS_COMPARISON_KO.md) | 공개 EA 예측 재채점. 실행기 재실행·속도 비교와 구분 |

## 재현

스크립트는 macOS `/usr/bin/time -l`을 사용합니다. 별도 가상환경을 만들고 결과 메타데이터의 의존성·Python 버전과 프로젝트 snapshot을 맞추세요. Requests/PyCG/Jarvis 실험은 평가 범위와 환경이 다르므로 표 사이의 절대 점수를 직접 비교하지 않습니다.

```bash
# 준비한 대상·환경 경로는 각자 지정
python3 experiments/2026-11-15-pr4-handoff/benchmark.py --help
python3 experiments/2026-11-16-groundtruth/hybrid_evaluation.py --help
python3 experiments/2026-11-16-jarvis/evaluate.py --help

# 공식 Jarvis artifact의 고정 snapshot 확보 후 공개 결과 재채점만 실행
git clone https://github.com/pythonJaRvis/pythonJaRvis.github.io.git /tmp/jarvis-artifact
git -C /tmp/jarvis-artifact checkout 8871b86494a1aec0095686ffa543994a7361af88
python3 experiments/2026-11-16-jarvis/rescore_published.py \
  --artifact /tmp/jarvis-artifact --out /tmp/jarvis-rescored.json
```

전체 수집 재실행 명령과 제외 테스트는 상세 보고서·프로토콜에 있습니다. Jarvis 평가기는 `--resume`을 지원하며, 실행별 240초 제한과 제한 초과 모드의 재시도 중단을 적용합니다. 초기 Requests/PyCG 스크립트는 당시 실행본을 보존한 것으로 같은 중단·재개 기능을 갖추지 않았습니다. 인계 폴더의 패치는 이미 병합된 수정의 기록이므로 현재 main에 다시 적용하지 마세요.

## 보존 정책과 해석

- `results/`에는 작은 점수·회차별 측정·추가 관계·로그·소스 해시·환경 정보를 보존합니다.
- 큰 실행 trace·전체 정적 산출물·외부 프로젝트 소스는 저장소에 넣지 않습니다. 로컬 `out/`에 생성합니다.
- 공개본의 호스트 절대 경로는 `<WORKSPACE>`, `<TMP>`, `<USER_HOME>` 등으로 치환했습니다. 명령·로그의 경로 표기는 템플릿이며 점수·시간·호출 쌍은 변경하지 않았습니다.
- 초기 파일 해시는 측정 당시 소스에 대한 값입니다. 이후 실험 실행기의 timeout/resume 보완으로 현재 스크립트가 달라질 수 있으며, 수집기와 채점 범위 변경과 구분해 보고서에 기록했습니다.
- 정상 종료는 전체 경로 검증을 뜻하지 않으며, GT 밖 관찰이 반드시 실제 오탐이라는 뜻도 아닙니다. 공식 채점에서는 이를 FP로 유지했습니다.
- 노션 요약은 최종 상태를 정리하고, 개별 보고서의 당시 미병합·미검증 기록은 후속 상태와 구분합니다.
