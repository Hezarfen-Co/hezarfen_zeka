"""Zamanlayici testleri -- cok okullu tam cevrim.

Kanitlanmasi istenen dort sey:

1. Okul basina sure butcesi ayri ayri uygulaniyor.
2. Butceyi asan okul **erteleniyor**: kalan ogrenciler saklaniyor ve bir
   sonraki kosuda listenin basina aliniyor.
3. Bir okul duserse tur durmuyor, diger okullar etkilenmiyor.
4. Gece penceresini beklemeden tetiklenebilen bir test kipi var ve bu kip
   uretim yolunun **ayni** kodu.

Okul listesi artik yapilandirmadan degil **dizinden** gelir: her tikte
`insight.schools.list` cagrilir. Testler sahte bir kopru ile kosar; gercek
veritabani yoktur.
"""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import Any

from src.compute import clock
from src.scheduler import WINDOW_END_HOUR, WINDOW_START_HOUR, Scheduler, in_window
from src.source import FileSource
from src.store import (
    CAP_PENDING,
    CAP_RUN,
    CAP_SCHOOLS,
    CAP_SUMMARY,
    BridgeStore,
    RecordingCaller,
)

from .fakes import FakeSource, dataset, write_fixtures

DAY = clock.DAY_MS
NOW = 1_699_963_200_000  # 2023-11-14 12:00 UTC
TERM_START = NOW - 150 * DAY


class LedgerCaller(RecordingCaller):
    """Kosu defterini tutan sahte backend.

    `insight.run.upsert` ile yazilan `pending_students`, `insight.pending.list`
    ile geri verilir: gercek backend de en taze kosunun listesini boyle okur
    (`db::insight::last_pending`). Okul listesi de buradan gelir.
    """

    def __init__(self, schools: list[str], **kw: Any) -> None:
        super().__init__(**kw)
        self.schools = list(schools)
        self.pending: dict[str, list[str]] = {}

    async def call(
        self, capability: str, school: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        if capability == CAP_SCHOOLS and not self.fail_times:
            self.calls.append((capability, school, payload))
            return {"schools": list(self.schools)}
        if capability == CAP_PENDING and not self.fail_times:
            self.calls.append((capability, school, payload))
            return {"students": list(self.pending.get(school, []))}
        reply = await super().call(capability, school, payload)
        if capability == CAP_RUN:
            self.pending[school] = list(payload["run"].get("pending_students") or [])
        return reply


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


def make_scheduler(
    data_by_school: dict[str, dict], **kw: Any
) -> tuple[Scheduler, LedgerCaller]:
    caller = LedgerCaller(list(data_by_school))
    store = BridgeStore(caller)
    failing = kw.pop("failing", set())

    def factory(school: str):
        if school in failing:
            raise RuntimeError(f"kaynak kurulamadi: {school}")
        return FakeSource(data_by_school.get(school, {}))

    scheduler = Scheduler(
        factory,
        store,
        term_start_ms=TERM_START,
        clock_fn=lambda: NOW,
        **kw,
    )
    return scheduler, caller


def ids_of(data: dict) -> list[str]:
    return [k for k in data if not k.startswith("_")]


def run_rows(caller: RecordingCaller, school: str | None = None) -> list[dict]:
    """Kosu defterine gonderilen satirlar (istege gore tek okul)."""
    rows = [
        (frame, payload["run"])
        for capability, frame, payload in caller.calls
        if capability == CAP_RUN
    ]
    return [row for frame, row in rows if school is None or frame == school]


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
        scheduler, caller = make_scheduler(data)
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["a-okul", "b-okul", "c-okul"])
        # Sira dizinden gelir: okul listesi tek bir cagriyla sorulur.
        self.assertEqual(
            [school for capability, school, _ in caller.calls if capability == CAP_SCHOOLS],
            [""],
        )

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
        self.assertEqual(scheduler.failures(), ["kirik-okul"])
        for result in results:
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.students_ok, 3)

    async def test_failed_school_is_retried_in_the_same_night(self) -> None:
        """Dusen okulun gunu isaretlenmez; ayni gece yeni tik onu yeniden dener."""
        data = {"kirik-okul": dataset(2)}
        scheduler, _ = make_scheduler(data, failing={"kirik-okul"})
        self.assertEqual(await scheduler.run_once(NOW), [])
        self.assertEqual(scheduler.failures(), ["kirik-okul"])
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
        scheduler = Scheduler(
            lambda school: FakeSource(data[school]),
            BridgeStore(LedgerCaller(list(data))),
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
# DIZIN (okul listesi) ve OKUL BASINA DEPO
# ===========================================================================


class DirectoryDrivenTests(unittest.IsolatedAsyncioTestCase):
    """Okul listesi YAPILANDIRMADAN degil, dizinden gelir.

    Her okul KENDI deposundan yazar; deposu cozulemeyen okul dusen okuldur.
    """

    async def test_the_tick_runs_exactly_what_the_directory_reports(self) -> None:
        data = {"a-okul": dataset(2), "b-okul": dataset(2)}
        caller = LedgerCaller(["a-okul"])
        store = BridgeStore(caller)
        scheduler = Scheduler(
            lambda school: FakeSource(data[school]),
            store,
            term_start_ms=TERM_START,
            clock_fn=lambda: NOW,
        )
        self.assertEqual([r.school for r in await scheduler.run_once(NOW)], ["a-okul"])

        # Dizin okul eklerse surec YENIDEN BASLATILMADAN onu da gorur.
        caller.schools.append("b-okul")
        self.assertEqual([r.school for r in await scheduler.run_once(NOW)], ["b-okul"])

    async def test_an_unreadable_directory_leaves_the_tick_empty_not_failed(
        self,
    ) -> None:
        def never(_school: str):
            raise AssertionError("okul listesi yokken kaynak kurulmamali")

        store = BridgeStore(RecordingCaller(fail_capabilities={CAP_SCHOOLS}))
        scheduler = Scheduler(never, store, clock_fn=lambda: NOW)
        self.assertEqual(await scheduler.run_once(NOW), [])
        self.assertEqual(scheduler.failures(), [])

    async def test_a_school_whose_store_cannot_open_fails_alone(self) -> None:
        data = {"b-okul": dataset(2)}

        class Directory:
            """Depo cozulemeyen okul: `TenantError`in yerini tutan sahte dizin."""

            async def active_schools(self) -> list[str]:
                return ["a-okul", "b-okul"]

            def store_for(self, slug: str):
                if slug == "a-okul":
                    raise RuntimeError("okul veritabani acilamadi")
                return BridgeStore(LedgerCaller(["b-okul"])).store_for(slug)

            async def close(self) -> None:
                return None

        scheduler = Scheduler(
            lambda school: FakeSource(data[school]),
            Directory(),
            term_start_ms=TERM_START,
            clock_fn=lambda: NOW,
        )
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["b-okul"])
        self.assertEqual(scheduler.failures(), ["a-okul"])


# ===========================================================================
# KOPRU UZERINDEN COK OKULLU TAM CEVRIM
# ===========================================================================


class FullCycleThroughTheBridge(unittest.IsolatedAsyncioTestCase):
    """Fikstur -> hesap -> tavsiye -> kopruye yazim -> kosu defteri."""

    async def asyncSetUp(self) -> None:
        self.caller = LedgerCaller(["kadikoy-lisesi", "uskudar-lisesi"])
        self.store = BridgeStore(self.caller)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.schools = ["kadikoy-lisesi", "uskudar-lisesi"]
        self.sizes = {"kadikoy-lisesi": 8, "uskudar-lisesi": 5}
        for school in self.schools:
            write_fixtures(self.root, school, dataset(self.sizes[school]))

    async def asyncTearDown(self) -> None:
        self._tmp.cleanup()

    def _scheduler(self, **kw: Any) -> Scheduler:
        return Scheduler(
            lambda school: FileSource(self.root),
            self.store,
            term_start_ms=TERM_START,
            clock_fn=lambda: NOW,
            **kw,
        )

    def summaries_of(self, school: str) -> list[dict]:
        return [
            row
            for capability, frame, payload in self.caller.calls
            if capability == CAP_SUMMARY and frame == school
            for row in payload["rows"]
        ]

    async def test_full_round_writes_both_schools(self) -> None:
        results = await self._scheduler().run_once(NOW)
        self.assertEqual(len(results), 2)
        for result in results:
            self.assertEqual(result.status, "ok")
            self.assertEqual(result.students_ok, self.sizes[result.school])
            self.assertGreater(result.rows_written, 0)

        for school in self.schools:
            self.assertEqual(len(self.summaries_of(school)), self.sizes[school])
            runs = run_rows(self.caller, school)
            self.assertEqual(len(runs), 2)  # baslangic + bitis
            self.assertEqual(runs[-1]["status"], "ok")

    async def test_every_write_carries_its_own_school_frame(self) -> None:
        """Okul kimligi CERCEVEDEDIR: her yazim kendi okulunun slug'iyla gider."""
        await self._scheduler().run_once(NOW)
        frames = {
            frame
            for capability, frame, _ in self.caller.calls
            if capability == CAP_SUMMARY
        }
        self.assertEqual(frames, set(self.schools))
        for school in self.schools:
            self.assertEqual(len(self.summaries_of(school)), self.sizes[school])

    async def test_budget_exceeded_school_is_deferred_others_are_not(self) -> None:
        scheduler = self._scheduler(budgets={"uskudar-lisesi": -1})
        results = {r.school: r for r in await scheduler.run_once(NOW)}
        self.assertEqual(results["kadikoy-lisesi"].status, "ok")
        self.assertEqual(results["uskudar-lisesi"].status, "partial")
        self.assertTrue(results["uskudar-lisesi"].budget_exceeded)

        # Butcesiz okulun satirlari var, ertelenen okulunkiler yok.
        self.assertEqual(len(self.summaries_of("kadikoy-lisesi")), 8)
        self.assertEqual(self.summaries_of("uskudar-lisesi"), [])
        # `insight_run` ertelemeyi kagit uzerinde tasiyor (ayni anahtara iki
        # yazim: basta 'running', sonda 'partial').
        row = run_rows(self.caller, "uskudar-lisesi")[-1]
        self.assertEqual(row["status"], "partial")
        self.assertTrue(row["budget_exceeded"])
        self.assertEqual(len(row["pending_students"]), 5)

        # Ertesi gece bol butceyle: kaldigi yerden tamamlaniyor.
        scheduler._budgets["uskudar-lisesi"] = 60_000
        second = {r.school: r for r in await scheduler.run_once(NOW + DAY)}
        self.assertEqual(second["uskudar-lisesi"].status, "ok")
        self.assertEqual(len(self.summaries_of("uskudar-lisesi")), 5)
        self.assertEqual(scheduler.pending_for("uskudar-lisesi"), [])

    async def test_one_broken_school_does_not_block_the_other(self) -> None:
        def factory(school: str):
            if school == "uskudar-lisesi":
                raise RuntimeError("kaynak kurulamadi")
            return FileSource(self.root)

        scheduler = Scheduler(
            factory, self.store, term_start_ms=TERM_START, clock_fn=lambda: NOW
        )
        results = await scheduler.run_once(NOW)
        self.assertEqual([r.school for r in results], ["kadikoy-lisesi"])
        self.assertEqual(len(self.summaries_of("kadikoy-lisesi")), 8)
        self.assertEqual(self.summaries_of("uskudar-lisesi"), [])
        self.assertEqual(scheduler.failures(), ["uskudar-lisesi"])

    async def test_pending_survives_a_process_restart(self) -> None:
        """Bellek sifirlansa bile devreden liste kosu defterinden geri gelir."""
        first = self._scheduler(budgets={"uskudar-lisesi": -1})
        await first.run_once(NOW)
        self.assertEqual(len(first.pending_for("uskudar-lisesi")), 5)

        # Yeni bir `Scheduler` nesnesi = yeniden baslatilmis surec.
        second = self._scheduler()
        self.assertEqual(second.pending_for("uskudar-lisesi"), [])
        results = {r.school: r for r in await second.run_once(NOW + DAY)}
        self.assertEqual(results["uskudar-lisesi"].status, "ok")
        self.assertEqual(results["uskudar-lisesi"].students_ok, 5)
        # Yeniden baslayan surec devreden listeyi KOPRUDEN sordu.
        self.assertIn(CAP_PENDING, [capability for capability, _, _ in self.caller.calls])

    async def test_serve_loop_runs_the_whole_cycle(self) -> None:
        """Test kipi: pencereyi ve 15 dakikalik tigi beklemeden tam cevrim."""
        scheduler = self._scheduler()
        ticks = await scheduler.serve(
            tick_seconds=0.001, ignore_window=True, max_ticks=2
        )
        self.assertEqual(ticks, 2)
        for school in self.schools:
            self.assertEqual(len(self.summaries_of(school)), self.sizes[school])
            self.assertEqual(len(run_rows(self.caller, school)), 2)


if __name__ == "__main__":
    unittest.main()
