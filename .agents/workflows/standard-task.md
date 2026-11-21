# 표준 Task 워크플로

## 0. 작업 복잡도 레벨 판정 (토큰 최적화 지침)
Controller는 Task 등록 시 작업 성격에 맞춰 실행 파이프라인을 결정합니다. 모든 작업에 7개 에이전트를 전부 호출하지 않습니다.

| 레벨 | 대상 예시 | 워크플로 파이프라인 | 원칙 |
|:---:|---|---|---|
| **Level 1**<br/>**단순 수정** | 버튼 문구, CSS 스타일, 경미한 버그 수정 | `Controller` → `Frontend`/`Backend` → *(필요 시)* `Reviewer` | Planner, Architect, Designer, QA 생략 |
| **Level 2**<br/>**일반 기능 개발** | 신규 화면, API 추가, 기존 기능 확장 | `Controller` → `Planner(간략)` → `필요 설계(선별)` → `개발자` → `Reviewer` → `관련 QA` | 기존 아키텍처/디자인 재사용, 변경분만 검토 |
| **Level 3**<br/>**복잡/신규 프로젝트** | 신규 아키텍처, 대규모 기능, 다중 시스템 연동 | `Controller` → `Planner` → `Architect` + `Designer` → `Frontend` + `Backend` → `Reviewer` → `QA` | WBS 계획, 정밀 설계, 2차 리뷰, 실 E2E 검증 |

## 1. 접수와 계획
1. Controller가 요청을 Task로 등록하고 ID를 부여합니다.
2. Planner가 요구사항, 범위, 수용 기준, 위험, 의존성을 정리합니다.
3. Controller가 범위와 우선순위를 확인합니다.

## 2. 설계
1. Architect가 기술 구조, 데이터 모델, API 계약을 작성합니다.
2. 화면이 있으면 Designer가 UI/UX 명세를 작성합니다.
3. Controller는 필수 명세가 준비되었는지 확인합니다.

## 3. 구현
1. Controller가 Frontend/Backend에 파일 소유권과 작업 경계를 배정합니다.
2. Frontend와 Backend는 API 계약을 기준으로 병렬 작업할 수 있습니다.
3. 개발자는 자체 테스트를 실행하고 development-report.md를 작성합니다.

## 4. 검토와 테스트
1. Reviewer가 독립 코드 리뷰를 수행합니다.
2. `CHANGES_REQUESTED`이면 담당 개발자가 수정하고 리뷰를 재요청합니다.
3. 리뷰 통과 후 QA가 통합/E2E/회귀 테스트를 실행합니다.
4. `FAIL`이면 QA가 증거를 기록하고 담당 개발자에게 수정 요청을 보냅니다.
5. 수정 후 Reviewer 또는 QA가 영향 범위에 맞게 재검증합니다.

## 5. 완료
Controller가 수용 기준, 개발 보고서, 리뷰 결과, QA 결과를 확인한 뒤에만 `COMPLETED`로 설정합니다.

## herdr 통신
각 단계의 요청·응답은 설치된 herdr Skill을 통해 전달합니다. 실제 명령·인수·pane 식별자는 설치된 Skill 문서에서 확인하며 추정하지 않습니다.
