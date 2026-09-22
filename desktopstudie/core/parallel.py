"""Load a batch of items in parallel, every item isolated from the others.

One helper, used by the orchestrator for per-fiche fetches and by the shell for the legend
images. It lives here rather than in `study.py` because it knows nothing about a study: it is a
thread pool with three properties that matter every time a batch of network calls goes out.

*Every item fails on its own.* `pool.map` re-raises the first failure at iteration time and the
remaining results are lost, so one unreachable fiche would cost the whole stage. Here each item
gets its own future and its own except.

*What did not load is counted and logged.* "0 opgehaald" without a reason is not a diagnosis,
and the label may be a function of the item, so a batch of places can name the place that fell out.

*A cancelled batch stops.* The caller's `should_cancel` is polled while items are queued and
after every result, so stopping does not wait for another hundred fetches.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Optional, Sequence, Union

DEFAULT_WORKERS = 4
# The one sentence a stopped run says, everywhere. It reaches the user (the message bar, the log
# panel, a script's exit line), so it is written once rather than retyped in every phase.
CANCELLED_MESSAGE = "afgebroken door de gebruiker"


class Cancelled(Exception):
    """The caller's should_cancel() asked the run to stop.

    Not a source failure: it is never recorded as one and never swallowed by an isolating
    handler. `study.StudyCancelled` is this same class under the name the rest of the code knows.
    """


def stop_if(should_cancel: Optional[Callable[[], bool]]) -> None:
    """Raise `Cancelled` when the caller asked to stop, and do nothing when nobody is asking.

    Every phase that can run for minutes polls this - between stages, before each WMS layer,
    between sheets of the layout, between runs of the exporter - so the check and its sentence
    live in one place. `None` is a run nobody can cancel (a script, a test), not an error.
    """
    if should_cancel is not None and should_cancel():
        raise Cancelled(CANCELLED_MESSAGE)


Label = Union[str, Callable[[Any], str]]


def _named(label: Label, item: Any) -> str:
    """What to call this item in a warning: one name for the whole batch, or one per item.

    A batch of fiches is a batch of fiches - "lithologie" says enough. A batch of doorprik points
    is a batch of PLACES, and "virtuele boring niet opgehaald" without the coordinate leaves the
    reader of the log nothing to go back to.
    """
    return label(item) if callable(label) else label


def load_each(items: Sequence[Any], load_one: Callable[[Any], None], label: Label,
              max_workers: int = DEFAULT_WORKERS, log=None,
              should_cancel: Optional[Callable[[], bool]] = None) -> int:
    """Run `load_one` over `items` in parallel; return how many raised.

    The count and the items that did load never depend on the order in which the threads finish.
    """
    if not items:
        return 0

    def check() -> None:
        stop_if(should_cancel)

    failed = 0
    # Not a `with`: its __exit__ is shutdown(wait=True), which joins the items the pool handed out
    # while we were reading the last result - so a cancel would cost two rounds instead of one
    # (measured: 6 s against 3 s on items of 3 s). Cancelling the queue is not enough for that;
    # the running ones have to be left behind too.
    pool = ThreadPoolExecutor(max_workers=max(1, max_workers))
    futures = {}
    try:
        for item in items:
            check()
            futures[pool.submit(load_one, item)] = item
        for future in as_completed(futures):
            try:
                future.result()
            except Cancelled:
                raise  # a cancelled run is not a broken item
            except Exception as exc:  # noqa: BLE001 - isolate every item
                failed += 1
                if log:
                    log.warning(f"{_named(label, futures[future])} niet opgehaald: "
                                f"{type(exc).__name__}: {exc}")
            check()
    except Cancelled:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
    return failed
