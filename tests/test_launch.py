import unittest
from unittest.mock import Mock,patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app'))
import launch


class LaunchTests(unittest.TestCase):
    def test_llama_loopback_hermes_minimum_context_and_quiet(self):
        with patch.object(launch.server,'initialize'),patch.object(launch.server,'verify_weights'),\
             patch.object(launch.server,'settings',return_value={'model':'qwen2.5-0.5b'}),\
             patch.object(launch.server.LOCAL_READY,'is_set',return_value=True),\
             patch.object(launch.subprocess,'Popen') as spawn,patch.object(launch.signal,'signal'),\
             patch.object(launch.threading,'Thread'),patch.object(launch.server,'main'):
            launch.main()
        args=spawn.call_args.args[0]
        self.assertEqual(args[args.index('--host')+1],'127.0.0.1')
        self.assertGreaterEqual(int(args[args.index('-c')+1]),64000)
        self.assertEqual(args[args.index('--parallel')+1],'1')
        self.assertIn('--log-disable',args)
        self.assertEqual(spawn.call_args.kwargs['stdout'],launch.subprocess.DEVNULL)
        self.assertEqual(spawn.call_args.kwargs['stderr'],launch.subprocess.DEVNULL)


if __name__=='__main__':unittest.main()
