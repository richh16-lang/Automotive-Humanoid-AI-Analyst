# Inchang's Agent — Claude 작업 규칙

## 프로젝트 한 줄 요약
Automotive/AI 반도체 뉴스를 수집·분석해 10섹션 보고서를 생성하고
Notion·Word·Gmail로 발송하는 자동화 시스템 + Streamlit 대시보드.

---

## 핵심 설계 계약 (절대 어기지 말 것)

### 계약 1 — 저장·읽기·렌더러 3자 일관성
어떤 데이터 포맷이든 반드시 3곳이 함께 움직인다:

```
저장  : notion_client._build_blocks() / _source_item_bullet()
읽기  : notion_client._extract_page_text() / _parse_raw_to_sections()
렌더링: streamlit_app._md_to_html()
```

**하나를 바꾸면 반드시 나머지 둘도 확인·수정한다.**
이 규칙을 어긴 경우가 이 프로젝트에서 버그의 가장 큰 원인이었다.

### 계약 2 — 섹션 경계 헤딩 등록
새로운 헤딩이 Notion에 저장된다면 반드시
`notion_client._SECTION_HEADING_VARIANTS`에 등록해야 한다.
미등록 시 `_parse_raw_to_sections()`가 해당 헤딩 이하 내용을
이전 섹션에 혼입시킨다.

### 계약 3 — max_tokens와 프롬프트 길이
SYSTEM_PROMPT나 ANALYSIS_TEMPLATE을 변경할 때마다
`llm_router.py`의 `max_tokens` 값이 충분한지 재확인한다.
출력이 정확히 한도에서 끊기면 토큰 한도 초과다.

---

## 수정 시 체크리스트

### Notion 저장 포맷 변경 시
- [ ] `_build_blocks()` 저장 로직 수정
- [ ] `_extract_page_text()` 읽기 로직 동시 수정
- [ ] `_parse_raw_to_sections()` 섹션 파싱 영향 여부 확인
- [ ] `_md_to_html()` 렌더링 영향 여부 확인

### SYSTEM_PROMPT / 분석 템플릿 변경 시
- [ ] `max_tokens` 값 충분한지 확인 (현재 16,000)
- [ ] 새 출력 포맷이 있다면 `_md_to_html()`에 렌더러 추가
- [ ] 새 출력 포맷이 있다면 `_parse_sections()`에서 인식되는지 확인

### 새 섹션 또는 특수 블록 추가 시
- [ ] `_SECTION_HEADING_VARIANTS`에 변형 등록
- [ ] `_match_heading()` 정규식 영향 여부 확인
- [ ] Streamlit 렌더러에서 해당 섹션 처리 여부 확인

---

## 반복 오류 패턴 (이미 발생한 것들)

1. **commit 후 push 안 함** → GitHub Actions에 반영 안됨. 항상 push까지 완료.

2. **max_tokens 미조정** → 10섹션 보고서는 최소 12,000토큰 필요.
   프롬프트 길이 늘리면 max_tokens도 같이 늘릴 것.

3. **새 특수문자/포맷 추가 시 렌더러 누락** → `_md_to_html()`은
   명시적으로 처리하지 않는 패턴은 continuation(이어붙이기)으로 처리한다.
   새 포맷이 생기면 반드시 렌더러에 분기를 추가할 것.

4. **저장 포맷과 읽기 포맷 비대칭** → Notion API는 쓰기 시 `plain_text` 불필요,
   읽기 시 `plain_text` 자동 포함. 이 비대칭을 항상 인지할 것.

5. **섹션 경계 미등록** → `_SECTION_HEADING_VARIANTS`에 없는 헤딩은
   섹션 구분자로 인식 안 됨. 새 헤딩 추가 시 반드시 등록.

6. **Groq 413 Too Large** → 기사를 한 번에 너무 많이 보내면 발생.
   Groq 전용 입력 한도: `_GROQ_MAX_USER_CHARS = 18,000` 이미 적용됨.

---

## 운영 원칙

- 코드 수정 후 항상: `git add` → `git commit` → `git push` 순서 완료
- 확인 요청 시 코드를 먼저 읽고 의견 제시, 수행은 사용자 컨펌 후
- 여러 파일에 영향 미치는 변경은 반드시 사전에 영향 범위 설명
- 수정 후 변경 내용 요약을 항상 제공

---

## 파일별 역할 한 줄 요약

| 파일 | 역할 |
|------|------|
| `main.py` | Daily 파이프라인 진입점 |
| `streamlit_app.py` | 대시보드 UI 전체 |
| `src/collector.py` | RSS/웹 뉴스 수집 |
| `src/groq_filter.py` | Groq 고속 관련성 필터 |
| `src/gemini_researcher.py` | Gemini 심층 배경 조사 |
| `src/analyzer.py` | 10섹션 분석 프롬프트 + LLM 호출 |
| `src/llm_router.py` | 멀티 LLM 폴백 라우터 |
| `src/notion_client.py` | Notion 저장/읽기/파싱 (가장 복잡) |
| `src/email_sender.py` | Gmail 발송 |
| `src/word_exporter.py` | Word 보고서 생성 |
| `src/markdown_exporter.py` | Markdown 보고서 생성 |
| `config/feeds.yaml` | RSS 피드 URL 목록 |
