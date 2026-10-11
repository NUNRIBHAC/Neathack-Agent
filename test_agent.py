"""Testes do DisruptRadarAgent em modo demo (sem rede, sem Bedrock)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent as agent_module
from agent import DisruptRadarAgent

FAKE_PLAN = (
    '["FETCH_DATA", "ANALYZE_SIGNALS", "VERIFY_METRICS", "ASSESS_RISK", "RENDER_REPORT"]'
)


def fake_bedrock(self, prompt, max_tokens=1024):
    """Substitui o Bedrock: devolve o plano completo para prompts de planning."""
    return FAKE_PLAN


@pytest.fixture
def agent(tmp_path, monkeypatch):
    """Fixar flags de demo, credenciais fictícias e diretório temporário."""
    monkeypatch.setenv("RUN_DEMO_FIXTURE_MODE", "true")
    monkeypatch.setenv("INJECT_LOCAL_FAULT_SIMULATION", "true")
    monkeypatch.setenv("NEATLOGS_API_KEY", "test-key")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(agent_module.DisruptRadarAgent, "call_bedrock", fake_bedrock)
    # Impede que o tracker abra threads de envio para a rede (timeouts de 10s).
    monkeypatch.setattr(agent_module.neatlogs, "get_tracker", lambda: None)

    instance = DisruptRadarAgent(
        goal="Teste de deteção de disrupção",
        target_domain="acme.example.com",
        max_retries=3,
    )
    instance.run_agent()
    return instance


def test_simulated_network_error_was_captured(agent):
    messages = [entry["error"] for entry in agent.state.errors_log]
    assert any("Simulated Network Timeout Anomaly" in msg for msg in messages)


def test_recovery_succeeded_on_attempt_2(agent):
    assert agent.state.task_attempts["FETCH_DATA"] == 2
    assert agent.state.findings["current_headcount"] == 140
    assert agent.state.findings["previous_headcount"] == 100


def test_math_recomputed_exactly_40(agent):
    assert agent.state.findings["growth_string"] == "+40.0%"


def test_risk_high_and_verified(agent):
    assert agent.state.risk_level == "HIGH"
    assert agent.state.is_verified is True