# WikiTrendBot

AI·IT 분야의 근거 기반 티스토리 글을 조사·작성·검수하고, 품질 기준을 통과한 본문만 업로드하는 FastAPI 도구입니다.

이 프로젝트의 품질 검사는 애드센스 승인을 보장하지 않습니다. 다만 출처 없는 요약, 주제 혼재, 허위 실사용 표현, 기존 글과의 중복, 고정 템플릿 반복처럼 “가치가 낮은 콘텐츠”로 보일 가능성이 큰 결과를 발행 전에 차단합니다.

## 품질 파이프라인

1. 네이버 검색 결과와 사용자가 넣은 공식 URL을 수집합니다.
2. 공개 웹 출처의 본문을 실제로 읽어 근거 자료를 만듭니다.
3. 사이트 핵심 분야, 위험도, 직접 경험 필요 여부를 먼저 판정합니다.
4. 근거가 있는 주장과 독자 결과를 포함한 기획안을 구조화해 만듭니다.
5. 출처 링크와 참고자료가 포함된 2,200~4,000자 수준의 글을 작성합니다.
6. 별도 편집 검수 모델과 규칙 기반 검사로 사실 근거·독창성·구체성·중복을 평가합니다.
7. 실패 시 한 번 자동 수정하고 다시 검사합니다.
8. 통과한 본문과 글자 하나까지 같은 본문만 티스토리 업로드를 허용합니다. 수정하면 재검사가 필요합니다.

기본 사이트 분야는 `AI 도구 실험, 업무 자동화, 1인 개발·SaaS, AI 산업·정책`입니다. 일반 연예·스포츠·맛집 트렌드는 기본적으로 생성 단계에서 거절됩니다.

## 실행

Python 3.11 이상을 권장합니다.

```bash
make install
cp .env.example .env
# .env에 OPENAI_API_KEY와 TISTORY_BLOG_URL 입력
make run
```

브라우저에서 `http://127.0.0.1:8000`을 엽니다.

테스트:

```bash
make test
```

테스트는 OpenAI API나 실제 티스토리에 요청하지 않습니다.

## 좋은 입력을 주는 방법

- 웹 화면에서는 구체적인 키워드만 입력합니다.
- 시스템이 검색 의도, 주요 독자, 글을 읽고 완료할 판단이나 작업을 자동으로 기획합니다.
- 공식 발표, 공식 문서, 일반 검색 결과와 보도자료도 자동으로 수집합니다.
- 실제 사용이나 측정이 필요한 리뷰·후기 주제는 자동 작성하지 않고 다른 정보형 키워드를 선택하도록 안내합니다.

검색 결과만으로 근거가 부족하면 억지로 글을 만들지 않고 422 오류와 보완 사유를 반환합니다.

API의 `user_purpose`, `firsthand_notes`, `source_urls`는 외부 자동화 연동이나 운영자가 실제 검증 자료를 보유한 경우에만 사용하는 선택 필드입니다. AI가 실제로 하지 않은 경험을 `firsthand_notes`에 생성해서는 안 됩니다.

## API

- `GET /trend`: 트렌드 키워드 조회
- `POST /generate`: 조사, 기획, 작성, 자동 검수
- `POST /quality-check`: 사용자가 수정한 본문 재검사
- `POST /publish`: 승인된 본문을 티스토리 편집기에 입력
- `GET /generate`: 이전 호출 방식과의 호환용. 추가 출처와 경험 메모를 넣을 수 없으므로 `POST /generate` 사용을 권장합니다.

`POST /generate` 예시:

```json
{
  "keyword": "OpenAI API 비용 최적화"
}
```

응답의 `quality_report.passed`가 `true`여야 업로드할 수 있습니다. `blocking_reasons`와 각 `checks`에서 수정할 항목을 확인할 수 있습니다.

## LLM 설정

기본 작성·검수 모델은 `gpt-5.4-mini`입니다. 비용이나 계정 지원 모델에 맞춰 각각 바꿀 수 있습니다.

- `OPENAI_API_KEY`: 필수
- `OPENAI_MODEL`: 작성·검수 공통 모델
- `OPENAI_WRITER_MODEL`: 작성 모델. 설정하면 `OPENAI_MODEL`보다 우선
- `OPENAI_REVIEW_MODEL`: 기획·검수 모델. 설정하면 작성 모델과 분리
- `OPENAI_REASONING_EFFORT`: 선택
- `OPENAI_TEMPERATURE`: 선택. GPT-5·o-series는 미설정 시 요청에서 제외
- `OPENAI_BASE_URL`: 기본값 `https://api.openai.com/v1`

LangChain의 구조화 출력을 우선 사용하고, 지원하지 않는 호환 API에서는 JSON 스키마 프롬프트 방식으로 대체합니다.

## 콘텐츠 품질 설정

- `CONTENT_SITE_FOCUS`: 블로그가 집중할 주제
- `CONTENT_MIN_RESEARCH_SOURCES`: 생성 전 실제로 읽을 수 있어야 하는 자료 수, 기본 3
- `CONTENT_MIN_SOURCE_LINKS`: 완성 글에 포함될 출처 링크 수, 기본 3
- `CONTENT_MIN_SOURCE_DOMAINS`: 출처 도메인 수, 기본 2
- `CONTENT_MIN_ARTICLE_CHARS`: 최소 본문 글자 수, 기본 1800
- `CONTENT_MIN_EDITORIAL_SCORE`: 발행 최소 점수, 기본 80
- `CONTENT_DUPLICATE_THRESHOLD`: RSS 기존 글과의 중복 차단 기준, 기본 0.72
- `CONTENT_MAX_REVISION_ROUNDS`: 자동 수정 횟수, 기본 1, 최대 2
- `CONTENT_ALLOW_HIGH_RISK_TOPICS`: 금융·의료·법률 조언 차단 해제. 기본 false이며 운영상 해제를 권장하지 않음

규칙 기반 검사는 H1 1개, H2 3개 이상, 참고자료 구역, 출처 수, 조사 목록 밖 URL, 직접 경험 근거, 양산형 고정 문구, 고위험 주제, 기존 글 중복, 이미지 슬롯 수를 검사합니다.

## 티스토리 업로드

- 첫 업로드에서 로그인하면 세션을 `.tistory-auth.json`에 저장합니다.
- 카카오 추가 인증, 캡차, 보안 확인은 수동 처리가 필요할 수 있습니다.
- 기본값은 최종 발행 버튼을 자동으로 누르지 않는 assisted 모드입니다.
- 서버를 재시작하면 메모리에 있던 품질 승인이 사라지므로 본문을 다시 검사해야 합니다.

설정:

- `TISTORY_BLOG_URL`: 블로그 홈 주소, 예: `https://내블로그.tistory.com`
- `TISTORY_LOGIN_ID`, `TISTORY_LOGIN_PASSWORD`: 선택
- `TISTORY_STORAGE_STATE_PATH`: 기본 `.tistory-auth.json`
- `TISTORY_HEADLESS`: 기본 `false`
- `TISTORY_KEEP_BROWSER_OPEN`: 기본 `false`
- `TISTORY_AUTO_FINAL_PUBLISH`: 기본 `false`
- `TISTORY_MANUAL_PUBLISH_TIMEOUT_SECONDS`: 기본 `1800`

`TISTORY_BLOG_URL`에는 `/manage`나 개별 글 주소가 아닌 블로그 홈 주소를 넣습니다.

## 운영 체크

자동 검사를 통과해도 다음은 사람이 최종 확인해야 합니다.

- 링크 원문이 실제 주장과 일치하는가
- 날짜, 가격, 버전, 수치가 게시 시점에도 유효한가
- 직접 하지 않은 일을 경험한 것처럼 쓰지 않았는가
- 독자가 실행할 수 있는 구체적인 기준이나 결과가 있는가
- 이미지가 장식이 아니라 설명에 필요한 캡처·도표인가

사이트 자체의 소개, 문의, 개인정보처리방침, 카테고리 정리와 기존 저품질 글 수정은 별도 운영 작업입니다. 자세한 항목은 [TISTORY_ADSENSE_ACTION_PLAN.md](TISTORY_ADSENSE_ACTION_PLAN.md)를 참고하세요.
