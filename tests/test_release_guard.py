import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import urllib.error

spec=importlib.util.spec_from_file_location('release_guard',Path(__file__).resolve().parents[1]/'tools/assert_new_version.py')
guard=importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class ReleaseGuardTests(unittest.TestCase):
    def invoke(self, response):
        with patch.dict(os.environ,{'VERSION':'0.1.0','GITHUB_REPOSITORY':'example-org/wizard-local-model','GH_TOKEN':'fixture-not-real'}),patch.object(guard.urllib.request,'urlopen',side_effect=response),contextlib.redirect_stdout(io.StringIO()):
            guard.main()
    def test_existing_version_refused(self):
        with self.assertRaisesRegex(RuntimeError,'existing version'):
            self.invoke([io.BytesIO(json.dumps([{'metadata':{'container':{'tags':['0.1.0']}}}]).encode())])
    def test_new_version_allowed(self):
        self.invoke([io.BytesIO(b'[]')])
    def test_first_package_not_found_allowed(self):
        self.invoke(urllib.error.HTTPError('https://fixture',404,'not found',None,None))
    def test_discovery_failure_never_publishes(self):
        with self.assertRaisesRegex(RuntimeError,'no publish'):
            self.invoke(urllib.error.HTTPError('https://fixture',403,'forbidden',None,None))


if __name__=='__main__': unittest.main()
