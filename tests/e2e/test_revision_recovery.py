"""T-RPC-01/02 and T-UI-01 in the real browser, Worker and IndexedDB."""

from scripts.browser_harness import browser_harness


def test_twenty_revisions_only_current_commits(browser_harness):
    result = browser_harness.page.evaluate("""async () => {
        const responses=await Promise.all(Array.from({length:20},(_,i)=>app.client.execute(request(i,'revisions'),{commitOnSuccess:true})));
        const snapshot=await app.client.exportProject('revisions');
        return {responses, revision:app.client.getCommittedRevision('revisions'), snapshot,
                commits:events.filter(e=>e.type==='request_committed' && e.project_id==='revisions')};
    }""")
    assert result["revision"] == 19
    assert all(x["project_revision"] == 19 for x in result["commits"]), result["commits"]
    assert len(result["commits"]) == 1
    assert result["responses"][-1]["status"] == "success"
    browser_harness.record("twenty-revisions", result)


def test_worker_cancel_restart_recovers_confirmed_snapshot(browser_harness):
    result = browser_harness.page.evaluate("""async () => {
        const committed=await app.client.execute(request(20,'recovery'),{commitOnSuccess:true});
        const before=await app.client.exportProject('recovery');
        const req=request(21,'recovery');
        const pending=app.client.execute(req,{commitOnSuccess:true});
        const cancelled=await app.client.cancel(req.request_id,{reason:'F9 cancellation',forceTerminate:true});
        await app.client.resetWorker('F9 mandatory recovery test');
        await pending.catch(()=>null);
        const after=await app.client.exportProject('recovery');
        const response=await app.client.execute(request(22,'recovery'),{commitOnSuccess:false});
        return {committed,before,after,response,cancelled,events:events.filter(e=>e.type==='worker_recovered')};
    }""")
    assert result["committed"]["status"] == "success"
    assert {k: v for k, v in result["before"].items() if k != "exported_at"} == {
        k: v for k, v in result["after"].items() if k != "exported_at"
    }
    assert result["cancelled"]
    assert result["events"]
    assert result["response"]["status"] == "success"
    browser_harness.record("worker-recovery", result)


def test_preview_is_never_persisted_then_real_commit(browser_harness):
    result = browser_harness.page.evaluate("""async () => {
        const lqr=app.shell.getLqrWorkspace();
        await lqr.commitCurrentDesign({computeTimeResponse:false});
        const before=await app.client.exportProject(lqr.getProjectId());
        lqr.pointerDown('f9-drag');
        for(let i=0;i<20;i++) lqr.pointerMove({qScale:1+i/20});
        const during=await app.client.exportProject(lqr.getProjectId());
        const preview=lqr.getPreviewState();
        const final=await lqr.pointerUp({qScale:2,computeTimeResponse:false});
        const after=await app.client.exportProject(lqr.getProjectId());
        return {before,during,after,preview,final,pending:lqr.isPendingCommit(),invalid:lqr.isControllerInvalidated()};
    }""")
    assert {k: v for k, v in result["before"].items() if k != "exported_at"} == {
        k: v for k, v in result["during"].items() if k != "exported_at"
    }
    assert result["preview"]["active"]
    assert result["final"] is not None
    assert {k: v for k, v in result["after"].items() if k != "exported_at"} != {
        k: v for k, v in result["before"].items() if k != "exported_at"
    }
    assert result["after"]["project_revision"] > result["before"]["project_revision"]
    assert (
        result["after"]["committed_result"]["result"]["K"]
        != result["before"]["committed_result"]["result"]["K"]
    )
    assert not result["pending"] and not result["invalid"]
    browser_harness.record("preview-real-commit", result)
