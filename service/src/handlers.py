"""The three `insight.*` capabilities the service serves to the backend.

`capabilities.py` owns the wire names and the dispatch table but registers no
handler: the table is the contract, this module is the product. `wire()` fills
it, and `bridge.run_once()` calls `wire()` together with
`capabilities.verify_dispatchable()` right before the `Hello` frame goes out --
a name that cannot be dispatched must never be advertised, and that is the
defect class this file exists to close (three names were announced for weeks
with an empty table behind them, so every `insight.student` /
`insight.refresh` dispatch was answered `unknown_capability`).

Why the handlers live outside `capabilities.py`: the table must stay
importable without the compute stack. A handler, on the other hand, is the
whole stack -- a `Source` read, `pipeline.run_school`, and the store writes.

Handlers are coroutines on purpose. `bridge.BridgeProtocol._handle()` awaits a
coroutine handler in the event loop and pushes only *sync* handlers into the
executor (`bridge.py:495-515`); the compute path is async end to end because
every school read is a bridge call of its own.

What each handler answers is the backend's contract, verbatim:
`hezarfen_backend/src/ai/insight.rs` (the payload structs) and
`src/web/insights.rs` (the doors). Where a contract field cannot be produced
from the data the bridge exposes, the answer says so in `coverage` instead of
filling it with a plausible value.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

from . import capabilities
from . import config
from .compute import attention as attention_mod
from .compute import marks as marks_mod
from .pipeline import StudentOutcome, run_school
from .protocol import CapabilityError
from .source import NOT_PERMITTED
from .store import attention_items, recommendation_rows

#: `StudentOutcome.error_kind` -> the refusal code the caller branches on.
#: A read that could not be made is `unavailable` (the source may come back);
#: a compute that fell over is `internal` (it will not).
_ERROR_CODES = {"fetch": "unavailable", "compute": "internal"}

#: A structured read-refusal code (`SourceError.code`) -> the refusal code the
#: answer carries. Only a genuine authority stop earns its own code: HTTP
#: 401/403 means "the identity we read as may not see this", which the caller
#: must be able to tell apart from "the service broke" (`unavailable`) --
#: `not_permitted` says exactly that. Every other source error keeps the
#: module's `_ERROR_CODES` mapping.
_REFUSAL_CODES = {NOT_PERMITTED: NOT_PERMITTED}


def _refusal_code(outcome: StudentOutcome) -> str:
    """The refusal code for one failed student, preferring a typed read code."""
    if outcome.error_code in _REFUSAL_CODES:
        return _REFUSAL_CODES[outcome.error_code]
    return _ERROR_CODES.get(outcome.error_kind or "compute", "internal")


def _refusals(outcomes: list[StudentOutcome]) -> list[dict[str, Any]]:
    """The structured read-refusals across a run, each with `user_id`.

    Empty when every failure was a compute break (no path/status to report):
    a bare message is all the caller can be told in that case.
    """
    rows: list[dict[str, Any]] = []
    for outcome in outcomes:
        refusal = outcome.refusal()
        if refusal is not None:
            rows.append({"user_id": outcome.student, **refusal})
    return rows

#: What this version cannot answer, said once. These notes travel in every
#: answer's `coverage.unavailable`: the contract's response members are all
#: optional (`total=False`), so an omitted field is legal -- but an omission a
#: reader cannot see is indistinguishable from a field nobody asked about.
_UNAVAILABLE = {
    "archetype": (
        "no study-pattern classifier exists in this version; the field is "
        "omitted rather than guessed"
    ),
    "topic_gaps": (
        "item-level data (question, choice, answer) is not in the bridge read "
        "allowlist; see docs/BACKEND-GEREKSINIMLERI.md item 2"
    ),
    "roster": (
        "no member listing; a class roster is derived from the ids addressed "
        "by that course's homework (the same workaround as "
        "pipeline.discover_students)"
    ),
    "term": "no term directory; `term` must be an ISO-8601 date",
}

#: School slug -> lock. One compute per school at a time: a dispatched refresh
#: and the night scheduler can overlap, and two `run_school` sweeps on one
#: school would interleave the day's run-ledger row (the row is keyed by
#: `run_day`) and race the per-student upserts. In-process only, which is
#: enough because the service is one process (`scheduler.py:44-45`).
_locks: dict[str, asyncio.Lock] = {}

#: Set once by `bridge._serve`: `school -> Source`. Writes and reads travel the
#: same bridge, so the factory closes over the live connection.
_source_factory: Callable[[str], Any] | None = None


def bind_source(factory: Callable[[str], Any]) -> None:
    """Bind the school -> `Source` factory. Called once, at startup."""
    global _source_factory
    _source_factory = factory


def _source(school: str) -> Any:
    """The live source for one school. Never a fabricated or default one:
    a handler that cannot read is `unavailable`, not silently empty."""
    if _source_factory is None:
        raise CapabilityError(
            "unavailable",
            "no data source is bound; bridge._serve() binds it at startup",
        )
    return _source_factory(school)


def _principal(payload: dict[str, Any], capability: str) -> str | None:
    """The identity a dispatch's reads run as: the payload's `requested_by`.

    Every read this dispatch makes must run as someone the backend will
    actually authorize. Named, the id travels as `on_behalf_of`; unnamed (an
    older backend that does not send the field yet) the reads fall back to
    today's behaviour -- the synthetic `ai` role -- which sees no course and
    therefore answers empty or 403. That is a degradation, never a refusal:
    the service must not start rejecting work merely because a field is
    missing, so the fallback is logged LOUDLY, once per dispatch, naming the
    consequence, and the dispatch proceeds.
    """
    who = payload.get("requested_by")
    if isinstance(who, str) and who.strip():
        return who.strip()
    config.log(
        "warn",
        f"{capability}: payload'da 'requested_by' yok (eski backend); okumalar "
        "servisin kendi 'ai' kimligiyle yapilir -- o rol hicbir dersi goremedigi "
        "icin sonuc BOS ya da 403 olur (ai/server.rs:853-867)",
    )
    return None


def wire() -> None:
    """Register every advertised name. Idempotent; called from `run_once`."""
    capabilities.register(capabilities.INSIGHT_STUDENT, student)
    capabilities.register(capabilities.INSIGHT_CLASS, klass)
    capabilities.register(capabilities.INSIGHT_REFRESH, refresh)


def _lock_for(school: str) -> asyncio.Lock:
    lock = _locks.get(school)
    if lock is None:
        lock = asyncio.Lock()
        _locks[school] = lock
    return lock


def _now_ms() -> int:
    return int(time.time() * 1000)


def _iso(ms: int) -> str:
    """Unix ms -> ISO-8601 UTC. The contract's `generated_at`/`started_at`."""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def _iso_ms(value: Any, field: str) -> int:
    """The only date shape this service can honor: ISO-8601 -> unix ms.

    It reaches the pipeline as `term_start_ms`, which is the one way a caller
    can move the `attention` window's start (`attention._cold_start`): a
    recent `since` means "the term just began", which is what an ISO date can
    honestly mean to a service that has no term directory.
    """
    if not isinstance(value, str) or not value.strip():
        raise CapabilityError("bad_request", f"'{field}' must be an ISO-8601 date")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        raise CapabilityError(
            "bad_request", f"'{field}' is not a readable ISO-8601 date: {value!r}"
        ) from None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _sections(value: Any) -> tuple[str, ...] | None:
    """`sections` as the pipeline's filter set; `None` is "all of them"."""
    if value is None:
        return None
    allowed = ", ".join(capabilities.SECTIONS)
    if not isinstance(value, list) or not all(
        isinstance(name, str) and name.strip() for name in value
    ):
        raise CapabilityError("bad_request", f"'sections' must name some of: {allowed}")
    names = tuple(name.strip() for name in value)
    unknown = [name for name in names if name not in capabilities.SECTIONS]
    if unknown:
        raise CapabilityError(
            "bad_request",
            f"'sections' names something this service does not compute: "
            f"{', '.join(unknown)} (allowed: {allowed})",
        )
    return names


def _top_n(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CapabilityError("bad_request", "'top_n' must be a positive integer")
    return value


def _cards(recs: list[Any]) -> list[dict[str, Any]]:
    """The answer's card shape = the stored row minus storage bookkeeping.

    Built through the same `store.recommendation_rows` the write uses, so the
    cards in the answer are exactly the cards that can land: a card the store
    would refuse (no evidence beyond `limitation`) is not claimed here either.
    `retain_until` stays out: it is the sweep's business, not the wire's.
    """
    rows, _rejected = recommendation_rows(recs)
    for row in rows:
        row.pop("retain_until", None)
    return rows


async def _sweep(
    school: str,
    student_ids: list[str] | None,
    *,
    now: int,
    term_start_ms: int | None = None,
    sections: tuple[str, ...] | None = None,
    nightly: bool = False,
    on_behalf_of: str | None = None,
) -> tuple[Any, list[StudentOutcome]]:
    """One scoped compute: the pipeline, the store, and the outcomes.

    `nightly=False` for the per-student and per-class handlers: the run
    ledger, the departed purge and the retention sweep belong to the
    school-wide job. A dispatched compute must not overwrite the day's
    `zeka_run` row (keyed by `run_day`) nor claim a subset of students is the
    active roster. `handlers.refresh` is the one caller that passes `True`:
    it *is* the school sweep, on demand, and its run record belongs in the
    same ledger row the backend's `GET /insights/runs` reads.
    """
    outcomes: list[StudentOutcome] = []
    store = capabilities.store().store_for(school)
    result = await run_school(
        _source(school),
        store,
        school,
        now_ms=now,
        student_ids=None if student_ids is None else list(student_ids),
        term_start_ms=term_start_ms,
        nightly=nightly,
        sections=sections,
        on_behalf_of=on_behalf_of,
        outcomes=outcomes,
    )
    return result, outcomes


async def student(school: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`insight.student` -- one student, computed and written now.

    The two request knobs are honored at the only place they can be:
    `since` moves the term start the attention window is measured from, and
    `sections` narrows which of the four summary modules is computed. A
    module that was not requested is written `null` -- the backend's
    `SummaryRow` calls that "not computed", distinct from `{}` ("read, and
    there was nothing").
    """
    user_id = capabilities.require_text(payload, "user_id")
    since = payload.get("since")
    term_start_ms = _iso_ms(since, "since") if since is not None else None
    sections = _sections(payload.get("sections"))
    on_behalf_of = _principal(payload, "insight.student")
    now = _now_ms()
    async with _lock_for(school):
        result, outcomes = await _sweep(
            school,
            [user_id],
            now=now,
            term_start_ms=term_start_ms,
            sections=sections,
            on_behalf_of=on_behalf_of,
        )
    outcome = outcomes[0]
    if outcome.error is not None or outcome.summary is None:
        # A read the requester's identity could not make is NOT an exception:
        # it is a fact the answer must carry, with the path and the status, so
        # the caller can separate "the requester may not read this" from "the
        # service broke". Everything else still raises a typed refusal.
        refusal = outcome.refusal()
        if refusal is not None and outcome.error_code == NOT_PERMITTED:
            return {
                "user_id": user_id,
                "generated_at": _iso(now),
                "signals": [],
                "recommendations": [],
                "coverage": {
                    "reads": dict(outcome.coverage),
                    "sections": sorted(sections) if sections else "all",
                    "write": {"rows_written": 0, "write_failed": 0},
                    "unavailable": {
                        **_UNAVAILABLE,
                        "attention_triggers": attention_mod.unavailable_triggers(),
                        "permission": [refusal],
                    },
                },
            }
        raise CapabilityError(
            _refusal_code(outcome),
            f"'{user_id}' could not be computed: {outcome.error}",
        )
    summary = outcome.summary
    return {
        "user_id": summary.student,
        "generated_at": _iso(summary.computed_at),
        # The attention list is the signal list. It is teacher-facing and the
        # backend decides who reads it (`web/insights.rs` keeps it out of the
        # student's own view); the handler does not pre-filter it away.
        "signals": attention_items(summary),
        # Cards addressed to this student, and only those: the same table
        # carries the teacher's T3/T4 cards about the student, and the role
        # gate (`audience_role`) is applied here as well as on the read side.
        "recommendations": _cards(
            [
                rec
                for rec in outcome.recommendations
                if rec.audience == user_id and str(rec.audience_role) == "student"
            ]
        ),
        "coverage": {
            "reads": dict(outcome.coverage),
            "sections": sorted(sections) if sections else "all",
            "write": {
                "rows_written": result.rows_written,
                "write_failed": result.write_failed,
            },
            "unavailable": {
                **_UNAVAILABLE,
                "attention_triggers": attention_mod.unavailable_triggers(),
            },
        },
    }


async def _roster_for_course(
    source: Any, school: str, course_id: str, *, on_behalf_of: str | None = None
) -> tuple[list[str], dict[str, int]]:
    """The students this course's homework was addressed to, in order.

    The same workaround `pipeline.discover_students` documents at school
    level, narrowed to one course: there is no member listing in the bridge's
    read allowlist (`docs/BACKEND-GEREKSINIMLERI.md` item 3). A student who
    never received addressed homework for this course is invisible here, and
    the answer says so in `coverage.unavailable.roster`.

    `on_behalf_of`: the school-wide list is only populated for manager+
    (`web/homework.rs::list_homework`), so this read runs as the dispatch's
    requester; without it the roster comes back empty.
    """
    rows = await source.homework_list(school, on_behalf_of)
    if isinstance(rows, dict):
        rows = rows.get("items") or []
    found: list[str] = []
    seen: set[str] = set()
    course_rows = 0
    for row in rows or []:
        if not isinstance(row, dict) or marks_mod.course_id_of(row) != course_id:
            continue
        course_rows += 1
        for uid in row.get("assigned") or []:
            key = str(uid)
            if key not in seen:
                seen.add(key)
                found.append(key)
    return found, {"homework_rows": len(rows or []), "course_rows": course_rows}


async def klass(school: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`insight.class` -- one course's roster, computed as a cohort.

    The backend declares the name but dispatches nothing to it yet
    (`hezarfen_backend/src/ai/insight.rs`, module docs); the handler exists so
    that the advertised name is true the moment a caller appears.

    The cohort is real but partial: the roster comes from homework addresses
    (see `_roster_for_course`), so `cohort_size` counts the students whose
    data could be read, and the answer never presents a truncated list as the
    whole one -- `coverage.attention` carries `total` next to `returned`.
    """
    course_id = capabilities.require_text(payload, "course_id")
    term = payload.get("term")
    term_start_ms = _iso_ms(term, "term") if term is not None else None
    top_n = _top_n(payload.get("top_n"))
    on_behalf_of = _principal(payload, "insight.class")
    now = _now_ms()
    async with _lock_for(school):
        source = _source(school)
        roster, roster_reads = await _roster_for_course(
            source, school, course_id, on_behalf_of=on_behalf_of
        )
        store = capabilities.store().store_for(school)
        outcomes: list[StudentOutcome] = []
        result = await run_school(
            source,
            store,
            school,
            now_ms=now,
            student_ids=roster,
            term_start_ms=term_start_ms,
            nightly=False,
            on_behalf_of=on_behalf_of,
            outcomes=outcomes,
        )
    attention_list: list[dict[str, Any]] = []
    for outcome in outcomes:
        if outcome.summary is None:
            continue
        for item in attention_items(outcome.summary):
            attention_list.append({"user_id": outcome.student, **item})
    # Deterministic order, never a ranking: the doc's own rule (no score, no
    # severity) survives truncation only if the order it truncates is the
    # writer's, not a computed one.
    attention_list.sort(key=lambda item: (item["user_id"], item["trigger"]))
    total = len(attention_list)
    if top_n is not None:
        attention_list = attention_list[:top_n]
    fetched = sum(1 for outcome in outcomes if outcome.coverage)
    return {
        "course_id": course_id,
        "generated_at": _iso(now),
        "cohort_size": fetched,
        "topic_gaps": [],
        "attention_list": attention_list,
        "coverage": {
            "roster": {
                "students": len(roster),
                "fetched": fetched,
                "failed": sum(1 for outcome in outcomes if outcome.error is not None),
                "budget_exceeded": result.budget_exceeded,
                "pending": len(result.pending_students),
                **roster_reads,
            },
            "attention": {"total": total, "returned": len(attention_list)},
            "write": {
                "rows_written": result.rows_written,
                "write_failed": result.write_failed,
            },
            "unavailable": {
                **_UNAVAILABLE,
                "permission": _refusals(outcomes),
            },
        },
    }


async def refresh(school: str, payload: dict[str, Any]) -> dict[str, Any]:
    """`insight.refresh` -- the school sweep, on demand.

    This is the night job's own pipeline (`run_school`, `nightly=True`), so
    the answer is written the same place the scheduler's is: the `zeka_run`
    row the backend's `GET /insights/runs` serves. A refresh of the whole
    school also purges departed students and sweeps retention, exactly like
    the night run; a refresh naming `user_ids` does not -- that list is a
    subset, and `insight.departed.purge` treats its list as the active roster.

    `force` is accepted and has no effect, stated rather than silently
    ignored: the service keeps no result cache, so every refresh recomputes.
    """
    user_ids = payload.get("user_ids")
    if user_ids is not None:
        if not isinstance(user_ids, list) or not all(
            isinstance(uid, str) and uid.strip() for uid in user_ids
        ):
            raise CapabilityError(
                "bad_request", "'user_ids' must be a list of non-empty strings"
            )
        user_ids = [uid.strip() for uid in user_ids]
    on_behalf_of = _principal(payload, "insight.refresh")
    now = _now_ms()
    async with _lock_for(school):
        result, outcomes = await _sweep(
            school, user_ids, now=now, nightly=True, on_behalf_of=on_behalf_of
        )
    return {
        "started_at": _iso(result.started_at),
        "requested": result.students_total,
        "computed": result.students_ok,
        "skipped": result.students_skipped,
        "failed": [
            {
                "user_id": outcome.student,
                "code": _refusal_code(outcome),
                "message": outcome.error or "",
                # A structured refusal carries which path and status stopped it,
                # so a reader can tell "the requester may not read this" (403)
                # from "the service broke" and does not have to parse a string.
                **{
                    key: value
                    for key, value in (outcome.refusal() or {}).items()
                    if key != "code"
                },
            }
            for outcome in outcomes
            if outcome.error is not None
        ],
        # Beyond the backend's struct, which ignores what it does not read.
        # Without it a reader would have to infer "ok" from counts, and a run
        # whose roster could not even be listed (status `failed`, nothing
        # counted) would read as a clean zero.
        "status": result.status,
    }


__all__ = [
    "bind_source",
    "klass",
    "refresh",
    "student",
    "wire",
]
