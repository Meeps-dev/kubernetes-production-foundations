# Day 98 — File guide and validation contract

The package supplies instructions and helpers, not prewritten test successes. Use Python 3.9+ with PyYAML 6.0.3 in the ignored repository-local environment. Kubernetes operations always specify the dedicated kubeconfig/context. Run from the repository root.

## Files

- `scripts/day98-lab.py`: isolated fault, validation, index-audit, verification and explicit teardown checkpoints.
- `scripts/test_day98.py`: offline guardrail tests; no Docker or cluster mutations.
- `README.week14.draft.md`: complete proposed README; review/merge into the real README, do not discard existing useful content blindly.
- `docs/architecture-week14.md`: topology, traffic, persistence and controller boundaries.
- `docs/kubectl-commands-week14.md`: consolidated operations reference.
- `docs/security-cost-week14.md`: implemented controls, test-only exceptions and production gaps.
- `docs/teardown-week14.md`: data-loss warning, optional private export, explicit deletion and image cleanup.

The helper generates `day-98-troubleshooting.md` only after all four drills have passing recovery results. Each investigation includes the initial symptom, first diagnostic command, relevant event/log, root cause, correct fix and preventive control.

## Prerequisite

Finish Day 97 and run its `final` checkpoint. The last chat diagnosis (four healthy replicas but an unmet two-replica handoff condition) is not proof of completed HPA or node-drain work. Day 98 requires the Day 97 final result plus fresh HPA/PDB/database/routing checks.

## Checkpoint order

```bash
python3 kubernetes/scripts/test_day98.py
python3 kubernetes/scripts/day98-lab.py preflight
python3 kubernetes/scripts/day98-lab.py setup
python3 kubernetes/scripts/day98-lab.py fault readiness
python3 kubernetes/scripts/day98-lab.py fault secret-key
python3 kubernetes/scripts/day98-lab.py fault crash
python3 kubernetes/scripts/day98-lab.py fault selector
python3 kubernetes/scripts/day98-lab.py remove-canary
python3 kubernetes/scripts/day98-lab.py validate
# Review the inventory/diff and reconcile or document expected differences.
python3 kubernetes/scripts/day98-lab.py final --reviewed
# Finish docs, stage, audit the index, inspect screenshots, commit and push.
# Teardown is a separate explicit command described in teardown-week14.md.
```

All records are flat `kubernetes/docs/day-98-*` files. An incomplete transcript stays `.tmp`. Do not rename it into a successful report. A failed rerun of a fault removes that fault's previous PASS marker. Interrupted jobs never fabricate verification success.

## Fault boundary

The canary is `meeps-day98-canary`, with a distinct application label, one replica, Recreate strategy and a separate ClusterIP Service. It inherits the API image, read-only runtime configuration and container hardening, but not the real API's topology selector. The main Ingress, HPA, Service and PDB do not select it. It mounts no PVC, executes no migrations, alters no passwords and creates no application records. Existing runtime Secret references are reused, not decoded or rewritten.

Faults are applied one at a time, observed, and repaired in a finally block. Normal API access and original records are checked around the failure. This is evidence at those checkpoints, not continuous uptime monitoring.

A killed terminal, unavailable cluster API or hard process kill can prevent automatic recovery. Use `python3 kubernetes/scripts/day98-lab.py recover` to restore the canary, then rerun the incomplete fault. `remove-canary` deletes only its labeled Deployment and Service. Never delete PostgreSQL or its PVC to fix a drill.

## What 'validate every manifest' means here

The helper inventories YAML/JSON under `kubernetes/`, rejects duplicate YAML keys, and reports the scope for each file:

| Category | Checks | Not done |
|---|---|---|
| Canonical full resources under base/ or cluster/ | Syntax, relevant image/security policy, server-side dry run, kubectl diff | No actual apply or forced conflict resolution |
| Existing historical/API/metrics patches | Syntax, rendering against their known target, server-side dry run of the result | Not applied to the live cluster or used as current desired state |
| Secret examples | Syntax and placeholder-only checks | No live write, no value diff |
| Optional Gateway example | Syntax | No CRDs installed, no live Gateway validation claimed |
| kind config | Syntax and this lab's node/port invariants | Not submitted to the Kubernetes API, no cluster creation |
| Saved docs/captures/snapshots | Syntax when YAML/JSON | Never replayed as desired state |
| Other full exercise examples | Server dry run | Never used to change the running service |

Unknown patch targets or malformed objects stop validation for explicit classification. Server dry runs validate API admission/schema, not successful scheduling, image pulling, credentials or application behavior. Secret references can be admitted even when a key is missing; that is why a runtime drill is separate.

## Reading diffs correctly

`kubectl diff`: 0 means no differences; 1 means differences; greater than 1 means a command failure. Each source resource's difference is recorded under `day-98-manifest-diff.txt` and inventory JSON. No automatic remediation is performed.

Possible expected differences include a TTL-removed one-off migration Job, Day 97 controller restart annotations, and the local Metrics Server certificate patch. Do not erase an intentional local patch or rerun migrations to force a zero diff. For intended configuration drift, update/apply only the exact reviewed healthy manifest, then rerun validation. Record accepted exceptions in `day-98-diff-review.md`; `final --reviewed` is an explicit review attestation, not an automated judgment that every difference is harmless.

## Secret review limits

`git-audit` checks actual index bytes (including staged changes), private paths, non-placeholder Secret objects, exact known local credentials and basic private-key markers. It reports paths without printing values. It cannot certify all repository history, unknown credentials or screenshots. Review all staged content and images manually. If a credential was actually disclosed, retire it in the real system; deleting a file is insufficient.

## No changes made by preparing the package

The package can be syntax-checked and unit-tested offline. Live admission, network behavior, scheduling, fault recovery and data preservation must pass on the user's machine. Teardown deliberately requires separate confirmation and a clean committed working tree after proof is saved.
