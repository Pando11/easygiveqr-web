PYTHON ?= python3

.PHONY: stripe-dev-up stripe-dev-bootstrap stripe-dev-launch-checks stripe-dev-minions-dry-run stripe-dev-trigger-test-events stripe-dev-help

stripe-dev-up:
	@$(MAKE) -C maverick stripe-dev-up PYTHON=$(PYTHON)

stripe-dev-bootstrap:
	@$(MAKE) -C maverick stripe-dev-bootstrap PYTHON=$(PYTHON)

stripe-dev-launch-checks:
	@$(MAKE) -C maverick stripe-dev-launch-checks PYTHON=$(PYTHON)

stripe-dev-minions-dry-run:
	@$(MAKE) -C maverick stripe-dev-minions-dry-run PYTHON=$(PYTHON)

stripe-dev-trigger-test-events:
	@$(MAKE) -C maverick stripe-dev-trigger-test-events PYTHON=$(PYTHON)

stripe-dev-help:
	@$(MAKE) -C maverick stripe-dev-help PYTHON=$(PYTHON)
