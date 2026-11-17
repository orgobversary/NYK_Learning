PYTHON ?= .venv-knicks/bin/python
HF_PREVIEW ?= build/hf-fixture
PASSING_PREVIEW ?= build/passing-lab
RESEARCH_RELEASE ?= build/research-staging
RESEARCH_BUCKET ?= obversarystudios/nyk-world-research

.PHONY: test hf-fixture hf-validate hf-serve passing-lab passing-serve research-sync-dry-run

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
