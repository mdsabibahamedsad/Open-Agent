# Zero Trust

Every request is evaluated in context: identity, org, resource, action,
environment, network, device, session, risk, auth strength, source,
time. Signals used: session risk (new device, failures, age, IP
policy, device trust), AAL step-up for sensitive actions, scoped
short-lived workload credentials, per-destination network policy with
SSRF floor, zone flow defaults (only listed east-west flows allowed).
Telemetry failure never blocks execution; security failures fail
closed. No per-request randomness, no excessive fingerprinting:
minimal device attributes only.
