PYTHON ?= python3

.PHONY: stripe-dev-up stripe-dev-bootstrap stripe-dev-launch-checks stripe-dev-minions-dry-run stripe-dev-trigger-test-events stripe-dev-help

stripe-dev-up: stripe-dev-bootstrap stripe-dev-launch-checks stripe-dev-minions-dry-run
	@echo ""
	@echo "stripe-dev-up complete."
	@echo "Optional next steps:"
	@echo "  stripe listen --forward-to http://localhost:5000/stripe/webhook"
	@echo "  make stripe-dev-trigger-test-events"

stripe-dev-bootstrap:
	@cd . && \
	if [ ! -f ".env" ]; then \
		cp ".env.example" ".env"; \
		echo "Created .env from .env.example. Fill Stripe keys and rerun."; \
	fi && \
	$(PYTHON) stripe_dev_bootstrap.py --check-api

stripe-dev-launch-checks:
	@$(PYTHON) run_launch_checks.py

stripe-dev-minions-dry-run:
	@$(PYTHON) run_stripe_minions.py --all --dry-run

stripe-dev-trigger-test-events:
	@stripe trigger payment_intent.succeeded
	@stripe trigger payment_intent.payment_failed

stripe-dev-help:
	@echo "Available targets:"
	@echo "  make stripe-dev-up                  # one-shot Stripe.dev bootstrap/checks/minions"
	@echo "  make stripe-dev-bootstrap           # env + Stripe key validation"
	@echo "  make stripe-dev-launch-checks       # full launch smoke checks"
	@echo "  make stripe-dev-minions-dry-run     # run all Stripe minions dry-run"
	@echo "  make stripe-dev-trigger-test-events # trigger Stripe test events"
