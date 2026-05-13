"""Anomaly → notification pipeline.

Reads `analytics_marts.mart_recovery_state` after each weekly_load run,
evaluates user-configurable rules against the trailing window, and fires
notifications (stdout + optional Pushover) on red transitions or
consecutive-strained-day streaks. Dedup is enforced by the
`(rule_name, day)` primary key on `raw.notification_log` — re-running
the flow on the same day fires zero new notifications.

Public surface:

    from ingest.notifications.notify import notify_on_state_change, NotifyResult
"""
