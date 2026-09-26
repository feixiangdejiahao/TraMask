"""Retrospective component replay; never a full repository or agent replay.
Extract candidate function bodies. Dependencies are declared minimal stubs.
For mergeText, inject normalized hunks at its only dependency seam; for Pebble,
replace base.SeqNum with uint64 and stub elapsed time and Batch fields.
"""
from pathlib import Path
import json, hashlib, subprocess, os
ROOT=Path(__file__).resolve().parents[2]
TRIALS=ROOT/'results/expanded_trials_20260926/trials'

def added_file(trial, name):
 text=(TRIALS/trial/'model.patch').read_text()
 block=text.split('diff --git a/'+name+' b/'+name+'\n',1)[1].split('\ndiff --git ',1)[0]
 return '\n'.join(line[1:] for line in block.splitlines() if line.startswith('+') and not line.startswith('+++'))+'\n'
def function(text, signature):
 start=text.index(signature)
 end=text.index('\n}',start)+2
 return text[start:end]

def run(trial,source,tests,transformations):
 out=TRIALS/trial/'review_evidence/component_replay';out.mkdir(parents=True,exist_ok=True)
 (out/'candidate.go').write_text(source)
 (out/'candidate_test.go').write_text(tests)
 env=dict(os.environ,GO111MODULE='off',GOCACHE=str(ROOT/'results/expanded_trials_20260926/go_component_cache'),GOTOOLCHAIN='local',GOPROXY='off')
 cmd=['/usr/local/go/bin/go','test','-count=1','-v','.']
 p=subprocess.run(cmd,cwd=out,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=60)
 (out/'stdout.txt').write_text(p.stdout)
 record={'scope':'component only, NOT repository replay','trial':trial,'command':cmd,'cwd':str(out.relative_to(ROOT)),'exit_code':p.returncode,'transformations':transformations,'patch_sha256':hashlib.sha256((TRIALS/trial/'model.patch').read_bytes()).hexdigest(),'files':[{'path':f.name,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()} for f in [out/'candidate.go',out/'candidate_test.go',out/'stdout.txt']]}
 (out/'result.json').write_text(json.dumps(record,indent=2)+'\n')
 print(trial,p.returncode,p.stdout)

trial='go-git-worktree-merge-conflicts__ruQZqrh'
s=added_file(trial,'worktree_merge.go')
f=function(s,'func mergeText(')
f=f.replace('func mergeText(base, ours, theirs string) (string, bool) {\n\toursDiffs := diff.Do(base, ours)\n\ttheirsDiffs := diff.Do(base, theirs)\n\toHunks := normalizeMergeHunks(oursDiffs)\n\ttHunks := normalizeMergeHunks(theirsDiffs)', 'func mergeText(base string, oHunks, tHunks []mergeHunk) (string, bool) {')
assert 'diff.Do' not in f
source='package review\nimport "strings"\ntype mergeHunk struct {baseStart,baseEnd int;newText string}\n'+function(s,'func splitLines(')+'\n'+function(s,'func conflictMarker(')+'\n'+f+'\n'
tests=r'''package review
import "testing"
func TestSourceRelations(t *testing.T){
 base:="a\nb\nc\nd\ne\n"
 _,same:=mergeText(base,[]mergeHunk{{1,2,"OURS\n"}},[]mergeHunk{{1,2,"THEIRS\n"}})
 _,apart:=mergeText(base,[]mergeHunk{{0,1,"OURS\n"}},[]mergeHunk{{3,4,"THEIRS\n"}})
 t.Logf("same_interval_conflict=%v disjoint_conflict=%v",same,apart)
 if !same||apart{t.Fatal("source controls")}
}
func TestMissingPartialOverlap(t *testing.T){
 got,conflict:=mergeText("a\nb\nc\nd\ne\n",[]mergeHunk{{1,3,"B_OURS\nC_OURS\n"}},[]mergeHunk{{2,4,"C_THEIRS\nD_THEIRS\n"}})
 t.Logf("A=[1,3) B=[2,4) conflict=%v output=%q",conflict,got)
 if !conflict{t.Error("partial overlap must conflict")}
}
'''
run(trial,source,tests,['Use exact splitLines/conflictMarker and mergeText loop from added candidate file.','Change mergeText signature to accept normalized hunks; remove only diff.Do and normalizeMergeHunks calls.','Does not exercise actual diff normalization, repository, index, or worktree.'])
trial='pebble-durability-wait-apis__2UjdyFm';s=added_file(trial,'durability.go')
source=r'''package review
import("errors";"sync";"time")
var ErrClosed=errors.New("closed")
var errDurabilityTooManySubscriber=errors.New("too many")
const maxDurabilityNotifiers=4096
type fakeStart struct{}
func(fakeStart)Elapsed()time.Duration{return time.Nanosecond}
type Batch struct {syncDuration time.Duration;syncStart fakeStart;durableSeqNum uint64;keyCount uint32;commitErr error}
type durabilityNotifier struct {seqNum uint64;ch chan error;pending bool}
type durabilityTracker struct {mu sync.Mutex;highestDurableSeqNum uint64;firstErr error;totalFailedCommits,totalDurableCommits uint64;cumulativeSyncDuration,maxSyncDuration time.Duration;closed bool;pendingWaiters int64;notifiers []*durabilityNotifier}
'''
for sig in ['func (t *durabilityTracker) onBatchSyncComplete(', 'func (t *durabilityTracker) signalLocked(', 'func (t *durabilityTracker) registerLocked(']:
 source+=function(s,sig).replace('base.SeqNum','uint64')+'\n'
tests=r'''package review
import "testing"
func TestSourceRelations(t *testing.T){
 tracker:=&durabilityTracker{}
 b:=&Batch{durableSeqNum:10,keyCount:2};tracker.onBatchSyncComplete(b)
 a,e:=tracker.registerLocked(10,false);bch,e2:=tracker.registerLocked(11,false);far,ef:=tracker.registerLocked(100000,false)
 t.Logf("synthetic_batch_start=10 keyCount=2 computed_high=%d target10_immediate=%v target11_immediate=%v target100000_pending=%v",tracker.highestDurableSeqNum,a==nil,bch==nil,far!=nil)
 if a!=nil||bch!=nil||far==nil||e!=nil||e2!=nil||ef!=nil{t.Fatal("source controls")}
}
func TestMissingExclusiveBoundary(t *testing.T){
 tracker:=&durabilityTracker{}
 b:=&Batch{durableSeqNum:10,keyCount:1};tracker.onBatchSyncComplete(b)
 target:=b.durableSeqNum+1;ch,err:=tracker.registerLocked(target,false)
 t.Logf("synthetic_batch_start=%d keyCount=%d computed_exclusive_high=%d target=%d immediate_success=%v error=%v",b.durableSeqNum,b.keyCount,tracker.highestDurableSeqNum,target,ch==nil&&err==nil,err)
 if ch==nil&&err==nil{t.Error("target at exclusive boundary is not durable")}
}
'''
run(trial,source,tests,['Extract exact onBatchSyncComplete, signalLocked, registerLocked from candidate added durability.go.','Replace base.SeqNum with uint64 (same underlying integer behavior); stub tracker/Batch fields and elapsed time.','Synthetic batch starts at 10; this is not a real DB-allocated sequence number. Does not execute WAL or full repository.'])
