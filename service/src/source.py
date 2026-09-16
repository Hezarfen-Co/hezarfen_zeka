"""VERI ERISIM CEPHESI -- hesap modullerinin gorecegi TEK veri yuzeyi.

Bu dosyanin varlik sebebi bir kisitlamadir, bir kolaylik degil.

--- YAPISAL KAPI ---
`Source` arayuzunde yemek, odeme, diyet, mesaj ve sohbet verisine erisen HICBIR
yontem YOKTUR. Bu bir yorum ya da bir kural degil, bir YAPI: hesap modulu o
veriyi isteyemez, cunku cagiracagi fonksiyon yoktur. "Istemeyin" demek yerine
"soyleyemezsiniz" demek, zamanla sapmayan tek yontemdir.

Bu ayni zamanda backend'in kendi cizgisiyle de ortusur: `AI_API_ALLOWLIST`
(`constant.rs:650-676`) "yalnizca bir calisma arkadasinin ihtiyaci olan sey"
diye belgelenir -- kimlik, notlar, dersin notlari, odevler ve ogrencinin kendi
ilerleme raporlari. Yemek, odeme ve mesajlasma yollari o listede zaten YOKTUR.
Yani bu cephe backend'in kapisini gevsetmez, ONU KENDI TARAFIMIZDA TEKRARLAR:
izin listesi degisip bir gun genislerse, ZEKA yine de bu sekiz yontemin disina
cikamaz.

Testte pinlenir: `tests/test_source.py::test_no_forbidden_data_methods`.

--- IKI UYGULAMA ---
* `BridgeSource` -- canli kopru uzerinden `api_get` ile okur. Her yontemin
  kullandigi yol `_TEMPLATES` icinde sabittir ve modul yuklenirken backend'in
  izin listesiyle karsilastirilir. Izin listesinde olmayan bir yolu cagirmayi
  DENEYEN kod yoktur.
* `FileSource` -- JSON fiksturlerden okur. Testlerde ve kopru yokken kullanilir.
  Imza birebir aynidir, boylece hesap modulu hangisiyle kostugunu bilmez.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from . import config
from .protocol import AI_API_ALLOWLIST, ApiErrorCode, ApiRefused, path_allowed


# --- arayuz ----------------------------------------------------------------


@runtime_checkable
class Source(Protocol):
    """Hesap modullerinin gorecegi tek veri yuzeyi.

    Her yontem tek bir okul icin calisir; okul cerceve seviyesinde tasinir ve
    varsayilani yoktur (`ai/protocol.rs:36-47`).
    """

    async def profile(self, school: str, user_id: str) -> dict | None: ...

    async def marks(self, school: str, user_id: str) -> list[dict]: ...

    async def attendance(self, school: str, user_id: str) -> list[dict]: ...

    async def pomodoro(self, school: str, user_id: str) -> list[dict]: ...

    async def homework_report(self, school: str, user_id: str) -> dict | None: ...

    async def homework_list(
        self, school: str, on_behalf_of: str | None = None
    ) -> list[dict]: ...

    async def notes(self, school: str, on_behalf_of: str) -> list[dict]: ...

    async def course_notes(
        self, school: str, course_id: str | None = None
    ) -> list[dict]: ...


#: Cephede ASLA bulunmamasi gereken veri alanlari. Koruma testi bu parcalari
#: `Source` uyelerinin adlarinda arar; biri eklenirse test kirilir.
FORBIDDEN_DATA_TERMS: tuple[str, ...] = (
    "meal",  # yemek menusu / rezervasyon / yoklama
    "menu",
    "dish",
    "payment",  # odeme, borc, defter
    "invoice",
    "ledger",
    "diet",  # diyet profili
    "dietary",
    "message",  # birebir mesajlasma
    "chat",  # sohbet gecmisi
    "conversation",
)

#: Cephenin tam yuzeyi. Buraya bir ad eklemek bilincli bir karardir.
SOURCE_METHODS: tuple[str, ...] = (
    "profile",
    "marks",
    "attendance",
    "pomodoro",
    "homework_report",
    "homework_list",
    "notes",
    "course_notes",
)


# --- yol defteri -----------------------------------------------------------
# Her yontemin karsilik geldigi IZIN LISTESI SABLONU. Somut yol degil, sablon:
# somut yol kayit kimligi tasir (`ai/api.rs:24-28`).

_TEMPLATES: dict[str, str] = {
    "profile": "/users/{id}/profile",
    "marks": "/marks/{user}",
    "attendance": "/attendance/{user}",
    "pomodoro": "/pomodoro/{user}",
    "homework_report": "/homework/report/{user}",
    "homework_list": "/homework",
    "notes": "/notes",
    "course_notes": "/course-notes",
}

# Modul yuklenirken denetlenir: bu defterdeki her sablon backend'in izin
# listesinde OLMAK ZORUNDA. Izin listesi daralirsa servis import aninda
# patlar -- calisma zamaninda sessizce `path_not_allowed` toplamaktansa.
for _name, _template in _TEMPLATES.items():
    if _template not in AI_API_ALLOWLIST:
        raise RuntimeError(
            f"source.{_name} '{_template}' yolunu kullaniyor ama bu yol backend'in "
            "AI_API_ALLOWLIST listesinde yok (constant.rs:656-676)"
        )
if set(_TEMPLATES) != set(SOURCE_METHODS):
    raise RuntimeError("yol defteri ile cephe yuzeyi ayristi")


class SourceError(Exception):
    """Veri okunamadi. `code` makine okunabilirdir."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _require_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceError(ApiErrorCode.MALFORMED, f"'{name}' bos olmayan bir metin olmali")
    return value.strip()


# --- govde cikarimi --------------------------------------------------------
#
# BURADA GENEL BIR NORMALIZE FONKSIYONU YOKTUR, KASITLI OLARAK.
#
# Onceki surumde tek bir `_as_list()` vardi: duz listeyi ve `{"items": ...}`
# zarfini acar, BASKA HER SEY ICIN BOS LISTE donerdi. Bu sessiz bir hataydi ve
# gercekten isliyordu: backend'in `/marks/{user}` ve `/attendance/{user}` uclari
# `items` DEGIL `courses` tasiyan rapor nesneleri dondurur, dolayisiyla kopru
# modunda o iki yontem HER ZAMAN bos liste donuyordu. Hata mesaji yoktu, gunluk
# satiri yoktu; not ve devam hesabinin tamami sessizce bosaliyordu. Fikstur modu
# etkilenmedigi icin testler de yakalamiyordu.
#
# Bu yuzden artik HER yontem kendi ucunun gercek bicimini bilir ve bekledigi
# anahtari adiyla ister. Beklenmeyen bicim SESSIZ BOS degil, `warn` gunlugu +
# ayirt edilebilir `SourceError("unexpected_shape")` uretir.


def _row_dicts(rows: list) -> list[dict]:
    return [row for row in rows if isinstance(row, dict)]


def _extract_rows(
    body: Any,
    key: str,
    *,
    method: str,
    path: str,
    reference: str,
) -> list[dict]:
    """Bir uctan gelen govdeden `key` altindaki satir listesini cikar.

    `body is None` yalnizca 404 demektir (`_get` onu oraya cevirir): router
    calisti ve "boyle bir sey yok" dedi. Bu bir bicim sorunu degildir, bos
    sonuctur.

    Baska her sapma gorunur olur:
    * `key` yoksa -> `warn` + `SourceError("unexpected_shape")`,
    * govde duz liste ise -> kabul edilir ama `warn` yazilir (belgelenen bicim
      zarftir; duz liste gelmesi backend'in degistigini gosterir).
    """
    if body is None:
        return []
    if isinstance(body, dict):
        rows = body.get(key)
        if isinstance(rows, list):
            return _row_dicts(rows)
        config.log(
            "warn",
            f"source.{method}: {path} govdesinde beklenen '{key}' listesi yok "
            f"(gelen anahtarlar: {sorted(body)[:8]}); beklenen bicim {reference}",
        )
        raise SourceError(
            "unexpected_shape",
            f"{path} -> '{key}' listesi yok; beklenen bicim {reference}",
        )
    if isinstance(body, list):
        config.log(
            "warn",
            f"source.{method}: {path} duz liste dondurdu ama belgelenen bicim "
            f"{reference}; backend sapmis olabilir, liste yine de kullaniliyor",
        )
        return _row_dicts(body)
    config.log(
        "warn",
        f"source.{method}: {path} ne nesne ne liste dondurdu ({type(body).__name__}); "
        f"beklenen bicim {reference}",
    )
    raise SourceError(
        "unexpected_shape",
        f"{path} -> {type(body).__name__} dondu; beklenen bicim {reference}",
    )


def _extract_object(
    body: Any,
    *,
    method: str,
    path: str,
    reference: str,
    require: tuple[str, ...] = (),
) -> dict | None:
    """Tek bir nesne dondurun uclar icin. 404 -> `None`.

    `require` verilirse o anahtarlarin hepsi bulunmak zorundadir; biri yoksa
    sessizce yarim bir sozluk dondurmek yerine `warn` + `unexpected_shape`.
    """
    if body is None:
        return None
    if not isinstance(body, dict):
        config.log(
            "warn",
            f"source.{method}: {path} nesne yerine {type(body).__name__} dondurdu; "
            f"beklenen bicim {reference}",
        )
        raise SourceError(
            "unexpected_shape",
            f"{path} -> {type(body).__name__} dondu; beklenen bicim {reference}",
        )
    missing = [name for name in require if name not in body]
    if missing:
        config.log(
            "warn",
            f"source.{method}: {path} govdesinde {missing} alan(lar)i yok "
            f"(gelen anahtarlar: {sorted(body)[:8]}); beklenen bicim {reference}",
        )
        raise SourceError(
            "unexpected_shape",
            f"{path} -> {missing} alan(lar)i yok; beklenen bicim {reference}",
        )
    return body


# --- kopru uygulamasi ------------------------------------------------------


class BridgeSource:
    """`Source`'un canli uygulamasi: her okuma bir `ApiRequest` akisidir.

    `client` yalnizca `api_get(school, path, query=None, on_behalf_of=None)`
    imzasini saglamak zorundadir; testte sahtesi konur.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    async def _get(
        self,
        method_name: str,
        school: str,
        path: str,
        query: str | None = None,
        on_behalf_of: str | None = None,
    ) -> Any:
        school = _require_id(school, "school")
        # Ikinci kemer: yol, defterden turetilse bile tele cikmadan once
        # izin listesine karsi denetlenir.
        if not path_allowed(path):
            raise SourceError(
                ApiErrorCode.PATH_NOT_ALLOWED,
                f"source.{method_name} izin listesi disinda bir yol uretti: {path!r}",
            )
        try:
            response = await self._client.api_get(
                school, path, query=query, on_behalf_of=on_behalf_of
            )
        except ApiRefused as exc:
            raise SourceError(exc.code, str(exc)) from exc
        if response.status == 404:
            # Router calisti ve "yok" dedi. Bu bir tasima hatasi degil
            # (`ai/protocol.rs:196-198`); bos sonuc olarak gecer.
            return None
        if not response.ok:
            raise SourceError(
                "http_error", f"{path} -> HTTP {response.status}"
            )
        return response.body

    async def profile(self, school: str, user_id: str) -> dict | None:
        """Izin listesi yolu: `/users/{id}/profile` (`constant.rs:659`).

        YANIT BICIMI -- `ProfileResponse`, DUZ NESNE (`web/users.rs:707`,
        handler `web/users.rs:1112` -> `Json<ProfileResponse>`):

            { id, username, display_name, ..., stats: {...} }

        Zarf YOKTUR. Nesne oldugu gibi dondurulur; `id` alani zorunlu tutulur
        ki bicim degisirse sessizce yarim bir sozluk gecmesin.

        404 -> `None` (kullanici yok).
        """
        user_id = _require_id(user_id, "user_id")
        path = f"/users/{user_id}/profile"
        body = await self._get("profile", school, path)
        return _extract_object(
            body,
            method="profile",
            path=path,
            reference="ProfileResponse duz nesnesi (web/users.rs:707)",
            require=("id",),
        )

    async def marks(self, school: str, user_id: str) -> list[dict]:
        """Izin listesi yolu: `/marks/{user}` (`constant.rs:670`).

        YANIT BICIMI -- `MarksReport`, RAPOR NESNESI (`web/marks.rs:65`,
        handler `Json<MarksReport>`):

            { user, courses: [CourseMarks], overall_average, overall_grade }

        DIKKAT: burada `items` YOKTUR, `courses` vardir. Sayfalama zarfi degil,
        rapor nesnesidir.

        DONEN SEY: `courses` listesi -- her ogesi bir `CourseMarks`
        (`web/marks.rs:50`):

            { course: CourseResponse, results: [MarkEntry],
              average, average_grade }

        Yani ders blogu listesi; tek tek sinav notlari her blogun `results`
        alanindadir.

        TASINMAYAN: `overall_average` ve `overall_grade`. Arayuz `list[dict]`
        donduruyor, bu yuzden rapor duzeyindeki bu iki alan disarida kalir --
        ikisi de `courses` uzerinden yeniden hesaplanabilir (duz ortalama).
        """
        user_id = _require_id(user_id, "user_id")
        path = f"/marks/{user_id}"
        body = await self._get("marks", school, path)
        return _extract_rows(
            body,
            "courses",
            method="marks",
            path=path,
            reference="MarksReport{user, courses, overall_average, overall_grade} "
            "(web/marks.rs:65)",
        )

    async def attendance(self, school: str, user_id: str) -> list[dict]:
        """Izin listesi yolu: `/attendance/{user}` (`constant.rs:672`).

        YANIT BICIMI -- `AttendanceReport`, RAPOR NESNESI
        (`web/attendance.rs:84`, handler `Json<AttendanceReport>`):

            { user,
              events:   StatusCounts,
              sessions: StatusCounts,
              courses:  [CourseAttendance] }

        DIKKAT: burada da `items` YOKTUR, `courses` vardir.

        DONEN SEY: `courses` listesi -- her ogesi bir `CourseAttendance`
        (`web/attendance.rs:76`):

            { course: CourseResponse, counts: StatusCounts }

        --- HESAP TARAFINA UYARI: BU UC SAYAC DONDURUR, SATIR DEGIL ---
        `StatusCounts` (`web/attendance.rs:31`) sudur:

            { present, absent, late, excused, custom: {...}, total, rate }

        Yani ders basina TOPLAM sayimlardir. Tek tek yoklama SATIRLARI ve
        onlarin TARIHLERI bu uctan GELMEZ. Dolayisiyla:

        * "hangi gun", "hafta ici mi", "haftanin gunu deseni", "son 30 gunde
          kac devamsizlik" gibi ZAMAN EKSENLI hicbir olcu bu veriyle
          hesaplanamaz;
        * hesaplanabilen sey ders basina oran ve kohort karsilastirmasidir.

        `rate` alani backend'de `(present + late) / (present + absent + late)`
        diye hesaplanir (`web/attendance.rs:66-70`); `excused` ve okulun kendi
        ekledigi statuler paydaya GIRMEZ, yalnizca `total`'a girer.

        TASINMAYAN: rapor duzeyindeki `events` ve `sessions` toplam sayaclari.
        Arayuz `list[dict]` donduruyor ve bu iki alan ders blogu degil; ders
        bloklari uzerinden `sessions` toplami yeniden toplanabilir, `events`
        (etkinlik yoklamasi) ise ders verisi olmadigi icin bu cephenin disinda
        kalir.
        """
        user_id = _require_id(user_id, "user_id")
        path = f"/attendance/{user_id}"
        body = await self._get("attendance", school, path)
        return _extract_rows(
            body,
            "courses",
            method="attendance",
            path=path,
            reference="AttendanceReport{user, events, sessions, courses} "
            "(web/attendance.rs:84)",
        )

    async def pomodoro(self, school: str, user_id: str) -> list[dict]:
        """Izin listesi yolu: `/pomodoro/{user}` (`constant.rs:674`).

        YANIT BICIMI -- `PomodoroLog`, SAYFA ZARFI + EK ALAN
        (`web/pomodoro.rs:78`, handler `web/pomodoro.rs:225` ->
        `Json<PomodoroLog>`):

            { items: [PomodoroResponse], total, limit, offset, total_focus_ms }

        Standart `Page<T>` DEGILDIR: uzerine bir de `total_focus_ms` ekler.
        Anahtar yine de `items`tir, bu dogrulanarak istenir.

        DONEN SEY: `items` listesi -- her ogesi bir `PomodoroResponse`
        (`web/pomodoro.rs:40`):

            { id, user, started_at, finished_at, duration_ms, counted }

        `started_at` / `finished_at` UTC unix-MILISANIYEDIR (saniye degil).
        `counted`, seansin omur boyu sayaclara girip girmedigidir ve devam eden
        seansta `null`'dur.

        TASINMAYAN: `total_focus_ms`. Arayuz `list[dict]` donduruyor; ayni sayi
        `items` uzerindeki `duration_ms` toplamindan elde edilir -- ancak
        dikkat, backend'inki SAYFALANMAMIS butun gunlugun toplamidir, satirlar
        ise yalnizca bu sayfadir.
        """
        user_id = _require_id(user_id, "user_id")
        path = f"/pomodoro/{user_id}"
        body = await self._get("pomodoro", school, path)
        return _extract_rows(
            body,
            "items",
            method="pomodoro",
            path=path,
            reference="PomodoroLog{items, total, limit, offset, total_focus_ms} "
            "(web/pomodoro.rs:78)",
        )

    async def homework_report(self, school: str, user_id: str) -> dict | None:
        """Izin listesi yolu: `/homework/report/{user}` (`constant.rs:668`).

        YANIT BICIMI -- `Page<HomeworkReportEntry>`, SAYFA ZARFI
        (`web/homework.rs:1166` girdi tipi, handler `web/homework.rs:1206` ->
        `Json<Page<HomeworkReportEntry>>`, zarf `web/page.rs:129`):

            { items: [HomeworkReportEntry], total, limit, offset }

        Her `HomeworkReportEntry` (`web/homework.rs:1166`):

            { course, homework, title, subject, due_at,
              submitted, late, missing, result }

        `due_at` UTC unix-MILISANIYEDIR. `missing`, "teslim yok VE tarih
        gecmis" demektir ve ogretmenin elle isaretledigi durumdan bagimsizdir.

        DONEN SEY: ZARFIN KENDISI (arayuz `dict | None` diyor), satirlar degil.
        `items` anahtarinin varligi dogrulanir; yoksa sessizce yarim zarf
        gecmez, `unexpected_shape` firlar.

        404 -> `None` (kullanici yok).
        """
        user_id = _require_id(user_id, "user_id")
        path = f"/homework/report/{user_id}"
        body = await self._get("homework_report", school, path)
        return _extract_object(
            body,
            method="homework_report",
            path=path,
            reference="Page<HomeworkReportEntry>{items, total, limit, offset} "
            "(web/homework.rs:1206)",
            require=("items",),
        )

    async def homework_list(
        self, school: str, on_behalf_of: str | None = None
    ) -> list[dict]:
        """Izin listesi yolu: `/homework` (`constant.rs:664`).

        YANIT BICIMI -- `Page<HomeworkResponse>`, SAYFA ZARFI (handler
        `web/homework.rs:160` -> `Json<Page<HomeworkResponse>>`):

            { items: [HomeworkResponse], total, limit, offset }

        DONEN SEY: `items` listesi.

        `on_behalf_of` verilmezse okuma servisin kendisi -- sentetik `ai` rolu --
        olarak kosar; o rol hicbir dersi goremedigi icin sonuc pratikte bostur
        (`ai/server.rs:694-711`). Yani bu alan burada opsiyonel gorunse de
        gercek kullanimda doldurulur.
        """
        body = await self._get("homework_list", school, "/homework", on_behalf_of=on_behalf_of)
        return _extract_rows(
            body,
            "items",
            method="homework_list",
            path="/homework",
            reference="Page<HomeworkResponse>{items, total, limit, offset} "
            "(web/homework.rs:160)",
        )

    async def notes(self, school: str, on_behalf_of: str) -> list[dict]:
        """Izin listesi yolu: `/notes` (`constant.rs:660`).

        YANIT BICIMI -- `Page<NoteResponse>`, SAYFA ZARFI
        (`web/notes.rs:106` -> `body = Page<NoteResponse>`):

            { items: [NoteResponse], total, limit, offset }

        DONEN SEY: `items` listesi.

        Kisisel notlar sahibine bagli oldugu icin `on_behalf_of` ZORUNLUDUR.
        """
        on_behalf_of = _require_id(on_behalf_of, "on_behalf_of")
        body = await self._get("notes", school, "/notes", on_behalf_of=on_behalf_of)
        return _extract_rows(
            body,
            "items",
            method="notes",
            path="/notes",
            reference="Page<NoteResponse>{items, total, limit, offset} "
            "(web/notes.rs:106)",
        )

    async def course_notes(
        self, school: str, course_id: str | None = None
    ) -> list[dict]:
        """Izin listesi yolu: `/course-notes` (`constant.rs:661`).

        Backend `GET /course-notes` icin `?course=` ZORUNLU kilar ve yalnizca o
        dersin notlarini listeler (`lib.rs`, `course-notes` etiket aciklamasi).
        `course_id` verilmezse listelenecek bir sey yoktur: uydurma bir istek
        gondermek yerine bos donup uyari yaziyoruz.

        YANIT BICIMI -- `Page<CourseNoteResponse>`, SAYFA ZARFI (handler
        `web/course_notes.rs:182` -> `Json<Page<CourseNoteResponse>>`):

            { items: [CourseNoteResponse], total, limit, offset }

        DONEN SEY: `items` listesi.
        """
        if not course_id:
            config.log(
                "warn",
                "course_notes: ders kimligi verilmedi; backend '?course=' zorunlu "
                "kildigi icin istek gonderilmedi",
            )
            return []
        course_id = _require_id(course_id, "course_id")
        body = await self._get(
            "course_notes", school, "/course-notes", query=f"course={course_id}"
        )
        return _extract_rows(
            body,
            "items",
            method="course_notes",
            path="/course-notes",
            reference="Page<CourseNoteResponse>{items, total, limit, offset} "
            "(web/course_notes.rs:182)",
        )


# --- dosya uygulamasi ------------------------------------------------------

_SAFE_KEY = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(value: str) -> str:
    """Kimligi dosya adina cevirirken yol kacisini imkansiz kil.

    `..` ve `/` gibi parcalar `_` olur; boylece fikstur koku disina cikan bir ad
    uretilemez.
    """
    return _SAFE_KEY.sub("_", value) or "_"


class FileSource:
    """`Source`'un fikstur uygulamasi: JSON dosyalarindan okur.

    Kopru yokken ve testlerde kullanilir. Dizin duzeni:

        <kok>/<okul>/profile/<user_id>.json          -> nesne
        <kok>/<okul>/marks/<user_id>.json            -> liste
        <kok>/<okul>/attendance/<user_id>.json       -> liste
        <kok>/<okul>/pomodoro/<user_id>.json         -> liste
        <kok>/<okul>/homework_report/<user_id>.json  -> nesne
        <kok>/<okul>/homework/<kim>.json             -> liste
        <kok>/<okul>/notes/<kim>.json                -> liste
        <kok>/<okul>/course_notes/<ders>.json        -> liste

    `<kim>` yoksa `_service`, `<ders>` yoksa `_all` kullanilir. Olmayan dosya
    hata degildir: nesne dondurenler `None`, liste dondurenler `[]` verir --
    kopru tarafinda 404'un karsiligi.

    Govde bicimi kopruyle AYNI normalizasyondan gecer: hem duz liste hem
    `{items: [...]}` zarfi kabul edilir, boylece gercek bir cevabi dosyaya
    oldugu gibi kaydedip fikstur yapmak mumkundur.
    """

    #: Yontem adi -> fikstur alt dizini.
    DIRECTORIES: dict[str, str] = {
        "profile": "profile",
        "marks": "marks",
        "attendance": "attendance",
        "pomodoro": "pomodoro",
        "homework_report": "homework_report",
        "homework_list": "homework",
        "notes": "notes",
        "course_notes": "course_notes",
    }

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)

    def _read(self, school: str, kind: str, key: str) -> Any:
        school = _require_id(school, "school")
        path = self._root / _safe(school) / self.DIRECTORIES[kind] / f"{_safe(key)}.json"
        if not path.is_file():
            return None
        try:
            with path.open("r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError) as exc:
            raise SourceError("fixture_unreadable", f"{path} okunamadi: {exc}") from exc

    def _rows(self, school: str, kind: str, key: str, envelope_key: str) -> list[dict]:
        """Fikstur govdesinden satirlari cikar.

        Fikstur iki bicimde yazilabilir:
        * GERCEK zarf (`{"courses": [...]}` / `{"items": [...]}`) -- gercek bir
          cevabi dosyaya oldugu gibi kaydetmek icin,
        * duz liste -- elle yazilan kucuk fiksturler icin.

        Duz liste burada UYARI URETMEZ (kopru tarafinin aksine): fikstur
        yazilmis bir seydir, telden gelmis degil. Ama yanlis anahtarli bir
        SOZLUK yine sessizce bos donmez, `unexpected_shape` firlatir -- fikstur
        modunda da sessiz bos yoktur.
        """
        body = self._read(school, kind, key)
        if body is None:
            return []
        if isinstance(body, list):
            return _row_dicts(body)
        if isinstance(body, dict):
            rows = body.get(envelope_key)
            if isinstance(rows, list):
                return _row_dicts(rows)
            config.log(
                "warn",
                f"fikstur {school}/{self.DIRECTORIES[kind]}/{key}.json bir sozluk ama "
                f"'{envelope_key}' listesi tasimiyor (anahtarlar: {sorted(body)[:8]})",
            )
            raise SourceError(
                "unexpected_shape",
                f"fikstur {kind}/{key}: '{envelope_key}' listesi yok",
            )
        config.log(
            "warn",
            f"fikstur {school}/{self.DIRECTORIES[kind]}/{key}.json ne liste ne sozluk "
            f"({type(body).__name__})",
        )
        raise SourceError(
            "unexpected_shape", f"fikstur {kind}/{key}: {type(body).__name__} okundu"
        )

    async def profile(self, school: str, user_id: str) -> dict | None:
        """Kopru karsiligi: `/users/{id}/profile` -> `ProfileResponse` duz nesnesi."""
        return _extract_object(
            self._read(school, "profile", _require_id(user_id, "user_id")),
            method="profile",
            path="fixture:profile",
            reference="ProfileResponse duz nesnesi (web/users.rs:707)",
        )

    async def marks(self, school: str, user_id: str) -> list[dict]:
        """Kopru karsiligi: `/marks/{user}` -> `MarksReport.courses` listesi."""
        return self._rows(school, "marks", _require_id(user_id, "user_id"), "courses")

    async def attendance(self, school: str, user_id: str) -> list[dict]:
        """Kopru karsiligi: `/attendance/{user}` -> `AttendanceReport.courses` listesi.

        Kopru surumunde oldugu gibi, her satirdaki `counts` bir SAYAC
        kumesidir; tek tek yoklama satiri ve tarihi icermez.
        """
        return self._rows(
            school, "attendance", _require_id(user_id, "user_id"), "courses"
        )

    async def pomodoro(self, school: str, user_id: str) -> list[dict]:
        """Kopru karsiligi: `/pomodoro/{user}` -> `PomodoroLog.items` listesi."""
        return self._rows(school, "pomodoro", _require_id(user_id, "user_id"), "items")

    async def homework_report(self, school: str, user_id: str) -> dict | None:
        """Kopru karsiligi: `/homework/report/{user}` -> `Page` ZARFININ KENDISI."""
        return _extract_object(
            self._read(school, "homework_report", _require_id(user_id, "user_id")),
            method="homework_report",
            path="fixture:homework_report",
            reference="Page<HomeworkReportEntry>{items, total, limit, offset} "
            "(web/homework.rs:1206)",
            require=("items",),
        )

    async def homework_list(
        self, school: str, on_behalf_of: str | None = None
    ) -> list[dict]:
        """Kopru karsiligi: `/homework` -> `Page.items` listesi."""
        return self._rows(
            school, "homework_list", on_behalf_of or "_service", "items"
        )

    async def notes(self, school: str, on_behalf_of: str) -> list[dict]:
        """Kopru karsiligi: `/notes` -> `Page.items` listesi."""
        return self._rows(
            school, "notes", _require_id(on_behalf_of, "on_behalf_of"), "items"
        )

    async def course_notes(
        self, school: str, course_id: str | None = None
    ) -> list[dict]:
        """Kopru karsiligi: `/course-notes?course=...` -> `Page.items` listesi."""
        return self._rows(school, "course_notes", course_id or "_all", "items")


#: Fikstur uygulamasinin ikinci adi; iki isim de ayni sinifi gosterir.
FixtureSource = FileSource


def build(settings: config.Config, client: Any | None = None) -> Source:
    """Yapilandirmaya gore cepheyi kur.

    `ZEKA_SOURCE=bridge` ise kopru istemcisi ZORUNLUDUR; sessizce fiksture
    dusmek, uretimde sahte veriyle hesap kosturmak olurdu.
    """
    if settings.source_mode == "bridge":
        if client is None:
            raise SourceError(
                "no_client", "ZEKA_SOURCE=bridge ama kopru istemcisi verilmedi"
            )
        return BridgeSource(client)
    return FileSource(settings.fixture_root)
