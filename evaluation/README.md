# DFSA v0.1 Evaluation 개발 이력

이 디렉터리는 v0.1의 Module별·E2E Evaluation 준비 기록이다. 당시 Dataset, Metric,
평가 코드와 절차는 확정되지 않았으며 폴더만 마련했다. [v0.1 팀 개발 명세서 §39](../docs/team-development-spec-v0.1.md)

v0.2에서는 별도 정량 Evaluation을 수행하지 않는다. 합성 fixture 기반 기능·회귀 검증과
별도 승인하에 수행하는 Live E2E를 적용한다. [v0.2 팀 개발 명세서 §13](../docs/team-development-spec-v0.2.md#13-테스트-및-definition-of-done)

## v0.1 평가 준비 당시 목적과 담당

| 위치 | 목적 | 담당 |
| --- | --- | --- |
| `module_a/` | 검색·수집 결과의 품질 평가 | Module A 정유채 |
| `module_b/` | 동일인 검증·Exposure 추출 결과의 품질 평가 | Module B 서동균 |
| `module_c/` | Risk 분석·설명·대응 방안 결과의 품질 평가 | Module C 강영림 |
| `e2e/` | 전체 Pipeline 결과의 품질 평가 | 팀 공동 협의; 단독 Owner는 미확정 |

## tests와의 차이

- `tests/contract/`: Public Contract의 구조·타입·validation 회귀 검증.
- `tests/modules/`: 각 Module의 동작·오류 처리 회귀 검증.
- `tests/integration/`: Orchestrator 호출 흐름·상태·결과 조합 검증.
- `evaluation/`: v0.1에서 별도 품질 평가를 위해 마련한 위치.

pytest는 기능과 동작의 회귀를 검증한다. `RiskPath.evaluation`은 v0.1 Contract의
응답 필드이며 이 폴더의 Dataset / Metric 설계와 구분한다.

## v0.1 당시 미결 사항

Module A/B/C 및 E2E Evaluation의 Dataset, Metric, 절차, 정량 평가 기준과 E2E 단독 담당자는 당시 미확정이었다. 팀 협의에서 확정하기 전에는 지표, threshold, 점수 및 평가 실행 명령을 정하지 않기로 했다.

## 데이터와 API Key

- API Key는 코드·Dataset·평가 결과에 넣지 않고 환경변수 또는 Git에서 제외된 `.env`로 관리한다.
- 개인정보·원문 수집 데이터·민감 로그를 commit하지 않는다. 공유 자료는 합성 또는 비식별 자료를 우선한다.
- 향후 평가 산출물 추가 전 민감 정보와 비밀값 포함 여부를 확인하고 필요한 제외 설정을 검토한다.
