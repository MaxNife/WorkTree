"""Child process entry point: run one activity and print the result envelope.

The parent writes one JSON request to stdin: the job envelope plus the secrets resolved for
this call only. Secrets never touch the environment, the workspace or the result.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

import structlog

from app.domain.activity import ActivityContext
from app.domain.clock import SystemClock
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.domain.workflow import substitute_secrets
from app.security.masking import SecretMasker, get_masker

MARKER = "__UAF_RESULT__"


def _configure_child_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)


def main() -> int:
    _configure_child_logging()
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
        envelope = JobEnvelope.model_validate(request["envelope"])
        secrets_raw: dict[str, Any] = request.get("secrets", {})
        secrets = {str(k): str(v) for k, v in secrets_raw.items()}
    except Exception as exc:
        print(
            f"{MARKER}{json.dumps({'outcome': 'failed', 'message': f'invalid job: {exc}', 'outputs': {}, 'artifacts': [], 'run_id': '', 'step_id': ''})}"
        )
        return 2

    masker: SecretMasker = get_masker()
    masker.register_many(list(secrets.values()))
    ctx = ActivityContext(
        run_id=envelope.run_id,
        step_id=envelope.step_id,
        workspace=Path(envelope.workspace),
        clock=SystemClock(),
        correlation_id=envelope.correlation_id,
        logger=structlog.get_logger("uaf.activity"),
        resolved_secrets=secrets,
        ai_enabled=os.environ.get("UAF_CHILD_AI_ENABLED", "0") == "1",
        ai_endpoint=os.environ.get("UAF_CHILD_AI_ENDPOINT", ""),
    )
    result_payload: dict[str, Any]
    try:
        from app.domain.activity_registry import ActivityRegistry

        extra = os.environ.get("UAF_CHILD_ACTIVITIES_EXTRA") or None
        registry = ActivityRegistry(Path(extra) if extra else None).discover()
        activity = registry.get(envelope.activity)
        if activity is None:
            result_payload = ResultEnvelope.failure(
                envelope, f"unknown activity: {envelope.activity}"
            ).model_dump(mode="json")
        else:
            resolved_inputs = substitute_secrets(envelope.inputs, secrets, keep_undeclared=True)
            if not isinstance(resolved_inputs, dict):
                raise ValueError("resolved inputs must be an object")
            result = activity.execute(ctx, resolved_inputs)
            result_payload = ResultEnvelope(
                run_id=envelope.run_id,
                step_id=envelope.step_id,
                iteration=envelope.iteration,
                correlation_id=envelope.correlation_id,
                outcome=result.outcome.value,
                outputs=masker.mask_obj(result.outputs),
                message=masker.mask(result.message),
                artifacts=result.artifacts,
            ).model_dump(mode="json")
    except Exception as exc:  # last-resort guard: the child must always answer
        result_payload = ResultEnvelope.failure(
            envelope, masker.mask(f"{type(exc).__name__}: {exc}")
        ).model_dump(mode="json")
    print(MARKER + json.dumps(result_payload, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
