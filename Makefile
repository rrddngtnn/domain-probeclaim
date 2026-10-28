export PYTHONPATH := packages

.PHONY: test doctor route run mock install

test:
	python3 -m pytest

doctor:
	python3 -m domainkit.cli doctor

route:
	python3 -m domainkit.cli route --mode $${MODE:-auto}

run:
	python3 -m domainkit.cli run --count $${N:-2} --mode $${MODE:-direct}

mock:
	python3 -m domainkit.cli mock

install:
	python3 -m pip install -e ".[dev]"
