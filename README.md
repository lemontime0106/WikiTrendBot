# WikiTrendBot

나무위키 트렌드 키워드를 가져와 LLM으로 글을 생성하는 봇입니다.

## 실행

```bash
python -m venv .venv
make install
make run
```

## 개발 환경

- Python 3.11 이상 권장
- 의존성 설치: `pip install -r requirements.txt`

## API

- `GET /trend`: 트렌드 키워드 가져오기
- `POST /generate`: 사용자가 선택한 키워드 1개로 글 생성
  - JSON 바디 예시: `{"keyword":"손흥민"}`
- `GET /generate`: 기존 호환용 엔드포인트
  - 쿼리 `keyword`를 주면 해당 키워드 1개로 작성합니다. 예: `/generate?keyword=손흥민`

## 웹 화면

- `GET /`: 키워드 10개를 조회하고, 원하는 키워드 1개를 선택해 글을 생성하는 프론트 페이지

## LLM 설정(환경변수)

`/generate`는 아래 우선순위로 LLM을 사용합니다.

1) `langchain_openai.ChatOpenAI`가 설치되어 있으면 그걸 사용  
2) 아니면 `OPENAI_API_KEY`를 이용해 OpenAI REST 호출로 동작

필수/선택 환경변수:

- **필수**: `OPENAI_API_KEY`
- **선택**: `OPENAI_MODEL` (기본값: `gpt-4o-mini`)
- **선택**: `OPENAI_TEMPERATURE` (기본값: `0.7`)
- **선택**: `OPENAI_BASE_URL` (기본값: `https://api.openai.com/v1`)
