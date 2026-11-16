#!/usr/bin/env python3
"""Offline guardrail tests; no Docker/Kubernetes calls or external connections."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent

def module(name, file):
    spec = importlib.util.spec_from_file_location(name, HERE / file)
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj

lab = module('day97_lab', 'day97-lab.py')
load = module('day97_load', 'day97-load.py')

class Guardrails(unittest.TestCase):
    def pod(self):
        return {'metadata': {'name':'api-1','namespace':'meeps-dev',
                             'labels':{'app.kubernetes.io/name':'meeps-api',
                                       'app.kubernetes.io/instance':'meeps-dev'},
                             'ownerReferences':[{'kind':'ReplicaSet','name':'rs','controller':True}]},
                'spec': {'volumes':[{'name':'tmp','emptyDir':{}}]},
                'status': {'phase':'Running','conditions':[{'type':'Ready','status':'True'}]}}
    def test_annotation_removes_only_replicas(self):
        original = {'spec': {'replicas':2, 'template':{'spec': {'containers':[{'image':'unchanged'}]}}}}
        new = json.loads(lab.remove_replicas(json.dumps(original)))
        self.assertNotIn('replicas', new['spec'])
        self.assertEqual(new['spec']['template'], original['spec']['template'])
        self.assertEqual(original['spec']['replicas'], 2)
    def test_annotation_idempotent(self):
        s = '{"spec":{"template":{}}}'
        self.assertEqual(json.loads(lab.remove_replicas(s)), json.loads(s))
    def test_annotation_rejects_invalid(self):
        with self.assertRaises(ValueError): lab.remove_replicas('not JSON')
    def test_ready(self): self.assertTrue(lab.ready(self.pod()))
    def test_running_not_ready(self):
        p=self.pod(); p['status']['conditions'][0]['status']='False'
        self.assertFalse(lab.ready(p))
    def test_terminating_not_ready(self):
        p=self.pod(); p['metadata']['deletionTimestamp']='now'
        self.assertFalse(lab.ready(p))
    def test_drain_excludes_database(self):
        a,b=lab.WORKERS
        self.assertEqual(lab.safe_node(a,{a:1,b:1}),b)
    def test_drain_requires_api(self):
        a,b=lab.WORKERS
        with self.assertRaises(RuntimeError): lab.safe_node(a,{a:2})
    def test_drain_api_tmp_allowed(self): self.assertTrue(lab.allowed_for_drain(self.pod()))
    def test_drain_pvc_rejected(self):
        p=self.pod(); p['spec']['volumes']=[{'persistentVolumeClaim':{'claimName':'db'}}]
        self.assertFalse(lab.allowed_for_drain(p))
    def test_drain_hostpath_rejected(self):
        p=self.pod(); p['spec']['volumes']=[{'hostPath':{'path':'/data'}}]
        self.assertFalse(lab.allowed_for_drain(p))
    def test_drain_unrelated_rejected(self):
        p=self.pod(); p['metadata']['labels']['app.kubernetes.io/name']='other'
        self.assertFalse(lab.allowed_for_drain(p))
    def test_daemonsets_ignored(self):
        p=self.pod(); p['metadata']['ownerReferences'][0]['kind']='DaemonSet'
        self.assertTrue(lab.allowed_for_drain(p))
    def test_default_load_bounded(self):
        a=load.settings([])
        self.assertEqual((a.rps,a.seconds,a.concurrency),(200,540,16))
    def test_excess_load_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()):
            for args in [['--rps','401'], ['--seconds','601'], ['--concurrency','33'], ['--rps','0']]:
                with self.subTest(args=args), self.assertRaises(SystemExit): load.settings(args)
    def test_load_is_local_get_only(self):
        s=(HERE/'day97-load.py').read_text()
        self.assertIn("client.get('http://meeps-api/openapi.json'",s)
        self.assertNotIn('client.post(',s)
    def test_drain_does_not_disable_eviction(self):
        s=(HERE/'day97-lab.py').read_text()
        self.assertNotIn("'--disable-eviction'",s)
        self.assertNotIn("'--force'",s)

if __name__=='__main__': unittest.main()
