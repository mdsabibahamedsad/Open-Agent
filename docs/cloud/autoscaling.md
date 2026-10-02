# Autoscaling

Inputs: queue depth/age, worker utilization, CPU/memory, execution
latency, concurrency, plan limits, region capacity. Output: desired
worker count (`decide_autoscale`). Safety rails: min/max workers,
cooldown, scale-up/down steps, tenant quotas, regional + global caps,
cost protection, runaway protection. A single malicious workflow can
never trigger unlimited infrastructure creation — ceilings clamp first,
pressure is evaluated second.
