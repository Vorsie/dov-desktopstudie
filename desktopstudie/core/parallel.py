"""Load a batch of items in parallel, every item isolated from the others.

One helper, used by the orchestrator for per-fiche fetches and by the shell for the legend
images. It lives here rather than in `study.py` because it knows nothing about a study: it is a
thread pool with three properties that matter every time a batch of network calls goes out.

*Every item fails on its own.* `pool.map` re-raises the first failure at iteration time and the
remaining results are lost, so one unreachable fiche would cost the whole stage. Here each item
gets its own future and its own except.

*What did not load is counted and logged.* "0 opgehaald" without a reason is not a diagnosis.

*A cancelled batch stops.* The caller's `should_cancel` is polled while items are queued and
after every result, so stopping does not wait for another hundred fetches.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional, Sequence

DEFAULT_WORKERS = 4


class Cancelled(Exception):
    """The caller's should_cancel() asked the run to stop.

    Not a source failure: it is never recorded as one and never swallowed by an isolating
    handler. `study.StudyCancelled` is this same class under the name the rest of the code knows.
    """


def load_each(items: Sequence[Any], load_one: Callable[[Any], None], label: str,
              max_workers: int = DEFAULT_WORKERS, log=None,
              should_cancel: Optional[Callable[[], bool]] = None) -> int:
    """Run `load_one` over `items` in parallel; return how many raised.

    The count and the items that did load never depend on the order in which the threads finish.
    """
    if not items:
        return 0
    stop = should_cancel or (lambda: False)

    def check() -> None:
        if stop():
            raise Cancelled("afgebroken door de gebruiker")

    failed = 0
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = []
        try:
            for item in items:
                check()
                futures.append(pool.submit(load_one, item))
            for future in as_completed(futures):
                try:
                    future.result()
                except Cancelled:
                    raise  # a cancelled run is not a broken item
                except Exception as exc:  # noqa: BLE001 - isolate every item
                    failed += 1
                    if log:
                        log.warning(f"{label} niet opgehaald: {type(exc).__name__}: {exc}")
                check()
        except Cancelled:
            # Drop what has not started yet. Leaving the queue alone would make the pool's own
            # shutdown work through every remaining fetch before the cancellation surfaces, so
            # "stop" would take as long as "finish".
            for future in futures:
                future.cancel()
            raise
    return failed
