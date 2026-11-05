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

ci: check eval lint
