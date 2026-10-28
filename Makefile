PYTHON ?= python3
REF ?= HEAD
PROFILE ?= atomic-rev9
OUTPUT ?= release
ARDUINO_CLI ?= arduino-cli

.PHONY: release verify

# Current firmware is rebuilt; the historical profile preserves its original HEX.
release:
	$(PYTHON) tools/release.py create --ref "$(REF)" --profile "$(PROFILE)" \
		--output "$(OUTPUT)" $(if $(filter atomic-rev9,$(PROFILE)),--rebuild) \
		--arduino-cli "$(ARDUINO_CLI)"

verify:
	$(if $(strip $(RELEASE)),,$(error Usage: make verify RELEASE=release/<bundle>))
	$(PYTHON) tools/release.py verify "$(RELEASE)"
