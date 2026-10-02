# Sandbox — Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `POLICY_DENIED` on execute | command not in profile allowlist / shell operators | use argv form, permitted binary, or higher profile |
| `sandbox.network.denied` | non-NONE network without `SANDBOX_EGRESS_PROXY` | set proxy or use NO_NETWORK profile |
| `WAITING_FOR_APPROVAL` | HIGH/CRITICAL risk, `approved` not set | re-execute with `approved: true` (MP19 UX later) |
| `TIMED_OUT` / `RESOURCE_LIMIT` | caps exceeded, OOM | raise profile/timeout within server caps; check `peak_memory_mb` |
| `Sandbox is …; start it` | lifecycle: execute needs READY | `POST …/start` first |
| `Quota exceeded` | org concurrency/sandbox caps | stop/destroy idle sandboxes; tune quotas |
| `Image … requires digest` | production pinning | set `SANDBOX_IMAGE_DIGEST` / per-request digest |
| `UNTRUSTED images …` | tier gate | use CORE/VERIFIED/ORGANIZATION or LEVEL_4 policy |
| `Local execution fallback not permitted` | prod or flag off | use `docker` provider |
| `Leased by another owner` | sharing without lease | `acquire_lease` with the coordinating owner |
| `Credential … not found/authorized` | no resolver or bad ref | wire resolver; verify ref + org scope |
| `Workspace mount escapes root` | path outside tenant root | pass the server-side workspace path |
| Empty artifacts | path outside mount / over size / secret-hit | check roots, `max_artifacts_mb`, scan |
| `docker create failed` | daemon down / image missing / egress net missing | check daemon, pull pinned image, create `sandbox-egress` net if filtered modes used |
| Cancelled run stuck RUNNING | worker lost | `cancel` restarts provider hygiene; sweep reaps |

## Debugging checklist

1. `GET /sandboxes/{id}` — status, profile, image pin.
2. `GET /sandboxes/{id}/executions` — normalized results + risk.
3. `GET /sandboxes/{id}/events` — requested/allowed/denied/completed + reasons.
4. `GET /sandboxes/security/check` — deployment posture.
5. Audit rows (`sandbox.*`) for actor + tenant trail.
