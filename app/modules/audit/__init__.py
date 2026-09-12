# No router.py: audit logs are written from inside other modules'
# request flows (log_action(), called from transfers, auth failures,
# etc.) and already exposed for reading via GET /admin/audit-logs. A
# second, duplicate endpoint here (e.g. /audit/logs) would be API
# duplication, not consistency. See PLAN.md § 10 for the full rationale
# across all modules.
