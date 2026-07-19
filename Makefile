.PHONY: install run test clean help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTHON_BIN ?= python3

help:
	@echo "사용 가능한 명령:"
	@echo "  make install  - requirements.txt 설치"
	@echo "  make run      - 기존 .venv로 FastAPI 개발 서버 실행"
	@echo "  make test     - 외부 API 호출 없는 단위 테스트 실행"
	@echo "  make clean    - .venv 제거"

$(PYTHON):
	$(PYTHON_BIN) -m venv $(VENV)

install: $(PYTHON)
	$(PIP) install -r requirements.txt

run: $(PYTHON)
	$(UVICORN) app.main:app --reload

test: $(PYTHON)
	$(PYTHON) -m unittest discover -s tests -v

clean:
	rm -rf $(VENV)
