# SCIM 2.0

`/api/v1/scim/v2/Users|Groups` (POST/GET/PATCH/PUT/DELETE) with SCIM
error bodies, filter subset (eq/ne/co/sw/ew/pr), capped pagination,
closed PATCH vocabulary (role/permission attributes rejected with
403), privilege-bearing user attributes rejected, deactivation
preserves history. Auth: dedicated per-org bearer credentials with
prefix/expiry/revocation/last-used (never Master passwords). Strict
per-operation rate buckets stop sync storms. Groups map to teams/
roles through the safe mapping layer.
