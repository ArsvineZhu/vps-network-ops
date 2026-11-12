import importlib.util
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('lab', ROOT/'ebpf/lab.py')
labmod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labmod)

class FakeRunner:
    def __init__(self):
        self.commands = []
        self.names = {'existing-important': (2, 1)}
        self.filters = []
        self.qdiscs = []
        self.fail_command = None
        self.uncertain_add = False
    def identity(self, name):
        return self.names[name]
    def run(self, args):
        self.commands.append(args)
        if self.fail_command is not None and len(self.commands) == self.fail_command:
            raise subprocess.TimeoutExpired(args, 30)
        if args == ['ip', '-j', 'netns', 'list']:
            return json.dumps([{'name': n} for n in self.names])
        if args[:3] == ['ip', 'netns', 'add']:
            if args[3] in self.names:
                raise labmod.SafetyError('exists')
            self.names[args[3]] = (2, len(self.names)+10)
            if self.uncertain_add:
                raise subprocess.TimeoutExpired(args, 30)
            return ''
        if args[:3] == ['ip', 'netns', 'delete']:
            del self.names[args[3]]
            return ''
        if args[:3] != ['ip', 'netns', 'exec']:
            raise AssertionError(f'Unexpected host command: {args}')
        ns, cmd = args[3], args[4:]
        assert ns in self.names and ns.startswith('tcpfp-')
        if cmd[:4] == ['tc', '-j', 'filter', 'show']:
            return json.dumps(self.filters)
        if cmd[:4] == ['tc', '-j', 'qdisc', 'show']:
            return json.dumps(self.qdiscs)
        if cmd[:3] == ['tc', 'qdisc', 'add']:
            self.qdiscs.append({'kind': 'clsact'}); return ''
        if cmd[:3] == ['tc', 'filter', 'add']:
            pref = int(cmd[cmd.index('pref')+1])
            self.filters.append(self.entry(pref));return ''
        if cmd[:3] == ['tc', 'filter', 'del']:
            assert cmd == ['tc', 'filter', 'del', 'dev', 'c0', 'egress', 'chain', '0',
                           'protocol', 'ip', 'pref', '49152', 'handle', '1', 'bpf']
            self.filters = [e for e in self.filters if e['pref'] != 49152]
            return ''
        if cmd[:2] == ['ip', 'link'] or cmd[:2] == ['ip', 'addr']:
            return ''
        raise AssertionError(f'Unexpected namespace command: {cmd}')
    @staticmethod
    def entry(pref, ident=73):
        return {'kind':'bpf','pref':pref,'protocol':'ip','chain':0,
                'options':{'handle':'0x1','prog':{'id':ident,'tag':'0123456789abcdef'}}}

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.lab = labmod.Lab(self.runner, '123456abcdef')
    def test_owned_setup_cleanup_preserves_foreign(self):
        client, server = self.lab.setup()
        links=[c for c in self.runner.commands if 'veth' in c]
        self.assertEqual(len(links),1)
        self.assertEqual(links[0][:4], ['ip','netns','exec',client.name])
        self.assertEqual(links[0][-2:], ['netns',server.name])
        self.lab.cleanup();self.lab.cleanup()
        self.assertEqual(self.runner.names,{'existing-important':(2,1)})
    def test_name_collision_never_deleted(self):
        self.runner.names['tcpfp-123456abcdef-client']=(2,55)
        with self.assertRaises(labmod.SafetyError): self.lab.create('client')
        self.lab.cleanup()
        self.assertFalse(any('delete' in c for c in self.runner.commands))
    def test_uncertain_creation_is_not_retried_or_deleted(self):
        self.runner.uncertain_add=True
        with self.assertRaises(subprocess.TimeoutExpired): self.lab.create('client')
        self.lab.cleanup()
        self.assertEqual(len(self.lab.notes),1)
        self.assertIn('tcpfp-123456abcdef-client',self.runner.names)
        self.assertFalse(any('delete' in c for c in self.runner.commands))
    def test_replaced_namespace_never_touched(self):
        ns=self.lab.create('client');self.runner.names[ns.name]=(9,99)
        with self.assertRaises(labmod.SafetyError): ns.run(['true'])
        with self.assertRaises(labmod.SafetyError): self.lab.cleanup()
        self.assertFalse(any('delete' in c or 'exec' in c for c in self.runner.commands))
    def test_partial_setup_failure_cleans_only_confirmed(self):
        # At each operation fail before execution; prior successful resources
        # remain the only resources eligible for cleanup.
        for fail_at in range(1,12):
            r=FakeRunner();l=labmod.Lab(r,'123456abcdef');r.fail_command=fail_at
            try:l.setup()
            except subprocess.TimeoutExpired:pass
            r.fail_command=None;l.cleanup()
            self.assertEqual(r.names,{'existing-important':(2,1)})
    def test_exact_filter_delete_preserves_foreign_and_qdisc(self):
        ns=self.lab.create('client');self.runner.filters=[FakeRunner.entry(123)]
        f=labmod.Filter(ns,'c0',49152);f.attach(Path('clean.o'),'tc_ios');f.detach()
        self.assertEqual([e['pref'] for e in self.runner.filters],[123])
        self.assertEqual(self.runner.qdiscs,[{'kind':'clsact'}])
        self.assertFalse(any(c[4:7]==['tc','qdisc','del'] for c in self.runner.commands))
    def test_pref_collision_never_replaced(self):
        ns=self.lab.create('client');self.runner.filters=[FakeRunner.entry(49152,9)]
        with self.assertRaises(labmod.SafetyError): labmod.Filter(ns,'c0',49152).attach(Path('clean.o'),'tc_ios')
        self.assertFalse(any(c[4:7] in (['tc','filter','add'],['tc','filter','del']) for c in self.runner.commands))
    def test_changed_filter_identity_never_deleted(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152);f.attach(Path('clean.o'),'tc_win')
        self.runner.filters[0]['options']['prog']['id']=74
        with self.assertRaises(labmod.SafetyError):f.detach()
        self.assertFalse(any(c[4:7]==['tc','filter','del'] for c in self.runner.commands))
    def test_unknown_json_fails_closed(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152);f.attach(Path('clean.o'),'tc_ios')
        del self.runner.filters[0]['options']['prog']['tag']
        with self.assertRaises(labmod.SafetyError):f.detach()
        self.assertFalse(any(c[4:7]==['tc','filter','del'] for c in self.runner.commands))
    def test_unconfirmed_filter_cannot_be_deleted(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152)
        with self.assertRaises(labmod.SafetyError):f.detach()
    def test_argument_validation(self):
        with self.assertRaises(ValueError):labmod.Lab(self.runner,'../unsafe')
        ns=self.lab.create('client')
        with self.assertRaises(ValueError):labmod.Filter(ns,'c0;evil',49152)
        with self.assertRaises(ValueError):labmod.Filter(ns,'c0',0)
        with self.assertRaises(ValueError):labmod.Filter(ns,'c0',49152).attach(Path('x'),'bad-section')
    def test_process_cleanup_error_cannot_report_success(self):
        self.lab.create('client')
        process=Mock();process.poll.return_value=None
        process.terminate.side_effect=OSError('cannot stop')
        report={}
        with self.assertRaises(labmod.SafetyError):labmod.cleanup_resources(self.lab,[process],report)
        self.assertFalse(report['cleanup_complete'])
        self.assertEqual(report['process_cleanup_errors'],['cannot stop'])
        self.assertEqual(self.runner.names,{'existing-important':(2,1)})
    def test_namespace_cleanup_error_is_reported(self):
        ns=self.lab.create('client');self.runner.names[ns.name]=(9,99);report={}
        with self.assertRaises(labmod.SafetyError):labmod.cleanup_resources(self.lab,[],report)
        self.assertFalse(report['cleanup_complete'])
        self.assertIn('identity changed',report['namespace_cleanup_error'])
    def test_stop_escalates_only_own_process(self):
        process=Mock();process.poll.return_value=None
        process.wait.side_effect=[subprocess.TimeoutExpired('own-process',10),0]
        labmod.stop_process(process)
        process.terminate.assert_called_once();process.kill.assert_called_once()
        self.assertEqual(process.wait.call_count,2)
    def test_absent_confirmed_namespace_reports_failure_not_broad_delete(self):
        ns=self.lab.create('client');del self.runner.names[ns.name]
        with self.assertRaises(labmod.SafetyError):self.lab.cleanup()
        self.assertFalse(any('delete' in c for c in self.runner.commands))
    def test_flat_tc_schema_is_rejected(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152)
        entry=FakeRunner.entry(49152);entry['options'].update(entry['options'].pop('prog'))
        with self.assertRaises(labmod.SafetyError):f.fingerprint(entry)
    def test_stats_snapshot_before_detach(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152);f.attach(Path('clean.o'),'tc_ios')
        responses=[json.dumps({'id':73,'map_ids':[8]}),
                   json.dumps({'id':8,'name':'stats'}),json.dumps([{'key':0,'value':2}])]
        with patch.object(ns,'run',side_effect=responses) as run:
            result=f.read_stats()
        self.assertTrue(result['available'])
        self.assertEqual(result['maps'][0]['values'],[{'key':0,'value':2}])
        self.assertEqual(run.call_count,3)
    def test_missing_bpftool_is_explicitly_unavailable(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152);f.attach(Path('clean.o'),'tc_ios')
        with patch.object(ns,'run',side_effect=FileNotFoundError('bpftool')):
            result=f.read_stats()
        self.assertFalse(result['available']);self.assertIn('bpftool',result['reason'])
    def test_stats_without_owned_program_rejected(self):
        ns=self.lab.create('client');f=labmod.Filter(ns,'c0',49152)
        with self.assertRaises(labmod.SafetyError):f.read_stats()
    def test_default_cli_is_dry_run(self):
        with patch('sys.argv',['lab.py']), patch.object(labmod.Runner,'run',side_effect=AssertionError('No commands allowed')), patch('builtins.print'):
            self.assertEqual(labmod.main(),0)

if __name__=='__main__': unittest.main()
