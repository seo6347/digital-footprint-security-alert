# DFSA Repository 작업 가이드

이 문서는 DFSA Repository에서 개발자와 Coding Agent가 **어디를 수정할 수 있는지, 어떤 규칙을 따라야 하는지, 어떤 문서를 확인해야 하는지** 빠르게 판단하기 위한 가이드이다.

상세 기술 명세나 구현 설명서를 대체하지 않는다.

---

## 1. Source of Truth

v0.2 개발 목표, Architecture, Public Contract 및 팀 결정의 기준은 `docs/team-development-spec-v0.2.md`다. Contract Freeze 시점은 해당 명세 §12를 따른다.

`docs/team-development-spec-v0.1.md`는 기존 실행과 개발 이력의 기준으로 보존한다. 신규 개발은 v0.2 공개 계약과 호출 경계를 사용한다.

README는 프로젝트 소개용, CONTRIBUTING은 팀원 정보 관리용이다. 코드와 해당 단계의 명세가 충돌하면 먼저 보고한다. 상세 기술 결정은 중앙 명세에 유지한다.

---

## 2. 수정 정책

| 정책             | 의미                            | 작업 기준                                  |
| -------------- | ----------------------------- | -------------------------------------- |
| 🟢 자유 수정       | 담당 Component의 내부 구현           | Public Contract와 명세를 지키는 범위에서 Owner 재량 |
| 🟡 담당 영역       | 특정 Owner가 관리하는 영역             | 다른 담당자가 수정하려면 Owner와 먼저 협의             |
| 🔴 공통 Contract | 여러 Component가 공유하는 Public API | 팀 합의 없이 누구도 임의 변경 금지                   |

### 기본 원칙

* 🟡 영역도 해당 Owner에게는 내부 구현 범위에서 🟢로 본다.
* 🔴 영역은 Owner 여부와 관계없이 팀 합의 없이 변경하지 않는다.
* 내부 구현 자율성은 Public field, Enum, required/optional, ID 구조, Public Interface 변경까지 포함하지 않는다.
* 테스트나 fixture를 완화해서 잘못된 Schema를 통과시키지 않는다.
* 명세에 없는 공통 영역에 임의로 Owner를 지정하지 않는다.

### 🔴 영역 변경이 필요한 경우

먼저 다음을 정리해 보고한다.

1. 변경이 필요한 이유
2. 영향받는 Component
3. 예상 변경 파일
4. Public Contract 영향

이미 팀에서 합의된 변경이라면 합의된 범위 안에서만 수정한다.

---

## 3. Repository Map

작은 helper나 단순 test 파일은 모두 나열하지 않는다.
주요 책임, Public Contract, Component 진입점처럼 다른 작업에 영향을 주는 파일만 관리한다.

| Path                                 | 역할 / 수정 시점                                            | 정책       |
| ------------------------------------ | ----------------------------------------------------- | -------- |
| `AGENTS.md`                          | Repository 구조, Ownership, 수정 정책, Agent 작업 방식이 바뀔 때 갱신 | 🟡       |
| `docs/team-development-spec-v0.2.md` | v0.2 Architecture, Contract, 책임, Pipeline 등 팀 공통 결정 | 🔴 |
| `docs/team-development-spec-v0.1.md` | 기존 구현 및 구조 분리 단계의 계약, 개발 이력 | 🔴 |
| `README.md`                          | 프로젝트 소개 및 주요 문서 안내                                    | 🟡       |
| `CONTRIBUTING.md`                    | 팀원 계정·이름 등 협업 정보 관리                                   | 🟡       |
| `src/dfsa/`                          | DFSA Python 패키지 루트                                    | 하위 정책 적용 |
| `src/dfsa/__init__.py`               | 패키지 초기화                                               | 🟡       |
| `src/dfsa/contracts/`                | A/Explorer/B/C, Orchestrator, UI가 공유하는 Pydantic Contract       | 🔴       |
| `src/dfsa/contracts/__init__.py`     | Public Contract import/export 진입점                     | 🔴       |
| `src/dfsa/contracts/common.py`       | 공통 모델, Subject, ErrorDetail, Enum                     | 🔴       |
| `src/dfsa/contracts/search.py`       | Module A 요청·응답 Contract                               | 🔴       |
| `src/dfsa/contracts/profiling.py`    | Module B 요청·응답, Source·Exposure Contract              | 🔴       |
| `src/dfsa/contracts/exploration.py` | Explorer 내부 계약과 공개 탐색 이력 | 🔴 |
| `src/dfsa/contracts/analysis.py` | C 계약, Profile/Graph/교육/대응 결과 | 🔴 |
| `src/dfsa/contracts/result.py`       | 최종 `DFSAResult`, stage, summary Contract              | 🔴       |
| `src/dfsa/modules/`                  | 실제 Module Python 패키지 루트; 하위 담당 영역별 작업 위치 | 하위 정책 적용 |
| `src/dfsa/modules/search/`           | Module A 구현 위치 — 정유채 담당                         | 🟡       |
| `src/dfsa/_documents.py` | Explorer와 B가 공유하는 내부 문서 자료형 | 🟡 |
| `src/dfsa/modules/profiling/` | Module B 구현 — 서동균 | 🟡 |
| `src/dfsa/modules/explorer/` | HTML Fetch, URL Policy, Parsing — 서동균 | 🟡 |
| `tests/modules/explorer/` | Fetch, URL Policy, Parsing 회귀 테스트 — 서동균 | 🟡 |
| `frontend/` | 예정: Web UI — 정유채, 기술·구현 상세 Owner 재량 | 🟡 |
| `src/dfsa/modules/risk/`             | Module C 구현 위치 — 강영림 담당                         | 🟡       |
| `src/dfsa/service/`                  | 서동균 담당 상위 Pipeline service                         | 🟡       |
| `src/dfsa/service/__init__.py`       | Public `run_pipeline` import 진입점                      | 🟡       |
| `src/dfsa/service/orchestrator.py`   | 요청 변환, 호출·상태 제어, 오류·결과 조합 및 Module callable 연결 | 🟡       |
| `src/dfsa/_v01/` | 임시 v0.1 실행 및 회귀 검증용 계약과 Orchestrator | 🟡 |
| `tests/contract/`                    | Public Contract validation 회귀 테스트                     | 🟡       |
| `tests/integration/`                 | Contract-valid Mock 기반 Orchestrator Pipeline 검증       | 🟡       |
| `tests/modules/search/`              | Module A 동작·오류 처리 테스트 위치 — 정유채 담당          | 🟡       |
| `tests/modules/profiling/`           | Module B 동작·오류 처리 테스트 위치 — 서동균 담당          | 🟡       |
| `tests/modules/risk/`                | Module C 동작·오류 처리 테스트 위치 — 강영림 담당          | 🟡       |
| `tests/fixtures/v02/` | v0.2 단계별 합성 객체와 UI 개발용 결과 JSON | 🟡 |
| `tests/legacy/` | v0.1 계약 및 Orchestrator 회귀 테스트와 fixture | 🟡 |
| `tests/e2e/` | v0.1 실제 모듈 Offline E2E 및 v0.1·v0.2 수동 Live runner | 🟡 |
| `tests/e2e/live_v02.py` | 승인된 v0.2 단계별 Live 실행 진입점 | 🟡 |
| `evaluation/README.md`               | v0.1 평가 준비 이력과 v0.2 검증 범위 | 🟡       |
| `evaluation/module_a/`               | Module A 품질 평가 위치 — 정유채 담당                    | 🟡       |
| `evaluation/module_b/`               | Module B 품질 평가 위치 — 서동균 담당                    | 🟡       |
| `evaluation/module_c/`               | Module C 품질 평가 위치 — 강영림 담당                    | 🟡       |
| `evaluation/e2e/`                    | E2E 품질 평가 위치 — 팀 공동 협의, 단독 Owner 미확정      | 🟡       |
| `pytest.ini`                         | pytest 탐색 및 import 설정                                 | 🟡       |
| `requirements.txt`                   | 공통 Python dependency 관리                               | 🟡       |
| `.gitignore`                         | 캐시·로컬 환경·민감 파일 제외 설정                                  | 🟡       |

Contract가 변경되면 관련 `tests/contract/`와 `tests/fixtures/`도 함께 확인한다.

---

## 4. 현재 구현 상태 및 전환 범위

| 영역 | 현재 상태 / v0.2 계획 |
| --- | --- |
| A/B/C | 기존 v0.1 구현으로 회귀를 검증한다. v0.2 callable 구현은 담당자별 후속 PR 범위다. |
| Orchestrator | v0.2 A → Explorer → B → C 호출 제어 구현. Mock 검증 가능. |
| Offline E2E | v0.1 실제 모듈 회귀 검증 유지. |
| Explorer | 기존 문서 확보 구현과 v0.2 호출 경계가 준비됐다. 실제 탐색은 후속 PR 범위다. |
| Frontend / UI | 담당자가 신규 구현 및 기술 상세 수정 |
| Evaluation | 별도 정량적 평가 제외; 기능·회귀·Live E2E 검증 유지 |

v0.2 담당자별 구현 예정 파일, import 경로, callable 연결 예시는 [README의 Module 연결 안내](README.md#v02-orchestrator-사용-및-module-연결)를 따른다. 구조 및 Contract 변경 후 Repository Map을 갱신한다.

---

## 5. Ownership

| 영역 | Owner | 책임 |
| --- | --- | --- |
| Module A | 정유채 | 실제 검색 및 발견 출처/이력 |
| Frontend / UI 및 API 연결 | 정유채 | 사용자 입력 및 결과 표시, UI 기술 선택 |
| Page Explorer | 서동균 | Fetch/Parsing/보안 정책 분리, 제한된 다중 페이지 탐색 |
| Module B | 서동균 | Rule+학교 LLM API Hybrid, 동일인 및 Exposure/Evidence 검증 |
| Module C | 강영림 | Profile, Graph, 교육용 위험 설명 및 대응 방안 |
| Orchestrator | 서동균 | A → Explorer → B → C 호출 제어 및 시간/상태/결과 조합 |
| 공통 Contract | 서동균 + 팀 Review | Public Contract 관리 및 변경 검토 |

v0.2에서는 Orchestrator가 A/Explorer/B/C를 각각 호출한다. C는 확인된 Exposure만 사용하며 Orchestrator는 분석 내용을 재생성하지 않는다. `dfsa._v01`은 기존 실행과 회귀 검증 전용이다. 신규 v0.2 코드의 의존성을 공개 v0.2 계약과 공유 내부 자료형으로 유지하고, 모든 모듈의 전환과 회귀 검증 이후 레거시 제거를 검토한다. UI 담당자는 추천 기술 스택과 구현 상세를 수정할 수 있으나 공통 계약 변경은 팀 합의를 거친다.

---

## 6. Spec Lookup Guide

`AGENTS.md`에서 Owner 및 작업 단계를 확인한 뒤 v0.2 상세 명세의 관련 절을 읽는다. v0.1 구조 분리 및 회귀 검증에는 기존 명세를 함께 확인한다.

| 작업 | v0.2 명세 |
| --- | --- |
| 전체 범위, 결과, 책임 | §1–3 |
| 공통 Contract/ID | §4 |
| Module A | §5 |
| Page Explorer | §6 |
| Module B / 학교 LLM API | §7 |
| Module C | §8 |
| Orchestrator / DFSAResult | §9 |
| UI | §10 |
| 라이브러리 및 개인정보 | §11 |
| 개발 순서 및 검증 | §12–14 |

미확인 학교 API 사양, 초기 탐색/LLM 제한은 검증 후 팀과 조정한다.

---

## 7. Agent Workflow

큰 작업은 다음 순서로 진행한다.

1. `AGENTS.md`와 현재 branch / working tree를 확인한다.
2. 기존 사용자 변경사항을 보존한다.
3. 작업 대상 Path와 🟢/🟡/🔴 정책을 확인한다.
4. 관련 명세 섹션만 찾아 읽는다.
5. 요청 범위와 현재 개발 단계를 확인한다.
6. 이후 Phase의 구현을 요청 없이 미리 시작하지 않는다.
7. 🔴 변경 필요, 명세 충돌, 미결 사항을 발견하면 먼저 보고한다.
8. 승인된 범위에서 구현한다.
9. 관련 테스트를 실행한다.
10. 필요한 경우 Documentation Update Policy에 따라 문서를 갱신한다.
11. 변경 내용, 테스트 결과, 남은 미결 사항을 보고한다.

PR 본문은 기술 명세의 `What / Why / Test` 형식을 따른다.

---

## 8. 테스트 및 검증

외부 라이브러리 사용을 적극 검토한다. Owner는 라이선스·호환성·보안·재현성을 확인하고 공통 의존성 변경을 PR에 기록한다. 기존 Evidence/URL 보안 정책을 약화시키지 않는다. 학교 API 키와 실개인정보는 저장소 및 로그에 저장하지 않는다.

기본 환경:

* Python 3.12
* Pydantic v2
* pytest

기본 전체 테스트:

```bash
python -m pytest
```

Contract 테스트만 실행:

```bash
python -m pytest tests/contract
```

Windows 로컬 환경에서는 필요하면 다음을 사용할 수 있다.

```bash
.venv\Scripts\python.exe -m pytest
```

문서만 변경한 경우에는 테스트 실행이 필수가 아닐 수 있다. 대신 다음을 확인한다.

* 실제 Path와 문서 내용 일치 여부
* Ownership 일치 여부
* 명세 참조 정확성
* 변경 diff

테스트를 실행하지 않았다면 그 이유를 최종 보고에 남긴다.

---

## 9. Documentation Update Policy

모든 코드 변경마다 문서를 수정하지 않는다.

### `AGENTS.md`를 갱신하는 경우

* 주요 폴더 또는 파일 추가·삭제
* 주요 파일의 책임 변경
* Component entry point 변경
* Ownership 변경
* 수정 정책 변경
* Agent 작업 방식 변경

작은 helper, 단순 test, 내부 refactoring은 일반적으로 반영하지 않는다.

### `team-development-spec-v0.2.md`를 갱신하는 경우

* Public Contract 변경
* Schema / Enum 변경
* Public Interface 변경
* Architecture / Data Flow 변경
* Module 책임 변경
* Pipeline 정책 변경
* 상태 / Error 처리 정책 변경
* 팀 공통 결정 변경

내부 구현 방식, helper 함수, 변수명 변경 등은 일반적으로 상세 명세 대상이 아니다.

Contract 관련 변경은 명세의 Contract 변경 절차를 따른다.

---

## 10. 문서 유지 원칙

`AGENTS.md`는 상세 구현 설명서가 아니다.

다음 원칙을 유지한다.

* 가능한 한 짧게 유지한다.
* Schema 전체를 복사하지 않는다.
* 함수 내부 알고리즘을 설명하지 않는다.
* 상세 정책을 중복 정의하지 않는다.
* Repository 구조와 작업 규칙을 빠르게 찾는 용도로 유지한다.

---

## 11. 향후 문서 분리

v0.2는 `team-development-spec-v0.2.md`를 중앙 상세 명세로 유지하며 v0.1은 이력으로 보존한다.

다음 상황이 생기면 Module별 문서 분리를 검토한다.

* Module 내부 설계가 크게 증가함
* 특정 Module 작업을 위해 무관한 내용을 지나치게 많이 탐색해야 함
* Algorithm / Provider / Evaluation 등 별도 상세 문서가 필요함
* 하나의 명세 파일에서 동시 편집 충돌이 잦아짐
* 공통 Contract와 Module 내부 설계를 분리할 필요가 생김

분리 이후에도 다음 항목은 가능한 한 중앙 명세에 유지한다.

* Architecture
* Public Contract
* Common Enum
* Data Flow
* Public Interface
* ID Ownership
* Pipeline 상태 규칙
* Contract 변경 정책

Module별 문서에는 내부 구현과 상세 설계를 둔다.

문서를 실제로 분리할 때는 `AGENTS.md`의 Repository Map과 참조 경로도 함께 갱신한다.
