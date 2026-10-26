"""Synthetic context preservation checks; no subject commands or Docker run."""
import copy
import hashlib
import io
import json
from pathlib import Path
import shlex
import tarfile
import tempfile
import unittest
from tramask_pilot import context_repair as cr


def bundle(directory, files, *, extra_members=()):
    directory.mkdir(parents=True, exist_ok=True)
    rows=[]
    archive=directory/'sources.tar.gz'
    with tarfile.open(archive,'w:gz') as tf:
        for name,data in files.items():
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644
            tf.addfile(info,io.BytesIO(data))
            rows.append({'path':'/'+name,'archive_path':name,'kind':'file','bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()})
        for info,data in extra_members:
            tf.addfile(info,io.BytesIO(data) if data is not None else None)
    manifest=directory/'manifest.json';manifest.write_text(json.dumps({'files':rows,'head':'a'*40,'base_commit':'a'*40}))
    patch=directory/'implementation.patch';patch.write_text('')
    receipt={'archive':str(archive),'manifest':str(manifest),'patch':str(patch),
        'archive_sha256':cr._sha(archive),'manifest_sha256':cr._sha(manifest),'patch_sha256':cr._sha(patch)}
    (directory/'receipt.json').write_text(json.dumps(receipt))
    return receipt


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_classification(self):
        paths=['tests/helpers.py','test/support.js','src/__tests__/helpers.ts','fixtures/logo.bin',
               'lib/retry_test.go','test_thing.py','conftest.py','WidgetTest.java','TestWidget.java','foo.test.ts','testdata/input.json']
        self.assertTrue(all(cr.is_test_context_path(p,repository_relative=True) for p in paths))
        c=cr.classify_historical_additions(paths+['src/new.py','deps/cache.py','README.md','node_modules/foo.js'],baseline_untracked=['deps/cache.py'])
        self.assertEqual(c['production_to_remove'],['src/new.py'])
        self.assertEqual(c['baseline_to_preserve'],['deps/cache.py','node_modules/foo.js'])
        self.assertFalse(cr.is_test_context_path('src/contest.py'))
    def test_archive_binary_complete_safe_deterministic(self):
        original={'app/tests/helpers.py':b'history','app/tests/fixtures/data.bin':b'\x00\xff',
                  'app/src/main.py':b'prod','tmp/custom_check':b'check','app/tests/.env':b'private'}
        snap=bundle(self.root/'historical',original)
        a=cr.build_test_context_archive(snap['archive'],self.root/'a',test_paths=['/tmp/custom_check'],manifest_path=snap['manifest'])
        b=cr.build_test_context_archive(snap['archive'],self.root/'b',test_paths=['/tmp/custom_check'],manifest_path=snap['manifest'])
        self.assertEqual(a['archive']['sha256'],b['archive']['sha256'])
        self.assertEqual({r['archive_path'] for r in a['files']},{'app/tests/helpers.py','app/tests/fixtures/data.bin','tmp/custom_check'})
        with tarfile.open(a['archive']['path']) as tf:
            self.assertTrue(all(m.isfile() and m.uid==0 and m.mtime==0 and not m.linkname for m in tf))
        self.assertFalse((self.root/'a/app').exists())
    def test_path_traversal_rejected(self):
        snap=bundle(self.root/'h',{'../app/tests/x.py':b'x'})
        with self.assertRaises(ValueError):cr.build_test_context_archive(snap['archive'],self.root/'o')
        self.assertFalse((self.root/'app').exists())
    def test_duplicate_member_rejected(self):
        m=tarfile.TarInfo('app/tests/x.py');m.size=1
        snap=bundle(self.root/'h',{'app/tests/x.py':b'x'},extra_members=[(m,b'z')])
        with self.assertRaisesRegex(ValueError,'duplicate'):cr.build_test_context_archive(snap['archive'],self.root/'o')
    def test_explicit_symlink_rejected(self):
        m=tarfile.TarInfo('app/tests/x.py');m.type=tarfile.SYMTYPE;m.linkname='/etc/passwd'
        snap=bundle(self.root/'h',{},extra_members=[(m,None)])
        with self.assertRaisesRegex(ValueError,'missing_or_nonregular'):cr.build_test_context_archive(snap['archive'],self.root/'o',test_paths=['/app/tests/x.py'])
    def test_hash_mismatch_rejected(self):
        snap=bundle(self.root/'h',{'app/tests/x.py':b'x'})
        m=json.loads(Path(snap['manifest']).read_text());m['files'][0]['sha256']='0'*64
        Path(snap['manifest']).write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):cr.build_test_context_archive(snap['archive'],self.root/'o',manifest_path=snap['manifest'])
    def test_patch_additions_text_and_binary(self):
        p=self.root/'p.patch';p.write_text('diff --git a/foo.test.py b/foo.test.py\nnew file mode 100644\n--- /dev/null\n+++ b/foo.test.py\n@@ -0,0 +1 @@\n++++ text\ndiff --git a/tests/data.bin b/tests/data.bin\nnew file mode 100644\nindex 000..abc\nGIT binary patch\nliteral 1\nabc\n')
        self.assertEqual(cr.patch_added_paths(p),['foo.test.py','tests/data.bin'])


class FakeContainer:
    fail_final=False
    extra_files={}
    last=None
    def __init__(self,image,output,head):
        self.image_id=image;self.output=Path(output);self.output.mkdir(parents=True);self.scratch='/tmp/fake-scratch'
        self.files={
          'app/src.py':b'historical-prod','app/tests/test_main.py':b'original test',
          'app/tests/helpers.py':b'historical helper','app/tests/fixture.bin':b'\x00data',
          'app/lib/extra_test.go':b'extra historical test','app/newimpl.py':b'historical-new',
          'app/newhelper.py':b'historical-helper','app/node_modules/preserve.js':b'dependency',
          'app/private_dependency.py':b'baseline dependency'}
        self.files.update(self.extra_files)
        self.tracked={'app/src.py','app/tests/test_main.py','app/tests/helpers.py'}
        self.baseline_untracked=[p[4:] for p in self.files if p.startswith('app/') and p not in self.tracked]
        self.copied={};self.records=[]
        FakeContainer.last=self
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def exec(self,command,label,timeout=180,workdir='/app'):
        result={'label':label,'command':command,'stdout':'','stderr':'','returncode':0,'timed_out':False,'transport_error':False}
        if label=='checkpoint_untracked_inventory':result['stdout']='\0'.join(self.baseline_untracked)+'\0'
        elif label=='historical_deleted_paths':result['stdout']='tests/old_deleted.py\0'
        elif label=='restore_base_source':
            self.files.update({'app/src.py':b'base prod','app/tests/test_main.py':b'base test',
                               'app/tests/helpers.py':b'base helper','app/tests/old_deleted.py':b'restored base deleted test'})
        elif label=='restore_historical_test_context':
            source=self.copied[shlex.split(command)[2]]
            with tarfile.open(source) as tf:
                for m in tf:self.files[m.name]=tf.extractfile(m).read()
        elif command.startswith('python3 -c '):
            payload=json.loads(Path(self.copied[shlex.split(command)[-1]]).read_text())
            for row in payload['files']:
                p=row['subject_path'].lstrip('/')
                if payload['action']=='remove':self.files.pop(p,None)
                elif payload['action']=='verify':
                    assert hashlib.sha256(self.files[p]).hexdigest()==row['sha256']
        elif label=='final_test_only':
            result['returncode']=1 # a genuine test failure must not block activation
            result['stdout']='1 failed, 2 passed'
            if self.fail_final:result.update(timed_out=True,returncode=124)
        else:raise AssertionError(label)
        self.records.append(result)
        return result
    def snapshot(self,label,extra_paths=()):
        explicit={p.lstrip('/') for p in extra_paths}
        names=self.tracked|explicit|{p for p in self.files if p.startswith('app/') and p not in {'app/'+x for x in self.baseline_untracked}}
        files={p:data for p,data in self.files.items() if p in names and not cr._blocked(p)}
        return bundle(self.output/'snapshots'/label,files)
    def copy_to(self,source,destination):self.copied[destination]=str(source)
    def copy_from(self,source,destination):
        p=Path(destination);p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(self.files[source.lstrip('/')]);return p
    def apply_patch(self,path,label):
        self.files.update({'app/src.py':b'delivered P','app/newimpl.py':b'P-new',
                           'app/tests/helpers.py':b'P helper must be reverted',
                           'app/tests/p_only_test.py':b'test absent historically'})
        directory=self.output/'patches'/label;directory.mkdir(parents=True)
        (directory/'implementation.patch').write_bytes(Path(path).read_bytes())
        r={'returncode':0};(directory/'result.json').write_text(json.dumps(r));return r
    def checkpoint(self,label):
        self.checkpoint_files=copy.deepcopy(self.files)
        return {'image_id':'sha256:'+'b'*64,'head':'a'*40}


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.run=Path(self.tmp.name)
        self.case=self.run/'runs/F001';self.old=self.case/'replay';self.old.mkdir(parents=True)
        self.primary={'execution_call_id':'s1_c0','test_command':'pytest tests/test_main.py',
          'test_paths':['/app/tests/test_main.py'],'source_paths':['src.py']}
        loc=self.case/'localization';loc.mkdir()
        (loc/'selection.json').write_text(json.dumps({'status':'located','primary':self.primary}))
        (loc/'command_review.json').write_text(json.dumps({'approved_for_isolated_replay':True,
          'selection_sha256':cr._sha(loc/'selection.json')}))
        self.checkpoint={'image_id':'sha256:'+'a'*64,'head':'a'*40}
        snapdir=self.old/'test_snapshot';snapdir.mkdir();test=snapdir/'00_test_main.py';test.write_bytes(b'original test')
        snap={'command':self.primary['test_command'],'working_directory':'/app','observation_paths':[],
          'context_image':self.checkpoint,'files':[{'subject_path':'/app/tests/test_main.py',**cr._receipt(test)}],
          'historical_production_additions_to_remove':['newimpl.py','newhelper.py','lib/extra_test.go']}
        (self.old/'test_snapshot.json').write_text(json.dumps(snap))
        bundle(self.old/'historical_sources',{'app/src.py':b'historical-prod','app/tests/test_main.py':b'original test','app/tests/helpers.py':b'historical helper'})
        summary={'id':'F001','selected_call':'s1_c0','status':'old','test_snapshot':cr._receipt(self.old/'test_snapshot.json'),
          'original_context_checkpoint':self.checkpoint,'final_context_checkpoint':self.checkpoint,
          'original_command_execution':{'command':self.primary['test_command']},
          'historical_test_only':{'command':self.primary['test_command'],'returncode':0},
          'final_test_only':{'command':self.primary['test_command'],'returncode':1}}
        (self.old/'summary.json').write_text(json.dumps(summary))
        (self.case/'active_replay.json').write_text(json.dumps({'directory':str(self.old),'summary':cr._receipt(self.old/'summary.json')}))
        inputs=self.run/'inputs/F001';inputs.mkdir(parents=True)
        (inputs/'model.patch').write_text('diff --git a/newimpl.py b/newimpl.py\nnew file mode 100644\n--- /dev/null\n+++ b/newimpl.py\n@@ -0,0 +1 @@\n+x\ndiff --git a/tests/p_only_test.py b/tests/p_only_test.py\nnew file mode 100644\n--- /dev/null\n+++ b/tests/p_only_test.py\n@@ -0,0 +1 @@\n+x\n')
        self.before={str(p.relative_to(self.old)):p.read_bytes() for p in self.old.rglob('*') if p.is_file()}
        FakeContainer.fail_final=False
        FakeContainer.extra_files={}
    def tearDown(self):self.tmp.cleanup()
    def test_complete_recovery_inherits_history_preserves_support_and_deps(self):
        r=cr.recover_final_context({'id':'F001','base_commit':'a'*40},run=self.run,container_factory=FakeContainer)
        self.assertTrue(r['activated']);self.assertEqual(r['final_returncode'],1)
        f=FakeContainer.last.checkpoint_files
        self.assertEqual(f['app/src.py'],b'delivered P')
        self.assertEqual(f['app/tests/helpers.py'],b'historical helper')
        self.assertEqual(f['app/tests/test_main.py'],b'original test')
        self.assertIn('app/lib/extra_test.go',f);self.assertIn('app/tests/fixture.bin',f)
        self.assertNotIn('app/tests/p_only_test.py',f);self.assertNotIn('app/tests/old_deleted.py',f)
        self.assertEqual(f['app/node_modules/preserve.js'],b'dependency')
        self.assertEqual(f['app/private_dependency.py'],b'baseline dependency')
        self.assertNotIn('app/newhelper.py',f)
        out=Path(r['directory']);summary=json.loads((out/'summary.json').read_text())
        self.assertEqual(summary['historical_test_only'],json.loads((self.old/'summary.json').read_text())['historical_test_only'])
        self.assertEqual(json.loads((out/'historical/records.json').read_text()),[])
        self.assertEqual(json.loads((out/'recovery.json').read_text())['original_replay'],str(self.old))
        self.assertEqual(self.before,{str(p.relative_to(self.old)):p.read_bytes() for p in self.old.rglob('*') if p.is_file()})
    def test_timeout_retains_old_pointer_and_failure_logs(self):
        FakeContainer.fail_final=True
        pointer=(self.case/'active_replay.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError,'runtime_failure'):
            cr.recover_final_context({'id':'F001','base_commit':'a'*40},run=self.run,container_factory=FakeContainer)
        self.assertEqual((self.case/'active_replay.json').read_bytes(),pointer)
        self.assertTrue((self.case/'replay_context_repair01/failure.json').is_file())
        self.assertFalse((self.case/'replay_context_repair01/summary.json').exists())
    def test_dry_activation_off_still_logs_actual_mock_execution(self):
        pointer=(self.case/'active_replay.json').read_bytes()
        r=cr.recover_final_context({'id':'F001','base_commit':'a'*40},run=self.run,container_factory=FakeContainer,activate=False)
        self.assertFalse(r['activated']);self.assertEqual((self.case/'active_replay.json').read_bytes(),pointer)

    def test_explicit_addendum_recovers_tmp_tests_and_binds_evidence(self):
        from tramask_pilot import evidence
        FakeContainer.extra_files={'tmp/test_http_edge.py':b'original HTTP test',
                                   'tmp/test_ws_incremental.py':b'original WS test'}
        path=self.case/'localization/test_context_addendum.json'
        value={'additional_test_paths':['/tmp/test_http_edge.py','/tmp/test_ws_incremental.py'],
               'reason':'These original files are also executed by the selected compound command.'}
        path.write_text(json.dumps(value))
        selection_before=(self.case/'localization/selection.json').read_bytes()
        result=cr.recover_final_context({'id':'F001','base_commit':'a'*40},run=self.run,container_factory=FakeContainer)
        snapshot=json.loads((Path(result['directory'])/'test_snapshot.json').read_text())
        self.assertEqual({r['subject_path'] for r in snapshot['files']},
                         {'/app/tests/test_main.py','/tmp/test_http_edge.py','/tmp/test_ws_incremental.py'})
        self.assertEqual(snapshot['test_context_addendum']['sha256'],cr._sha(path))
        self.assertEqual(len(evidence._selection(self.case)[2]),3)
        self.assertEqual((self.case/'localization/selection.json').read_bytes(),selection_before)
        value['reason']='Changed after the frozen snapshot.';path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError,'addendum_not_bound'):
            evidence._selection(self.case)

    def test_public_noncode_patch_collision_is_archived_before_clear(self):
        FakeContainer.extra_files={'app/docs/change.rst':b'historical docs'}
        patch=self.run/'inputs/F001/model.patch'
        patch.write_text(patch.read_text()+'diff --git a/docs/change.rst b/docs/change.rst\nnew file mode 100644\n--- /dev/null\n+++ b/docs/change.rst\n@@ -0,0 +1 @@\n+new\n')
        result=cr.recover_final_context({'id':'F001','base_commit':'a'*40},run=self.run,container_factory=FakeContainer)
        manifest=json.loads((Path(result['directory'])/'historical_sources_supplement01/manifest.json').read_text())
        row=next(row for row in manifest['files'] if row['path']=='/app/docs/change.rst')
        self.assertEqual(row['sha256'],hashlib.sha256(b'historical docs').hexdigest())


def test_large_context_uses_copied_payload_not_shell_argument(tmp_path):
    runtime=FakeContainer('sha256:'+'a'*64,tmp_path/'runtime','a'*40)
    rows=[{'subject_path':f'/app/tests/fixture_{i:06d}.py'} for i in range(20000)]
    result=cr._path_operation(runtime,'preflight',rows,'large_context_preflight')
    assert len(result['command'].encode())<4096
    assert result['context_operation_payload']['bytes']>1_000_000

