.PHONY: install run clean help

VENV := .venv
PYTHON := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
UVICORN := $(VENV)/bin/uvicorn
PYTHON_BIN ?= python3

help:
	@echo "사용 가능한 명령:"
	@echo "  make install  - requirements.txt 설치"
	@echo "  make run      - 기존 .venv로 FastAPI 개발 서버 실행"
	@echo "  make clean    - .venv 제거"

$(PYTHON):
	$(PYTHON_BIN) -m venv $(VENV)

install: $(PYTHON)
	$(PIP) install -r requirements.txt

run: $(PYTHON)
	$(UVICORN) app.main:app --reload

clean:
	rm -rf $(VENV)
