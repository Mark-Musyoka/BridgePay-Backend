# No models.py: transfers owns no table of its own. A transfer is two
# Account balance updates plus one Transaction row, both owned by their
# respective modules (see transfers/repository.py, which composes
# AccountRepository rather than duplicating its data). See PLAN.md § 10
# for the full rationale across all modules.
