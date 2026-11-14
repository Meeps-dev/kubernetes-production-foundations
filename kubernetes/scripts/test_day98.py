#!/usr/bin/env python3
"""Offline guardrail tests; no Docker or Kubernetes mutations."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('day98', Path(__file__).with_name('day98-lab.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def template():
    return {'metadata': {'labels': {'app.kubernetes.io/name': 'meeps-api'}},
            'spec': {'serviceAccountName': 'meeps-api', 'automountServiceAccountToken': False,
                     'nodeSelector': {'meeps.dev/node-pool': 'worker'},
                     'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001,
                                         'seccompProfile': {'type': 'RuntimeDefault'}},
                     'topologySpreadConstraints': [{'labelSelector': {'matchLabels': {'app.kubernetes.io/name': 'meeps-api'}}}],
                     'containers': [{'name': 'api', 'image': 'meeps-users-posts-api:week14-v2',
                        'command': ['python','-m','uvicorn'], 'args':['app.main:app'],
                        'env': [{'name': 'DATABASE_URL', 'valueFrom': {'secretKeyRef': {'name':'meeps-api-credentials','key':'DATABASE_URL'}}}],
                        'readinessProbe': {'httpGet': {'path': '/ready', 'port': 'http'}},
                        'startupProbe': {'httpGet': {'path': '/health', 'port': 'http'}},
                        'livenessProbe': {'httpGet': {'path': '/health', 'port': 'http'}},
                        'securityContext': {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False,
                                            'capabilities': {'drop': ['ALL']}},
                        'resources': {'requests': {'cpu':'100m','memory':'128Mi'}, 'limits':{'cpu':'500m','memory':'256Mi'}}}],
                     'volumes': [{'name':'tmp','emptyDir':{'sizeLimit':'64Mi'}}]}}


class TestSafety(unittest.TestCase):
    def setUp(self):
        self.t = template()

    def test_distinct_labels(self):
        d,s = m.make_canary(self.t)
        self.assertEqual(d['spec']['replicas'],1)
        self.assertEqual(d['spec']['strategy']['type'],'Recreate')
        self.assertNotEqual(s['spec']['selector']['app.kubernetes.io/name'],'meeps-api')
        self.assertEqual(s['spec']['selector'],d['spec']['selector']['matchLabels'])

    def test_clone_does_not_modify_original(self):
        original=copy.deepcopy(self.t); m.make_canary(self.t)
        self.assertEqual(self.t,original)

    def test_clone_keeps_security_and_secret_ref(self):
        d,_ = m.make_canary(self.t); p=d['spec']['template']['spec']
        self.assertFalse(p['automountServiceAccountToken'])
        self.assertEqual(p['securityContext']['runAsUser'],10001)
        self.assertEqual(p['containers'][0]['env'],self.t['spec']['containers'][0]['env'])
        self.assertNotIn('topologySpreadConstraints',p)

    def test_no_pvc_mount(self):
        self.t['spec']['volumes']=[{'name':'db','persistentVolumeClaim':{'claimName':'db'}}]
        with self.assertRaises(RuntimeError): m.make_canary(self.t)

    def test_no_inline_credential(self):
        self.t['spec']['containers'][0]['env']=[{'name':'DATABASE_URL','value':'do-not-print'}]
        with self.assertRaises(RuntimeError): m.make_canary(self.t)

    def test_no_unreviewed_sidecar(self):
        self.t['spec']['containers'].append({'name':'extra'})
        with self.assertRaises(RuntimeError): m.make_canary(self.t)

    def test_missing_key_only_changes_reference(self):
        with patch.object(m,'healthy_canary',return_value=m.make_canary(self.t)):
            d,_=m.fault_objects('secret-key')
        ref=d['spec']['template']['spec']['containers'][0]['env'][0]['valueFrom']['secretKeyRef']
        self.assertEqual(ref['name'],'meeps-api-credentials')
        self.assertEqual(ref['key'],'DAY98_INTENTIONALLY_ABSENT')
        self.assertFalse(ref['optional'])

    def test_readiness_does_not_break_liveness(self):
        with patch.object(m,'healthy_canary',return_value=m.make_canary(self.t)):
            d,_=m.fault_objects('readiness')
        c=d['spec']['template']['spec']['containers'][0]
        self.assertEqual(c['readinessProbe']['httpGet']['path'],'/__day98_wrong_ready')
        self.assertEqual(c['livenessProbe']['httpGet']['path'],'/health')

    def test_crash_known_exit(self):
        with patch.object(m,'healthy_canary',return_value=m.make_canary(self.t)):
            d,_=m.fault_objects('crash')
        c=d['spec']['template']['spec']['containers'][0]
        self.assertEqual(c['command'],['python','-c'])
        self.assertIn('sys.exit(42)',c['args'][0])

    def test_selector_only_targets_canary(self):
        with patch.object(m,'healthy_canary',return_value=m.make_canary(self.t)):
            d,s=m.fault_objects('selector')
        self.assertEqual(s['metadata']['name'],m.CANARY)
        self.assertNotIn('meeps.dev/intentionally-missing', d['spec']['template']['metadata']['labels'])

    def test_refuses_unowned_resource(self):
        with self.assertRaises(RuntimeError): m.own({'metadata':{'name':'meeps-api','labels':{}}})

    def test_duplicate_yaml_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'x.yaml'; p.write_text('a: 1\na: 2\n')
            with self.assertRaises(ValueError): m.load_yaml(p)

    def test_safe_yaml_rejects_python_tag(self):
        with self.assertRaises(m.yaml.YAMLError):
            list(m.yaml.load_all('!!python/object/apply:os.system [echo nope]',Loader=m.UniqueLoader))

    def test_secret_example_has_only_placeholders(self):
        self.assertTrue(m.placeholder_secret({'kind':'Secret','stringData':{'DATABASE_URL':'postgresql://u:GENERATE_LOCALLY@db/d'}}))
        self.assertFalse(m.placeholder_secret({'kind':'Secret','stringData':{'password':'actual-value'}}))
        self.assertFalse(m.placeholder_secret({'kind':'Secret','data':{'password':'eA=='}}))

    def test_index_credential_match_does_not_print_value(self):
        token=b'0123456789SECRETpassword'
        hits=m.index_findings(['notes.md'],lambda _: b'copied '+token,{token})
        self.assertTrue(hits); self.assertNotIn(token.decode(),str(hits))

    def test_private_index_path_detected(self):
        hits=m.index_findings(['.local/meeps-dev/secret.local.yaml'],lambda _: b'x: y',set())
        self.assertTrue(hits)

    def test_index_allow_placeholder_example(self):
        doc={'kind':'Secret','stringData':{'key':'GENERATE_LOCALLY'}}
        hits=m.index_findings(['kubernetes/examples/s.yaml'],lambda _: json.dumps(doc).encode(),set())
        self.assertEqual(hits,[])

    def test_index_rejects_secret_in_other_path(self):
        doc={'kind':'Secret','data':{'key':'eA=='}}
        hits=m.index_findings(['kubernetes/base/s.json'],lambda _: json.dumps(doc).encode(),set())
        self.assertTrue(hits)

    def test_code_containing_key_detector_does_not_self_flag(self):
        data=Path(m.__file__).read_bytes()
        hits=m.index_findings(['kubernetes/scripts/day98-lab.py'],lambda _:data,set())
        self.assertEqual(hits,[])

    def test_latest_rejected(self):
        o={'kind':'Deployment','metadata':{'name':'meeps-api'},'spec':{'template':self.t}}
        o['spec']['template']['spec']['containers'][0]['image']='example:latest'
        with self.assertRaises(RuntimeError): m.deployment_security(o)

    def test_fixed_replicas_rejected_under_hpa(self):
        o={'kind':'Deployment','metadata':{'name':'meeps-api'},'spec':{'replicas':2,'template':self.t}}
        with self.assertRaises(RuntimeError): m.deployment_security(o)

    def test_api_security_accepts_baseline(self):
        m.deployment_security({'kind':'Deployment','metadata':{'name':'meeps-api'},'spec':{'template':self.t}})

    def test_wrong_kind_mapping_rejected(self):
        o={'apiVersion':'kind.x-k8s.io/v1alpha4','kind':'Cluster','nodes':[{'role':'control-plane'},{'role':'worker'},{'role':'worker'}]}
        with self.assertRaises(RuntimeError): m.validate_kind(o)

    def test_no_teardown_without_explicit_confirmation(self):
        import argparse
        with self.assertRaises(RuntimeError): m.teardown(argparse.Namespace(confirm='yes'))


    def test_validate_uses_dry_run_and_correct_namespace(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'kubernetes/cluster').mkdir(parents=True)
            service={'apiVersion':'v1','kind':'Service',
                     'metadata':{'name':'traefik','namespace':'traefik-system'},
                     'spec':{'ports':[{'port':80}]}}
            (root/'kubernetes/cluster/service.yaml').write_text(json.dumps(service))
            with patch.object(m,'ROOT',root), patch.object(m,'check_cluster_saved'), \
                 patch.object(m,'save'), patch.object(m,'k',return_value=SimpleNamespace(returncode=0,stdout='',stderr='')) as k:
                m.validate(None)
                self.assertEqual(k.call_count,2)
                for call in k.call_args_list:
                    self.assertEqual(call.kwargs['ns'],'traefik-system')
                    if call.args[0]=='apply': self.assertIn('--dry-run=server',call.args)

    def test_placeholder_secret_never_sent_to_cluster(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); (root/'kubernetes/examples').mkdir(parents=True)
            secret={'apiVersion':'v1','kind':'Secret','metadata':{'name':'example'},
                    'stringData':{'password':'GENERATE_LOCALLY'}}
            (root/'kubernetes/examples/secret.example.yaml').write_text(json.dumps(secret))
            with patch.object(m,'ROOT',root), patch.object(m,'check_cluster_saved'), \
                 patch.object(m,'save'), patch.object(m,'k') as k:
                m.validate(None)
                k.assert_not_called()


if __name__=='__main__':
    unittest.main(verbosity=2)
