# DFSA Repository 작업 가이드

## Purpose / Source of Truth

- 개발자와 Coding Agent가 작업 위치, 책임자, 변경 범위를 찾기 위한 가이드이다.
- 상세 기술 명세나 구현 설명서를 대체하지 않는다.
- v0.1 Architecture / Public Contract / Schema / Pipeline 정책의 단일 상세 Source of Truth는
  [docs/team-development-spec-v0.1.md](docs/team-development-spec-v0.1.md)이다.
- README는 프로젝트 소개이고 CONTRIBUTING은 현재 팀원 계정 목록이다. 상세 결정은 명세를 따른다.
- 명세와 코드의 명백한 충돌은 먼저 보고한다. 요청 범위를 넘어 어느 쪽도 임의 수정하지 않는다.

## Repository Modification Policy

| 정책 | 의미 | 작업 기준 |
| --- | --- | --- |
| 🟢 Owner 자유 수정 | 담당 Component의 내부 구현 | 요청 범위와 명세를 지키는 한 내부 설계는 Owner 재량 |
| 🟡 담당 영역 | 다른 담당자에게 영향이 있는 변경 | 다른 담당자가 수정하려면 Owner와 협의 |
| 🔴 팀 공통 Public Contract | 여러 Component가 공유하는 계약 | Owner도 팀 합의 없이 임의 변경 금지 |

- 🟡 영역은 해당 Owner가 작업할 때 🟢 원칙을 적용한다. 🔴 계약에는 이 예외가 없다.
- 내부 구현의 자율성이 Public field, Enum, required/optional, ID 구조, Interface 변경을 허용하지 않는다.
- 🔴 변경이 필요하면 변경 이유와 영향받는 Component를 먼저 보고하고 명세 §29 절차를 따른다.
- 이미 명시적으로 합의·승인된 변경 요청은 그 범위에서 진행한다. 편의를 위한 계약 확장은 금지한다.
- 테스트나 fixture를 약화하여 잘못된 Schema를 허용하지 않는다.
- 개별 Owner가 명세에 없는 공통 파일은 임의의 Owner를 지정하지 말고 영향받는 담당자와 협의한다.

## Repository Map

아래 Path는 현재 실제 존재한다. 역할·Owner가 바뀌지 않는 작은 helper/test는 개별 나열하지 않는다.

| Path | 역할 / 수정할 때 | 수정 정책 |
| --- | --- | --- |
| `AGENTS.md` | 작업 위치·Owner·수정 정책 또는 작업 방식 변경 시 갱신 | 🟡 팀 공통 가이드 |
| `docs/team-development-spec-v0.1.md` | 상세 계약·책임·흐름·공통 결정의 기준; 합의된 변경 반영 | 🔴 팀 공통 명세 |
| `README.md` | 프로젝트 소개 및 명세 안내; 소개가 변경·불일치할 때 수정 | 🟡 팀 공통 문서 |
| `CONTRIBUTING.md` | 팀원 계정·이름 목록; 구성원 정보 변경 시 수정 | 🟡 팀 공통 문서 |
| `src/dfsa/` | `src/` 아래 Python 패키지; 현재는 Contract 코드만 존재 | 하위 파일 정책 적용 |
| `src/dfsa/__init__.py` | 패키지 초기화; 패키지 진입 구조 변경 시 확인 | 🟡 공통 패키지 |
| `src/dfsa/contracts/` | A/B/C·Orchestrator·UI가 공유할 Pydantic v2 계약 | 🔴 팀 공통 Public Contract |
| `src/dfsa/contracts/__init__.py` | 주요 Public Model import/export 진입점 | 🔴 공통 export |
| `src/dfsa/contracts/common.py` | 공통 모델 기반, Subject, ErrorDetail, Enum; 공통 계약 변경 시 확인 | 🔴 공통 모델·Enum |
| `src/dfsa/contracts/search.py` | A의 요청·응답 및 검색 결과 모델; Search 계약 변경 시 확인 | 🔴 A 경계 계약 |
| `src/dfsa/contracts/profiling.py` | B의 요청·응답, 재사용 Source·Exposure; Profiling 계약 변경 시 확인 | 🔴 B 경계·공유 모델 |
| `src/dfsa/contracts/risk.py` | C의 요청·응답, Evaluation·RiskPath; Risk 계약 변경 시 확인 | 🔴 C 경계·공유 모델 |
| `src/dfsa/contracts/result.py` | UI가 받을 DFSAResult·stages·summary; 최종 결과 계약 변경 시 확인 | 🔴 Service/UI 계약 |
| `tests/contract/` | 입력·출력 validation 회귀 검증; 계약 변경·검증 결함 수정 시 갱신 | 🟡 계약 담당·영향받는 Owner 협의 |
| `tests/fixtures/` | Contract-valid JSON 예시; 합의된 계약 변경 시 관련 테스트와 함께 갱신 | 🟡 데이터, 🔴 계약 의미 변경 |
| `pytest.ini` | 테스트 탐색 및 src import 설정; 테스트 실행 구조 변경 시 확인 | 🟡 공통 실행 설정 |
| `requirements.txt` | 공통 dependency source; 필요한 새 package를 추가할 때 갱신 | 🟡 공통 의존성 |
| `.gitignore` | 로컬 환경·캐시·민감 설정 제외; 새 제외 항목이 필요할 때 추가 | 🟡 공통 설정; 기존 항목 보존 |

### 아직 구현되지 않은 영역

명세 §26의 추천 구조와 실제 생성된 구조를 구분한다. 아래는 현재 파일 경로가 아니라 책임 영역이다.

| 영역 | 현재 상태 | 향후 내부 구현 수정 정책 |
| --- | --- | --- |
| Module A | 구현 디렉터리·실행 entry point 없음 | 🟡 정유채 담당, Owner 내부 구현은 🟢 |
| Module B | 구현 디렉터리·실행 entry point 없음 | 🟡 서동균 담당, Owner 내부 구현은 🟢 |
| Module C | 구현 디렉터리·실행 entry point 없음 | 🟡 강영림 담당, Owner 내부 구현은 🟢 |
| Orchestrator | Service 디렉터리·실행 entry point 없음 | 🟡 서동균 담당, Owner 내부 구현은 🟢 |
| Integration tests | 통합 테스트 디렉터리 없음 | 🟡 관련 Component Owner 협의 |
| Frontend / UI | UI 디렉터리·실행 entry point 없음 | 🟡 정유채 담당, Owner 내부 구현은 🟢 |

위 영역의 파일이나 entry point를 이미 존재하는 것으로 가정하지 않는다. 구현 추가 후 실제 경로로 Map을 갱신한다.

## Ownership

명세 §3, §31, §37 기준이다. Contract 파일 이름과 Component 내부 구현의 소유권은 동일하지 않다.

| 영역 | Owner | 책임 요약 |
| --- | --- | --- |
| Module A / Frontend | 정유채 | 검색 수집·후보 관련성 판단 및 UI |
| Module B | 서동균 | 동일인 검증·Exposure 추출/검증 및 Source/Evidence 보존 |
| Module C | 강영림 | Risk 분석·상태·평가 및 설명/대응 방안 생성 |
| Orchestrator | 서동균 | B와 별도 Component; 호출 순서·상태·실패 전파·결과 조합 |
| Phase 1 공통 Contract | 서동균 + 팀 Review | 공통 계약 고정; 개인 판단으로 계약 변경 불가 |

- A/B/C는 서로 직접 호출하지 않는다. Orchestrator가 Public Interface를 통해 흐름을 관리한다.
- 설명·reason·recommendations 생성은 C 책임이다. Orchestrator는 이를 새로 생성하거나 수정하지 않는다.
- C의 template 우선 및 내부 LLM fallback 방향, 미결 supported 정책은 명세를 확인한다.

## Spec Lookup Guide

매 작업마다 상세 명세 전체를 다시 읽을 필요는 없다. AGENTS 전체 확인 → 작업 영역 파악 → heading/keyword 검색 → 관련 절 읽기 순서로 확인한다.

| 작업 | 실제 명세 heading / 확인할 절 |
| --- | --- |
| 범위·책임 파악 | §1 문서 목적, §2 v0.1 프로젝트 범위, §3 Component 및 담당 범위 |
| Module A | §3.1, §9 SearchRequest, §10 SearchResponse |
| Module B | §3.2, §11 ProfilingRequest, §12 Module B 내부 Pipeline, §13~17 Identity / Exposure / Source |
| Module C | §3.3, §18 RiskRequest, §19 C Risk Rule v0.1, §20 Risk Path Status, §21 Risk Evaluation, §22 RiskResponse |
| Orchestrator | §3.4, §23 DFSAResult, §24 Orchestrator Pipeline 제어, §25 Public Interface |
| Contract | 해당 Schema, §6 공통 규칙, §7 ID Ownership, §8 공통 Module Status, §26~29 Contract / Validation / Enum / 변경 규칙 |
| Test / Fixture | 해당 Contract, §27 Contract Validation 규칙, §30 Mock Data, §32 Integration 순서, §35 PR Merge 최소 조건 |
| UI | §23 Schema 7 — Service → UI, §37 UI Contract |
| 개발 순서·완료 조건 | §31 개발 순서, §32 Integration 순서, §34 PR 규칙, §36 Module별 Definition of Done — v0.1 |
| 품질 평가 설계 | §39 Evaluation 이후 계획; 미결 Dataset / Metric / 절차를 임의 확정하지 않음 |

heading은 `rg -n '^#|Public Interface|Contract 변경 규칙' docs/team-development-spec-v0.1.md` 등으로 찾는다.
영향 범위가 여러 Component에 걸치면 각 관련 절과 공통 규칙을 함께 읽는다.

## Agent Workflow

1. `AGENTS.md` 전체와 현재 branch / working tree를 확인한다. 기존 사용자 변경을 보존한다.
2. 대상 Path, Owner, 🟢/🟡/🔴 정책을 확인한다. 없는 구현이나 entry point를 추측하지 않는다.
3. 관련 명세 heading / keyword를 검색하고 필요한 절을 읽는다.
4. 요청 범위와 현재 개발 단계를 확인한다. 이후 Phase의 구현을 요청 없이 시작하지 않는다.
5. 🔴 변경 필요성이나 명세 충돌·미결 사항은 먼저 보고한다. 승인된 범위 밖의 임의 변경은 하지 않는다.
6. 합의된 범위에서 구현한다. 상세 알고리즘·Schema를 이 문서에 중복 정의하지 않는다.
7. 관련 테스트를 실행한다. Contract 변경이면 영향받는 fixture와 테스트도 함께 검증한다.
8. 아래 정책에 해당할 때만 문서를 갱신한다.
9. 변경 내용, 테스트 결과, 미결 사항을 보고한다. PR 본문은 §34의 What / Why / Test 형식을 따른다.

### 현재 실행 환경과 검증

- Python 3.12, Pydantic v2, pytest를 사용한다. 공통 의존성은 root `requirements.txt`에서 관리한다.
- 테스트 실행 진입점은 `python -m pytest`이다. `pytest.ini`가 `src`를 import 경로에 추가한다.
- Windows의 현재 로컬 환경에서는 `.venv\Scripts\python.exe -m pytest`를 사용할 수 있다.
- 관련 Contract 테스트만 실행할 때는 `python -m pytest tests/contract`를 사용한다.
- 문서만 변경하면 Path·Owner·명세 참조·diff를 대조한다. 검증 결과와 테스트 미실행 사유를 보고한다.

## Documentation Update Policy

모든 코드 변경마다 문서를 수정하지 않는다.

| 대상 | 갱신하거나 갱신을 검토할 때 |
| --- | --- |
| `AGENTS.md` | 주요 파일/폴더 추가·삭제, 책임·entry point·Ownership·수정 정책·작업 방식 변경 |
| 상세 기술 명세 | Public Contract / Schema / Enum / Interface / Architecture / Data Flow / Module 책임 / Pipeline·상태·Error 정책 / 팀 공통 결정 변경 |

- Repository Map은 구조·주요 책임이 변할 때 갱신한다. 작은 helper/test 추가만으로 모두 나열하지 않는다.
- 내부 refactoring, helper 추가, 변수명 변경 등은 일반적으로 상세 명세 갱신 대상이 아니다.
- 상세 명세 변경은 §29 절차를 따른다. 이미 합의된 의미를 이 가이드에서 별도로 재정의하지 않는다.
- 이 문서는 약 100~200줄의 짧은 가이드로 유지하고, Schema·함수 내부 알고리즘 설명은 넣지 않는다.

## 향후 문서 분리 정책

- 현재는 중앙 상세 명세 하나를 유지하며 Module별 Spec을 새로 만들지 않는다.
- 내부 설계 증가, 무관한 내용 탐색 부담, Module별 Algorithm/Provider/Evaluation 설명 필요,
  동시 편집 충돌 증가, 공통 Contract와 내부 설계의 분리 필요가 생기면 팀과 문서 분리를 검토한다.
- 분리하더라도 Architecture, Public Contract, Common Enum, Data Flow, Public Interface,
  ID Ownership, Pipeline 상태 규칙, Contract 변경 정책은 가능한 한 중앙 명세에 유지한다.
- 향후 Module별 문서에는 내부 구현·상세 설계를 둔다. 실제 분리 시 이 가이드의 Map과 참조를 갱신한다.
