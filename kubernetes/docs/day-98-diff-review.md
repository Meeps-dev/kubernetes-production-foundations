# Day 98 — Manifest diff review

Review `day-98-validation-inventory.json` and `day-98-manifest-diff.txt` before using `final --reviewed`.

| Resource/file | Difference actually observed | Explanation or precise corrective action | Rechecked |
|---|---|---|---|
| Fill from the actual diff, not from assumed behavior | | | |

Potential explanations to investigate, not automatic approvals:

- Migration Job removed after TTL: source remains a deploy-once artifact; do not rerun it merely to match this snapshot.
- Traefik/Metrics Server `restartedAt` from Day 97 maintenance: operational annotation, not necessarily application drift.
- Metrics Server certificate bypass: accept only as the documented local-test exception or replace with trusted certificates; do not silently erase it by applying the raw vendor file.
- HPA replica ownership: current API manifest should omit `spec.replicas`; old snapshots or day-96 patches must not become desired state.

A diff command error, unintended security weakening, unknown image, wrong selector or missing current control is not an acceptable exception. Repair the specific issue and rerun validation. No unobserved difference is marked reviewed in this template.
