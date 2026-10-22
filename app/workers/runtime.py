"""Worker runtime: claim jobs, resolve secrets for one call, run in a child process."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from app.adapters.secrets.base import SecretStore
from app.bus.base import MessageBus
from app.bus.db_bus import worker_identity
from app.domain.clock import Clock
from app.domain.envelope import JobEnvelope, ResultEnvelope
from app.logging_setup import correlation_scope, get_logger
from app.security.masking import get_masker
from app.telemetry import span
from app.workers.process import ProcessOutcome, run_activity_process

ResultCallback = Callable[[JobEnvelope, ResultEnvelope], None]
LEASE_GRACE_SECONDS = 60


class WorkerRuntime:
    def __init__(
        self,
        *,
        worker_id: str,
        bus: MessageBus,
        secret_store: SecretStore,
        clock: Clock,
        on_result: ResultCallback,
        extra_folder: Path | None = None,
        ai_enabled: bool = False,
        ai_endpoint: str = "",
        queue: str = "default",
    ) -> None:
        self.worker_id = worker_id
        self.bus = bus
        self.secret_store = secret_store
        self.clock = clock
        self.on_result = on_result
        self.extra_folder = extra_folder
        self.ai_enabled = ai_enabled
        self.ai_endpoint = ai_endpoint
        self.queue = queue
        self.log = get_logger(__name__)
        self._stop = threading.Event()

    def stop(self) -> None:
        self._stop.set()

    def run_once(self) -> bool:
        job = self.bus.claim(self.worker_id, queue=self.queue)
        if job is None:
            return False
        try:
            envelope = JobEnvelope.model_validate(job.payload)
        except Exception as exc:
            self.log.error("invalid_job_payload", job_id=job.id, error=str(exc))
            self.bus.nack(job.id, f"invalid job payload: {exc}")
            return True
        # Hold the job for as long as the activity may legitimately run, so the lease never
        # expires (and the job is never redelivered) while the child process still works.
        self.bus.extend(job.id, envelope.timeout_seconds + LEASE_GRACE_SECONDS)
        with (
            correlation_scope(
                envelope.correlation_id, run_id=envelope.run_id, step_id=envelope.step_id
            ),
            span("uaf.activity", activity=envelope.activity, run_id=envelope.run_id),
        ):
            self._execute(job.id, envelope)
        return True

    def _execute(self, job_id: int, envelope: JobEnvelope) -> None:

        masker = get_masker()
        secrets: dict[str, str] = {}
        missing: list[str] = []
        for name in envelope.secret_refs:
            value = self.secret_store.get(name)
            if value is None:
                missing.append(name)
            else:
                secrets[name] = value
                masker.register(value)
        if missing:
            result = ResultEnvelope.failure(
                envelope, f"secret(s) not found: {', '.join(sorted(missing))}"
            )
            self._finish(job_id, envelope, result)
            return

        try:
            outcome = run_activity_process(
                envelope,
                secrets,
                extra_folder=str(self.extra_folder) if self.extra_folder else None,
                ai_enabled=self.ai_enabled,
                ai_endpoint=self.ai_endpoint,
            )
        except Exception as exc:  # defensive: worker must not die on a launcher bug
            result = ResultEnvelope.failure(envelope, f"worker error: {type(exc).__name__}")
            self._finish(job_id, envelope, result)
            return
        self._log_outcome(envelope, outcome)
        self._finish(job_id, envelope, outcome.result)

    def _log_outcome(self, envelope: JobEnvelope, outcome: ProcessOutcome) -> None:
        self.log.info(
            "activity_finished",
            run_id=envelope.run_id,
            step_id=envelope.step_id,
            activity=envelope.activity,
            outcome=outcome.result.outcome,
            exit_code=outcome.exit_code,
            timed_out=outcome.timed_out,
        )

    def _finish(self, job_id: int, envelope: JobEnvelope, result: ResultEnvelope) -> None:
        self.bus.ack(job_id, result.model_dump(mode="json"))
        try:
            self.on_result(envelope, result)
        except Exception as exc:
            # The result stays on the acked bus job; the engine reconciles it on its next tick.
            self.log.error(
                "result_callback_failed",
                run_id=envelope.run_id,
                step_id=envelope.step_id,
                error=str(exc),
            )

    def run_forever(self, poll_seconds: float = 0.5) -> None:  # pragma: no cover - thread loop
        while not self._stop.is_set():
            processed = self.run_once()
            if not processed:
                self._stop.wait(poll_seconds)


class WorkerPool:
    """Several worker runtimes in one process. Each job still runs in its own child process."""

    def __init__(
        self,
        *,
        bus: MessageBus,
        secret_store: SecretStore,
        clock: Clock,
        on_result: ResultCallback,
        count: int = 2,
        extra_folder: Path | None = None,
        ai_enabled: bool = False,
        ai_endpoint: str = "",
        poll_seconds: float = 0.5,
        queue: str = "default",
    ) -> None:
        self.poll_seconds = poll_seconds
        self.workers = [
            WorkerRuntime(
                worker_id=worker_identity(f"worker-{index + 1}"),
                bus=bus,
                secret_store=secret_store,
                clock=clock,
                on_result=on_result,
                extra_folder=extra_folder,
                ai_enabled=ai_enabled,
                ai_endpoint=ai_endpoint,
                queue=queue,
            )
            for index in range(count)
        ]
        self._threads: list[threading.Thread] = []

    def start(self) -> None:
        for worker in self.workers:
            thread = threading.Thread(
                target=worker.run_forever,
                args=(self.poll_seconds,),
                name=worker.worker_id,
                daemon=True,
            )
            thread.start()
            self._threads.append(thread)

    def stop(self) -> None:
        for worker in self.workers:
            worker.stop()
        for thread in self._threads:
            thread.join(timeout=5)
        self._threads.clear()

    def process_one(self) -> bool:
        """Test helper: run one job on the first worker."""
        return self.workers[0].run_once()
