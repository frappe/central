# CERT-In reporting

## Purpose

This document is how Central reports cyber security incidents to CERT-In, the Indian Computer Emergency Response Team. It is part of [Abuse protection](ABUSE.md).

Status: planned. Central does not implement this yet. First, responders follow this process by hand with the Abuse Case and plain email. Later, Central automates the clocks, the alerts, and "Build report".

## Rules

From the CERT-In Directions of 28 April 2022 and the FAQs of May 2022:

- Report a severe incident within 6 h of noticing it (FAQ Q30). Severe incidents are DoS, DDoS, intrusion, malware, data breaches and leaks, large-scale or frequent incidents, and incidents that affect human safety.
- Report other Annexure I types as early as possible (Q10). A partial first report is acceptable.
- The entity that notices an incident must report it. The duty cannot be transferred (Q13). It overrides contract confidentiality (Q22).
- The FAQs do not define "noticing" (Q24).
- Name a point of contact (Q29) and register it with CERT-In by email.
- Keep logs for 180 days. Storage outside India is allowed if the logs can be produced (Q35).
- Sync clocks to NIC or NPL, or to sources traceable to them (Direction (i)).
- CERT-In publishes its incident contacts on its [contact page](https://www.cert-in.org.in/s2cMainServlet?pageid=CONTACTUS): email incident@cert-in.org.in, phone +91-11-22902657. Central reads the report address from `cert_in_incident_email`.

## Tiers

| Tier | What | Deadline |
|---|---|---|
| R1 | Our systems (Metal, proxy, IPv6 router, Atlas, Central, Cargo, Datum), customer data leaks from them, and DDoS that degrades service | 6 h from confirmation |
| R2 | Confirmed severe incidents from or on tenant resources: outbound DoS, a VM that spreads malware or is used for intrusion, large phishing, one attack from many tenants | 6 h from confirmation |
| R3 | Other confirmed Annexure I incidents on tenant resources: one scan, brute force, a miner on a compromised VM, a defacement | Same business day |
| None | AUP violations that are not cyber incidents: owner mining, spam only, blocked inbound attacks with no impact, unconfirmed signals | No report. Record the reason. |

## Clock

The clock starts when an operator confirms the case, not at the first signal. To confirm, the operator checks the signal and the attribution. Signals can be false or spoofed.

- The case keeps `first_signal_at` and `confirmed_at`.
- The 1 h SLA for Critical cases keeps the gap small.
- A case that is not confirmed within its SLA alerts `#abuse-p1`.

This reading of Q24 needs a legal check before Central automates the clock.

## Workflow

- The case holds the tier, the Annexure I category, the decision reason, the due time, the report time, and the sent reports. The decision reason is required for tier None. Layout: [Abuse layouts](ABUSE_LAYOUTS.md#abuse-case).
- The policy engine proposes a tier from the finding code. The operator confirms it.
- "Build report" fills the CERT-In Incident Reporting Form: reporter (our point of contact), affected entity, type, occurrence and detection times, IPs, region, description, and actions.
- The operator checks the report and sends it from `abuse_email` to `cert_in_incident_email`. Central keeps the sent copy on the case.
- About a tenant, Central sends only IPs, times, type, and actions. Central sends more only on request from an officer of Deputy Secretary rank or above (Q38).
- R2 and R3 customer notices say: "If you operate in India, you may have your own duty to report this to CERT-In."
- Clock alerts: email to `abuse_email` at 4 h and 2 h left. A `#abuse-p1` page at 2 h left.

"Build report" refuses until all the `cert_in_contact_*` fields in Central Settings are set. See [Settings](ABUSE.md#settings).

## Compliance gaps

| Gap | Fix |
|---|---|
| Point of contact | Not named yet. Name it, register it with CERT-In, and fill the `cert_in_contact_*` fields. |
| Time source | Hosts and service VMs do not use NIC or NPL time servers. Point chrony at `samay1.nic.in`, `samay2.nic.in`, and `time.nplindia.org` after a check of the hostnames. This is Atlas work. |
| Logs | There is no NAT log, and proxy access logs rotate within hours on each node. [Cargo abuse logs](https://github.com/frappe/cargo/blob/develop/docs/abuse-logs.md) and [Public IP history](ABUSE.md#public-ip-history) fix this. |

## Sources

- CERT-In Directions, 28 April 2022: https://www.cert-in.org.in/PDF/CERT-In_Directions_70B_28.04.2022.pdf
- CERT-In FAQs, May 2022: https://www.cert-in.org.in/PDF/FAQs_on_CyberSecurityDirections_May2022.pdf
- CERT-In incident form: https://cert-in.org.in/PDF/certinirform.pdf
- CERT-In contact page: https://www.cert-in.org.in/s2cMainServlet?pageid=CONTACTUS
