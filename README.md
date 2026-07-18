# WikiTrendBot

나무위키 트렌드 키워드를 가져와 LLM으로 글을 생성하는 봇입니다.

## 실행

```bash
make run
```

`make run`은 `.venv`의 Python/uvicorn으로 개발 서버를 실행합니다.

## 개발 환경

- Python 3.11 이상 권장
- 의존성 설치: `make install`

## API

- `GET /trend`: 트렌드 키워드 가져오기
- `POST /generate`: 사용자가 선택한 키워드 1개로 글 생성
  - JSON 바디 예시: `{"keyword":"손흥민"}`
- `GET /generate`: 기존 호환용 엔드포인트
  - 쿼리 `keyword`를 주면 해당 키워드 1개로 작성합니다. 예: `/generate?keyword=손흥민`
- `POST /publish`: 생성한 글과 이미지 파일을 받아 티스토리에 Playwright로 업로드

## 웹 화면

- `GET /`: 키워드 10개를 조회하고, 원하는 키워드 1개를 선택해 글 생성 후 티스토리 업로드까지 진행하는 프론트 페이지

## LLM 설정(환경변수)

`/generate`는 아래 우선순위로 LLM을 사용합니다.

1) `langchain_openai.ChatOpenAI`가 설치되어 있으면 그걸 사용  
2) 아니면 `OPENAI_API_KEY`를 이용해 OpenAI REST 호출로 동작

필수/선택 환경변수:

- **필수**: `OPENAI_API_KEY`
- **선택**: `OPENAI_MODEL` (기본값: `gpt-4o-mini`)
- **선택**: `OPENAI_TEMPERATURE` (기본값: `0.7`)
- **선택**: `OPENAI_BASE_URL` (기본값: `https://api.openai.com/v1`)

## 티스토리 업로드 설정

- 브라우저 자동화는 기본적으로 `headless=False`로 실행되어 로그인 과정을 눈으로 확인할 수 있습니다.
- 첫 업로드 시 티스토리 로그인 화면이 뜨면 직접 로그인하면 되고, 로그인 상태는 `.tistory-auth.json`에 저장됩니다.
- `TISTORY_LOGIN_ID`, `TISTORY_LOGIN_PASSWORD`를 넣어두면 일반 로그인 폼이 보일 때 자동 입력을 먼저 시도합니다.
- 다만 카카오 추가 인증, 캡차, 보안 확인 화면이 뜨면 완전 자동 로그인 대신 수동 확인이 필요할 수 있습니다.
- 기본값은 최종 발행 버튼을 자동으로 누르지 않는 assisted 모드입니다. 제목, 본문, 이미지, 태그 입력과 검증이 끝나면 브라우저에서 직접 최종 발행을 확인합니다.

선택 환경변수:

- `TISTORY_BLOG_URL` (업로드 대상 블로그 기본 주소, 예: `https://내블로그.tistory.com`)
- `TISTORY_LOGIN_ID` (선택, 자동 로그인용 아이디/이메일)
- `TISTORY_LOGIN_PASSWORD` (선택, 자동 로그인용 비밀번호)
- `TISTORY_STORAGE_STATE_PATH` (기본값: `.tistory-auth.json`)
- `TISTORY_HEADLESS` (기본값: `false`)
- `TISTORY_KEEP_BROWSER_OPEN` (기본값: `false`)
- `TISTORY_AUTO_FINAL_PUBLISH` (기본값: `false`, `true`면 검증 후 최종 발행 버튼까지 자동 클릭)
- `TISTORY_MANUAL_PUBLISH_TIMEOUT_SECONDS` (기본값: `1800`, assisted 모드에서 수동 발행 완료를 기다리는 시간)

`TISTORY_BLOG_URL`에는 블로그의 기본 홈 주소를 넣어야 합니다.

- 올바른 예: `https://내블로그.tistory.com`
- 올바른 예: `myblog.tistory.com`
- 넣지 말아야 할 값: `https://www.tistory.com`
- 넣지 말아야 할 값: `https://내블로그.tistory.com/manage`
- 넣지 말아야 할 값: 개별 글 URL

이 값이 기준이 되어 내부에서 `/manage/post` 또는 `/manage/newpost`로 붙어서 글쓰기 화면으로 이동합니다.
