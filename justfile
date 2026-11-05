# One runner. Agents and CI call `just`, not a pile of tool scripts.

# engine contract over jobs/
check:
	python3 scripts/check.py

# contract eval: fixtures that must pass or fail
eval:
	python3 scripts/check.py --fixtures evals/contract

# engine docs stay subject-free
lint:
	python3 scripts/lint_docs.py

# engine tests, including one local end-to-end render (needs ffmpeg)
test:
	python3 -m pytest -q

ci: check eval lint test
