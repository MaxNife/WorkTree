"""DB message bus: enqueue, claim, ack, retry, dead-letter, redelivery and no double processing."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from app.adapters.db.database import Database
from app.bus.db_bus import CANCELLED, DEAD, DONE, DbMessageBus, worker_identity
from app.domain.clock import FakeClock


@pytest.fixture
def bus(tmp_path: Path, fake_clock: FakeClock) -> DbMessageBus:
    database = Database(f"sqlite:///{(tmp_path / 'bus.db').as_posix()}")
    database.create_all()
    yield DbMessageBus(database, fake_clock, visibility_timeout_seconds=30, max_attempts=2)
    database.dispose()


def test_enqueue_claim_ack(bus: DbMessageBus) -> None:
    job_id = bus.enqueue({"n": 1})
    assert bus.pending_count() == 1
    job = bus.claim("w1")
    assert job is not None and job.id == job_id and job.payload == {"n": 1}
    assert job.attempts == 1
    assert bus.claim("w2") is None, "a claimed job is invisible to other workers"
    bus.ack(job.id, {"ok": True})
    stored = bus.get(job.id)
    assert stored is not None and stored.metadata["state"] == DONE and stored.result == {"ok": True}
    assert bus.pending_count() == 0


def test_delayed_job_is_invisible_until_due(bus: DbMessageBus, fake_clock: FakeClock) -> None:
    bus.enqueue({"n": 1}, delay_seconds=10)
    assert bus.claim("w1") is None
    fake_clock.advance(10)
    assert bus.claim("w1") is not None


def test_nack_retries_then_dead_letters(bus: DbMessageBus, fake_clock: FakeClock) -> None:
    bus.enqueue({"n": 1})
    first = bus.claim("w1")
    assert first is not None
    bus.nack(first.id, "boom", retry_delay_seconds=5)
    assert bus.claim("w1") is None, "retry waits for its delay"
    fake_clock.advance(5)
    second = bus.claim("w1")
    assert second is not None and second.attempts == 2
    bus.nack(second.id, "boom again")
    stored = bus.get(second.id)
    assert stored is not None and stored.metadata["state"] == DEAD
    assert bus.dead_count() == 1
    assert bus.requeue_dead(second.id)
    assert bus.claim("w1") is not None


def test_redelivery_after_simulated_worker_crash(bus: DbMessageBus, fake_clock: FakeClock) -> None:
    bus.enqueue({"n": 1})
    crashed = bus.claim("w1")
    assert crashed is not None
    # The worker dies without ack/nack. Before the lease expires nobody else sees the job.
    fake_clock.advance(29)
    assert bus.claim("w2") is None
    fake_clock.advance(2)
    redelivered = bus.claim("w2")
    assert redelivered is not None and redelivered.id == crashed.id
    assert redelivered.attempts == 2


def test_extended_lease_prevents_redelivery_of_long_jobs(
    bus: DbMessageBus, fake_clock: FakeClock
) -> None:
    bus.enqueue({"n": 1})
    job = bus.claim("w1")
    assert job is not None
    bus.extend(job.id, 600)
    fake_clock.advance(300)
    assert bus.claim("w2") is None, "a job still inside its extended lease is not redelivered"
    fake_clock.advance(301)
    assert bus.claim("w2") is not None


def test_orphaned_claims_from_dead_local_processes_are_released(bus: DbMessageBus) -> None:
    bus.enqueue({"n": 1})
    bus.enqueue({"n": 2})
    dead_pid = 2**22 + 12345  # far above any live pid on the test machine
    orphan = bus.claim(worker_identity("worker-1", pid=dead_pid))
    alive = bus.claim(worker_identity("worker-2"))
    assert orphan is not None and alive is not None
    assert bus.release_orphans() == 1
    again = bus.claim("w3")
    assert again is not None and again.id == orphan.id


def test_cancelled_job_is_not_claimed_and_ack_does_not_revive_it(bus: DbMessageBus) -> None:
    job_id = bus.enqueue({"n": 1})
    job = bus.claim("w1")
    assert job is not None
    with bus.database.session() as session:
        assert bus.cancel_in(session, job_id, "run cancelled")
    bus.ack(job_id, {"late": True})
    bus.nack(job_id, "late failure")
    stored = bus.get(job_id)
    assert stored is not None and stored.metadata["state"] == CANCELLED
    assert bus.claim("w2") is None


def test_concurrent_claimers_never_process_a_job_twice(bus: DbMessageBus) -> None:
    total = 60
    for index in range(total):
        bus.enqueue({"n": index})
    seen: list[int] = []
    lock = threading.Lock()

    def worker(name: str) -> None:
        while True:
            job = bus.claim(name)
            if job is None:
                return
            with lock:
                seen.append(job.id)
            bus.ack(job.id)

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert len(seen) == total
    assert len(set(seen)) == total, "no job may be claimed by two workers"
    assert bus.pending_count() == 0
    for job_id in seen:
        stored = bus.get(job_id)
        assert stored is not None and stored.metadata["state"] == DONE


def test_unavailable_bus_adapter_is_refused() -> None:
    # The engine enqueues jobs inside its own transaction (an outbox), which a broker cannot
    # join, so only the database bus exists (RabbitMQ removed, upgrade guide D8).
    from pydantic import ValidationError

    from app.config import BusSettings

    with pytest.raises(ValidationError):
        BusSettings.model_validate({"adapter": "rabbitmq"})
