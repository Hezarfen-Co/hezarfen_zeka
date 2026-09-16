"""Istem surumleri (versiyonlu) ve rol istemleri.

SURUMLEME NEDEN ZORUNLU (bulgu 5):
  Barrie/Palaiologou/Tornberg: LLM etiketleri anlamca ESDEGER istem
  varyasyonlarina karsi kirilgandir; yalnizca cumle yapisini yeniden duzenlemek
  etiket dagilimini 8,38-28,10 yuzde puani kaydirabiliyor. Bu yuzden HER cikti
  hangi istem surumuyle uretildigini tasir (`ItemSegmentation.prompt_version`)
  ve onbellek anahtarinda istem surumu YER ALIR.

PARAFRAZ URETIMI (bulgu 6 kaydi):
  PSS'in inter-PSS adimi PEGASUS'a bagli ve INGILIZCE odaklidir. Bizim
  istemlerimiz Turkce oldugundan parafraz uretimi DeepSeek ile Turkce yapilir
  (`generate_paraphrase_variants`). Anahtar yokken kullanilmak uzere elle
  yazilmis 3 Turkce esdeger varyant (`MANUAL_VARIANTS`) da paketlenmistir;
  bunlar cevrimdisi/varsayilan yoldur.

ISTEM TOPLULUGU:
  Bulgu 5'in onerdigi cozum tek "optimal istem" aramak degil, istem toplulugu +
  PSS raporlamasidir. `ALL_VERSIONS` bu toplulugu tasir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .rubric import DIMENSION_ORDER, render_full_rubric
from .schema import response_template

SYSTEM_TR = (
    "Sen Turk lise mufredatina hakim, olcme-degerlendirme egitimi almis bir "
    "soru analistisin. Gorevin coktan secmeli bir soruyu verilen yonergeye gore "
    "dort boyutta etiketlemek. YALNIZCA gecerli JSON dondur; aciklama, markdown "
    "ya da kod citasi ekleme."
)


@dataclass(frozen=True)
class PromptVersion:
    """Tek bir istem surumu."""

    version: str
    #: Govde sablonu; `{rubric}`, `{template}`, `{item}` yer tutuculari.
    body: str
    system: str = SYSTEM_TR
    with_examples: bool = True
    #: Bu surumun hangi surumun parafrazi oldugu (inter-PSS icin).
    paraphrase_of: str | None = None
    note: str = ""

    def render(self, item: dict, *, course_name: str | None = None) -> str:
        return self.body.format(
            rubric=render_full_rubric(course_name, with_examples=self.with_examples),
            template=response_template(),
            item=format_item(item),
            dimensions=", ".join(DIMENSION_ORDER),
        )


def format_item(item: dict) -> str:
    """Soruyu isteme gomulecek sabit bicime cevirir.

    Sik indeksleri 0-TABANLIDIR ve istemde acikca soylenir; `tuzak_sik_index`
    bu indekslere gore dogrulanir (`schema.parse_label_json`).
    """
    lines = []
    ders = item.get("course_name") or "(bilinmiyor)"
    konu = item.get("subject_name") or "(bilinmiyor)"
    lines.append(f"Ders: {ders}")
    lines.append(f"Konu: {konu}")
    lines.append(f"Soru kokü: {(item.get('text') or '').strip()}")
    lines.append("Siklar (0-tabanli indeksli):")
    for i, ch in enumerate(item.get("choices") or []):
        lines.append(f"  [{i}] {ch}")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# v1 — taban istem (Asama 1 kontrol grubu bunu kullanir)
# --------------------------------------------------------------------------

_V1 = """Asagidaki coktan secmeli soruyu YONERGE'ye gore dort boyutta etiketle.

YONERGE
{rubric}

SORU
{item}

KURALLAR
- Her boyut icin yalnizca izinli etiketlerden birini sec.
- Her boyut icin 0 ile 1 arasinda bir guven ver; emin degilsen dusuk ver.
- dikkat_tuzagi "var" ise tuzak_sik_index alanina o sikkin 0-tabanli indeksini
  yaz; "yok" ise null yaz.
- gerekce en fazla iki cumle olsun.
- Sorunun dogru cevabini bulmaya calisma; gorevin siniflandirmak.

CIKTI — tam olarak bu semada, yalnizca JSON:
{template}
"""

# --------------------------------------------------------------------------
# v1 parafrazlari (inter-PSS icin, anlamca ESDEGER — bulgu 5/6)
# Elle yazildi: kelime secimi ve cumle sirasi degisti, TALIMAT ICERIGI degismedi.
# --------------------------------------------------------------------------

_V1_P1 = """Bir sinav maddesini siniflandiracaksin. Once yonergeyi oku, sonra
soruyu dort boyutta etiketle.

YONERGE
{rubric}

INCELENECEK MADDE
{item}

UYULACAK NOKTALAR
- Boyut basina tek etiket; etiket izinli kume disindan olamaz.
- Etiketin yaninda 0-1 araliginda bir guven degeri bulunmali; kararsizsan
  degeri dusur.
- Eger dikkat_tuzagi icin "var" dersen, tuzak_sik_index alanini o sikkin
  0-tabanli sira numarasiyla doldur; "yok" dersen bu alan null kalir.
- Iki cumleyi asmayan bir gerekce yaz.
- Maddenin dogru cevabini isaretlemen istenmiyor; yalnizca siniflandirma.

Yanitin yalnizca su JSON olmalidir:
{template}
"""

_V1_P2 = """Gorev: asagida verilen coktan secmeli maddeyi, altindaki olcutlere
dayanarak {dimensions} boyutlarinda kodla.

OLCUTLER
{rubric}

MADDE
{item}

KODLAMA KOSULLARI
- Her boyutta izinli etiketlerden yalnizca biri secilir.
- Her secimin yanina 0 ile 1 arasi bir guven yazilir; belirsizlikte dusuk deger
  kullanilir.
- dikkat_tuzagi icin "var" secildiginde, ilgili sikkin 0-tabanli indeksi
  tuzak_sik_index alanina girilir; aksi durumda null birakilir.
- Gerekce iki cumleyi gecmez.
- Dogru cevabi bulmak gorevin parcasi degildir.

Ciktiyi yalnizca asagidaki JSON semasiyla ver:
{template}
"""

_V1_P3 = """Asagidaki madde icin dort boyutlu bir etiket kumesi uret. Yonerge
etiketlerin anlamini ve sinir durumlarini tanimlar.

{rubric}

--- MADDE ---
{item}
--- MADDE SONU ---

Dikkat et: boyut basina tek etiket, boyut basina bir guven (0-1); dikkat_tuzagi
"var" ise tuzak_sik_index sikkin 0-tabanli indeksi, degilse null; gerekce en
fazla iki cumle. Dogru cevabi bulman beklenmiyor.

Yalnizca su JSON'u dondur:
{template}
"""

# v2 — ornek ICERMEYEN surum. Bulgu 3'teki KARSI KANIT ("sifir-ornekli +
# tanimlar, few-shot'i gecebilir") bir yasa degil, olculmesi gereken bir sorudur;
# bu yuzden ornekli/ornekisiz iki surum de toplulukta durur.
_V2 = _V1


V1 = PromptVersion("v1", _V1, note="taban istem (ornekli)")
V1_P1 = PromptVersion("v1-p1", _V1_P1, paraphrase_of="v1",
                      note="elle yazilmis Turkce parafraz 1")
V1_P2 = PromptVersion("v1-p2", _V1_P2, paraphrase_of="v1",
                      note="elle yazilmis Turkce parafraz 2")
V1_P3 = PromptVersion("v1-p3", _V1_P3, paraphrase_of="v1",
                      note="elle yazilmis Turkce parafraz 3")
V2_NOEX = PromptVersion("v2-noex", _V2, with_examples=False,
                        note="ornek icermeyen surum (bulgu 3 karsi kaniti)")

ALL_VERSIONS: dict[str, PromptVersion] = {
    p.version: p for p in (V1, V1_P1, V1_P2, V1_P3, V2_NOEX)
}
BASELINE_VERSION = "v1"
MANUAL_VARIANTS: tuple[str, ...] = ("v1-p1", "v1-p2", "v1-p3")


def get(version: str) -> PromptVersion:
    try:
        return ALL_VERSIONS[version]
    except KeyError as exc:
        raise KeyError(
            f"Bilinmeyen istem surumu: {version!r}; "
            f"mevcut: {', '.join(sorted(ALL_VERSIONS))}") from exc


def register(prompt: PromptVersion) -> None:
    """Kosu sirasinda uretilmis parafrazi toplulukta kaydet."""
    ALL_VERSIONS[prompt.version] = prompt


# --------------------------------------------------------------------------
# Rol istemleri — heterogeneous_roles varyanti (bulgu 10)
# --------------------------------------------------------------------------
# Bulgu 10: homojen ajanlarla YONLENDIRILMEMIS tartisma sikofantik uyum uretiyor
# (modal benimseme %85,5'e kadar). Bu yuzden ajanlar HOMOJEN TARTISMA yapmaz;
# rolleri AYRISTIRILMISTIR ve birbirlerinin gerekcesini gormezler. Birlestirici
# yalnizca ETIKETLERI gorur — akran gerekcesiyle bulasma yolu kapalidir.

ROLE_PROMPTS: dict[str, str] = {
    "konu_uzmani": (
        "ROL: Bu dersin konu uzmanisin. Soruyu MUFREDAT bilgisi acisindan "
        "degerlendir: hangi kazanim, hangi kural, kac kural birlikte gerekiyor. "
        "Ogrenci psikolojisiyle ilgilenme."
    ),
    "ogrenci_hatasi": (
        "ROL: Siniftaki tipik hatalari toplayan bir ogretmensin. Soruya "
        "'ogrenci nerede yanilir' gozuyle bak: hangi sik yaygin bir yanilgiyi "
        "soze dokuyor, hangi sik yalnizca yanlis sayidir. Mufredat tartismasina "
        "girme."
    ),
    "olcme": (
        "ROL: Olcme-degerlendirme uzmanisin. Maddenin BICIMSEL yukunu "
        "degerlendir: kok uzunlugu, cumle yapisi, sik uzunluklari, kac bagli "
        "islem gerektigi. Icerigin dogrulugunu tartisma."
    ),
}

MERGER_PROMPT = """Uc bagimsiz degerlendirici ayni soruyu etiketledi. Asagida
YALNIZCA etiketleri ve guvenleri goruyorsun; gerekceleri bilerek verilmedi
(akran gerekcesinin yaydigi hatayi onlemek icin).

SORU
{item}

DEGERLENDIRICI ETIKETLERI
{agents}

GOREVIN: her boyut icin nihai etiketi belirle.
- Uc degerlendirici ayni etiketi verdiyse onu kullan ve guveni yuksek tut.
- Ayrildilarsa, o boyutta UZMAN OLAN degerlendiriciye agirlik ver:
  bilissel_talep ve adim_sayisi -> konu_uzmani ve olcme,
  dikkat_tuzagi -> ogrenci_hatasi,
  okuma_yuku -> olcme.
- Uzlasma olmayan boyutlarda guveni DUSUR; yuksek uyum otomatik dogruluk
  demek degildir.
- dikkat_tuzagi "var" ise tuzak_sik_index'i mutlaka doldur.

Yalnizca su JSON'u dondur:
{template}
"""

CRITIC_PROMPT = """Bir degerlendiricinin ayni soru icin urettigi etiketleri
denetliyorsun.

SORU
{item}

ONERILEN ETIKETLER
{proposal}

YONERGE (olcut kaynagi)
{rubric}

GOREVIN: yalnizca yonergeye acikca AYKIRI olan etiketleri duzelt. Aykirilik
yoksa etiketleri OLDUGU GIBI birak. Zorlama duzeltme yapma; degisiklik
onerdigin her boyut icin hangi sinir durumunu ihlal ettigini gerekcede yaz.

Yalnizca su JSON'u dondur:
{template}
"""


def render_role(role: str, prompt_version: str, item: dict,
                course_name: str | None = None) -> tuple[str, str]:
    """Rol ajani icin (system, user) ciftini uretir."""
    if role not in ROLE_PROMPTS:
        raise KeyError(f"Bilinmeyen rol: {role!r}")
    pv = get(prompt_version)
    system = SYSTEM_TR + "\n" + ROLE_PROMPTS[role]
    return system, pv.render(item, course_name=course_name)


def render_merger(item: dict, agent_labels: list[dict]) -> tuple[str, str]:
    """Birlestirici ajani icin (system, user). Gerekceler KASITLI olarak yok."""
    lines = []
    for entry in agent_labels:
        role = entry.get("_rol", "?")
        body = ", ".join(f"{k}={v}" for k, v in entry.items() if not k.startswith("_"))
        lines.append(f"- {role}: {body}")
    user = MERGER_PROMPT.format(item=format_item(item), agents="\n".join(lines),
                                template=response_template())
    return SYSTEM_TR, user


def render_critic(item: dict, proposal_json: str,
                  course_name: str | None = None) -> tuple[str, str]:
    """Generator-critic varyantinin elestirmen adimi (bulgu 8: kendisi olculur)."""
    user = CRITIC_PROMPT.format(
        item=format_item(item), proposal=proposal_json,
        rubric=render_full_rubric(course_name, with_examples=False),
        template=response_template())
    return SYSTEM_TR, user


# --------------------------------------------------------------------------
# DeepSeek ile Turkce parafraz uretimi (bulgu 6 kaydi)
# --------------------------------------------------------------------------

PARAPHRASE_INSTRUCTION = """Asagidaki Turkce TALIMAT metnini anlamca TAMAMEN
esdeger kalacak sekilde yeniden yaz. Kurallar:
- Hicbir talimat maddesini ekleme, cikarma ya da anlamini degistirme.
- Suslu parantezli yer tutuculari ({{rubric}}, {{item}}, {{template}},
  {{dimensions}}) AYNEN koru.
- Yalnizca cumle yapisini, sozcuk secimini ve sirayi degistir.
- Yalnizca yeniden yazilmis metni dondur; aciklama ekleme.

METIN:
{body}
"""

_PLACEHOLDERS = ("{rubric}", "{item}", "{template}")


def paraphrase_prompt_body(body: str) -> str:
    return PARAPHRASE_INSTRUCTION.format(body=body)


def validate_paraphrase(original: str, candidate: str) -> None:
    """Parafrazin yer tutucularini koruyup korumadigini DOGRULAR.

    Bulgu 5'in ruhu: istem varyanti anlamca esdeger OLMALI. Yer tutucu kaybi
    sessizce kabul edilirse inter-PSS olcumu anlamsizlasir.
    """
    if not candidate or not candidate.strip():
        raise ValueError("Parafraz bos.")
    for ph in _PLACEHOLDERS:
        if ph in original and ph not in candidate:
            raise ValueError(f"Parafraz yer tutucuyu kaybetti: {ph}")
    # Kacak yer tutucu (LLM uydurmus olabilir) -> format() cokmesin.
    extra = set(re.findall(r"\{([a-z_]+)\}", candidate)) - {
        "rubric", "item", "template", "dimensions"}
    if extra:
        raise ValueError(f"Parafrazda bilinmeyen yer tutucu: {sorted(extra)}")


def generate_paraphrase_variants(provider, base_version: str = BASELINE_VERSION,
                                 n: int = 3, *, temperature: float = 0.9
                                 ) -> list[PromptVersion]:
    """DeepSeek (ya da Mock) ile Turkce istem parafrazlari uretir.

    Bulgu 6: inter-PSS'in PEGASUS adimi Ingilizce odaklidir; Turkce istemler icin
    parafraz uretimi DeepSeek ile IKAME EDILIR. Uretilen her varyant
    `validate_paraphrase` ile denetlenir; denetimi gecemeyen ATILIR (sessiz kabul
    yok) ve yerine elle yazilmis varyant kullanilir.
    """
    base = get(base_version)
    out: list[PromptVersion] = []
    for i in range(n):
        version = f"{base_version}-dp{i + 1}"
        try:
            res = provider.chat(paraphrase_prompt_body(base.body),
                                system="Sen Turkce yazan bir metin editorusun.",
                                temperature=temperature, kind="paraphrase")
            validate_paraphrase(base.body, res.text)
            pv = PromptVersion(version, res.text, paraphrase_of=base_version,
                               note="DeepSeek ile uretilmis Turkce parafraz")
        except Exception:  # noqa: BLE001 — geri dusus bilincli
            fallback = MANUAL_VARIANTS[i % len(MANUAL_VARIANTS)]
            pv = get(fallback)
        register(pv)
        out.append(pv)
    return out
