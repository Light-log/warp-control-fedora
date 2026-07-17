import threading

from warp_control.services.tasks import BackgroundTasks, PeriodicScheduler


def test_background_worker_is_daemon_and_delivers_only_through_idle_add():
    idle_calls = []
    delivered = []
    created = []

    class ImmediateThread:
        def __init__(self, *, target, name, daemon):
            created.append((name, daemon))
            self.target = target

        def start(self):
            self.target()

    tasks = BackgroundTasks(
        idle_add=lambda callback: idle_calls.append(callback) or 1,
        thread_factory=ImmediateThread,
    )

    tasks.submit(lambda: "done", delivered.append)

    assert created == [("warp-control-worker", True)]
    assert delivered == []
    assert len(idle_calls) == 1
    assert idle_calls.pop()() is False
    assert delivered == ["done"]


def test_background_worker_routes_exceptions_through_idle_add():
    idle_calls = []
    errors = []

    class ImmediateThread:
        def __init__(self, *, target, **_kwargs):
            self.target = target

        def start(self):
            self.target()

    tasks = BackgroundTasks(
        idle_add=lambda callback: idle_calls.append(callback),
        thread_factory=ImmediateThread,
    )

    def fail():
        raise RuntimeError("boom")

    tasks.submit(fail, lambda _result: None, errors.append)
    assert errors == []
    idle_calls.pop()()
    assert isinstance(errors[0], RuntimeError)


def test_default_background_worker_uses_real_daemon_threads():
    tasks = BackgroundTasks(idle_add=lambda callback: callback())
    finished = threading.Event()
    thread = tasks.submit(lambda: "ok", lambda _result: finished.set())

    assert thread.daemon is True
    assert finished.wait(1)


def test_periodic_scheduler_restarts_and_cancels_cleanly():
    installed = []
    removed = []
    ticks = []

    scheduler = PeriodicScheduler(
        timeout_add_seconds=lambda seconds, callback: installed.append(
            (seconds, callback)
        )
        or len(installed),
        source_remove=lambda source_id: removed.append(source_id),
    )

    scheduler.start(lambda: ticks.append(None), 5)
    assert installed[0][0] == 5
    assert installed[0][1]() is True
    assert ticks == [None]

    scheduler.start(lambda: ticks.append(None), 10)
    assert removed == [1]
    assert installed[1][0] == 10
    scheduler.stop()
    scheduler.stop()
    assert removed == [1, 2]
