# Jarvis 공개 예측 결과와 비교

**범위를 맞춘 재채점에서는 KnitCode 정적+호출 중심이 재현율·F1이 높고, Jarvis는 정밀도가 높았다.** Jarvis 실행기를 같은 환경에서 재실행한 결과는 아니다.

## 비교 방법

- 공식 artifact 커밋 `8871b86494a1aec0095686ffa543994a7361af88`의 `reproducing_RQ2/macro_benchmark/{project}/jarvis/jarvis_EA.json` 사용
- 앞선 실험과 같은 `EA.json` 정답과 독립적인 소스 AST 함수 목록 사용
- GT·Jarvis 예측·KnitCode 예측 모두 양 끝점이 앱의 선언된 함수인 관계로 제한
- 이름의 임의 suffix 매칭·정답 기반 호출 삭제 없이 고유 함수 쌍의 TP·FP·FN으로 계산

## 결과

| 프로젝트 | 방법 | 정밀도 | 재현율 | F1 | TP / FP / FN |
|---|---|---:|---:|---:|---:|
| sqlparse | Jarvis 공개 EA 결과 | 99.43% | 49.57% | 66.16% | 174 / 1 / 177 |
| sqlparse | KnitCode 정적 단독 | 89.52% | 53.56% | 67.02% | 188 / 22 / 163 |
| sqlparse | KnitCode 정적 + 호출 중심 | 88.17% | 97.72% | 92.70% | 343 / 46 / 8 |
| furl | Jarvis 공개 EA 결과 | 100.00% | 50.26% | 66.90% | 95 / 0 / 94 |
| furl | KnitCode 정적 단독 | 86.46% | 43.92% | 58.25% | 83 / 13 / 106 |
| furl | KnitCode 정적 + 호출 중심 | 71.81% | 86.24% | 78.37% | 163 / 64 / 26 |

## 해석과 한계

- sqlparse에서는 혼합 방식이 Jarvis 공개 결과보다 F1 **26.54%p**, furl에서는 **11.46%p** 높다. 정밀도는 각각 **11.25%p**, **28.19%p** 낮다.
- 혼합 방식은 실제 테스트 실행 정보를 사용한다. 순수 정적 분석인 Jarvis와 입력 정보·실행 비용이 다르므로 일반적인 알고리즘 우위로 해석하지 않는다.
- 비교 범위는 앱 함수 간 호출이며, Jarvis 논문 전체 EA·진입점 중심·라이브러리 포함 점수를 재현한 것이 아니다. 두 프로젝트만 평가했다.
- 이름·범위 규칙은 고정했지만 도구 간 출력 표현 차이에 대한 추가 검토가 필요하다.
- Jarvis 실행 시간·메모리를 같은 환경에서 측정하지 않아 속도 우위를 주장할 수 없다. 논문 실행 시간과 현재 측정 시간을 직접 비교하지 않는다.

다음 직접 비교는 Jarvis 실행기와 의존성을 준비해 같은 소스·평가 범위·환경에서 재실행하고, 정확도와 전체 비용을 함께 측정해야 한다.

원본 점수와 예측 파일 해시: `results/jarvis_published_comparison.json`. 재채점 스크립트: `rescore_published.py` (`--help` 참고).

출처: [공식 artifact](https://github.com/pythonJaRvis/pythonJaRvis.github.io/tree/master/Jarvis/reproducing_RQ2/macro_benchmark), [Jarvis 논문](https://arxiv.org/html/2305.05949).
