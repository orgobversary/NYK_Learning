PYTHON ?= .venv-knicks/bin/python
HF_PREVIEW ?= build/hf-fixture
PASSING_PREVIEW ?= build/passing-lab
RESEARCH_RELEASE ?= build/research-staging
RESEARCH_BUCKET ?= obversarystudios/nyk-world-research
PUBLIC_FIXTURE ?= build/public-fixture

.PHONY: test hf-fixture hf-validate hf-serve passing-lab passing-serve research-sync-dry-run public-fixture public-validate

test:
	$(PYTHON) -m unittest discover -s tests -v

hf-fixture:
	$(PYTHON) scripts/build_hf_fixture_preview.py --output $(HF_PREVIEW)

hf-validate:
	$(PYTHON) scripts/validate_hf_release.py $(HF_PREVIEW)

hf-serve:
	$(PYTHON) -m http.server 8000 --bind 127.0.0.1 --directory $(HF_PREVIEW)/space

passing-lab:
	$(PYTHON) scripts/build_passing_lab.py --output $(PASSING_PREVIEW)

passing-serve:
	$(PYTHON) -m http.server 8001 --bind 127.0.0.1 --directory $(PASSING_PREVIEW)

research-sync-dry-run:
	$(PYTHON) scripts/sync_research_bucket.py --release $(RESEARCH_RELEASE) --bucket $(RESEARCH_BUCKET)

public-fixture:
	$(PYTHON) scripts/build_public_checkpoint.py \
		--output $(PUBLIC_FIXTURE)/analytics --start 2024 --end 2024 \
		--terms-reviewed-at 2026-11-22 --terms-basis 'offline invented fixture' \
		--fixture fixtures/balldontlie-games-demo.json --no-models

public-validate:
	$(PYTHON) scripts/validate_public_checkpoint.py $(PUBLIC_FIXTURE) --allow-synthetic-fixture
