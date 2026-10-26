"""Verify complete trajectory coverage and frozen state receipts for all 40 cases."""
from collections import Counter
from datetime import datetime,timezone
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from tramask_pilot.corpus import RUN,read,write,receipt
from tramask_pilot.submission_replay import OUTPUT,submission_actions,state_directory

def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    cases=sum([read(RUN/f'formal_{k}_cohort.json')['cases'] for k in ('failed','successful')],[])
    rows=[];effective_command_changes=[]
    for c in cases:
        directory=state_directory(c['id']);source=RUN/'inputs'/c['id']
        summary=read(directory/'summary.json')
        v=read(directory/'validation_v03/report.json')
        actions,marker=submission_actions(read(source/'trajectory.json'))
        records=read(directory/'runtime/records.json')
        assert [a['id'] for a in actions]==[r['id'] for r in records],c['id']+' action coverage'
        assert marker['id']==summary['terminal_marker'],c['id']+' terminal marker'
        for action,result in zip(actions,records):
            call=directory/'runtime/calls'/action['id']
            command=(call/'command.sh').read_bytes()
            assert command==action['command'].encode(),str(call)+' command'
            assert hashlib.sha256(command).hexdigest()==result['command_sha256']
            assert hashlib.sha256((call/'output.bin').read_bytes()).hexdigest()==result['output_sha256']
            assert result['shell']=='/bin/sh' and result['timeout_seconds']==30
            assert result['output_compared'] is False
            if result.get('execution_mapping'):
                mapping_receipt=result['execution_mapping']
                assert receipt(mapping_receipt['path'])==mapping_receipt
                mapping=read(mapping_receipt['path'])
                effective=(call/'execution_command.sh').read_bytes()
                assert hashlib.sha256(effective).hexdigest()==result['execution_command_sha256']
                assert c['id']=='F027' and action['id']=='s101_c0'
                bound=mapping['replay_process']
                assert bound['argv']==['python3','/tmp/webhook_server.py']
                assert all(mapping['before_action_process'][key]==bound[key]
                           for key in ('pid','start_ticks','argv'))
                assert effective==command.replace(b'kill 6506 ',('kill '+str(bound['pid'])+' ').encode(),1)
                effective_command_changes.append({'case_id':c['id'],'action':action['id'],'mapping':mapping_receipt})
        observation=Path(v['observation'])
        assert receipt(observation)['sha256']==v['observation_sha256']
        assert receipt(source/'model.patch')['sha256']==v['submitted_patch_sha256']
        inventory=Path(summary['inventory']['path'])
        assert receipt(inventory)['sha256']==summary['inventory']['sha256']
        assert v['image_id']==summary['checkpoint']['image_id'],c['id']+' validated checkpoint'
        assert v['submission_state_status']=='matched',c['id']+' final state mismatch'
        assert v['submitted_commit_tree_matches'] and v['working_tree_matches_submitted_commit']
        assert not v['subject_files_or_real_index_patched']
        original_container=read(directory/'runtime/container.json')
        assert original_container['closed'] and not [e for e in original_container['lifecycle'] if e['event']=='restart_after_timeout']
        obs=read(observation)
        assert not obs['untracked'],c['id']+' unexpected untracked files'
        files=read(inventory)
        assert not files['errors'],c['id']+' inventory errors'
        if c['id'] in ('F027','S026'):
            process_state=read(directory/'process_state_validation.json')
            assert process_state['known_processes_quiescent'] and not process_state['survivors']
        rows.append({'case_id':c['id'],'actions_verified':len(actions),'compared_paths':v['compared_paths'],
            'inventory_files':len(files['files']),'checkpoint_image':v['image_id'],
            'validation':receipt(directory/'validation_v03/report.json'),
            'provenance':receipt(directory/'validation_v03/provenance.json')})
    result={'created_at':datetime.now(timezone.utc).isoformat(),'status':'passed',
        'cases':len(rows),'actions':sum(r['actions_verified'] for r in rows),
        'compared_paths':sum(r['compared_paths'] for r in rows),
        'inventoried_files':sum(r['inventory_files'] for r in rows),
        'effective_command_changes':effective_command_changes,
        'output_equality_used':False,'scope':'All recorded actions covered; frozen submitted and working trees match independently; no claim of original untracked/dependency manifest equality.',
        'rows':rows}
    write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))

if __name__=='__main__':main()
