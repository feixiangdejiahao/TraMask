cd /tmp && python - <<'PY'
s = open('/tmp/test_coalesce.py').read()
# add progress print after each test call in main by inserting a print statement
calls = [
    ("test_async_invoke", "test_async_invoke()"),
    ("test_sync_invoke_threads", "test_sync_invoke_threads()"),
    ("test_dict_key_order", "test_dict_key_order()"),
    ("test_config_kwargs_ignored", "test_config_kwargs_ignored()"),
    ("test_fresh_after_complete", "test_fresh_after_complete()"),
    ("test_stream_join_replays", "test_stream_join_replays()"),
    ("test_stream_sync", "test_stream_sync()"),
    ("test_batch_coalesce", "test_batch_coalesce()"),
    ("test_batch_as_completed_consecutive", "test_batch_as_completed_consecutive()"),
    ("test_abatch_as_completed_consecutive", "test_abatch_as_completed_consecutive()"),
    ("test_join_callbacks_async", "test_join_callbacks_async()"),
    ("test_join_callbacks_sync", "test_join_callbacks_sync()"),
    ("test_error_propagation", "test_error_propagation()"),
    ("test_clear_cancels_waiters", "test_clear_cancels_waiters()"),
    ("test_clear_cancels_async_waiters", "test_clear_cancels_async_waiters()"),
    ("test_transform_passthrough", "test_transform_passthrough()"),
    ("test_shared_backend", "test_shared_backend()"),
    ("test_separate_wrappers_independent", "test_separate_wrappers_independent()"),
    ("test_graph_delegation", "test_graph_delegation()"),
    ("test_sync_leader_async_joiner", "test_sync_leader_async_joiner()"),
    ("test_async_leader_sync_joiner", "test_async_leader_sync_joiner()"),
]
for name, call in calls:
    s = s.replace(f"    {call}\n", f"    print('RUN {name}', flush=True)\n    {call}\n    print('DONE {name}', flush=True)\n", 1)
open('/tmp/test_coalesce.py','w').write(s)
print("ok")
PY