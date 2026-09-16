"""Zamanlayici testleri -- cok okullu tam cevrim.

Kanitlanmasi istenen dort sey:

1. Okul basina sure butcesi ayri ayri uygulaniyor.
2. Butceyi asan okul **erteleniyor**: kalan ogrenciler saklaniyor ve bir
   sonraki kosuda listenin basina aliniyor.
3. Bir okul duserse tur durmuyor, diger okullar etkilenmiyor.
4. Gece penceresini beklemeden tetiklenebilen bir test kipi var ve bu kip
   uretim yolunun **ayni** kodu.

Birim testleri sahte bir `Store` ile kosar; entegrasyon testleri gercek
SurrealDB'ye yazar (konteyner yoksa atlanir).
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from src.compute import clock
from src.scheduler import WINDOW_END_HOUR, WINDOW_START_HOUR, Scheduler, in_window
from src.source import FileSource
from src.store import CollectingClient, Store

from .fakes import FakeSource
from .zeka_db import (
    NOW,
    TERM_START,
    count_rows,
    dataset,
    fresh_schema_client,
    requires_db,
    select,
    write_fixtures,
)

DAY = clock.DAY_MS


class FakeMonotonic:
    """Her okumada sabit miktar ilerleyen sahte kronometre.

    Butce testleri gercek `time.monotonic` ile makinenin hizina baglanirdi;
    burada her cagri `step` saniye ilerler, dolayisiyla "kac ogrenciden sonra
    butce dolar" **sayilabilir** bir seydir.
    """

    def __init__(self, step: float = 0.0) -> None:
        self.value = 0.0
        self.step = step

    def __call__(self) -> float:
        current = self.value
        self.value += self.step
        return current


def make_scheduler(data_by_school: dict[str, dict], **kw) -> tuple[Scheduler, Store]:
    store = Store(CollectingClient())
    failing = kw.pop("failing", set())

    def factory(school: str):
        if school in failing:
            raise RuntimeError(f"kaynak kurulamadi: {school}")
        return FakeSource(data_by_school.get(school, {}))

    scheduler = Scheduler(
        factory,
        store,
        list(data_by_school),
        term_start_ms=TERM_START,
        clock_fn=lambda: NOW,
        **kw,
    )
    return scheduler, store


def ids_of(data: dict) -> list[str]:
    return [k for k in data if not k.startswith("_")]


# ===========================================================================
# BIRIM
# ===========================================================================


class TestWindow(unittest.TestCase):
    def test_window_is_three_to_five_tr(self) -> None:
        base = clock.tr_day(NOW) * DAY - clock.TR_OFFSET_MS
        for hour in range(24):
            stamp = base + hour * 3_600_000
            self.assertEqual(
                in_window(stamp),
                WINDOW_START_HOUR <= hour < WINDOW_END_HOUR,
                hour,
            )


class TestOrderingAndOnceADay(unittest.IsolatedAsyncioTestCase):
    async def test_schools_run_in_fixed_alphabetical_order(self) -> None:
        data = {"c-okul": dataset(3), "a-okul": dataset(3), "b-okul": dataset(3)}
        scheduler, _ = make_scheduler(data)
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["a-okul", "b-okul", "c-okul"])

    async def test_a_school_runs_only_once_per_tr_day(self) -> None:
        data = {"a-okul": dataset(3)}
        scheduler, _ = make_scheduler(data)
        first = await scheduler.run_once(NOW)
        second = await scheduler.run_once(NOW + 3_600_000)
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        # Ertesi TR gunu yeniden kosar.
        third = await scheduler.run_once(NOW + DAY)
        self.assertEqual(len(third), 1)

    async def test_partial_school_is_promoted_next_round(self) -> None:
        data = {"a-okul": dataset(3), "b-okul": dataset(3)}
        scheduler, _ = make_scheduler(data, budgets={"b-okul": -1})
        await scheduler.run_once(NOW)
        order = await scheduler.run_once(NOW + DAY)
        self.assertEqual([r.school for r in order][0], "b-okul")


class TestPerSchoolBudget(unittest.IsolatedAsyncioTestCase):
    async def test_budget_is_per_school(self) -> None:
        data = {"bol-okul": dataset(4), "dar-okul": dataset(4)}
        scheduler, _ = make_scheduler(
            data, budget_ms=60_000, budgets={"dar-okul": -1}
        )
        results = {r.school: r for r in await scheduler.run_once(NOW)}
        self.assertEqual(scheduler.budget_for("bol-okul"), 60_000)
        self.assertEqual(scheduler.budget_for("dar-okul"), -1)
        self.assertFalse(results["bol-okul"].budget_exceeded)
        self.assertEqual(results["bol-okul"].status, "ok")
        self.assertTrue(results["dar-okul"].budget_exceeded)
        self.assertEqual(results["dar-okul"].status, "partial")

    async def test_exceeding_school_defers_its_students(self) -> None:
        data = {"dar-okul": dataset(5)}
        scheduler, _ = make_scheduler(data, budgets={"dar-okul": -1})
        result = (await scheduler.run_once(NOW))[0]
        self.assertEqual(len(result.pending_students), 5)
        self.assertEqual(scheduler.pending_for("dar-okul"), result.pending_students)

    async def test_next_run_resumes_from_the_deferred_students(self) -> None:
        """Ertelenen ogrenciler bir sonraki kosuda listenin BASINA alinir."""
        clockwork = FakeMonotonic(step=0.0)
        data = {"okul": dataset(6)}
        scheduler, _ = make_scheduler(
            data, budgets={"okul": -1}, monotonic_fn=clockwork
        )
        first = (await scheduler.run_once(NOW))[0]
        self.assertEqual(first.students_ok, 0)
        deferred = scheduler.pending_for("okul")
        self.assertEqual(len(deferred), 6)

        # Ikinci gece bol butceyle: hepsi isleniyor, bekleyen kalmiyor.
        scheduler._budgets["okul"] = 60_000
        second = (await scheduler.run_once(NOW + DAY))[0]
        self.assertEqual(second.students_ok, 6)
        self.assertEqual(scheduler.pending_for("okul"), [])

    async def test_partial_budget_leaves_exactly_the_unprocessed_students(self) -> None:
        """Sahte kronometre: butce tam ortada dolar, kalanlar sayilabilir."""
        data = {"okul": dataset(8)}
        # `run_school` her ogrenci icin bir kez `elapsed_ms()` cagirir: once
        # 1. gecis (8 cagri), sonra 2. gecis (8 cagri). Adim 1 sn secilirse
        # 11 sn butce, 1. gecisin tamamina + 2. gecisin ilk ucune yeter.
        scheduler, _ = make_scheduler(
            data, budget_ms=11_000, monotonic_fn=FakeMonotonic(step=1.0)
        )
        result = (await scheduler.run_once(NOW))[0]
        self.assertTrue(result.budget_exceeded)
        self.assertEqual(result.status, "partial")
        self.assertEqual(result.students_ok, 3)
        self.assertEqual(len(result.pending_students), 5)
        self.assertEqual(
            result.students_ok + result.students_skipped + result.students_failed,
            8,
        )
        # Yarim kalan ogrenciler bir sonraki kosuya devredildi.
        self.assertEqual(scheduler.pending_for("okul"), result.pending_students)


class TestSchoolIsolation(unittest.IsolatedAsyncioTestCase):
    async def test_a_failing_school_does_not_stop_the_round(self) -> None:
        data = {"a-okul": dataset(3), "kirik-okul": dataset(3), "z-okul": dataset(3)}
        scheduler, _ = make_scheduler(data, failing={"kirik-okul"})
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["a-okul", "z-okul"])
        self.assertEqual(scheduler._failures, ["kirik-okul"])
        for result in results:
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.students_ok, 3)

    async def test_failed_school_is_retried_in_the_same_night(self) -> None:
        """Dusen okulun gunu isaretlenmez; ayni gece yeni tik onu yeniden dener."""
        data = {"kirik-okul": dataset(2)}
        scheduler, _ = make_scheduler(data, failing={"kirik-okul"})
        self.assertEqual(await scheduler.run_once(NOW), [])
        self.assertEqual(scheduler._failures, ["kirik-okul"])
        # Kaynak duzelirse ayni gece kosar.
        scheduler._source_factory = lambda school: FakeSource(data[school])
        again = await scheduler.run_once(NOW + 900_000)
        self.assertEqual(len(again), 1)


class TestServeTestMode(unittest.IsolatedAsyncioTestCase):
    async def test_serve_can_be_driven_without_waiting_for_the_night(self) -> None:
        data = {"a-okul": dataset(3), "b-okul": dataset(3)}
        scheduler, _ = make_scheduler(data)
        ticks = await scheduler.serve(
            tick_seconds=0.001, ignore_window=True, max_ticks=3
        )
        self.assertEqual(ticks, 3)
        # Gunde bir kural: uc tik atildi, her okul yine de bir kez kostu.
        self.assertEqual(sorted(scheduler._last_run_day), ["a-okul", "b-okul"])

    async def test_serve_outside_the_window_does_nothing(self) -> None:
        """Pencere kontrolu uretim yolunda aynen duruyor."""
        noon = clock.tr_day(NOW) * DAY - clock.TR_OFFSET_MS + 12 * 3_600_000
        data = {"a-okul": dataset(2)}
        store = Store(CollectingClient())
        scheduler = Scheduler(
            lambda school: FakeSource(data[school]),
            store,
            list(data),
            clock_fn=lambda: noon,
        )
        await scheduler.serve(tick_seconds=0.001, max_ticks=2)
        self.assertEqual(scheduler._last_run_day, {})

    async def test_stop_event_ends_the_loop(self) -> None:
        scheduler, _ = make_scheduler({"a-okul": dataset(2)})
        stop = asyncio.Event()
        task = asyncio.create_task(
            scheduler.serve(stop=stop, tick_seconds=0.01, ignore_window=True)
        )
        await asyncio.sleep(0.05)
        stop.set()
        ticks = await asyncio.wait_for(task, timeout=2)
        self.assertGreaterEqual(ticks, 1)


# ===========================================================================
# ENTEGRASYON -- gercek SurrealDB, cok okullu tam cevrim
# ===========================================================================


@requires_db
class TestFullCycleAgainstSurreal(unittest.IsolatedAsyncioTestCase):
    """Fikstur -> hesap -> tavsiye -> GERCEK yazim -> `insight_run`."""

    async def asyncSetUp(self) -> None:
        self.client = fresh_schema_client("cevrim")
        self.store = Store(self.client)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.schools = ["kadikoy-lisesi", "uskudar-lisesi"]
        self.sizes = {"kadikoy-lisesi": 8, "uskudar-lisesi": 5}
        for school in self.schools:
            write_fixtures(self.root, school, dataset(self.sizes[school]))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def _scheduler(self, **kw) -> Scheduler:
        return Scheduler(
            lambda school: FileSource(self.root),
            self.store,
            self.schools,
            term_start_ms=TERM_START,
            clock_fn=lambda: NOW,
            **kw,
        )

    async def test_full_round_writes_both_schools(self) -> None:
        results = await self._scheduler().run_once(NOW)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.students_ok, self.sizes[result.school])
            self.assertGreater(result.rows_written, 0)

        for school in self.schools:
            self.assertEqual(
                count_rows(self.client, "student_summary", f"school = '{school}'"),
                self.sizes[school],
            )
            self.assertEqual(
                count_rows(self.client, "insight_run", f"school = '{school}'"), 1
            )
        self.assertGreater(count_rows(self.client, "recommendation"), 0)

    async def test_tenant_isolation_end_to_end(self) -> None:
        await self._scheduler().run_once(NOW)
        for school in self.schools:
            rows = select(
                self.client,
                "SELECT school, student FROM student_summary WHERE school = $s;",
                {"s": school},
            )
            self.assertEqual(len(rows), self.sizes[school])
            self.assertTrue(all(r["school"] == school for r in rows))
            recs = select(
                self.client,
                "SELECT school FROM recommendation WHERE school = $s;",
                {"s": school},
            )
            self.assertTrue(all(r["school"] == school for r in recs))
        # Toplam, iki okulun toplamindan fazla degil: sizan satir yok.
        self.assertEqual(
            count_rows(self.client, "student_summary"), sum(self.sizes.values())
        )

    async def test_budget_exceeded_school_is_deferred_others_are_not(self) -> None:
        scheduler = self._scheduler(budgets={"uskudar-lisesi": -1})
        results = {r.school: r for r in await scheduler.run_once(NOW)}
        self.assertEqual(results["kadikoy-lisesi"].status, "ok")
        self.assertEqual(results["uskudar-lisesi"].status, "partial")
        self.assertTrue(results["uskudar-lisesi"].budget_exceeded)

        # Butcesiz okulun satirlari var, ertelenen okulunkiler yok.
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'kadikoy-lisesi'"), 8
        )
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'uskudar-lisesi'"), 0
        )
        # `insight_run` ertelemeyi kagit uzerinde tasiyor.
        row = select(
            self.client,
            "SELECT * FROM insight_run WHERE school = 'uskudar-lisesi';",
        )[0]
        self.assertEqual(row["status"], "partial")
        self.assertTrue(row["budget_exceeded"])
        self.assertEqual(len(row["pending_students"]), 5)

        # Ertesi gece bol butceyle: kaldigi yerden tamamlaniyor.
        scheduler._budgets["uskudar-lisesi"] = 60_000
        second = {r.school: r for r in await scheduler.run_once(NOW + DAY)}
        self.assertEqual(second["uskudar-lisesi"].status, "ok")
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'uskudar-lisesi'"), 5
        )
        self.assertEqual(scheduler.pending_for("uskudar-lisesi"), [])

    async def test_one_broken_school_does_not_block_the_other(self) -> None:
        def factory(school: str):
            if school == "uskudar-lisesi":
                raise RuntimeError("kaynak kurulamadi")
            return FileSource(self.root)

        scheduler = Scheduler(
            factory,
            self.store,
            self.schools,
            term_start_ms=TERM_START,
            clock_fn=lambda: NOW,
        )
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["kadikoy-lisesi"])
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'kadikoy-lisesi'"), 8
        )
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'uskudar-lisesi'"), 0
        )

    async def test_pending_survives_a_process_restart(self) -> None:
        """Bellek sifirlansa bile devreden liste `insight_run`'dan geri gelir."""
        first = self._scheduler(budgets={"uskudar-lisesi": -1})
        await first.run_once(NOW)
        self.assertEqual(len(first.pending_for("uskudar-lisesi")), 5)

        # Yeni bir `Scheduler` nesnesi = yeniden baslatilmis surec.
        second = self._scheduler()
        self.assertEqual(second.pending_for("uskudar-lisesi"), [])
        results = {r.school: r for r in await second.run_once(NOW + DAY)}
        self.assertEqual(results["uskudar-lisesi"].status, "ok")
        self.assertEqual(results["uskudar-lisesi"].students_ok, 5)
        self.assertEqual(
            count_rows(self.client, "student_summary", "school = 'uskudar-lisesi'"), 5
        )

    async def test_serve_loop_runs_the_whole_cycle(self) -> None:
        """Test kipi: pencereyi ve 15 dakikalik tigi beklemeden tam cevrim."""
        scheduler = self._scheduler()
        ticks = await scheduler.serve(
            tick_seconds=0.001, ignore_window=True, max_ticks=2
        )
        self.assertEqual(ticks, 2)
        self.assertEqual(
            count_rows(self.client, "student_summary"), sum(self.sizes.values())
        )
        self.assertEqual(count_rows(self.client, "insight_run"), 2)

    async def test_rerunning_the_same_day_does_not_duplicate_rows(self) -> None:
        scheduler = self._scheduler()
        await scheduler.run_once(NOW)
        before = count_rows(self.client, "student_summary")
        scheduler._last_run_day.clear()  # gun kapisini elle ac
        await scheduler.run_once(NOW)
        self.assertEqual(count_rows(self.client, "student_summary"), before)


if __name__ == "__main__":
    unittest.main()
