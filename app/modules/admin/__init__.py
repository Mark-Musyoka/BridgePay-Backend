# No models.py: admin owns no table of its own. It's a read-only
# reporting layer over other modules' data (see admin/repository.py,
# which composes accounts/users/transactions/audit repositories rather
# than duplicating their data). See PLAN.md § 10 for the full rationale
# across all modules.
