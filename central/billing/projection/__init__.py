# Copyright (c) 2026, Frappe and contributors
# For license information, please see license.txt
"""Billing asked what it *will* do, rather than run and observed afterwards.

A **projection** is the output — what the engine says happens next. A **scenario**
is the input it was computed under. Nothing here is a *run*: that word belongs to
the monthly billing run, the job that moves money.

The engine does not model billing. It calls the same decision functions the run
calls (`rate_team_period`, `dunning_schedule`) and stops before the effects. If a
projection ever needs a function the run does not call, that function is a bug.
"""
