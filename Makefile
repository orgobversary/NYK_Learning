PYTHON ?= .venv-knicks/bin/python
HF_PREVIEW ?= build/hf-fixture
PASSING_PREVIEW ?= build/passing-lab

.PHONY: test hf-fixture hf-validate hf-serve passing-lab passing-serve

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
