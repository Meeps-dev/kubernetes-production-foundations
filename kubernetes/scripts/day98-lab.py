#!/usr/bin/env python3
"""Day 98 checkpoints. Run from the repo root using Python 3.9+ and PyYAML 6.0.3.
Cluster writes before explicit teardown are confined to one labeled canary Deployment/Service.
No production credentials are printed, exported, changed, or included in generated manifests.
"""
import argparse
import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener

import yaml

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / 'kubernetes/docs'
CONFIG = Path.home() / '.kube/meeps-k8s-cluster.yaml'
CTX = 'kind-meeps-k8s-cluster'
CLUSTER = 'meeps-k8s-cluster'
NS = 'meeps-dev'
CANARY = 'meeps-day98-canary'
MARK = 'meeps.dev/day98-owner'
OWNER = 'failure-lab-v1'
API_SELECTOR = 'app.kubernetes.io/name=meeps-api,app.kubernetes.io/instance=meeps-dev'
CANARY_SELECTOR = 'app.kubernetes.io/name=' + CANARY
FAULTS = ('readiness', 'secret-key', 'crash', 'selector')
ALLOWED_IMAGES = ('meeps-users-posts-api:k8s-baseline', 'meeps-users-posts-api:k8s-v1',
                  'meeps-users-posts-api:k8s-v2', 'meeps-users-posts-api:week14-v2')


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def run(cmd, data=None, check=True, timeout=240, binary=False):
    p = subprocess.run([str(x) for x in cmd], input=data, capture_output=True,
                       text=not binary, timeout=timeout, cwd=ROOT,
                       env={**os.environ, 'DOCKER_CONTEXT': 'desktop-linux',
                            'KIND_EXPERIMENTAL_PROVIDER': 'docker'})
    if check and p.returncode:
        # Do not print the full command: some commands contain synthetic fixture JSON.
        out = p.stdout + p.stderr
        if binary:
            out = out.decode('utf-8', 'replace')
        raise RuntimeError('Command failed: ' + str(cmd[0]) + '\n' + out)
    return p


def k(*args, ns=NS, data=None, check=True, timeout=240):
    return run(['kubectl', '--kubeconfig', CONFIG, '--context', CTX,
                '-n', ns, *args], data, check, timeout)


def get(kind, name=None, ns=NS, selector=None):
    args = ['get', kind] + ([name] if name else [])
    if selector:
        args += ['-l', selector]
    return json.loads(k(*args, '-o', 'json', ns=ns).stdout)


def optional(kind, name, ns=NS):
    p = k('get', kind, name, '--ignore-not-found', '-o', 'json', ns=ns)
    return json.loads(p.stdout) if p.stdout.strip() else None


def file(suffix):
    return DOCS / ('day-98-' + suffix)


def save(suffix, value):
    target = file(suffix)
    temp = Path(str(target) + '.tmp')
    temp.write_text(value if isinstance(value, str) else json.dumps(value, indent=2) + '\n')
    temp.replace(target)


def saved(suffix):
    p = file(suffix)
    require(p.is_file(), 'Missing checkpoint: ' + str(p.relative_to(ROOT)))
    x = json.loads(p.read_text())
    require(x.get('result') == 'PASS', 'Checkpoint did not pass: ' + suffix)
    return x


def cond(obj):
    return {x['type']: x for x in obj.get('status', {}).get('conditions', [])}


def ready(pod):
    return (not pod['metadata'].get('deletionTimestamp')
            and pod.get('status', {}).get('phase') == 'Running'
            and cond(pod).get('Ready', {}).get('status') == 'True')


def wait(fn, message, timeout=240, interval=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if value:
            return value
        time.sleep(interval)
    raise RuntimeError('Timed out: ' + message)


def cluster_id():
    require(Path.cwd().resolve() == ROOT, 'Run from the repository root.')
    require(CONFIG.is_file(), 'Lab kubeconfig is missing; activate the session helper.')
    require(k('config', 'current-context').stdout.strip() == CTX, 'Wrong context in lab kubeconfig.')
    return get('namespace', 'kube-system')['metadata']['uid']


def check_cluster_saved():
    b = saved('baseline.json')
    require(cluster_id() == b['cluster_uid'], 'The recorded cluster no longer matches this cluster.')
    return b


def api_pods():
    return get('pods', selector=API_SELECTOR)['items']


def main_health():
    nodes = get('nodes')['items']
    require({x['metadata']['name'] for x in nodes} ==
            {CLUSTER + '-control-plane', CLUSTER + '-worker', CLUSTER + '-worker2'},
            'Unexpected nodes; wrong cluster or incomplete topology.')
    for n in nodes:
        require(cond(n).get('Ready', {}).get('status') == 'True', 'A node is not Ready.')
        require(not n['spec'].get('unschedulable'), 'A node is still cordoned.')
        require(not any(cond(n).get(t, {}).get('status') == 'True' for t in
                        ('MemoryPressure', 'DiskPressure', 'PIDPressure')), 'Node pressure detected.')
    d = get('deployment', 'meeps-api')
    n = d['spec'].get('replicas', 1)
    require(2 <= n <= 5, 'API desired count is outside the configured HPA range.')
    pods = api_pods()
    require(d['status'].get('observedGeneration', 0) >= d['metadata']['generation'], 'Deployment is not reconciled.')
    require(all(d['status'].get(f, 0) == n for f in ('updatedReplicas', 'readyReplicas', 'availableReplicas')),
            'API replicas are not all updated, ready and available.')
    require(len(pods) == n and all(ready(p) for p in pods), 'API rollout is still settling or unhealthy.')
    h = get('hpa', 'meeps-api')
    require(h['spec'].get('minReplicas') == 2 and h['spec']['maxReplicas'] == 5, 'HPA range changed.')
    require(all(cond(h).get(t, {}).get('status') == 'True' for t in ('AbleToScale', 'ScalingActive')),
            'Current HPA is unhealthy; inspect its live conditions. No Day 97 report is required.')
    pdb = get('pdb', 'meeps-api')
    require(pdb['spec'].get('minAvailable') == 1, 'Normal PDB has not been restored.')
    require(optional('job', 'meeps-day97-load') is None, 'Stop the Day 97 load Job first.')
    pg = get('pod', 'postgres-0'); pvc = get('pvc', 'postgres-data-postgres-0')
    require(ready(pg) and pvc['status']['phase'] == 'Bound', 'PostgreSQL/PVC are unhealthy.')
    with build_opener(ProxyHandler({})).open(
            Request('http://127.0.0.1:8080/ready', headers={'Host': 'api.meeps.local'}), timeout=10) as r:
        require(r.status == 200 and json.load(r) == {'status': 'ready'}, 'Ingress readiness failed.')
    print(k('get', 'deployment,pods,hpa,pdb,svc,pvc', '-o', 'wide').stdout)
    return {'postgres_uid': pg['metadata']['uid'], 'pvc_uid': pvc['metadata']['uid'],
            'api_template': d['spec']['template'], 'hpa_spec': h['spec'], 'pdb_spec': pdb['spec'],
            'api_service_spec': get('service', 'meeps-api')['spec']}


def unchanged(b):
    fresh = main_health()
    for key in ('postgres_uid', 'pvc_uid', 'api_template', 'hpa_spec', 'pdb_spec', 'api_service_spec'):
        require(fresh[key] == b[key], 'Protected resource changed during Day 98: ' + key)


def verify_records():
    fixture_path = ROOT / 'kubernetes/docs/day-94-fixture.json'
    script = ROOT / 'kubernetes/scripts/day96-verify.py'
    require(fixture_path.is_file() and script.is_file(), 'Original fixture or GET-only verifier missing.')
    fixture = json.loads(fixture_path.read_text())
    require(fixture.get('result') == 'PASS', 'Original fixture is not a successful test result.')
    pods = [p for p in api_pods() if ready(p)]
    require(pods, 'No ready API Pod for read-only verification.')
    out = k('exec', '-i', pods[0]['metadata']['name'], '-c', 'api', '--', 'python', '-',
            '--expect-version', 'week14-v2', '--fixture-json', json.dumps(fixture), data=script.read_text()).stdout
    x = json.loads(out); require(x.get('result') == 'PASS', 'Original record verification failed.')
    print(out); return x


def preflight(_):
    # Independent Day 98: require live safety checks, not earlier exercise reports.
    print('Day 98 live checks only. Day 97 drain deferred; no drain success claimed.')
    uid = cluster_id()
    health = main_health(); verify_records()
    main = load_yaml(ROOT / 'kubernetes/base/api-deployment.yaml')[0]
    require('replicas' not in main['spec'], 'Saved API manifest still controls replicas; finish HPA handoff.')
    last = get('deployment', 'meeps-api')['metadata'].get('annotations', {}).get(
        'kubectl.kubernetes.io/last-applied-configuration')
    require(last and 'replicas' not in json.loads(last)['spec'], 'Last-applied annotation still owns replicas.')
    require(not run(['git', 'ls-files', '--', '.local/']).stdout, 'Private files are tracked or staged.')
    require(optional('deployment', CANARY) is None and optional('service', CANARY) is None,
            'Existing Day 98 canary: inspect or run recover; do not reset the baseline.')
    save('baseline.json', {'result': 'PASS', 'at': now(), 'cluster_uid': uid,
                          'readiness_basis': 'live_day98_checks',
                          'day97_drain': 'DEFERRED_NOT_VERIFIED', **health})
    print('PREFLIGHT PASSED. Main workloads unchanged; no fault resources created.')


def api_container(template):
    cs = template['spec']['containers']
    require(len(cs) == 1 and cs[0]['name'] == 'api', 'Expected a single api container; inspect before cloning.')
    return cs[0]


def make_canary(template):
    tpl = copy.deepcopy(template)
    tpl['metadata'] = {'labels': {'app.kubernetes.io/name': CANARY,
                                 'app.kubernetes.io/instance': 'meeps-dev', MARK: OWNER}}
    spec = tpl['spec']
    for key in ('topologySpreadConstraints', 'affinity', 'nodeName'):
        spec.pop(key, None)
    c = api_container(tpl)
    require(c['image'] == 'meeps-users-posts-api:week14-v2', 'Unexpected baseline image.')
    for e in c.get('env', []):
        require(not (re.search(r'PASSWORD|TOKEN|SECRET|DATABASE_URL', e['name']) and 'value' in e),
                'Sensitive literal environment setting; use the existing Secret references.')
    require(not spec.get('initContainers'), 'Canary cloning does not allow unreviewed init containers.')
    require(all('persistentVolumeClaim' not in v and 'hostPath' not in v for v in spec.get('volumes', [])),
            'Canary must not mount persistent or host storage.')
    c['imagePullPolicy'] = 'Never'
    dep = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
           'metadata': {'name': CANARY, 'namespace': NS, 'labels': {MARK: OWNER}},
           'spec': {'replicas': 1, 'strategy': {'type': 'Recreate'}, 'revisionHistoryLimit': 1,
                    'minReadySeconds': 0, 'progressDeadlineSeconds': 180,
                    'selector': {'matchLabels': {'app.kubernetes.io/name': CANARY}}, 'template': tpl}}
    svc = {'apiVersion': 'v1', 'kind': 'Service',
           'metadata': {'name': CANARY, 'namespace': NS, 'labels': {MARK: OWNER}},
           'spec': {'type': 'ClusterIP', 'selector': {'app.kubernetes.io/name': CANARY},
                    'ports': [{'name': 'http', 'port': 80, 'targetPort': 'http'}]}}
    return dep, svc


def healthy_canary():
    b = saved('baseline.json')
    return make_canary(b['api_template'])


def own(obj):
    require(obj['metadata']['name'] == CANARY and obj['metadata'].get('labels', {}).get(MARK) == OWNER,
            'Refusing to modify an unowned canary resource.')


def apply_canary(dep, svc):
    for obj in (svc, dep):
        require(obj['metadata']['name'] == CANARY, 'Only the canary can be applied by this helper.')
        previous = optional(obj['kind'], CANARY)
        if previous:
            own(previous)
        else:
            print(k('create', '-f', '-', data=json.dumps(obj)).stdout)
            continue
        print(k('apply', '-f', '-', data=json.dumps(obj)).stdout)


def canary_pods():
    return [p for p in get('pods', selector=CANARY_SELECTOR)['items']
            if not p['metadata'].get('deletionTimestamp')]


def one_canary():
    p = canary_pods()
    return p[0] if len(p) == 1 else None


def endpoints(name=CANARY):
    slices = get('endpointslices', selector='kubernetes.io/service-name=' + name)['items']
    return [e for s in slices for e in s.get('endpoints', [])]


def healthy_endpoints():
    return [e for e in endpoints() if e.get('conditions', {}).get('ready') is True]


def service_request(expect_success):
    pods = [p for p in api_pods() if ready(p)]
    require(pods, 'No healthy main API Pod for HTTP client.')
    script = '''import json, sys
from urllib.request import build_opener, ProxyHandler
from urllib.error import HTTPError, URLError
try:
    with build_opener(ProxyHandler({})).open('http://meeps-day98-canary/ready',timeout=5) as r:
        ok = r.status == 200 and json.load(r) == {'status':'ready'}
        print(json.dumps({'success':ok,'http_status':r.status}))
except (HTTPError, URLError, TimeoutError, OSError) as e:
    print(json.dumps({'success':False,'error_type':type(e).__name__}))
'''
    result = json.loads(k('exec', '-i', pods[0]['metadata']['name'], '-c', 'api', '--',
                          'python', '-', data=script).stdout)
    require(result['success'] is expect_success, 'Unexpected canary Service response: ' + str(result))
    print(json.dumps(result)); return result


def settled_canary():
    d = get('deployment', CANARY)
    p = one_canary()
    return (p and ready(p) and d['status'].get('observedGeneration', 0) >= d['metadata']['generation']
            and d['status'].get('availableReplicas') == 1)


def restore_canary():
    dep, svc = healthy_canary()
    apply_canary(dep, svc)
    wait(settled_canary, 'one healthy canary replica', 240)
    wait(lambda: len(healthy_endpoints()) == 1, 'ready canary Service backend', 90)
    service_request(True)


def setup(_):
    b = check_cluster_saved(); unchanged(b)
    restore_canary()
    dep, svc = healthy_canary()
    save('canary-healthy.json', {'apiVersion': 'v1', 'kind': 'List', 'items': [dep, svc]})
    print('CANARY READY. Separate selectors; no Ingress/HPA/PDB targets this test Deployment.')


def event_objects(pod):
    return get('events', selector=None)['items'] if not pod else json.loads(k(
        'get', 'events', '--field-selector', 'involvedObject.uid=' + pod['metadata']['uid'], '-o', 'json').stdout)['items']


def fault_objects(which):
    dep, svc = healthy_canary(); c = api_container(dep['spec']['template'])
    if which == 'readiness':
        c['readinessProbe']['httpGet']['path'] = '/__day98_wrong_ready'
    elif which == 'secret-key':
        refs = [e for e in c.get('env', []) if e['name'] == 'DATABASE_URL']
        require(len(refs) == 1 and 'secretKeyRef' in refs[0].get('valueFrom', {}), 'Missing database Secret reference.')
        refs[0]['valueFrom']['secretKeyRef']['key'] = 'DAY98_INTENTIONALLY_ABSENT'
        refs[0]['valueFrom']['secretKeyRef']['optional'] = False
    elif which == 'crash':
        c['command'] = ['python', '-c']
        c['args'] = ["import sys; print('DAY98_INTENTIONAL_CRASH',flush=True); sys.exit(42)"]
    elif which == 'selector':
        svc['spec']['selector']['meeps.dev/intentionally-missing'] = 'yes'
    else:
        raise RuntimeError('Unknown fault')
    return dep, svc


def symptom(which):
    p = one_canary()
    if not p:
        return False
    statuses = p.get('status', {}).get('containerStatuses', [])
    state = statuses[0] if statuses else {}
    waiting = state.get('state', {}).get('waiting', {}).get('reason')
    if which == 'readiness':
        msgs = [e.get('message', '') for e in event_objects(p)]
        return (p.get('status', {}).get('phase') == 'Running' and not ready(p)
                and any('Readiness probe failed' in m and '404' in m for m in msgs)
                and not healthy_endpoints())
    if which == 'secret-key':
        return waiting == 'CreateContainerConfigError' and any(
            'DAY98_INTENTIONALLY_ABSENT' in e.get('message', '') for e in event_objects(p))
    if which == 'crash':
        return (waiting == 'CrashLoopBackOff' and state.get('restartCount', 0) >= 1
                and state.get('lastState', {}).get('terminated', {}).get('exitCode') == 42)
    if which == 'selector':
        return ready(p) and not endpoints()
    return False


def fault(args):
    b = check_cluster_saved(); unchanged(b)
    restore_canary()
    previous_pass = file('fault-' + args.scenario + '.json')
    if previous_pass.exists():
        previous_pass.unlink()  # A failed rerun must not leave a stale PASS for this drill.
    dep, svc = fault_objects(args.scenario)
    save('fault-' + args.scenario + '-request.json', {'apiVersion': 'v1', 'kind': 'List', 'items': [dep, svc]})
    error = None; observed = False
    try:
        apply_canary(dep, svc)
        wait(lambda: symptom(args.scenario), 'expected ' + args.scenario + ' symptom', 240)
        p = one_canary(); name = p['metadata']['name']
        snapshots = {'pod': p, 'events': event_objects(p), 'endpoints': endpoints(),
                     'service_selector': get('service', CANARY)['spec']['selector']}
        print(k('get', 'pods', '-l', CANARY_SELECTOR, '-o', 'wide').stdout)
        for e in snapshots['events']:
            print(e.get('reason', ''), e.get('message', ''))
        save('fault-' + args.scenario + '-observed.json', snapshots)
        describe = k('describe', 'pod', name).stdout
        save('fault-' + args.scenario + '-describe.txt', describe)
        if args.scenario == 'crash':
            logs = k('logs', name, '-c', 'api', '--previous', '--tail=30').stdout
            require('DAY98_INTENTIONAL_CRASH' in logs, 'Expected previous-container crash log missing.')
        elif args.scenario == 'secret-key':
            logs = 'Container did not start; application logs are not expected. See events.\n'
        else:
            logs = k('logs', name, '-c', 'api', '--tail=30').stdout
        print(logs); save('fault-' + args.scenario + '-logs.txt', logs)
        service_request(False)
        unchanged(b); verify_records()
        observed = True
    except BaseException as exc:
        error = exc
    finally:
        try:
            restore_canary()
            print('RECOVERY: canary is ready and Service responds again.')
        except BaseException as recovery_error:
            print('RECOVERY INCOMPLETE: run the recover checkpoint.', file=sys.stderr)
            if error is None:
                error = recovery_error
    if error:
        raise error
    require(observed, 'Expected fault not observed.')
    unchanged(b)
    save('fault-' + args.scenario + '.json', {'result': 'PASS', 'scenario': args.scenario,
           'at': now(), 'cluster_uid': b['cluster_uid'], 'failure_observed': True,
           'canary_repaired': True, 'main_api_verified_before_after': True})
    print('FAULT AND RECOVERY PASSED:', args.scenario)


def remove_canary(_):
    check_cluster_saved()
    for kind in ('deployment', 'service'):
        o = optional(kind, CANARY)
        if o:
            own(o)
            print(k('delete', kind, CANARY, '--wait=true', '--timeout=120s').stdout)
    wait(lambda: not get('pods', selector=CANARY_SELECTOR)['items'], 'canary Pods removed', 120)
    print('Only the Day 98 canary resources were removed.')


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    loader.flatten_mapping(node)
    pairs = loader.construct_pairs(node, deep=deep)
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate YAML key: ' + str(key))
        result[key] = value
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def load_yaml(p):
    return list(yaml.load_all(p.read_text(), Loader=UniqueLoader))


def items(o):
    if isinstance(o, dict) and o.get('kind') == 'List':
        return o.get('items', [])
    return [o]


def is_resource(o):
    return isinstance(o, dict) and 'apiVersion' in o and 'kind' in o and o.get('metadata', {}).get('name')


def placeholder_secret(o):
    if o.get('kind') != 'Secret':
        return True
    if o.get('data'):
        return False
    values = o.get('stringData', {}).values()
    return all(isinstance(v, str) and any(t in v for t in ('GENERATE_LOCALLY', 'REPLACE_ME', 'CHANGE_ME'))
               for v in values)


def validate_kind(o):
    require(o.get('apiVersion') == 'kind.x-k8s.io/v1alpha4' and o.get('kind') == 'Cluster', 'Unexpected kind config.')
    roles = [n.get('role') for n in o.get('nodes', [])]
    require(roles.count('control-plane') == 1 and roles.count('worker') == 2, 'Expected 1 control plane + 2 workers.')
    maps = [m for n in o['nodes'] for m in n.get('extraPortMappings', [])]
    expected = {(30080, 8080, '127.0.0.1'), (30443, 8443, '127.0.0.1')}
    require(expected <= {(m['containerPort'], m['hostPort'], m.get('listenAddress')) for m in maps},
            'kind host mappings differ from this lab.')


def deployment_security(o):
    if o.get('kind') not in ('Deployment', 'StatefulSet', 'Job'):
        return
    pod = o['spec']['template']['spec']; security = pod.get('securityContext', {})
    for c in pod.get('containers', []):
        image = c['image']
        require('@sha256:' in image or (':' in image.rsplit('/', 1)[-1] and not image.endswith(':latest')),
                'Missing version pin/latest tag: ' + o['metadata']['name'])
        if o['metadata']['name'] in ('meeps-api', 'postgres', 'traefik', 'meeps-db-migrate-day93'):
            sc = c.get('securityContext', {})
            require(sc.get('allowPrivilegeEscalation') is False, 'Privilege escalation not disabled.')
            require(sc.get('readOnlyRootFilesystem') is True, 'Root filesystem is not read-only.')
            require('ALL' in sc.get('capabilities', {}).get('drop', []), 'Capabilities not fully dropped.')
            require(security.get('runAsNonRoot') is True, 'Workload not configured non-root.')
            require((sc.get('seccompProfile') or security.get('seccompProfile', {})).get('type') == 'RuntimeDefault',
                    'Seccomp RuntimeDefault missing.')
            require(c.get('resources', {}).get('requests') and c.get('resources', {}).get('limits'),
                    'Resource requests or limits missing.')
        if o['metadata']['name'] == 'meeps-api':
            require('replicas' not in o['spec'], 'Do not validate/reapply a fixed API replica count after HPA handoff.')
            require(pod.get('automountServiceAccountToken') is False, 'API token mounting enabled.')
            require(security.get('runAsUser') == 10001 and security.get('runAsGroup') == 10001, 'Wrong API UID/GID.')


def rendered_patch(p, doc):
    rel = p.relative_to(ROOT).as_posix()
    if p.name == 'kind-local-tls.patch.json':
        target = ROOT / 'kubernetes/cluster/metrics-server/components-v0.9.1.yaml'
        metrics = [o for d in load_yaml(target) for o in items(d)
                   if is_resource(o) and o['kind'] == 'Deployment' and o['metadata']['name'] == 'metrics-server']
        require(len(metrics) == 1, 'Metrics Server patch target missing.')
        baseline = metrics[0]; typ = 'json'
    elif 'day-95-api-probes.patch' in rel or 'day-96-rollout.patch' in rel or 'day-97-topology.patch' in rel:
        baseline = load_yaml(ROOT / 'kubernetes/base/api-deployment.yaml')[0]; typ = 'strategic'
    else:
        return None
    pch = k('patch', '--local', '--type=' + typ, '-f', '-', '-p', json.dumps(doc), '-o', 'json',
            data=json.dumps(baseline),
            ns=baseline.get('metadata', {}).get('namespace', NS))
    return json.loads(pch.stdout)


def validate(_):
    check_cluster_saved()
    rows = []; problems = []; differences = []
    sources = sorted(p for p in (ROOT / 'kubernetes').rglob('*') if p.suffix in ('.yaml', '.yml', '.json'))
    for p in sources:
        rel = p.relative_to(ROOT).as_posix()
        if p.is_symlink():
            problems.append(rel + ': symlink not accepted'); continue
        try:
            docs = [d for d in load_yaml(p) if d is not None]
            row = {'path': rel, 'syntax': 'PASS', 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
            if '/docs/' in rel:
                row['scope'] = 'capture/snapshot: syntax only, never reapplied'
            elif p.name == 'kind-config.yaml':
                require(len(docs) == 1, 'Multiple kind configs in one file.')
                validate_kind(docs[0]); row['scope'] = 'kind configuration: syntax + lab invariants; not a Kubernetes API object'
            elif '.patch.' in p.name:
                require(len(docs) == 1, 'Unexpected multi-document patch.')
                rendered = rendered_patch(p, docs[0])
                require(rendered is not None, 'Unknown patch target; explicitly review and classify this file.')
                k('apply', '--dry-run=server', '--validate=strict', '-f', '-', data=json.dumps(rendered),
                  ns=rendered.get('metadata', {}).get('namespace', NS))
                row['scope'] = 'patch rendered into target + server dry run only; NEVER applied/diffed as desired state'
            else:
                objects = [o for doc in docs for o in items(doc)]
                require(objects and all(is_resource(o) for o in objects), 'Not a complete Kubernetes resource; classify explicitly.')
                if any(o['kind'] == 'Secret' for o in objects):
                    require('/examples/' in rel and all(placeholder_secret(o) for o in objects),
                            'Real/encoded Secret in deployable tree; move to ignored local storage.')
                    row['scope'] = 'placeholder Secret: syntax/placeholder checks only; no API request or diff'
                elif '/examples/' in rel:
                    if any(str(o['apiVersion']).startswith('gateway.networking.k8s.io/') for o in objects):
                        row['scope'] = 'optional Gateway reference: syntax only; not deployed or server-validated'
                    else:
                        k('apply', '--dry-run=server', '--validate=strict', '-f', '-',
                          data=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': objects}))
                        row['scope'] = 'lab/example resources: server dry run only; NEVER applied/diffed as desired state'
                else:
                    require('/base/' in rel or '/cluster/' in rel, 'Unknown deployment scope.')
                    for o in objects:
                        deployment_security(o)
                        namespace = o.get('metadata', {}).get('namespace', NS)
                        k('apply', '--dry-run=server', '--validate=strict', '-f', '-', data=json.dumps(o), ns=namespace)
                        diff = k('diff', '-f', '-', data=json.dumps(o), ns=namespace, check=False)
                        require(diff.returncode in (0, 1), 'kubectl diff failed: ' + diff.stderr)
                        key = o['kind'] + '/' + o['metadata']['name']
                        print('DIFF', key, 'exit=' + str(diff.returncode))
                        if diff.returncode == 1:
                            differences.append({'file': rel, 'resource': key, 'diff': diff.stdout})
                    row['scope'] = 'canonical resource: security/image checks + server dry run + diff'
            rows.append(row); print(row['path'] + ': ' + row['scope'])
        except Exception as exc:
            problems.append(rel + ': ' + str(exc))
            print('FAILED:', problems[-1])
    report = {'result': 'PASS' if not problems else 'FAIL', 'at': now(), 'files': rows,
              'problems': problems, 'differences': differences,
              'note': 'PASS covers the explicitly listed scope; reference-only files are not live-validated.'}
    save('validation-inventory.json', report)
    save('manifest-diff.txt', '\n\n'.join(x['file'] + ' ' + x['resource'] + '\n' + x['diff'] for x in differences)
         or 'No differences found in canonical resources.\n')
    require(not problems, 'Manifest validation failed. Review inventory; do not blanket-apply fixes.')
    print('VALIDATION COMPLETE. Review day-98-manifest-diff.txt; diff exit 1 means differences, not a CLI error.')


def known_secret_material():
    tokens = set()
    for name in ('secret.local.yaml', 'api-secret.local.yaml'):
        p = ROOT / '.local/meeps-dev' / name
        if not p.exists():
            continue
        for obj in load_yaml(p):
            require(isinstance(obj, dict) and obj.get('kind') == 'Secret', 'Unexpected local credential file structure.')
            for val in obj.get('data', {}).values():
                require(isinstance(val, str), 'Malformed Secret data value.')
                tokens.add(val.encode())
                try:
                    tokens.add(base64.b64decode(val, validate=True))
                except ValueError:
                    raise RuntimeError('Malformed base64 in local Secret file.')
            tokens.update(str(v).encode() for v in obj.get('stringData', {}).values())
    # Decode DATABASE_URL credentials as separate strings as well.
    from urllib.parse import urlsplit, unquote
    for t in list(tokens):
        if t.startswith(b'postgresql://'):
            u = urlsplit(t.decode())
            if u.password:
                tokens.add(unquote(u.password).encode())
    return {t for t in tokens if len(t) >= 12}


def index_findings(names, reader, tokens):
    findings = []
    for name in names:
        leaf = Path(name).name
        if name.startswith('.local/') or leaf.endswith('.kubeconfig') or leaf in ('secret.local.yaml', 'api-secret.local.yaml'):
            findings.append(name + ': private file in index')
        if leaf.startswith('.env') and not (leaf.endswith('.example') or leaf == '.env.example'):
            findings.append(name + ': environment file in index')
        data = reader(name)
        if any(t in data for t in tokens):
            findings.append(name + ': matches known local credential material (value suppressed)')
        if re.search(rb'(?m)^-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', data):
            findings.append(name + ': private key marker')
        if name.endswith(('.yaml', '.yml', '.json')):
            try:
                docs = list(yaml.load_all(data.decode(), Loader=UniqueLoader))
                for d in docs:
                    for o in items(d):
                        if isinstance(o, dict) and o.get('kind') == 'Secret':
                            if '/examples/' not in name or not placeholder_secret(o):
                                findings.append(name + ': non-placeholder Secret object in index')
            except (UnicodeDecodeError, yaml.YAMLError, ValueError):
                pass
    return sorted(set(findings))


def git_audit(_):
    raw = run(['git', 'ls-files', '-z'], binary=True).stdout
    names = [s.decode() for s in raw.split(b'\0') if s]
    tokens = known_secret_material()
    findings = index_findings(names, lambda n: run(['git', 'show', ':' + n], binary=True).stdout, tokens)
    for p in ('.local/meeps-dev/secret.local.yaml', '.local/meeps-dev/api-secret.local.yaml'):
        require(run(['git', 'check-ignore', '--quiet', '--no-index', p], check=False).returncode == 0,
                'Private Secret path is not ignored: ' + p)
    if findings:
        print('\n'.join(findings))
    save('git-index-audit.json', {'result': 'FAIL' if findings else 'PASS', 'at': now(),
         'files_checked': len(names), 'findings': findings,
         'scope': 'Current Git index plus exact known local credentials and basic markers; not a full secret/history scanner.'})
    require(not findings, 'Secret/index review failed. Do not commit or publish.')
    print('GIT INDEX CHECK PASSED. Review diffs/logs/screenshots manually; history is not certified.')


def troubleshooting():
    cases = {
        'readiness': ('Pod Running but not Ready; readiness HTTP 404; no ready canary backend',
                      'kubectl -n meeps-dev describe pod <canary-pod>',
                      'The readiness URL was intentionally changed to a nonexistent path.',
                      'Reapply the healthy canary template with /ready.',
                      'Test endpoint contracts before deployment; inspect Pod conditions and endpoints.'),
        'secret-key': ('CreateContainerConfigError; no application process/logs',
                       'kubectl -n meeps-dev describe pod <canary-pod>',
                       'DATABASE_URL referenced an intentionally nonexistent key in the existing Secret.',
                       'Restore the DATABASE_URL key reference; do not regenerate passwords.',
                       'Validate Secret key names and namespace references; never dump values into logs.'),
        'crash': ('CrashLoopBackOff; previous container exit code 42',
                  'kubectl -n meeps-dev logs <canary-pod> -c api --previous',
                  'The entrypoint printed a known marker and deliberately exited with code 42.',
                  'Restore the normal Uvicorn command/arguments through the healthy template.',
                  'Test the container entrypoint and keep previous-container logs and exit codes.'),
        'selector': ('Ready canary Pod, but its Service has no endpoints and HTTP cannot succeed',
                     'kubectl -n meeps-dev get endpointslice -l kubernetes.io/service-name=meeps-day98-canary',
                     'A Service selector term matched no Pod label.',
                     'Restore the saved Service selector; no Pod or database reset.',
                     'Check selectors against Pod labels and verify EndpointSlices after deployment.')}
    out = ['# Day 98 — Recorded failure investigations', '',
           'Only scenarios with a generated PASS result are marked verified. All faults used the isolated canary.', '']
    for name in FAULTS:
        r = saved('fault-' + name + '.json'); details = cases[name]
        out += ['## ' + name, '', '- **Initial symptom:** ' + details[0],
                '- **First diagnostic command:** `kubectl -n meeps-dev get pods -l app.kubernetes.io/name=meeps-day98-canary`',
                '- **Focused follow-up:** `' + details[1] + '`',
                '- **Relevant log/event:** `day-98-fault-' + name + '-observed.json` and `day-98-fault-' + name + '-logs.txt`.',
                '- **Root cause:** ' + details[2], '- **Correct fix:** ' + details[3],
                '- **Preventive control:** ' + details[4], '- **Verified recovery:** ' + r['at'], '']
    save('troubleshooting.md', '\n'.join(out))


def final(args):
    b = check_cluster_saved()
    for f in FAULTS:
        require(saved('fault-' + f + '.json')['cluster_uid'] == b['cluster_uid'], 'Fault evidence is from another cluster.')
    require(optional('deployment', CANARY) is None and optional('service', CANARY) is None,
            'Remove the recovered canary first.')
    unchanged(b); verify_records()
    v = saved('validation-inventory.json')
    for x in v['files']:
        if '/docs/' in x['path']:
            continue  # Capture files can be regenerated without changing deployment configuration.
        p = ROOT / x['path']
        require(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == x['sha256'],
                'A validated manifest changed; rerun validate: ' + x['path'])
    require(args.reviewed, 'Review the diff and security exceptions, then supply --reviewed. No changes are auto-applied.')
    git_audit(None)
    troubleshooting()
    live_rows = []
    for kind, name, namespace in (('deployment', 'meeps-api', NS), ('statefulset', 'postgres', NS),
                                  ('deployment', 'traefik', 'traefik-system'),
                                  ('deployment', 'metrics-server', 'kube-system')):
        workload = get(kind, name, ns=namespace)
        policy_copy = copy.deepcopy(workload)
        if name == 'meeps-api':
            policy_copy['spec'].pop('replicas', None)  # Live replicas correctly belong to HPA.
        deployment_security(policy_copy)
        pod = workload['spec']['template']['spec']
        for c in pod['containers']:
            live_rows.append({'namespace': namespace, 'workload': name, 'container': c['name'],
                              'image': c['image'], 'pod_security': pod.get('securityContext', {}),
                              'container_security': c.get('securityContext', {}),
                              'service_account': pod.get('serviceAccountName'),
                              'token_automount': pod.get('automountServiceAccountToken', 'default'),
                              'resources': c.get('resources', {})})
    save('live-security-review.json', live_rows)
    print(json.dumps(live_rows, indent=2))
    print(k('get', 'nodes', '-o', 'wide').stdout)
    print(k('get', 'deployment,replicaset,pods,svc,hpa,pdb,pvc', '-o', 'wide').stdout)
    print(k('get', 'endpointslice', '-l', 'kubernetes.io/service-name=meeps-api').stdout)
    print(k('top', 'nodes').stdout); print(k('top', 'pods', '-l', API_SELECTOR, '--containers').stdout)
    print(k('rollout', 'history', 'deployment/meeps-api').stdout)
    print(k('logs', '-l', API_SELECTOR, '-c', 'api', '--prefix=true', '--tail=15').stdout)
    save('final-result.json', {'result': 'PASS', 'at': now(), 'cluster_uid': b['cluster_uid'],
         'four_canary_faults_repaired': True, 'database_preserved': True,
         'manifest_review_attested': True, 'teardown_completed': False})
    print('DAY 98 PRE-TEARDOWN CHECKS PASSED. Review captures, complete docs, commit/push before deletion.')


def teardown(args):
    require(args.confirm == 'DELETE-meeps-k8s-cluster', 'Explicit deletion confirmation is required.')
    r = saved('final-result.json')
    require(cluster_id() == r['cluster_uid'], 'Refusing to delete a cluster different from the verified cluster.')
    require(not run(['git', 'status', '--porcelain']).stdout.strip(),
            'Commit/review all non-ignored files before deleting the cluster.')
    require(run(['git', 'ls-files', '--error-unmatch', 'kubernetes/docs/day-98-final-result.json'],
                check=False).returncode == 0, 'Final result is not saved in Git.')
    require(not run(['git', 'ls-files', '--', '.local/']).stdout.strip(), 'Private files are tracked.')
    for name in ('secret.local.yaml', 'api-secret.local.yaml'):
        p = ROOT / '.local/meeps-dev' / name
        require(not p.is_symlink(), 'Refusing symlinked private file: ' + name)
    require(not CONFIG.is_symlink(), 'Refusing symlinked kubeconfig.')
    for p in (ROOT / '.local/meeps-dev', ROOT / '.env.preflight'):
        require(not p.is_symlink(), 'Refusing symlinked cleanup path: ' + str(p))
        require(ROOT.resolve() in p.resolve().parents, 'Private cleanup path resolves outside the repository.')
    print('DELETING local kind cluster and its node-local PostgreSQL data. This is not reversible without your own backup.')
    print(run(['kind', 'delete', 'cluster', '--name', CLUSTER, '--kubeconfig', CONFIG], timeout=300).stdout)
    names = run(['kind', 'get', 'clusters']).stdout.splitlines()
    require(CLUSTER not in names, 'Cluster still listed after deletion.')
    containers = run(['docker', '--context', 'desktop-linux', 'ps', '-aq', '--filter',
                      'label=io.x-k8s.kind.cluster=' + CLUSTER]).stdout.strip()
    require(not containers, 'Some cluster containers remain; private files retained for investigation.')
    deleted = []
    for p in (ROOT / '.local/meeps-dev/secret.local.yaml', ROOT / '.local/meeps-dev/api-secret.local.yaml',
              ROOT / '.env.preflight', CONFIG):
        require(not p.is_symlink(), 'Refusing to remove symlink: ' + str(p))
        if p.is_file():
            p.unlink(); deleted.append(str(p.relative_to(ROOT)) if ROOT in p.parents else '~/.kube/meeps-k8s-cluster.yaml')
    save('teardown-result.json', {'result': 'PASS', 'at': now(), 'cluster': CLUSTER,
         'cluster_nodes_absent': True, 'removed_private_files': deleted,
         'note': 'File deletion is not guaranteed secure erasure; backups/snapshots/history require separate review.'})
    print('TEARDOWN VERIFIED. Only the named cluster and listed private files were removed.')


def images(args):
    require(not run(['docker', '--context', 'desktop-linux', 'ps', '-aq', '--filter',
                     'label=io.x-k8s.kind.cluster=' + CLUSTER]).stdout.strip(), 'Cluster containers still exist.')
    saved('teardown-result.json')
    rows = []
    for image in ALLOWED_IMAGES:
        found = run(['docker', '--context', 'desktop-linux', 'image', 'inspect', image], check=False)
        if found.returncode:
            continue
        used = run(['docker', '--context', 'desktop-linux', 'ps', '-aq', '--filter', 'ancestor=' + image]).stdout.strip()
        row = {'image': image, 'in_use': bool(used), 'removed': False}
        if args.remove and not used:
            p = run(['docker', '--context', 'desktop-linux', 'image', 'rm', '--no-prune', image], check=False)
            row['removed'] = p.returncode == 0
            if p.returncode:
                print('SKIPPED removal:', image, p.stderr)
        print(json.dumps(row)); rows.append(row)
    if args.remove:
        save('image-cleanup.json', {'at': now(), 'images': rows,
             'note': 'No forced deletion, global prune, or shared postgres/traefik/kindest image cleanup.'})


class Tee:
    def __init__(self, *streams): self.streams = streams
    def write(self, s):
        for out in self.streams: out.write(s); out.flush()
        return len(s)
    def flush(self):
        for out in self.streams: out.flush()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ('preflight', 'setup', 'recover', 'remove-canary', 'validate', 'git-audit'):
        sub.add_parser(name)
    f = sub.add_parser('fault'); f.add_argument('scenario', choices=FAULTS)
    f = sub.add_parser('final'); f.add_argument('--reviewed', action='store_true')
    f = sub.add_parser('teardown'); f.add_argument('--confirm', required=True)
    f = sub.add_parser('images'); f.add_argument('--remove', action='store_true')
    args = parser.parse_args()
    require(Path.cwd().resolve() == ROOT, 'Run from repository root.')
    DOCS.mkdir(exist_ok=True, parents=True)
    if args.action == 'final' and file('final-result.json').exists():
        file('final-result.json').unlink()
    suffix = args.action + ('-' + args.scenario if args.action == 'fault' else '')
    dest = file('final-verification.txt' if args.action == 'final' else suffix + '-transcript.txt')
    temp = Path(str(dest) + '.tmp')
    oldout, olderr = sys.stdout, sys.stderr
    # Teardown requires a clean tree. Its transcript is opened only after its clean-tree check.
    if args.action == 'teardown':
        teardown(args); return
    try:
        with temp.open('w') as f:
            sys.stdout = Tee(oldout, f); sys.stderr = Tee(olderr, f)
            print('Day 98 checkpoint:', suffix, '|', now())
            if args.action == 'recover':
                check_cluster_saved(); restore_canary(); print('CANARY RESTORED. No success result fabricated.')
            else:
                globals()[args.action.replace('-', '_')](args)
    finally:
        sys.stdout, sys.stderr = oldout, olderr
    temp.replace(dest)
    print('Saved:', dest.relative_to(ROOT))


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nInterrupted. Use recover for an interrupted canary drill; cluster deletion is separate.', file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print('STOP:', exc, file=sys.stderr)
        sys.exit(1)
