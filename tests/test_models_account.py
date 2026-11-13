from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from support import Router, Runner, json_response, models_response


def test_models_table(cli: Runner) -> None:
    result = cli("models", handler=Router(models=models_response()))
    assert result.code == 0
    lines = result.out.splitlines()
    assert lines[0].split() == ["ID", "NAME", "AVAILABLE"]
    assert lines[1].split() == ["glm-5.3-flash", "GLM-5.3-Flash", "yes"]
    assert lines[3].split() == ["gemma4-26b-a4b-qat", "Gemma4-26B-A4B-QAT", "no"]
    # Columns line up.
    assert lines[0].index("NAME") == lines[1].index("GLM-5.3-Flash")


def test_models_without_molochai_extensions(cli: Runner) -> None:
    router = Router(models=models_response([{"id": "local-model"}]))
    result = cli("models", handler=router)
    assert result.out.splitlines()[1].split() == ["local-model", "unknown"]


def test_models_empty(cli: Runner) -> None:
    result = cli("models", handler=Router(models=models_response([])))
    assert result.out == "The server returned no models.\n"


def test_models_payment_required(cli: Runner) -> None:
    router = Router(
        models=json_response(402, {"error": {"type": "no_active_plan", "message": "x"}})
    )
    result = cli("models", handler=router)
    assert result.code == 1
    assert "No active plan and no credit (HTTP 402)." in result.err
    assert "https://dash.molochai.dev/?utm_source=github" in result.err


def account_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": 1,
        "email": "dev@example.com",
        "plan": "pro",
        "plan_expires_at": (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
        "tier": "pro",
        "credit_usd": 12.5,
        "email_verified": True,
        "api_base": "https://api.example.test/api/v1",
        "default_model": "glm-5.3-flash",
        "context_limit": 131072,
        "models": [
            {"id": "glm-5.3-flash", "name": "GLM", "available": True, "context_limit": 131072},
            {"id": "gemma4-26b-a4b-qat", "name": "G", "available": False, "context_limit": None},
        ],
    }
    body.update(overrides)
    return body


def test_account(cli: Runner) -> None:
    router = Router(account=json_response(200, account_body()))
    result = cli("account", handler=router)
    assert result.code == 0
    assert str(router.requests[0].url) == "https://api.example.test/api/auth/me"
    fields = {
        line.split("  ")[0]: line.split("  ", 1)[1].strip()
        for line in result.out.split("\n\n")[0].splitlines()
    }
    assert fields["Plan"] == "pro"
    assert fields["Plan expires"].endswith("(in 29 days)") or fields["Plan expires"].endswith(
        "(in 30 days)"
    )
    assert fields["Tier"] == "pro"
    assert fields["Credit"] == "$12.50"
    assert fields["Email verified"] == "yes"
    assert fields["Default model"] == "glm-5.3-flash"
    assert fields["Context limit"] == "131,072 tokens (plan)"
    assert "Email" not in fields
    assert "dev@example.com" not in result.out
    table = result.out.split("\n\n")[1].splitlines()
    assert table[0].split() == ["MODEL", "AVAILABLE", "CONTEXT", "LIMIT"]
    assert table[1].split() == ["glm-5.3-flash", "yes", "131,072"]
    assert table[2].split() == ["gemma4-26b-a4b-qat", "no", "-"]


def test_account_show_email(cli: Runner) -> None:
    router = Router(account=json_response(200, account_body()))
    result = cli("account", "--show-email", handler=router)
    assert "Email           dev@example.com" in result.out


def test_account_payg_and_missing_fields(cli: Runner) -> None:
    body = account_body(
        plan=None,
        plan_expires_at=None,
        tier="payg",
        credit_usd=None,
        email_verified=None,
        default_model=None,
        api_base=None,
        context_limit=None,
        models=[],
    )
    result = cli("account", handler=Router(account=json_response(200, body)))
    assert result.code == 0
    assert "Plan            none" in result.out
    assert "payg (running on credit, no plan)" in result.out
    assert "Credit          unknown" in result.out
    assert "Plan expires" not in result.out
    assert "MODEL" not in result.out


def test_account_on_a_server_without_the_endpoint(cli: Runner) -> None:
    result = cli("account", handler=Router())  # the router answers 404
    assert result.code == 1
    assert "does not look like the MolochAI API" in result.err
    assert "works only against MolochAI" in result.err


def test_account_with_a_base_url_not_ending_in_v1(cli: Runner) -> None:
    result = cli("account", handler=Router(), env={"MOLOCHAI_BASE_URL": "http://localhost:8000"})
    assert result.code == 1
    assert "ending in /v1" in result.err


def test_account_unauthenticated(cli: Runner) -> None:
    router = Router(account=json_response(401, {"message": "Unauthenticated."}))
    result = cli("account", handler=router)
    assert result.code == 1
    assert "The API key was not accepted (HTTP 401)." in result.err
    assert "molochai config show" in result.err
