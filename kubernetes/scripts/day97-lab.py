#!/usr/bin/env python3
"""Checkpointed Day 97 lab. Python 3.9+, stdlib only; run from repository root.
Every Kubernetes call explicitly selects the existing local cluster.
No function recreates PostgreSQL, deletes a PVC, or changes credentials.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import threading
import time
from urllib.request import build_opener, ProxyHandler, Request

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'kubernetes/docs'
DEPLOY = ROOT / 'kubernetes/base/api-deployment.yaml'
CONTEXT = 'kind-meeps-k8s-cluster'
CONFIG = str(Path.home() / '.kube/meeps-k8s-cluster.yaml')
NS = 'meeps-dev'
WORKERS = ['meeps-k8s-cluster-worker', 'meeps-k8s-cluster-worker2']
SELECTOR = 'app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev'
ANNOTATION = 'kubectl.kubernetes.io/last-applied-configuration'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def run(args, data=None, check=True, timeout=420):
    p = subprocess.run([str(a) for a in args], input=data, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       timeout=timeout, cwd=str(ROOT))
    if check and p.returncode:
        raise RuntimeError('Command failed: ' + ' '.join(str(x) for x in args[:8])
                           + '\n' + p.stdout + p.stderr)
    return p


def k(*args, ns=NS, data=None, check=True, timeout=420):
    return run(['kubectl', '--kubeconfig', CONFIG, '--context', CONTEXT,
                '--namespace', ns, *args], data, check, timeout)


def get(resource, name=None, ns=NS, extra=()):
    args = ['get', resource] + ([name] if name else []) + list(extra) + ['-o', 'json']
    return json.loads(k(*args, ns=ns).stdout)


def exists(resource, name, ns=NS):
    return bool(k('get', resource, name, '--ignore-not-found', '-o', 'name', ns=ns).stdout.strip())


def path(suffix):
    return DOCS / ('day-97-' + suffix)


def save(suffix, obj):
    destination = path(suffix)
    tmp = Path(str(destination) + '.tmp')
    tmp.write_text(json.dumps(obj, indent=2) + '\n' if not isinstance(obj, str) else obj)
    tmp.replace(destination)


def result(suffix):
    p = path(suffix)
    require(p.is_file(), 'Missing checkpoint: ' + str(p.relative_to(ROOT)))
    data = json.loads(p.read_text())
    require(data.get('result') == 'PASS', 'Checkpoint has not passed: ' + suffix)
    return data


def conditions(obj):
    return {c['type']: c for c in obj.get('status', {}).get('conditions', [])}


def ready(pod):
    return (not pod['metadata'].get('deletionTimestamp')
            and pod.get('status', {}).get('phase') == 'Running'
            and conditions(pod).get('Ready', {}).get('status') == 'True')


def api_pods():
    return get('pods', extra=('-l', SELECTOR))['items']


def deployment():
    return get('deployment', 'meeps-api')


def wait_for(predicate, message, timeout=300, interval=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise RuntimeError('Timed out: ' + message)


def exact_replicas(count):
    d = deployment()
    pods = api_pods()
    return (d['spec'].get('replicas') == count
            and d['status'].get('observedGeneration', 0) >= d['metadata']['generation']
            and all(d['status'].get(key, 0) == count for key in
                    ('updatedReplicas', 'readyReplicas', 'availableReplicas'))
            and len(pods) == count and all(ready(p) for p in pods))


def wait_replicas(count):
    wait_for(lambda: exact_replicas(count), 'exactly %d available API replicas' % count)


def cluster_check():
    require(Path.cwd().resolve() == ROOT, 'Run from the repository root.')
    require(Path(CONFIG).is_file(), 'Missing lab kubeconfig. Source the session helper.')
    require(k('config', 'current-context').stdout.strip() == CONTEXT,
            'Wrong current context in the lab kubeconfig.')
    nodes = get('nodes')['items']
    expected = set(WORKERS + ['meeps-k8s-cluster-control-plane'])
    require({n['metadata']['name'] for n in nodes} == expected, 'Unexpected cluster topology.')
    for n in nodes:
        c = conditions(n)
        require(c.get('Ready', {}).get('status') == 'True', 'Node not Ready: ' + n['metadata']['name'])
        require(not any(c.get(t, {}).get('status') == 'True' for t in
                        ['MemoryPressure', 'DiskPressure', 'PIDPressure']),
                'Node pressure detected; stop load and investigate.')
    return nodes


def verify_records():
    f = ROOT / 'kubernetes/docs/day-94-fixture.json'
    script = ROOT / 'kubernetes/scripts/day96-verify.py'
    require(f.is_file() and script.is_file(), 'Missing original fixture or Day 96 GET-only verifier.')
    fixture = json.loads(f.read_text())
    require(fixture.get('result') == 'PASS', 'Original fixture did not pass.')
    pods = [p for p in api_pods() if ready(p)]
    require(pods, 'No ready API Pod for GET-only verification.')
    out = k('exec', '-i', pods[0]['metadata']['name'], '-c', 'api', '--',
            'python', '-', '--fixture-json', json.dumps(fixture),
            '--expect-version', 'week14-v2', data=script.read_text()).stdout
    checked = json.loads(out)
    require(checked.get('result') == 'PASS', 'Original record verification failed.')
    print(out.strip(), flush=True)
    return checked


def external_check():
    opener = build_opener(ProxyHandler({}))
    req = Request('http://127.0.0.1:8080/ready', headers={'Host': 'api.meeps.local'})
    with opener.open(req, timeout=5) as response:
        require(response.status == 200 and json.load(response) == {'status': 'ready'},
                'External Ingress readiness failed.')


def preflight(_):
    nodes = cluster_check()
    require(not any(n['spec'].get('unschedulable') for n in nodes), 'A node is already cordoned.')
    require(not exists('hpa', 'meeps-api'), 'HPA already exists; do not repeat manual scaling against it.')
    wait_replicas(2)
    d = deployment()
    c = next(c for c in d['spec']['template']['spec']['containers'] if c['name'] == 'api')
    require(c['image'] == 'meeps-users-posts-api:week14-v2', 'Restore the successful Day 96 image first.')
    require(c.get('imagePullPolicy') == 'Never', 'Unexpected image pull policy.')
    require(c.get('resources', {}).get('requests', {}).get('cpu') == '100m', 'Expected API CPU request 100m.')
    require(c.get('readinessProbe', {}).get('httpGet', {}).get('path') == '/ready', 'Readiness not restored.')
    pg = get('pod', 'postgres-0')
    pvc = get('pvc', 'postgres-data-postgres-0')
    require(ready(pg) and pvc['status']['phase'] == 'Bound', 'Database/PVC not ready.')
    require(not exists('job', 'meeps-day97-load'), 'A previous load Job exists. Stop it before restarting.')
    verify_records()
    external_check()
    print(k('get', 'nodes', '-o', 'wide').stdout)
    print(k('get', 'pods,pvc', '-o', 'wide').stdout)
    save('baseline.json', {'result': 'PASS', 'at': now(), 'postgres_uid': pg['metadata']['uid'],
                         'postgres_node': pg['spec']['nodeName'], 'pvc_uid': pvc['metadata']['uid']})
    print('PREFLIGHT PASSED. No workloads changed.')


def manual(args):
    cluster_check()
    require(not exists('hpa', 'meeps-api'), 'Do not manually scale a Deployment controlled by HPA.')
    expected = 2 if args.replicas == 4 else 4
    require(exact_replicas(expected), 'Expected %d ready replicas before this step.' % expected)
    print(k('scale', 'deployment/meeps-api', '--current-replicas=' + str(expected),
            '--replicas=' + str(args.replicas)).stdout)
    wait_replicas(args.replicas)
    print(k('get', 'deployment,replicaset,pods', '-l', SELECTOR, '-o', 'wide').stdout)
    verify_records()
    save('manual-%d.json' % args.replicas,
         {'result': 'PASS', 'at': now(), 'replicas': args.replicas, 'pods': api_pods()})


def remove_replicas(annotation):
    obj = json.loads(annotation)
    obj.setdefault('spec', {}).pop('replicas', None)
    return json.dumps(obj, separators=(',', ':'))


def handoff(_):
    cluster_check()
    result('manual-2.json')
    require(exact_replicas(2), 'Need two healthy replicas before ownership handoff.')
    require(not exists('hpa', 'meeps-api'), 'HPA already exists; handoff is a one-time step.')
    d = deployment()
    annotations = d['metadata'].get('annotations', {})
    require(ANNOTATION in annotations, 'Missing client-side last-applied annotation; inspect field ownership.')
    old = DEPLOY.read_text()
    local = json.loads(k('create', '--dry-run=client', '--validate=false', '-f', str(DEPLOY), '-o', 'json').stdout)
    require(local['spec'].get('replicas') == 2, 'Expected the saved manifest to specify two replicas.')
    new = k('patch', '--local', '--type=json', '-f', str(DEPLOY), '-p',
            json.dumps([{'op': 'remove', 'path': '/spec/replicas'}]), '-o', 'yaml').stdout
    save('before-hpa-deployment.yaml', old)
    patch = [
        {'op': 'test', 'path': '/metadata/resourceVersion', 'value': d['metadata']['resourceVersion']},
        {'op': 'replace', 'path': '/metadata/annotations/kubectl.kubernetes.io~1last-applied-configuration',
         'value': remove_replicas(annotations[ANNOTATION])},
    ]
    # Change only the last-applied annotation first; do not default live replicas to one.
    print(k('patch', 'deployment', 'meeps-api', '--type=json', '-p', json.dumps(patch)).stdout)
    DEPLOY.write_text(new)
    print(k('apply', '--dry-run=server', '-f', str(DEPLOY)).stdout)
    print(k('apply', '-f', str(DEPLOY)).stdout)
    require(deployment()['spec']['replicas'] == 2, 'Replica count changed during handoff; inspect immediately.')
    print(k('apply', '--dry-run=server', '-f', 'kubernetes/base/hpa.yaml').stdout)
    print(k('apply', '-f', 'kubernetes/base/hpa.yaml').stdout)
    save('replica-handoff.json', {'result': 'PASS', 'at': now(), 'manifest_replicas_removed': True,
                                'last_applied_replicas_removed': True, 'live_replicas': 2})
    print('HPA CREATED. Do not reapply an old manifest or checkpoint that sets spec.replicas.')


def hpa_healthy():
    obj = get('hpa', 'meeps-api')
    c = conditions(obj)
    return obj, (c.get('AbleToScale', {}).get('status') == 'True'
                 and c.get('ScalingActive', {}).get('status') == 'True')


def load_start(args):
    cluster_check()
    h, healthy = hpa_healthy()
    require(healthy, 'HPA has no usable metrics; fix metrics before generating load.')
    require(h['spec']['minReplicas'] == 2 and h['spec']['maxReplicas'] == 5, 'Unexpected HPA bounds.')
    require(exact_replicas(2), 'Begin this load test at two healthy replicas.')
    require(not exists('job', 'meeps-day97-load'), 'Previous load Job exists; capture and stop it first.')
    cm = k('create', 'configmap', 'meeps-day97-load',
           '--from-file=load.py=kubernetes/scripts/day97-load.py',
           '--dry-run=client', '-o', 'json').stdout
    print(k('apply', '-f', '-', data=cm).stdout)
    spec = json.loads(k('create', '--dry-run=client', '--validate=false',
                       '-f', 'kubernetes/examples/day-97-load-job.yaml', '-o', 'json').stdout)
    spec['spec']['template']['spec']['containers'][0]['args'] = [
        '--rps', str(args.rps), '--seconds', '540', '--concurrency', '16']
    save('load-request.json', {'at': now(), 'target_rps': args.rps, 'seconds': 540,
                             'max_concurrency': 16, 'path': '/openapi.json'})
    print(k('create', '-f', '-', data=json.dumps(spec)).stdout)
    print('Bounded load Job started. Watch HPA, metrics and API readiness; stop on errors or pressure.')


def load_stop(_):
    if exists('job', 'meeps-day97-load'):
        log = k('logs', 'job/meeps-day97-load', '--tail=200', check=False)
        save('load-log.txt', log.stdout + log.stderr)
        print(log.stdout)
        save('load-job-at-stop.json', get('job', 'meeps-day97-load'))
        print(k('delete', 'job', 'meeps-day97-load', '--wait=true', '--timeout=120s').stdout)
        wait_for(lambda: not get('pods', extra=('-l', 'job-name=meeps-day97-load'))['items'],
                 'load Pods to terminate', timeout=120)
    print(k('delete', 'configmap', 'meeps-day97-load', '--ignore-not-found').stdout)
    print('Load stopped. HPA remains enabled; allow its stabilization and scale-in policy to operate.')


def observe(args):
    cluster_check()
    if args.direction == 'in':
        result('scale-out.json')
        require(not exists('job', 'meeps-day97-load'), 'Run load-stop before waiting for scale-in.')
    else:
        require(exists('job', 'meeps-day97-load'), 'Start bounded load first.')
    log = path('scale-%s-samples.jsonl' % args.direction)
    end = time.monotonic() + args.timeout
    stable_since = None
    max_ready = 0
    max_desired = 0
    with log.open('w') as f:
        while time.monotonic() < end:
            h, good = hpa_healthy()
            d = deployment()
            pods = api_pods()
            count = sum(ready(p) for p in pods)
            want = h.get('status', {}).get('desiredReplicas', 0)
            max_ready, max_desired = max(max_ready, count), max(max_desired, want)
            row = {'at': now(), 'desired': want, 'ready': count, 'hpa_healthy': good,
                   'metrics': h.get('status', {}).get('currentMetrics', []),
                   'conditions': h.get('status', {}).get('conditions', [])}
            f.write(json.dumps(row) + '\n'); f.flush()
            print('desired=%s ready=%s HPA_healthy=%s CPU=%s' %
                  (want, count, good, row['metrics']), flush=True)
            if args.direction == 'out':
                passed = good and want >= 3 and count >= 3
            else:
                settled = good and want == 2 and exact_replicas(2)
                stable_since = (stable_since or time.monotonic()) if settled else None
                passed = stable_since is not None and time.monotonic() - stable_since >= 30
            if passed:
                save('scale-%s.json' % args.direction,
                     {'result': 'PASS', 'at': now(), 'observed_ready': count,
                      'desired': want, 'max_ready_observed': max_ready,
                      'max_desired_observed': max_desired})
                save('hpa-events-%s.txt' % args.direction,
                     k('describe', 'hpa', 'meeps-api').stdout)
                print('SCALE-%s OBSERVED.' % args.direction.upper())
                return
            time.sleep(10)
    raise RuntimeError('Scaling target not observed. Stop load, inspect HPA/metrics/events; do not claim success.')


def spread(_):
    cluster_check()
    result('scale-in.json')
    require(not exists('job', 'meeps-day97-load'), 'Stop load before placement changes.')
    require(exact_replicas(2), 'Wait for two healthy replicas before topology changes.')
    for node in WORKERS:
        print(k('label', 'node', node, 'meeps.dev/node-pool=worker', '--overwrite').stdout)
    new = k('patch', '--local', '--type=strategic', '-f', str(DEPLOY),
            '--patch-file', 'kubernetes/examples/day-97-topology.patch.yaml', '-o', 'yaml').stdout
    DEPLOY.write_text(new)
    print(k('apply', '--dry-run=server', '-f', str(DEPLOY)).stdout)
    print(k('apply', '-f', str(DEPLOY)).stdout)
    print(k('rollout', 'status', 'deployment/meeps-api', '--timeout=240s').stdout)
    wait_replicas(2)
    pods = api_pods()
    placement = Counter(p['spec']['nodeName'] for p in pods)
    print(k('get', 'pods', '-l', SELECTOR, '-o', 'wide').stdout)
    require(set(placement) == set(WORKERS),
            'Soft spreading is a preference; Pods did not land on both workers. Inspect scheduling before the drain.')
    save('topology.json', {'result': 'PASS', 'at': now(), 'placement': dict(placement), 'pods': pods})
    print('One API Pod observed on each worker. The policy is deliberately soft for maintenance.')


def safe_node(pg_node, placements):
    choices = [n for n in WORKERS if n != pg_node and placements.get(n, 0) > 0]
    require(bool(choices), 'No worker with an API Pod is available without draining PostgreSQL.')
    return choices[0]


def active_on_node(node):
    all_pods = get('pods', extra=('-A', '--field-selector', 'spec.nodeName=' + node))['items']
    return [p for p in all_pods if p.get('status', {}).get('phase') not in ('Succeeded', 'Failed')]


def owner(p):
    return next((o for o in p['metadata'].get('ownerReferences', []) if o.get('controller')), {})


def allowed_for_drain(p):
    if owner(p).get('kind') == 'DaemonSet':
        return True
    labels = p['metadata'].get('labels', {})
    return (p['metadata'].get('namespace') == NS and owner(p).get('kind') == 'ReplicaSet'
            and labels.get('app.kubernetes.io/name') == 'meeps-api'
            and not any('persistentVolumeClaim' in v or 'hostPath' in v
                        for v in p['spec'].get('volumes', [])))


class Traffic:
    def __init__(self):
        self.stop = threading.Event()
        self.rows = []
        self.thread = threading.Thread(target=self.sample, daemon=True)
    def sample(self):
        opener = build_opener(ProxyHandler({}))
        while not self.stop.is_set():
            row = {'at': now()}
            try:
                req = Request('http://127.0.0.1:8080/ready', headers={'Host': 'api.meeps.local'})
                with opener.open(req, timeout=5) as r:
                    row['status'] = r.status
                    row['ok'] = r.status == 200 and json.load(r) == {'status': 'ready'}
            except Exception as exc:
                row.update(ok=False, error=type(exc).__name__)
            self.rows.append(row)
            self.stop.wait(1)
    def finish(self):
        self.stop.set(); self.thread.join(timeout=8)
        save('drain-http-samples.json', self.rows)


def budget_value(minimum):
    print(k('patch', 'pdb', 'meeps-api', '--type=merge', '-p',
            json.dumps({'spec': {'minAvailable': minimum}})).stdout)
    def reconciled():
        p = get('pdb', 'meeps-api')
        return (p['status'].get('observedGeneration', 0) >= p['metadata']['generation']
                and p['status'].get('currentHealthy') == 2
                and p['status'].get('disruptionsAllowed') == 2 - minimum)
    wait_for(reconciled, 'PDB to reflect the temporary/normal budget', timeout=90)


def drain(_):
    nodes = cluster_check()
    result('topology.json'); result('scale-in.json')
    require(not any(n['spec'].get('unschedulable') for n in nodes), 'A node is already cordoned.')
    require(not exists('job', 'meeps-day97-load'), 'Stop the load Job before the drain.')
    require(exact_replicas(2), 'Need two healthy API replicas for this controlled PDB exercise.')
    h, good = hpa_healthy()
    require(good and h['status'].get('desiredReplicas') == 2, 'HPA is not stable at two.')
    pdb = get('pdb', 'meeps-api')
    require(pdb['spec'].get('minAvailable') == 1, 'Normal PDB must have minAvailable: 1.')
    pg = get('pod', 'postgres-0')
    pods = api_pods()
    placement = Counter(p['spec']['nodeName'] for p in pods)
    require(set(placement) == set(WORKERS), 'Need one API Pod on each worker before draining.')
    node = safe_node(pg['spec']['nodeName'], placement)
    save('drain-target.txt', node + '\n')
    save('pods-before-drain.json', pods)
    print('PostgreSQL remains on: ' + pg['spec']['nodeName'])
    print('Chosen maintenance worker: ' + node)
    print(k('get', 'pods', '-A', '--field-selector', 'spec.nodeName=' + node, '-o', 'wide').stdout)
    # Refuse unknown/stateful occupants before making any changes.
    known_infra = {('traefik-system', 'traefik'), ('kube-system', 'metrics-server')}
    for p in active_on_node(node):
        if allowed_for_drain(p):
            continue
        o = owner(p)
        require(o.get('kind') == 'ReplicaSet', 'Unexpected non-Deployment workload on drain worker.')
        rs = get('replicaset', o['name'], ns=p['metadata']['namespace'])
        controller = owner(rs)
        require((p['metadata']['namespace'], controller.get('name')) in known_infra,
                'Unexpected workload on worker; do not drain it automatically.')
        require(not any('persistentVolumeClaim' in v or 'hostPath' in v for v in p['spec'].get('volumes', [])),
                'Stateful volume on worker; refusing automatic drain.')
    traffic = Traffic()
    traffic.thread.start()
    blocked = False
    completed = False
    error = None
    try:
        print(k('cordon', node).stdout)
        # Move only known singleton infrastructure via rolling restarts while the
        # target is cordoned. Their old Pods remain until replacements are ready.
        for ns, name in sorted(known_infra):
            dep = get('deployment', name, ns=ns)
            labels = dep['spec']['selector']['matchLabels']
            selector = ','.join('%s=%s' % pair for pair in labels.items())
            selected = get('pods', ns=ns, extra=('-l', selector))['items']
            if any(p['spec'].get('nodeName') == node and not p['metadata'].get('deletionTimestamp') for p in selected):
                strategy = dep['spec'].get('strategy', {})
                require(strategy.get('type', 'RollingUpdate') == 'RollingUpdate', 'Infrastructure is not configured for rolling update.')
                print(k('rollout', 'restart', 'deployment/' + name, ns=ns).stdout)
                print(k('rollout', 'status', 'deployment/' + name, '--timeout=240s', ns=ns).stdout)
        wait_for(lambda: all(allowed_for_drain(p) for p in active_on_node(node)),
                 'known infrastructure to finish moving off worker', timeout=120)
        require(exact_replicas(2), 'Replica count changed; stop PDB demonstration and retry after stabilization.')
        save('drain-node-occupants.json', active_on_node(node))
        # Deliberate, reversible PDB failure. All remaining non-DaemonSet Pods are API Pods.
        budget_value(2)
        denied = k('drain', node, '--ignore-daemonsets', '--delete-emptydir-data',
                   '--timeout=20s', check=False, timeout=55)
        denial_text = denied.stdout + denied.stderr
        print(denial_text)
        save('pdb-blocked-drain.txt', denial_text)
        blocked = denied.returncode != 0 and 'disruption budget' in denial_text.lower()
        require(blocked, 'Expected a PDB refusal, not another error or a successful drain.')
        require({p['metadata']['uid'] for p in api_pods()} == {p['metadata']['uid'] for p in pods},
                'Pods changed during the deliberately blocked drain; inspect concurrency.')
        save('pdb-during-block.json', get('pdb', 'meeps-api'))
        budget_value(1)
        ok = k('drain', node, '--ignore-daemonsets', '--delete-emptydir-data', '--timeout=180s')
        print(ok.stdout + ok.stderr)
        save('successful-drain.txt', ok.stdout + ok.stderr)
        wait_replicas(2)
        after = api_pods()
        require(all(p['spec']['nodeName'] != node for p in after), 'API still scheduled on drained node.')
        require(all(owner(p).get('kind') == 'DaemonSet' for p in active_on_node(node)),
                'Unexpected active non-DaemonSet Pod remains on drained worker.')
        require(get('pod', 'postgres-0')['metadata']['uid'] == pg['metadata']['uid'],
                'Database Pod was replaced unexpectedly.')
        verify_records(); external_check()
        save('pods-after-drain.json', after)
        completed = True
    except BaseException as exc:
        error = exc
    finally:
        # No node deletion, no forced evictions, no bypass of the eviction API.
        recovery_errors = []
        for command in [('apply', '-f', 'kubernetes/base/pdb.yaml'), ('uncordon', node)]:
            try:
                recovery = k(*command, check=False)
                print(recovery.stdout + recovery.stderr)
                if recovery.returncode:
                    recovery_errors.append(' '.join(command))
            except Exception as exc:
                recovery_errors.append(str(exc))
        traffic.finish()
        if recovery_errors:
            print('RECOVERY INCOMPLETE: run recover. ' + '; '.join(recovery_errors), file=sys.stderr)
            if error is None:
                error = RuntimeError('Recovery incomplete; run the recover command before continuing.')
    if error:
        raise error
    require(completed and blocked, 'Drain exercise did not complete.')
    require(traffic.rows and all(r['ok'] for r in traffic.rows),
            'HTTP failures were captured; node/PDB recovered. Inspect samples; do not claim uninterrupted traffic.')
    save('drain-result.json', {'result': 'PASS', 'at': now(), 'node': node,
                             'postgres_uid_unchanged': True, 'pdb_block_observed': True,
                             'normal_drain_completed': True, 'uncordoned': True,
                             'http_samples': len(traffic.rows), 'failed_samples': 0})
    print('DRAIN PASSED; worker uncordoned. Existing Pods are not automatically rebalanced.')


def recover(_):
    p = path('drain-target.txt')
    if exists('pdb', 'meeps-api'):
        print(k('apply', '-f', 'kubernetes/base/pdb.yaml').stdout)
    if p.is_file():
        node = p.read_text().strip()
        require(node in WORKERS, 'Recorded target is not an expected lab worker.')
        print(k('uncordon', node).stdout)
    load_stop(None)
    print('Recovery commands completed. This does not mark a failed exercise as passed.')


def final(_):
    nodes = cluster_check()
    require(not any(n['spec'].get('unschedulable') for n in nodes), 'A node is still cordoned.')
    for suffix in ['manual-4.json', 'manual-2.json', 'replica-handoff.json',
                   'scale-out.json', 'scale-in.json', 'topology.json', 'drain-result.json']:
        result(suffix)
    require(not exists('job', 'meeps-day97-load'), 'Load Job still exists.')
    wait_replicas(2)
    h, good = hpa_healthy()
    require(good and h['spec']['minReplicas'] == 2 and h['spec']['maxReplicas'] == 5, 'HPA is not healthy.')
    require(h['status'].get('desiredReplicas') == 2, 'Wait for idle HPA to return to two.')
    pdb = get('pdb', 'meeps-api')
    require(pdb['spec'].get('minAvailable') == 1 and pdb['status'].get('disruptionsAllowed') == 1,
            'Normal PDB not restored/reconciled.')
    local = json.loads(k('create', '--dry-run=client', '--validate=false', '-f', str(DEPLOY), '-o', 'json').stdout)
    require('replicas' not in local['spec'], 'Tracked manifest still controls replicas.')
    require('replicas' not in json.loads(deployment()['metadata']['annotations'][ANNOTATION])['spec'],
            'Last-applied annotation still controls replicas.')
    pg = get('pod', 'postgres-0'); pvc = get('pvc', 'postgres-data-postgres-0')
    baseline = result('baseline.json')
    require(ready(pg) and pg['metadata']['uid'] == baseline['postgres_uid'], 'Database Pod changed during this lab.')
    require(pvc['metadata']['uid'] == baseline['pvc_uid'] and pvc['status']['phase'] == 'Bound', 'PVC changed/not bound.')
    verify_records(); external_check()
    slices = get('endpointslices', extra=('-l', 'kubernetes.io/service-name=meeps-api'))['items']
    ready_names = {e.get('targetRef', {}).get('name') for item in slices
                   for e in item.get('endpoints', []) if e.get('conditions', {}).get('ready') is True}
    require(ready_names == {p['metadata']['name'] for p in api_pods()},
            'Ready Service endpoints do not match current API Pods.')
    require(not run(['git', 'ls-files', '--', '.local/']).stdout.strip(), 'Private files are tracked.')
    print(k('get', 'deployment,replicaset,pods,hpa,pdb,svc,pvc', '-o', 'wide').stdout)
    print(k('top', 'nodes').stdout)
    print(k('top', 'pods', '-l', SELECTOR, '--containers').stdout)
    print(k('get', 'apiservice', 'v1beta1.metrics.k8s.io').stdout)
    print(k('get', 'nodes', '-o', 'wide').stdout)
    print(k('describe', 'hpa', 'meeps-api').stdout)
    save('final-result.json', {'result': 'PASS', 'at': now(), 'replicas': 2,
                             'metrics_available': True, 'hpa_min': 2, 'hpa_max': 5,
                             'pdb_min_available': 1, 'postgres_preserved': True,
                             'all_workers_schedulable': True})
    print('DAY 97 CHECKS PASSED. This local lab does not establish production HA or capacity sizing.')


class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, text):
        for s in self.streams: s.write(text); s.flush()
        return len(text)
    def flush(self):
        for s in self.streams: s.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ['preflight', 'handoff', 'load-stop', 'spread', 'drain', 'recover', 'final']:
        sub.add_parser(name)
    p = sub.add_parser('manual'); p.add_argument('replicas', type=int, choices=[2, 4])
    p = sub.add_parser('load-start'); p.add_argument('--rps', type=int, choices=[100, 200, 300, 400], default=200)
    p = sub.add_parser('observe'); p.add_argument('direction', choices=['out', 'in'])
    p.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT, 'Run from the repository root.')
    DOCS.mkdir(parents=True, exist_ok=True)
    suffix = args.action
    if args.action == 'manual': suffix += '-' + str(args.replicas)
    if args.action == 'observe': suffix += '-' + args.direction
    name = 'final-verification.txt' if args.action == 'final' else suffix + '-transcript.txt'
    destination = path(name); temporary = Path(str(destination) + '.tmp')
    old_stdout, old_stderr = sys.stdout, sys.stderr
    try:
        with temporary.open('w') as f:
            sys.stdout = Tee(old_stdout, f); sys.stderr = Tee(old_stderr, f)
            print('Day 97 checkpoint:', suffix, '|', now())
            try:
                globals()[args.action.replace('-', '_')](args)
            except Exception as exc:
                print('STOP:', exc, file=sys.stderr)
                raise
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    temporary.replace(destination)
    print('Saved:', destination.relative_to(ROOT))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted. Stop load and run recover if maintenance was started.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print('Checkpoint unsuccessful:', exc, file=sys.stderr)
        sys.exit(1)
