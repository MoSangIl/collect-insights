# Collect Insights — LLM Wiki Schema

이 프로젝트는 기술 뉴스/인사이트를 자동 수집하고, Claude AI가 관리하는 위키로 합성하는 시스템입니다.

## 3계층 아키텍처

### vault/ — Raw Sources (불변)
수집된 원본 기사/릴리스 노트. LLM이 읽기만 하고 절대 수정하지 않음.

### wiki/ — 합성 위키 (LLM 관리)
LLM이 생성하고 유지하는 구조화된 지식 베이스. 사용자는 읽기만 함.

### CLAUDE.md — 스키마 (이 파일)
위키 구조, 규칙, 워크플로우를 정의.

---

## 디렉토리 구조

```
wiki/
├── entities/     # 도구, 서비스, 라이브러리, 회사 등 명명된 대상
├── concepts/     # 패턴, 아이디어, 기술 개념
├── comparisons/  # 엔티티/개념 간 비교 분석
├── summaries/    # 주간/주제별 종합 요약
├── index.md      # 전체 위키 페이지 카탈로그
└── log.md        # 작업 이력 (append-only)
```

---

## 페이지 타입 및 프론트매터

### Entity (entities/)
```yaml
---
title: "엔티티 이름"
type: entity
entity_class: tool | service | library | framework | company | protocol | language | person
tags: []
related_pages: []  # [[위키링크]] 목록
source_count: 0    # 이 엔티티를 언급한 raw source 수
last_updated: YYYY-MM-DD
status: active | deprecated | uncertain
---
```

### Concept (concepts/)
```yaml
---
title: "개념 이름"
type: concept
tags: []
related_pages: []
source_count: 0
last_updated: YYYY-MM-DD
---
```

### Comparison (comparisons/)
```yaml
---
title: "A vs B"
type: comparison
compared: ["엔티티A", "엔티티B"]
tags: []
last_updated: YYYY-MM-DD
---
```

### Summary (summaries/)
```yaml
---
title: "주제 — 기간"
type: summary
period: YYYY-MM-DD ~ YYYY-MM-DD
tags: []
last_updated: YYYY-MM-DD
---
```

---

## 택소노미

### 엔티티 (Tier 1 — 자동 생성 대상)
- Claude Code (tool) — Anthropic의 AI 코딩 CLI
- Anthropic SDK (library) — Python/TS SDK
- MCP (protocol) — Model Context Protocol
- PostgreSQL (service) — 데이터베이스
- Rust (language)
- TypeScript (language)
- Docker (tool) — 컨테이너화
- GitHub (service) — 코드 호스팅/협업

### 개념 (Tier 1)
- ai-coding — AI 보조 개발 워크플로우
- agentic-workflows — 멀티스텝 AI 에이전트 패턴
- mcp-protocol — MCP 생태계, 도구, 패턴
- performance-optimization — DB, 런타임, 빌드 성능
- developer-tooling — CLI, 에디터, 빌드 도구
- security — 공급망, 샌드박싱, 취약점
- distributed-systems — 합의, CDN, 데이터베이스
- fullstack-architecture — SaaS, 인프라, 프론트엔드

---

## 위키링크 규칙

- `[[Entity Name]]` 형식 사용 (대소문자 구분, 파일명에서 .md 제외)
- 새 엔티티/개념 언급 시 반드시 해당 페이지 존재 여부 확인
- 존재하면 링크, 없으면 새 페이지 생성

---

## 업데이트 규칙

1. **기존 페이지 업데이트 시**: 기존 내용 삭제 금지. `## YYYY-MM-DD 업데이트` 섹션을 추가하여 새 정보 append
2. **새 페이지 생성 시**: 프론트매터 + 개요 + 관련 소스 섹션 포함
3. **source_count**: raw source에서 해당 엔티티/개념이 언급될 때마다 +1
4. **related_pages**: 양방향 링크 유지 (A가 B를 참조하면 B도 A를 참조)
5. **모순 발견 시**: 삭제하지 말고 `> ⚠️ 모순:` 블록쿼트로 표시

---

## index.md 형식

```markdown
# Wiki Index

## Entities
| Page | Class | Description | Sources | Updated |
|------|-------|-------------|---------|---------|
| [[Claude Code]] | tool | Anthropic의 AI 코딩 CLI | 15 | 2026-04-13 |

## Concepts
| Page | Description | Sources | Updated |
|------|-------------|---------|---------|
| [[ai-coding]] | AI 보조 개발 워크플로우 | 8 | 2026-04-13 |

## Comparisons
...

## Summaries
...
```

---

## log.md 형식

```
YYYY-MM-DD HH:MM | OPERATION | description
```

Operations: `INGEST`, `QUERY`, `LINT`, `BACKFILL`

예시:
```
2026-04-13 18:00 | INGEST | 5 items processed, 2 entities updated, 1 concept created
2026-04-14 10:00 | LINT | 3 orphan pages found, 1 missing concept page
```

---

## 평가 컨텍스트

이 위키의 소유자: Claude Code 파워유저, 풀스택 개발자, 자동화/AI 코딩 도구에 관심이 높음.
인사이트 평가 시 이 컨텍스트를 기준으로 관련성을 판단.
