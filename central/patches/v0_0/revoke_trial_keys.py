from central.services.doctype.ai_trial_key.ai_trial_key import AITrialKey


def execute() -> None:
	"""Revoke every trial key Central still holds live — the pool's Available keys and the
	Assigned ones on running trials — the way an expiry does: marked Revoking here, Grove told
	after the commit, retried by the scheduler if refused. A converted key is the team's now and
	stays; the refill job mints the pools fresh."""
	AITrialKey.queue_revoke()
