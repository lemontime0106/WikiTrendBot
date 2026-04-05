.PHONY: install run

PYTHON := .venv/bin/python
PIP := .venv/bin/pip

install:
	@if [ ! -x "$(PIP)" ]; then \
		echo ".venv 가 없어서 시스템 pip 로 설치합니다."; \
		pip install -r requirements.txt; \
	else \
		$(PIP) install -r requirements.txt; \
	fi

run:
	@if [ ! -x "$(PYTHON)" ]; then \
		echo ".venv/bin/python 을 찾지 못했습니다. 가상환경이 없다면 먼저 생성해 주세요."; \
		echo "예시: python -m venv .venv && make install"; \
		exit 1; \
	fi
	$(PYTHON) -m uvicorn app.main:app --reload
