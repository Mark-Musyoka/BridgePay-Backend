# No models.py or repository.py: webhooks owns no state of its own. It
# verifies signatures and dispatches events to the modules that do own
# the affected data (deposits, payouts — see webhooks/service.py). See
# PLAN.md § 10 for the full rationale across all modules.
