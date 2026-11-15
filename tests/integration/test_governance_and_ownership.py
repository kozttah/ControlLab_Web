"""Testes independentes da Frente F9 para governança, ownership e runner Web (AUD-012, AUD-013, AUD-015)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEOWNERS_PATH = REPO_ROOT / "CODEOWNERS"
PROJECT_STATE_PATH = REPO_ROOT / "PROJECT_STATE.json"
RUNNER_PATH = REPO_ROOT / "scripts" / "run_web_tests.mjs"
HANDOFF_TEMPLATE_PATH = REPO_ROOT / "docs" / "architecture" / "HANDOFF_TEMPLATE_APENDICE_E.md"
EVIDENCE_MATRIX_PATH = REPO_ROOT / "docs" / "audits" / "MATRIZ_EVIDENCIAS_WPS_GATES.md"
GOV_HANDOFF_PATH = REPO_ROOT / "docs" / "audits" / "handoffs" / "WP-AUDIT-FIX-F9-GOV.md"


def _strip_inline_comment(line: str) -> str:
    escaped = False
    for idx, ch in enumerate(line):
        if ch == "\\" and not escaped:
            escaped = True
            continue
        if ch == "#" and not escaped:
            return line[:idx]
        escaped = False
    return line


def _glob_to_regex(glob_expr: str) -> str:
    parts: list[str] = []
    i = 0
    n = len(glob_expr)
    while i < n:
        if glob_expr.startswith("**/", i):
            parts.append("(?:.+/)?")
            i += 3
        elif glob_expr.startswith("/**", i):
            parts.append("(?:/.*)?")
            i += 3
        elif glob_expr.startswith("**", i):
            parts.append(".*")
            i += 2
        elif glob_expr[i] == "*":
            parts.append("[^/]*")
            i += 1
        elif glob_expr[i] == "?":
            parts.append("[^/]")
            i += 1
        else:
            parts.append(re.escape(glob_expr[i]))
            i += 1
    return "".join(parts)


def _compile_codeowners_pattern(pattern: str) -> re.Pattern[str]:
    if not pattern:
        raise ValueError("Padrão CODEOWNERS vazio não permitido")
    dir_only = pattern.endswith("/")
    anchored = "/" in pattern[:-1]

    core = pattern.lstrip("/")
    if dir_only:
        core = core.rstrip("/")

    regex_body = _glob_to_regex(core)
    if dir_only:
        if anchored:
            return re.compile(f"^{regex_body}/.+$")
        return re.compile(f"(?:^|/){regex_body}/.+$")

    if anchored:
        return re.compile(f"^{regex_body}(?:/.+)?$")
    return re.compile(f"(?:^|/){regex_body}(?:/.+)?$")


def parse_codeowners(text: str) -> list[tuple[str, re.Pattern[str], list[str]]]:
    rules: list[tuple[str, re.Pattern[str], list[str]]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = _strip_inline_comment(raw_line).strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if len(tokens) < 2:
            raise ValueError(f"Linha {lineno} de CODEOWNERS sem owners explícitos: {raw_line!r}")
        pattern, owners = tokens[0], tokens[1:]
        for owner in owners:
            if not owner.startswith("@"):
                raise ValueError(f"Owner inválido na linha {lineno} de CODEOWNERS: {owner!r}")
        rules.append((pattern, _compile_codeowners_pattern(pattern), owners))
    return rules


def resolve_codeowners(
    rules: Iterable[tuple[str, re.Pattern[str], list[str]]],
    rel_posix_path: str,
) -> list[str]:
    matched: list[str] = []
    normalized = rel_posix_path.lstrip("/")
    for _, regex, owners in rules:
        if regex.match(normalized):
            matched = list(owners)
    return matched


def expected_normative_owners(rel_posix_path: str) -> list[str]:
    p = rel_posix_path.lstrip("/")
    f1_prefixes = (
        "control_lab/core/",
        "control_lab/diagnostics/",
        "control_lab/io/",
        "tests/unit/f1/",
    )
    f2_prefixes = ("control_lab/statespace/", "tests/unit/f2/")
    f3_prefixes = ("control_lab/frequency/", "tests/unit/f3/")
    f4_prefixes = ("control_lab/identification/", "tests/unit/f4/")
    f5_prefixes = ("control_lab/fuzzy/", "tests/unit/f5/")
    f6_prefixes = (
        "control_lab/optimization/",
        "control_lab/experimental/sdp_educational/",
        "tests/unit/f6/",
    )
    f7_prefixes = ("web/bridge/", "web/worker/", "web/storage/", "tests/unit/f7/")
    f8_prefixes = ("web/features/", "web/charts/", "web/app/", "tests/unit/f8/")

    if p.startswith(f1_prefixes):
        return ["@f1-core-io"]
    if p.startswith(f2_prefixes):
        return ["@f2-statespace"]
    if p.startswith(f3_prefixes):
        return ["@f3-frequency"]
    if p.startswith(f4_prefixes):
        return ["@f4-identification"]
    if p.startswith(f5_prefixes):
        return ["@f5-fuzzy-ts"]
    if p.startswith(f6_prefixes):
        return ["@f6-optimization-lmi"]
    if p.startswith(f7_prefixes):
        return ["@f7-worker-bridge"]
    if p.startswith(f8_prefixes):
        return ["@f8-ui-charts"]

    if p.startswith("contracts/fixtures/") or p.startswith("contracts/examples/"):
        return ["@f9-integration-qa"]
    if p.startswith("contracts/"):
        return ["@f9-integration-qa", "@f1-core-io"]

    return ["@f9-integration-qa"]


def test_codeowners_covers_all_tracked_paths_and_fixtures_exclusive_to_f9() -> None:
    content = CODEOWNERS_PATH.read_text(encoding="utf-8")
    lowered = content.lower()
    assert "last-match-wins" in lowered or "última correspondência" in lowered
    assert "branch protection" in lowered
    assert "aud-012" in lowered

    rules = parse_codeowners(content)
    patterns = [pat for pat, _, _ in rules]
    assert "*" not in patterns, "CODEOWNERS não deve usar curinga global '*' que mascare lacunas."

    # Precedência last-match-wins: fixtures/ e examples/ devem vir após /contracts/
    idx_contracts = patterns.index("/contracts/")
    idx_schemas = patterns.index("/contracts/schemas/")
    idx_fixtures = patterns.index("/contracts/fixtures/")
    idx_examples = patterns.index("/contracts/examples/")
    assert idx_fixtures > idx_contracts and idx_fixtures > idx_schemas
    assert idx_examples > idx_contracts and idx_examples > idx_schemas

    git_proc = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    tracked_files = [line.strip() for line in git_proc.stdout.splitlines() if line.strip()]
    assert tracked_files, "git ls-files não retornou arquivos rastreados."

    for rel_path in tracked_files:
        owners = resolve_codeowners(rules, rel_path)
        assert owners, f"Arquivo rastreado sem dono em CODEOWNERS: {rel_path}"
        expected = expected_normative_owners(rel_path)
        assert owners == expected, (
            f"Ownership divergente para {rel_path}: obtido {owners}, esperado {expected}"
        )
        if rel_path.startswith("contracts/fixtures/"):
            assert owners == ["@f9-integration-qa"], (
                f"Fixture ouro {rel_path} deve pertencer exclusivamente a @f9-integration-qa"
            )
            assert "@f1-core-io" not in owners

    # Caminhos normativos de fases futuras / entradas críticas (mesmo ainda não criados)
    normative_future_paths = [
        "contracts/fixtures/B-DARE-12x3.json",
        "contracts/fixtures/B-ARX-PRBS.json",
        "contracts/fixtures/B-MIMO-2x2.json",
        "contracts/fixtures/B-PVM-LQR.json",
        "contracts/fixtures/checksums.sha256",
        "contracts/examples/new_example.json",
        "contracts/schemas/new_contract.schema.json",
        "contracts/README.md",
        "control_lab/core/rpc.py",
        "tests/metamorphic/test_care_metamorphic.py",
        "tests/integration/test_new_suite.py",
        "tests/wasm/test_pyodide_care.py",
        "tests/e2e/test_lqr_workflow.py",
        "tests/performance/test_cold_warm.py",
        "tests/security/test_offline_csp.py",
        ".github/workflows/ci.yml",
        "docs/legal/THIRD_PARTY_LICENSES.md",
        "docs/architecture/adr/ADR-013.md",
        "docs/audits/handoffs/WP-AUDIT-FIX-F1-CORE-RPC.md",
        "web/package-lock.json",
    ]
    for path_str in normative_future_paths:
        owners = resolve_codeowners(rules, path_str)
        expected = expected_normative_owners(path_str)
        assert owners == expected, (
            f"Ownership normativo futuro divergente para {path_str}: obtido {owners}, esperado {expected}"
        )


def test_project_state_governance_and_handoff_invariants() -> None:
    # AUD-016: validate evolving records, never a historical queue/verdict snapshot.
    from scripts.project_governance import validate_state

    state = json.loads(PROJECT_STATE_PATH.read_text(encoding="utf-8"))
    validate_state(state, REPO_ROOT)


def test_appendix_e_handoff_template_and_evidence_matrix() -> None:
    template_text = HANDOFF_TEMPLATE_PATH.read_text(encoding="utf-8")
    for required_fragment in (
        "WorkPackage ID",
        "Requisito",
        "Frente F",
        "allowed_paths",
        "Contratos consumidos",
        "Entradas / saídas",
        "Hipótese matemática",
        "Limite da implementação",
        "Testes de aceite",
        "Fixtures",
        "Dependências",
        "Bloqueadores",
        "Evidência / PR esperado",
        "Risco",
        "maturidade",
        "accepted",
        "changes_requested",
        "blocked_by_gate",
        "rejected_with_evidence",
        "ACCEPTED_BY_F9",
        "stable",
    ):
        assert required_fragment in template_text, (
            f"Fragmento obrigatório ausente em {HANDOFF_TEMPLATE_PATH.name}: {required_fragment}"
        )

    expected_checklist_phrases = [
        "API foi testada com contrato F1/F9 aprovado e fornecido a consumidores F7/F8?",
        "Saída contém status, diagnósticos e proveniência, inclusive casos de falha?",
        "Testes analíticos foram escritos antes da otimização prematura?",
        "Existe confronto independente da implementação, em vez de autorreferência?",
        "O PR respeita ownership e não modificou mocks/expected values para esconder defeito?",
        "O mesmo teste funciona em CPython e Pyodide no domínio anunciado?",
        "Alterações de schema tiveram migração/versão e revisão F9?",
        "Logs, matrizes de fixture e resultados de benchmark foram anexados?",
        "Um método experimental permanece visualmente classificado como tal?",
        "Qualquer limitação conhecida tem issue e mensagens de falha adequadas?",
    ]
    for phrase in expected_checklist_phrases:
        assert phrase in template_text, f"Item normativo do Apêndice E ausente no template: {phrase}"

    matrix_text = EVIDENCE_MATRIX_PATH.read_text(encoding="utf-8")
    for commit_sha in (
        "cfa5270",
        "f95ec4d",
        "08b6277",
        "676e1bc",
        "b989543",
        "f2c2226",
        "7e8d468",
        "2e1ec08",
        "fb7ba7a",
        "202ec9d",
        "1c1c819",
        "e4b166a",
        "1a298c0",
        "f1b9408",
    ):
        assert commit_sha in matrix_text, f"Commit histórico ausente na matriz: {commit_sha}"

    for wp_id in (
        "WP-00-F9-BOOTSTRAP",
        "WP-01-F1-CORE-MODELS",
        "WP-02-F2-CARE-LQR",
        "WP-03-F6-SDP-MODELING-AND-GATE0B",
        "WP-04-F7-RPC-BRIDGE-WORKER",
        "WP-05-F1-IO-CTRLAB-PVM",
        "WP-06-F8-UI-MVP-LQR",
        "WP-07-F3-FREQ-SISO-MIMO",
        "WP-08-F4-IDENTIFICATION",
        "WP-09-F5-FUZZY-FML-ANFIS",
        "WP-10-F6-SDP-EDUCATIONAL-SOLVER",
    ):
        assert wp_id in matrix_text, f"WP histórico ausente na matriz: {wp_id}"

    for gate_id in ("G-0A", "G-0B", "G-0C", "G-0D"):
        assert gate_id in matrix_text
    assert "cpython_local_only" in matrix_text
    assert "CHANGES_REQUESTED" in matrix_text
    assert "BLOCKED_BY_GATE" in matrix_text
    assert "ACCEPTED_BY_F9" in matrix_text

    gov_handoff_text = GOV_HANDOFF_PATH.read_text(encoding="utf-8")
    for marker in (
        "WP-AUDIT-FIX-F9-GOV",
        "AUD-012",
        "AUD-013",
        "AUD-015",
        "REM-01",
        "REM-03",
        "## 1. Cabeçalho da Tarefa (Apêndice E)",
        "## 2. Entregáveis Produzidos",
        "## 3. Checklist de Handoff de 10 Itens",
        "## 4. Registro de Ambiente, SHA e Saída de Execução",
        "## 5. Parecer Independente da Frente F9",
    ):
        assert marker in gov_handoff_text, f"Marcador obrigatório ausente em {GOV_HANDOFF_PATH.name}: {marker}"

    sec3 = _extract_markdown_section(gov_handoff_text, 3)
    for item_num in range(1, 11):
        assert f"| **{item_num}** |" in sec3, (
            f"Item {item_num} ausente na tabela da Seção 3 de {GOV_HANDOFF_PATH.name}"
        )
    for phrase in expected_checklist_phrases:
        assert phrase in sec3, (
            f"Item do Apêndice E ausente na Seção 3 de {GOV_HANDOFF_PATH.name}: {phrase}"
        )

    sec4 = _extract_markdown_section(gov_handoff_text, 4)
    for evidence_marker in (
        "f1b9408d246ea2afab6375fe4db4a991fb1f60ab",
        "pytest tests/oracles/ tests/integration/ -v",
        "node --test tests/integration/*.test.mjs",
        "verify_fixtures.py",
        "npm --prefix web test",
    ):
        assert evidence_marker in sec4, (
            f"Evidência obrigatória ausente na Seção 4 de {GOV_HANDOFF_PATH.name}: {evidence_marker}"
        )

    sec5 = _extract_markdown_section(gov_handoff_text, 5)
    assert re.search(
        r"^-\s*\*\*Veredito F9[^:]*:\*\*\s*`(?:PENDENTE|accepted|changes_requested|blocked_by_gate|rejected_with_evidence)`(?:\s|$)",
        sec5,
        flags=re.MULTILINE,
    ), f"Linha válida de Veredito F9 ausente na Seção 5 de {GOV_HANDOFF_PATH.name}."


def _extract_markdown_section(text: str, section_number: int) -> str:
    header_re = re.compile(rf"^##\s+{section_number}\.\s+.*$", re.MULTILINE)
    match = header_re.search(text)
    assert match is not None, f"Seção '## {section_number}.' ausente no dossiê."
    rest = text[match.end() :]
    next_sec = re.search(r"^##\s+\d+\.\s+", rest, re.MULTILINE)
    return rest[: next_sec.start()] if next_sec is not None else rest


def _validate_accepted_dossier(dossier_text: str, wp_id: str) -> None:
    from scripts.project_governance import validate_handoff_text

    validate_handoff_text(dossier_text, wp_id)


def test_accepted_dossier_validator_rejects_pending_and_template_false_positives() -> None:
    def _build_dossier(*, sec3_audit: str, veredito: str, sec5_sha: str) -> str:
        rows = "\n".join(
            f"| **{i}** | Pergunta {i}? | `SIM` | Evidência {i} | {sec3_audit} |"
            for i in range(1, 11)
        )
        return (
            "# Dossiê Exemplo\n\n"
            "Status alvo: ACCEPTED_BY_F9\n\n"
            "## 3. Checklist de Handoff de 10 Itens (Apêndice E)\n\n"
            "| # | Pergunta | Resposta | Evidência | Auditoria F9 |\n"
            "| :-: | :--- | :--- | :--- | :--- |\n"
            f"{rows}\n\n"
            "## 4. Registro de Ambiente, SHA e Saída de Execução\n\nOK\n\n"
            "## 5. Parecer Independente da Frente F9\n\n"
            "- **Veredito F9 (`accepted` | `changes_requested` | `blocked_by_gate` | `rejected_with_evidence`):** "
            f"{veredito}\n"
            "- **Revisor independente:** `f9-integration-qa`\n"
            f"- **Commit SHA auditado:** {sec5_sha}\n"
            "- **Data (UTC):** `2026-11-14`\n"
        )

    # Caso falso positivo clássico: contém `accepted` no rótulo do template e ACCEPTED_BY_F9, mas veredito é PENDENTE
    pending_with_template_text = _build_dossier(
        sec3_audit="`PENDENTE`",
        veredito="`PENDENTE`",
        sec5_sha="`PENDENTE`",
    )
    with pytest.raises(AssertionError):
        _validate_accepted_dossier(pending_with_template_text, "WP-SYNTHETIC-PENDING")

    # Caso com Veredito F9 = `accepted`, mas Seção 3 ainda pendente
    accepted_with_pending_sec3 = _build_dossier(
        sec3_audit="`PENDENTE`",
        veredito="`accepted`",
        sec5_sha="`f1b9408d246ea2afab6375fe4db4a991fb1f60ab`",
    )
    with pytest.raises(AssertionError):
        _validate_accepted_dossier(accepted_with_pending_sec3, "WP-SYNTHETIC-SEC3")

    # Caso com Veredito F9 = `accepted`, Seção 3 conforme, mas SHA na Seção 5 ainda pendente
    accepted_with_pending_sec5 = _build_dossier(
        sec3_audit="`CONFORME`",
        veredito="`accepted`",
        sec5_sha="`PENDENTE`",
    )
    with pytest.raises(AssertionError):
        _validate_accepted_dossier(accepted_with_pending_sec5, "WP-SYNTHETIC-SEC5")

    # Caso com Veredito F9 = `changes_requested`
    changes_requested_dossier = _build_dossier(
        sec3_audit="`CONFORME`",
        veredito="`changes_requested`",
        sec5_sha="`f1b9408d246ea2afab6375fe4db4a991fb1f60ab`",
    )
    with pytest.raises(AssertionError):
        _validate_accepted_dossier(changes_requested_dossier, "WP-SYNTHETIC-CR")

    # Caso válido e auditado: deve passar
    valid_accepted = _build_dossier(
        sec3_audit="`CONFORME`",
        veredito="`accepted`",
        sec5_sha="`f1b9408d246ea2afab6375fe4db4a991fb1f60ab`",
    )
    _validate_accepted_dossier(valid_accepted, "WP-SYNTHETIC-OK")



def test_acceptance_runner_requires_tsc_and_tests() -> None:
    node_exe = shutil.which("node")
    assert node_exe is not None, "Node.js não encontrado no PATH."

    clean_env = dict(os.environ)
    clean_env.pop("NODE_TEST_CONTEXT", None)

    node_test_proc = subprocess.run(
        [node_exe, "--test", "tests/integration/test_run_web_tests_fail_closed.test.mjs"],
        cwd=REPO_ROOT,
        env=clean_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert node_test_proc.returncode == 0, (
        f"Falha na suíte Node fail-closed:\nSTDOUT:\n{node_test_proc.stdout}\nSTDERR:\n{node_test_proc.stderr}"
    )
    assert "test_acceptance_runner_requires_tsc_and_tests" in node_test_proc.stdout

    # Confirma também via subprocesso Python direto com PATH vazio (zero tsc possível)
    with tempfile.TemporaryDirectory(prefix="controllab-empty-path-") as empty_dir:
        no_tsc_env = dict(clean_env)
        no_tsc_env["PATH"] = empty_dir

        repo_has_local_tsc = (
            (REPO_ROOT / "web" / "node_modules" / ".bin" / "tsc").exists()
            or (REPO_ROOT / "node_modules" / ".bin" / "tsc").exists()
        )
        if not repo_has_local_tsc:
            for args in ([], ["--scope", "all"], ["--scope", "f7"]):
                proc = subprocess.run(
                    [node_exe, str(RUNNER_PATH), *args],
                    cwd=REPO_ROOT,
                    env=no_tsc_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                assert proc.returncode != 0, (
                    f"Runner não falhou fechado sem tsc (args={args}): {proc.stdout}"
                )
                assert "[typecheck] FAIL" in proc.stderr
                assert "[typecheck] PASS" not in proc.stdout
                assert "[unit-tests] PASS" not in proc.stdout
