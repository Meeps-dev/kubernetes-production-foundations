#!/usr/bin/env python3
"""Day 96 rollout lab. Python 3.9+ standard library only; run from the repo root.

Subcommands are separate checkpoints. Only update, fail, and rollback mutate
cluster resources, and only the meeps-api Deployment is mutated. The fail step
leaves its deliberate failure in place for inspection. No secrets are read,
users/posts created, migrations run, or storage objects deleted.
"""
import argparse
import copy
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import threading
import time

DOCS = Path("kubernetes/docs")
MANIFEST = Path("kubernetes/base/api-deployment.yaml")
VERIFY = Path("kubernetes/scripts/day96-verify.py")
FIXTURE = DOCS / "day-94-fixture.json"
SELECTOR = "app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev"
OLD_IMAGE = "meeps-users-posts-api:k8s-v2"
IMAGE = "meeps-users-posts-api:week14-v2"
VERSION = "week14-v2"
KUBE = ["kubectl", "--kubeconfig", str(Path.home() / ".kube/meeps-k8s-cluster.yaml"),
        "--context", "kind-meeps-k8s-cluster"]


class LabError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise LabError(message)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def path(name):
    return DOCS / ("day-96-" + name)


def save_json(name, value):
    destination = path(name)
    temporary = Path(str(destination) + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(destination)


def read_json(name):
    return json.loads(path(name).read_text())


def run(command, data=None, check=True, timeout=60):
    result = subprocess.run(command, input=data, text=True, capture_output=True,
                            timeout=timeout)
    if check and result.returncode:
        raise LabError("Command failed: {0}\n{1}\n{2}".format(
            " ".join(command[:12]), result.stdout, result.stderr))
    return result


def k(*arguments, ns="meeps-dev", data=None, check=True, timeout=60):
    return run(KUBE + ["-n", ns] + list(arguments), data, check, timeout)


def get(resource, name=None, selector=None, ns="meeps-dev"):
    arguments = ["get", resource]
    if name:
        arguments.append(name)
    if selector:
        arguments.extend(["-l", selector])
    arguments.extend(["-o", "json", "--request-timeout=20s"])
    return json.loads(k(*arguments, ns=ns).stdout)


def api_container(deployment):
    matches = [c for c in deployment["spec"]["template"]["spec"]["containers"]
               if c["name"] == "api"]
    require(len(matches) == 1, "Expected one container named api")
    return matches[0]


def revision(deployment):
    value = deployment["metadata"].get("annotations", {}).get(
        "deployment.kubernetes.io/revision", "")
    require(value.isdigit(), "Deployment revision is not available yet")
    return int(value)


def template(deployment):
    value = copy.deepcopy(deployment["spec"]["template"])
    value.get("metadata", {}).get("labels", {}).pop("pod-template-hash", None)
    value.get("metadata", {}).pop("creationTimestamp", None)
    return value


def state(deployment):
    return {"revision": revision(deployment), "image": api_container(deployment)["image"],
            "template": template(deployment), "captured_at": now()}


def guard_security_and_probes(deployment):
    pod = deployment["spec"]["template"]["spec"]
    container = api_container(deployment)
    for probe, expected in (("startupProbe", "/health"),
                            ("livenessProbe", "/health"), ("readinessProbe", "/ready")):
        require(container.get(probe, {}).get("httpGet", {}).get("path") == expected,
                "Wrong or missing " + probe + "; complete Day 95 first")
    context = pod.get("securityContext", {})
    require(context.get("runAsUser") == 10001 and context.get("runAsGroup") == 10001,
            "Unexpected API UID/GID")
    require(context.get("runAsNonRoot") is True, "runAsNonRoot is not enabled")
    require(context.get("seccompProfile", {}).get("type") == "RuntimeDefault",
            "Expected RuntimeDefault seccomp")
    require(pod.get("automountServiceAccountToken") is False,
            "API ServiceAccount token mounting must stay disabled")
    security = container.get("securityContext", {})
    require(security.get("allowPrivilegeEscalation") is False,
            "Privilege escalation is not disabled")
    require(security.get("readOnlyRootFilesystem") is True, "Root filesystem is not read-only")
    require("ALL" in security.get("capabilities", {}).get("drop", []), "Capabilities not dropped")
    credentials = [e for e in container.get("env", []) if e["name"] == "DATABASE_URL"]
    require(len(credentials) == 1 and "secretKeyRef" in credentials[0].get("valueFrom", {}),
            "DATABASE_URL must remain a Secret reference, not a literal credential")
    for kind in ("requests", "limits"):
        require(all(container.get("resources", {}).get(kind, {}).get(r) for r in ("cpu", "memory")),
                "CPU and memory " + kind + " are required")


def healthy(expected_image, rollout_settings=False):
    deployment = get("deployment", "meeps-api")
    spec, status = deployment["spec"], deployment.get("status", {})
    require(not spec.get("paused", False), "Deployment is paused")
    require(spec["replicas"] == 2, "Expected two desired replicas")
    require(status.get("observedGeneration", 0) >= deployment["metadata"]["generation"],
            "Controller has not observed this Deployment generation")
    require(all(status.get(key, 0) == 2 for key in
                ("replicas", "updatedReplicas", "readyReplicas", "availableReplicas")),
            "Deployment is not fully reconciled with two available replicas")
    container = api_container(deployment)
    require(container["image"] == expected_image, "Unexpected live image: " + container["image"])
    require(container.get("imagePullPolicy") == "Never", "Healthy local images must use Never")
    guard_security_and_probes(deployment)
    if rollout_settings:
        require(spec.get("strategy") == {"type": "RollingUpdate", "rollingUpdate":
                                         {"maxUnavailable": 0, "maxSurge": 1}}, "Wrong rollout strategy")
        require(spec.get("minReadySeconds") == 10, "Expected minReadySeconds=10")
        require(spec.get("progressDeadlineSeconds") == 180, "Expected progressDeadlineSeconds=180")
        require(spec.get("revisionHistoryLimit") == 5, "Expected revisionHistoryLimit=5")
    pods = get("pods", selector=SELECTOR)["items"]
    require(len(pods) == 2 and not any(p["metadata"].get("deletionTimestamp") for p in pods),
            "Expected two settled API Pods; old terminating Pods may still be draining")
    for pod in pods:
        require(any(c["type"] == "Ready" and c["status"] == "True"
                    for c in pod.get("status", {}).get("conditions", [])), "An API Pod is not Ready")
        actual = next(c for c in pod["spec"]["containers"] if c["name"] == "api")
        require(actual["image"] == expected_image, "A Pod still runs a different image")
    slices = get("endpointslices", selector="kubernetes.io/service-name=meeps-api")["items"]
    ready = {e.get("targetRef", {}).get("name") for s in slices for e in s.get("endpoints", [])
             if e.get("conditions", {}).get("ready") is True}
    require(ready == {p["metadata"]["name"] for p in pods}, "Ready endpoints do not match both API Pods")
    return deployment, pods


def settle(expected_image, rollout_settings=False):
    last = ""
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        try:
            return healthy(expected_image, rollout_settings)
        except LabError as error:
            last = str(error)
            time.sleep(2)
    raise LabError("Workload did not settle: " + last)


def snapshot(label):
    for suffix, obj in (
        ("deployment", get("deployment", "meeps-api")),
        ("pods", get("pods", selector=SELECTOR)),
        ("replicasets", get("replicasets", selector=SELECTOR)),
        ("endpoints", get("endpointslices", selector="kubernetes.io/service-name=meeps-api")),
    ):
        save_json(label + "-" + suffix + ".json", obj)
    result = k("get", "deployment,replicaset,pods", "-l", SELECTOR, "-o", "wide").stdout
    history = k("rollout", "history", "deployment/meeps-api").stdout
    path(label + "-objects.txt").write_text(result + "\n" + history)
    print(result + "\n" + history, flush=True)


def verify_records(label, expected_version=None, each_pod=False):
    args = ["python", "-", "--fixture-json", FIXTURE.read_text()]
    if expected_version:
        args += ["--expect-version", expected_version]
    targets = [("deployment/meeps-api", "http://traefik.traefik-system")]
    if each_pod:
        targets += [(p["metadata"]["name"], "http://127.0.0.1:8000")
                    for p in get("pods", selector=SELECTOR)["items"]]
    results = []
    for target, base in targets:
        output = k("exec", "-i", target, "-c", "api", "--", *args,
                   "--base-url", base, data=VERIFY.read_text(), timeout=120).stdout
        record = json.loads(output)
        require(record.get("result") == "PASS", "Record verification failed")
        results.append(record)
    save_json(label + "-records.json", results)
    print(json.dumps(results, indent=2), flush=True)


def curl(route):
    command = ["curl", "--noproxy", "*", "--silent", "--show-error", "--max-time", "5",
               "--connect-timeout", "2", "--header", "Connection: close", "--resolve",
               "api.meeps.local:8080:127.0.0.1", "--output", os.devnull,
               "--write-out", "%{http_code}\t%{time_total}",
               "http://api.meeps.local:8080" + route]
    try:
        result = run(command, check=False, timeout=8)
        parts = result.stdout.strip().split("\t")
        return parts[0] if parts else "000", parts[1] if len(parts) > 1 else "0", result.returncode
    except subprocess.TimeoutExpired:
        return "000", "8", 124


class Traffic:
    """Continuous host-to-Ingress sampling in this local command, no retries."""
    def __init__(self, phase):
        self.phase = phase
        self.stop = threading.Event()
        self.rows = []
        self.error = None
        self.worker = threading.Thread(target=self.collect, daemon=True)

    def collect(self):
        try:
            with path(self.phase + "-traffic.tsv").open("w", newline="") as stream:
                writer = csv.writer(stream, delimiter="\t")
                writer.writerow(["utc", "path", "http_status", "seconds", "curl_exit"])
                while not self.stop.is_set():
                    for route in ("/", "/ready"):
                        if self.stop.is_set():
                            break
                        timestamp = now()
                        status, duration, rc = curl(route)
                        row = [timestamp, route, status, duration, rc]
                        writer.writerow(row)
                        stream.flush()
                        self.rows.append(row)
                    self.stop.wait(0.5)
        except Exception as error:
            self.error = str(error)

    def wait_samples(self, count):
        deadline = time.monotonic() + 30
        while len(self.rows) < count and time.monotonic() < deadline:
            require(self.error is None and self.worker.is_alive(), "Traffic sampler stopped unexpectedly")
            time.sleep(0.1)
        require(len(self.rows) >= count, "Insufficient HTTP samples; inspect ingress before proceeding")

    def __enter__(self):
        self.worker.start()
        try:
            self.wait_samples(6)
            require(all(row[2] == "200" and row[4] == 0 for row in self.rows),
                    "Baseline HTTP request failed before any mutation")
        except BaseException:
            self.finish(False)
            raise
        print("HTTP sampling active: / and /ready via 127.0.0.1:8080", flush=True)
        return self

    def finish(self, operation_ok):
        self.stop.set()
        self.worker.join(timeout=10)
        bad = [row for row in self.rows if row[2] != "200" or row[4] != 0]
        result = {"result": "PASS" if operation_ok and not bad and not self.error and len(self.rows) >= 6 else "FAIL",
                  "requests": len(self.rows), "failed_requests": len(bad),
                  "sampler_error": self.error, "completed_operation": operation_ok,
                  "max_seconds": max((float(row[3]) for row in self.rows), default=0),
                  "scope": "Finite samples of / and /ready through host Ingress; no retry and no zero-downtime guarantee."}
        save_json(self.phase + "-traffic-summary.json", result)
        print(json.dumps(result, indent=2), flush=True)
        return result

    def __exit__(self, kind, value, traceback):
        if kind is None:
            try:
                self.wait_samples(len(self.rows) + 6)
            except BaseException:
                self.finish(False)
                raise
        result = self.finish(kind is None)
        if kind is None:
            require(result["result"] == "PASS", "HTTP failures were observed; preserve and investigate the report")
        return False


def preflight():
    require(api_container(get("deployment", "meeps-api"))["image"] == OLD_IMAGE,
            "Expected Day 95 image k8s-v2; do not relabel an unverified baseline")
    print(k("rollout", "status", "deployment/meeps-api", "--timeout=180s", timeout=200).stdout)
    deployment, _ = settle(OLD_IMAGE)
    nodes = get("nodes")["items"]
    require(len(nodes) == 3 and all(any(c["type"] == "Ready" and c["status"] == "True"
                                      for c in n["status"]["conditions"]) for n in nodes),
            "Expected three Ready kind nodes")
    require(not any(h["spec"]["scaleTargetRef"].get("name") == "meeps-api"
                    for h in get("hpa")["items"]), "Disable no objects blindly: HPA is outside this Day 96 lab")
    print(k("rollout", "status", "statefulset/postgres", "--timeout=180s", timeout=200).stdout)
    require(get("pvc", "postgres-data-postgres-0")["status"]["phase"] == "Bound", "PVC not Bound")
    print(k("rollout", "status", "deployment/traefik", "--timeout=180s",
            ns="traefik-system", timeout=200).stdout)
    source = json.loads(k("apply", "--dry-run=server", "-f", str(MANIFEST), "-o", "json").stdout)
    require(api_container(source)["image"] == OLD_IMAGE, "Run preflight before modifying the tracked Deployment")
    require(template(source) == template(deployment), "Tracked baseline Pod template differs from live state; reconcile before starting")
    for route in ("/", "/ready"):
        code, _, rc = curl(route)
        require(code == "200" and rc == 0, "Host Ingress baseline failed at " + route)
    verify_records("baseline")
    if path("baseline-state.json").exists():
        require(read_json("baseline-state.json")["template"] == template(deployment),
                "An earlier Day 96 baseline exists with a different template; preserve it")
    else:
        shutil.copyfile(MANIFEST, path("baseline-deployment.yaml"))
        save_json("baseline-state.json", state(deployment))
    snapshot("baseline")
    print("PREFLIGHT PASSED. Baseline saved; cluster workloads have not been modified.")


def ensure_new_manifest():
    candidate = json.loads(k("apply", "--dry-run=server", "-f", str(MANIFEST), "-o", "json").stdout)
    require(api_container(candidate)["image"] == IMAGE, "Patch the tracked manifest to week14-v2 first")
    require(api_container(candidate)["imagePullPolicy"] == "Never", "Healthy release must retain Never")
    guard_security_and_probes(candidate)
    require(candidate["spec"].get("minReadySeconds") == 10 and
            candidate["spec"].get("progressDeadlineSeconds") == 180 and
            candidate["spec"].get("revisionHistoryLimit") == 5, "Wrong rollout timing/history settings")
    require(candidate["spec"].get("strategy") == {"type": "RollingUpdate", "rollingUpdate":
                                                  {"maxUnavailable": 0, "maxSurge": 1}}, "Wrong rollout strategy")


def update():
    require(not path("good-state.json").exists(), "A known-good Day 96 release is already saved; do not repeat the update blindly")
    baseline = read_json("baseline-state.json")
    live, _ = healthy(OLD_IMAGE)
    require(template(live) == baseline["template"], "Live baseline changed after preflight")
    ensure_new_manifest()
    with Traffic("update"):
        print(k("apply", "-f", str(MANIFEST)).stdout, flush=True)
        output = k("rollout", "status", "deployment/meeps-api", "--timeout=240s", timeout=260).stdout
        print(output, flush=True)
        path("update-rollout.txt").write_text(output)
        deployment, _ = settle(IMAGE, True)
        require(revision(deployment) != baseline["revision"], "No new Deployment revision observed")
        verify_records("update", VERSION, each_pod=True)
        snapshot("update")
        shutil.copyfile(MANIFEST, path("known-good-deployment.yaml"))
        save_json("good-state.json", state(deployment))
        path("good-revision.txt").write_text(str(revision(deployment)) + "\n")
    print("UPDATE PASSED. The recorded known-good revision is the rollback target.")


def fail_rollout():
    require(read_json("update-traffic-summary.json")["result"] == "PASS", "Successful monitored update is required")
    require(not path("failed-state.json").exists(), "A failure attempt is already recorded; inspect or roll back instead")
    good = read_json("good-state.json")
    deployment, _ = healthy(IMAGE, True)
    require(template(deployment) == good["template"] and revision(deployment) == good["revision"],
            "Live revision/template changed; do not select an ambiguous rollback target")
    require(MANIFEST.read_bytes() == path("known-good-deployment.yaml").read_bytes(),
            "Tracked Deployment changed after the good snapshot")
    bad_image = "docker.io/library/python:meeps-day96-missing-" + secrets.token_hex(8)
    patch = {"metadata": {"annotations": {"kubernetes.io/change-cause": "Day 96 intentional missing-image drill"}},
             "spec": {"template": {"metadata": {"labels": {"app.kubernetes.io/version": "day96-bad-image"}},
                                     "spec": {"containers": [{"name": "api", "image": bad_image,
                                                                 "imagePullPolicy": "Always"}]}}}}
    broken = Path("kubernetes/examples/day-96-broken-deployment.yaml")
    broken.write_text("# INTENTIONAL FAILURE EXAMPLE. Do not apply with normal workloads.\n" +
                      k("patch", "--local", "--type=strategic", "-f", str(MANIFEST),
                        "-p", json.dumps(patch), "-o", "yaml").stdout)
    print(k("apply", "--dry-run=server", "-f", str(broken)).stdout)
    save_json("failed-state.json", {"bad_image": bad_image, "good_revision": good["revision"],
                                   "result": "INCOMPLETE", "started_at": now()})
    seen_backoff = False
    with Traffic("failed-rollout"):
        print(k("apply", "-f", str(broken)).stdout, flush=True)
        deadline = time.monotonic() + 330
        bad_pods = []
        observed_missing_tag = False
        observed_reason = False
        while time.monotonic() < deadline:
            deployment = get("deployment", "meeps-api")
            bad_pods = [p for p in get("pods", selector=SELECTOR)["items"]
                        if any(c["name"] == "api" and c["image"] == bad_image for c in p["spec"]["containers"])]
            for pod in bad_pods:
                for status in pod.get("status", {}).get("containerStatuses", []):
                    waiting = status.get("state", {}).get("waiting", {})
                    if waiting.get("reason") == "ImagePullBackOff":
                        if not seen_backoff:
                            print("Observed ImagePullBackOff; waiting for the controller's progress deadline.", flush=True)
                            save_json("image-pull-backoff-pod.json", pod)
                        seen_backoff = True
                    message = waiting.get("message", "").lower()
                    observed_missing_tag |= "not found" in message or "manifest unknown" in message
            condition = next((c for c in deployment.get("status", {}).get("conditions", [])
                              if c["type"] == "Progressing"), {})
            observed_reason = (condition.get("status") == "False" and
                               condition.get("reason") == "ProgressDeadlineExceeded")
            if observed_reason and seen_backoff:
                break
            time.sleep(2)
        snapshot("failed")
        for pod in bad_pods:
            name = pod["metadata"]["name"]
            path("failed-pod-describe.txt").write_text(k("describe", "pod", name).stdout)
            events = k("get", "events", "--field-selector", "involvedObject.name=" + name,
                       "--sort-by=.metadata.creationTimestamp").stdout
            path("failed-pod-events.txt").write_text(events)
            observed_missing_tag |= "not found" in events.lower() or "manifest unknown" in events.lower()
        require(seen_backoff, "ImagePullBackOff was not observed; inspect the saved failure diagnostics")
        require(observed_reason, "ProgressDeadlineExceeded was NOT observed; a client timeout alone is not proof")
        require(deployment.get("status", {}).get("availableReplicas") == 2,
                "The two good replicas were not both available during the failure checkpoint")
        result = k("rollout", "status", "deployment/meeps-api", "--timeout=5s", check=False, timeout=20)
        path("failed-rollout-status.txt").write_text(result.stdout + result.stderr)
        require(result.returncode != 0 and "progress deadline" in (result.stdout + result.stderr).lower(),
                "Rollout status did not report the expected server-side progress failure")
        require(observed_missing_tag, "A pull failure occurred, but the missing-tag cause was not confirmed; inspect DNS/auth/rate-limit errors")
        verify_records("during-failure", VERSION)
        save_json("failed-state.json", {"result": "PASS", "bad_image": bad_image,
                                        "failed_revision": revision(deployment), "good_revision": good["revision"],
                                        "ImagePullBackOff": True, "ProgressDeadlineExceeded": True,
                                        "missing_tag_confirmed": True, "available_replicas": 2})
    print("EXPECTED FAILURE CAPTURED. Good replicas still serve traffic. Run rollback next; recovery is not automatic.")


def rollback():
    good = read_json("good-state.json")
    attempt = read_json("failed-state.json")
    require(MANIFEST.read_bytes() == path("known-good-deployment.yaml").read_bytes(),
            "Good tracked manifest changed; compare it with the saved recovery file before continuing")
    current = get("deployment", "meeps-api")
    require(api_container(current)["image"] == attempt["bad_image"],
            "Live Deployment is not the recorded faulty attempt; inspect before rolling back")
    retained = get("replicasets", selector=SELECTOR)["items"]
    targets = [rs for rs in retained if rs["metadata"].get("annotations", {}).get(
        "deployment.kubernetes.io/revision") == str(good["revision"])]
    require(len(targets) == 1, "Recorded good revision is not uniquely retained")
    require(template(targets[0]) == good["template"], "Retained revision template differs from the saved good template")
    with Traffic("rollback"):
        print(k("rollout", "undo", "deployment/meeps-api", "--to-revision=" + str(good["revision"])).stdout, flush=True)
        print(k("rollout", "status", "deployment/meeps-api", "--timeout=240s", timeout=260).stdout, flush=True)
        deployment, _ = settle(IMAGE, True)
        require(template(deployment) == good["template"], "Rollback did not restore the full known-good Pod template")
        # Bring last-applied configuration back into agreement with the tracked good manifest.
        print(k("apply", "-f", str(MANIFEST)).stdout, flush=True)
        print(k("rollout", "status", "deployment/meeps-api", "--timeout=240s", timeout=260).stdout, flush=True)
        deployment, _ = settle(IMAGE, True)
        require(template(deployment) == good["template"], "Tracked manifest does not agree with restored Pod template")
        verify_records("after-rollback", VERSION, each_pod=True)
        snapshot("rollback")
        save_json("rollback-state.json", {"result": "PASS", "restored_image": IMAGE,
                                          "restored_imagePullPolicy": "Never", "target_revision": good["revision"],
                                          "current_revision": revision(deployment), "full_template_matches": True})
    print("ROLLBACK PASSED. Healthy week14-v2 and its Never pull policy are restored; tracked manifest agrees.")


def final_check():
    require(read_json("failed-state.json").get("result") == "PASS", "Failure drill lacks a complete verified result")
    require(read_json("rollback-state.json").get("result") == "PASS", "Rollback has not been verified")
    good = read_json("good-state.json")
    deployment, _ = settle(IMAGE, True)
    require(template(deployment) == good["template"], "Live template differs from the recorded good release")
    require(MANIFEST.read_bytes() == path("known-good-deployment.yaml").read_bytes(), "Tracked good manifest changed")
    verify_records("final", VERSION, each_pod=True)
    for route in ("/", "/ready", "/version"):
        code, duration, rc = curl(route)
        require(code == "200" and rc == 0, "Fresh external HTTP check failed at " + route)
        print("External {0}: HTTP {1}, {2}s".format(route, code, duration))
    require(get("pvc", "postgres-data-postgres-0")["status"]["phase"] == "Bound", "PostgreSQL PVC is not Bound")
    print(k("rollout", "status", "statefulset/postgres", "--timeout=180s", timeout=200).stdout)
    summaries = {}
    for phase in ("update", "failed-rollout", "rollback"):
        summary = read_json(phase + "-traffic-summary.json")
        require(summary["result"] == "PASS" and summary["failed_requests"] == 0 and summary["requests"] >= 6,
                "Traffic did not pass for " + phase)
        summaries[phase] = summary
    require(not run(["git", "ls-files", "--", ".local/"]).stdout.strip(), "Private .local files are tracked/staged")
    print(run(["git", "check-ignore", "-v", ".local/meeps-dev/api-secret.local.yaml"]).stdout)
    snapshot("final")
    report = {"result": "PASS", "image": IMAGE, "current_revision": revision(deployment),
              "restored_template": True, "original_database_records": "verified using GET only",
              "sampled_http_results": summaries,
              "scope": "Observed requests only; not proof of all traffic, load capacity, DB failover, or guaranteed zero downtime."}
    save_json("final-result.json", report)
    print(json.dumps(report, indent=2))
    print("DAY 96 CHECKS PASSED. Review captured logs and the deliberately broken example before committing.")


class Tee:
    def __init__(self, console, stream):
        self.console, self.stream = console, stream
    def write(self, value):
        self.console.write(value)
        self.stream.write(value)
        self.flush()
        return len(value)
    def flush(self):
        self.console.flush()
        self.stream.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("step", choices=("preflight", "update", "fail", "rollback", "final"))
    args = parser.parse_args()
    require(sys.version_info >= (3, 9), "Use Python 3.9 or newer; no pip dependencies are required")
    require(Path.cwd().resolve() == Path(__file__).resolve().parents[2], "Run from the repository root")
    for executable in ("kubectl", "curl", "git"):
        require(shutil.which(executable) is not None, "Missing command: " + executable)
    for source in (MANIFEST, VERIFY, FIXTURE):
        require(source.is_file() and source.stat().st_size > 0, "Missing prerequisite: " + str(source))
    require(json.loads(FIXTURE.read_text()).get("result") == "PASS", "Day 94 fixture is not marked PASS")
    DOCS.mkdir(parents=True, exist_ok=True)
    filename = "final-verification.txt" if args.step == "final" else args.step + "-verification.txt"
    target = path(filename)
    temporary = Path(str(target) + ".tmp")
    console = sys.stdout
    try:
        with temporary.open("w") as stream:
            sys.stdout = Tee(console, stream)
            print("DAY 96 / {0} / {1}".format(args.step, now()))
            try:
                {"preflight": preflight, "update": update, "fail": fail_rollout,
                 "rollback": rollback, "final": final_check}[args.step]()
            except (LabError, OSError, ValueError, KeyError, subprocess.TimeoutExpired, KeyboardInterrupt) as error:
                print("STOP: {0}".format(error))
                print("This attempt is incomplete; its report remains .tmp. Do not rename it to claim success.")
                if args.step in ("update", "fail", "rollback"):
                    print("Inspect the Deployment. No automatic workload rollback has been performed.")
                return 1
    finally:
        sys.stdout = console
    temporary.replace(target)
    print("Saved: " + str(target))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (LabError, OSError, ValueError, KeyError) as error:
        print("STOP: {0}".format(error), file=sys.stderr)
        sys.exit(1)
