use crate::{Context, JsValue, NativeFunction, Source, js_string, job::GenericJob};

#[test]
fn jobs_spawned_under_handle_are_associated_and_skipped() {
    use crate::gc::{Gc, GcRefCell};

    let mut context = Context::default();
    let handle = context.new_evaluation_handle();
    let cancel_handle = handle.clone();
    let executed = Gc::new(GcRefCell::new(false));

    let executed_cancel = executed.clone();
    context
        .register_global_callable(
            js_string!("enqueueAndCancel"),
            0,
            NativeFunction::from_copy_closure_with_captures(
                move |_, _, (handle, executed), context| {
                    let executed = executed.clone();
                    let job = GenericJob::new(
                        move |_| {
                            *executed.borrow_mut() = true;
                            Ok(JsValue::undefined())
                        },
                        context.realm().clone(),
                    )
                    .into();
                    context.enqueue_job(job);
                    let _ = handle.cancel();
                    Ok(JsValue::undefined())
                },
                (cancel_handle, executed_cancel),
            ),
        )
        .expect("should register global callable");

    let result = context.eval_with_evaluation(Source::from_bytes("enqueueAndCancel();"), &handle);
    assert!(result.is_err());

    context.run_jobs().expect("run jobs should succeed");
    assert!(!*executed.borrow());
}
