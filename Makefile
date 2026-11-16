export PYTHONPATH := packages

.PHONY: test doctor route run mock install cfast-api

test:
	python3 -m pytest

doctor:
	python3 -m domain_probeclaim.cli doctor

route:
	python3 -m domain_probeclaim.cli route --mode $${MODE:-auto}

run:
	python3 -m domain_probeclaim.cli run --count $${N:-2} --mode $${MODE:-direct}

mock:
	python3 -m domain_probeclaim.cli mock

cfast-api:
	TS_BIN=/home/azuramaru/tools/cfast/challenge \
	TS_PROFILE=/home/azuramaru/tools/cfast/profile_fast.json \
	TS_PORT=$${TS_PORT:-8810} \
	python3 /home/azuramaru/tools/cfast/solver_api.py

install:
	python3 -m pip install -e ".[dev]"
