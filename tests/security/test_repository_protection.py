"""ADR-009 validates the adopted file/CI controls and the explicit owner decision."""
import copy
import json
from pathlib import Path
import pytest
from scripts.project_governance import GovernanceError, validate_state
from scripts.ci_gate import unresolved_release_gates
ROOT = Path(__file__).resolve().parents[2]


def test_personal_repository_controls_and_f9_evidence():
    state = json.loads((ROOT/'PROJECT_STATE.json').read_text())
    validate_state(state, ROOT)
    release = state['release_governance']
    assert release['status'] == 'VERIFIED_BY_FILE_GOVERNANCE'
    assert release['manual_process_is_not_server_enforcement'] is True
    assert state['audit_reference']['accepted_external_constraints']['AUD-018']['decision'] == 'ADR-009'
    state['gates']['G-0A']['status'] = 'PENDING'
    assert 'G-0A' in unresolved_release_gates(state), 'File governance preserves scientific gate enforcement.'


@pytest.mark.parametrize('control', ['project_governance','ci_gate','f9_handoffs'])
def test_missing_file_control_rejected(control):
    state = json.loads((ROOT/'PROJECT_STATE.json').read_text())
    state['release_governance']['required_controls'].remove(control)
    with pytest.raises(GovernanceError, match='all local/CI controls'):
        validate_state(state, ROOT)


def test_native_gate_requires_numeric_and_export_evidence():
    state = json.loads((ROOT/'PROJECT_STATE.json').read_text())
    gate = state['gates']['G-0B']
    gate.update(status='ACCEPTED_BY_F9', f9_review='accepted', decision='pass',
                assessed_commit='3ce128a6d8a18ad1eeb18ee83b666df6708d30d0',
                acceptance_scope='native_sdp', blocking_wps=[], audit_verdict='PASS',
                evidence_ref='docs/architecture/ADR-010-native-sdp-and-offline-exports.md',
                validation={'production_sdp_wasm':True, 'browsers':['Chromium','Firefox']})
    with pytest.raises(GovernanceError, match='native primal/dual'):
        validate_state(state, ROOT)
    gate['validation'].update(backend='native_primal_dual',independent_primal_dual=True)
    with pytest.raises(GovernanceError, match='ladder'):
        validate_state(state, ROOT)
