"""Real B-CARE-12x3 first/warm RPC measurements after explicit engine init."""

import json
import os
import platform
from pathlib import Path

import numpy as np
from scripts.browser_harness import browser_harness, care_request

ROOT = Path(__file__).resolve().parents[2]


def test_care_12x3_cold_warm_and_ui_heartbeat(browser_harness):
    fixture = json.loads((ROOT / "contracts/fixtures/B-CARE-12x3.json").read_text())
    req = care_request(fixture, project="benchmark")
    report = browser_harness.page.evaluate(
        """async req => {
        let ticks=0; const timer=setInterval(()=>ticks++,1);
        const times=[];
        for(let i=0;i<11;i++){
            req.request_id='benchmark-'+i; req.project_revision=i;
            const t=performance.now(); const response=await app.client.execute(req,{commitOnSuccess:false});
            if(response.status!=='success') throw Error(JSON.stringify(response));
            times.push(performance.now()-t);
        }
        clearInterval(timer);
        return {runtime_init_ms:globalThis.f9InitMs,first_rpc_ms:times[0],warm_ms:times.slice(1),ticks,metrics:app.client.getMetrics(),
            userAgent:navigator.userAgent,threads:navigator.hardwareConcurrency,
            memory:performance.memory?{used:performance.memory.usedJSHeapSize,total:performance.memory.totalJSHeapSize}:null};
    }""",
        req,
    )
    assert report["ticks"] > 0
    assert len(report["warm_ms"]) == 10 and all(x >= 0 for x in report["warm_ms"])
    report.update(
        {
            "median_warm_ms": float(np.median(report["warm_ms"])),
            "p95_warm_ms": float(np.percentile(report["warm_ms"], 95)),
            "variation_std_ms": float(np.std(report["warm_ms"])),
            "system": platform.platform(),
            "cpu": platform.processor(),
            "ram_bytes": os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"),
            "hardware_scope": "container host; no reference-notebook performance approval",
            "repetitions": 10,
            "peak_rss_note": "JS heap snapshot only, not full browser RSS peak",
        }
    )
    browser_harness.record("care-12x3-benchmark", report)
