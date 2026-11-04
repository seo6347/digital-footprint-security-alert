# DFSA v0.1 Evaluation

Module별 및 E2E Evaluation을 위한 작업 위치이다. v0.1 완료 범위에 포함되며,
상세 기준은 [팀 개발 명세서 §39](../docs/team-development-spec-v0.1.md)를 따른다.
현재는 폴더만 준비하며 Dataset, Metric, 평가 코드나 절차는 제공하지 않는다.

## 목적과 담당

| 위치 | 목적 | 담당 |
| --- | --- | --- |
| `module_a/` | 검색·수집 결과의 품질 평가 | Module A 정유채 |
| `module_b/` | 동일인 검증·Exposure 추출 결과의 품질 평가 | Module B 서동균 |
| `module_c/` | Risk 분석·설명·대응 방안 결과의 품질 평가 | Module C 강영림 |
| `e2e/` | 전체 Pipeline 결과의 품질 평가 | 팀 공동 협의; 단독 Owner는 미확정 |

## tests와의 차이

- `tests/contract/`: Public Contract의 구조·타입·validation 회귀 검증.
- `tests/modules/`: 각 Module의 동작·오류 처리 회귀 테스트를 추가할 위치.
- `tests/integration/`: Orchestrator 호출 흐름·상태·결과 조합 검증.
- `evaluation/`: 합의된 Dataset과 기준에 따른 Module별·전체 결과 품질 평가 위치.

pytest 통과를 품질 평가 완료로 간주하지 않는다. 기존 `RiskPath.evaluation` field는
Public Contract의 일부이며 이 폴더의 Dataset / Metric 설계와 구분한다.

## 미결 사항

**[DECISION REQUIRED] Module A/B/C 및 E2E Evaluation의 Dataset / Metric / 절차와
정량 평가 기준은 추후 팀 회의에서 확정한다.** 임의의 지표, threshold, 점수나
평가 실행 명령을 먼저 정의하지 않는다. E2E 평가의 단독 담당자도 팀에서 정한다.

## 데이터와 API Key

- API Key는 코드·Dataset·평가 결과에 넣지 않고 환경변수 또는 Git에서 제외된 `.env`로 관리한다.
- 개인정보·원문 수집 데이터·민감 로그를 commit하지 않는다. 공유 자료는 합성 또는 비식별 자료를 우선한다.
- 향후 평가 산출물 추가 전 민감 정보와 비밀값 포함 여부를 확인하고 필요한 제외 설정을 검토한다.
