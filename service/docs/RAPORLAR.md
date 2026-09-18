# ZEKA Raporları

> ZEKA sonuç üretiyor ama kimse göremiyordu: analizler okulun veritabanına
> yazılıyor ve orada kalıyordu. Frontend'de değişiklik yapılmayacağı için
> teslim biçimi **rapor**dur. Bu belge o katmanı anlatır.
>
> Kod: `service/src/report/`. Sözleşme: `docs/CIKTI-SOZLESMESI.md`.
> Testler: `service/tests/test_report.py`.

---

## 0. Beş cümlede

1. Rapor **hattı olduğu gibi koşturup yazılan satırları bellekten yakalar**:
   ne açılan bir veritabanı, ne bir sürücü, ne bir bağlantı dizesi. Taşıma `store.py`'nin
   köprü deposudur; rapor onun yerine bir yakalayıcı koyar.
2. Dört rapor vardır: `okul` (yönetim), `ogretmen`, `ogrenci` (öğrenci/veli),
   `ham` (teknik ekip).
3. Üç biçim vardır: **JSON** (makine okunabilir), **HTML** (tek dosya, gömülü
   stil, tarayıcıdan PDF'e basılabilir), **CSV** (tablo hâline gelen bölümler).
4. **Dış bağımlılık yoktur**: ne yeni bir kütüphane, ne şablon motoru, ne CDN.
   Yalnız standart kütüphane; HTML elle üretilir.
5. **Dikkat listesi öğrenci ve veli raporunda yer almaz** ve bu bir filtre
   değil, **tip düzeyinde bir kapıdır** (§3).

---

## 1. Kullanım

```bash
python -m src.cli report --school ataturk-anadolu \
    --type okul|ogretmen|ogrenci|ham \
    --format json|html|csv \
    --out DIZIN [--about ÖĞRENCİ] [--teacher ÖĞRETMEN] \
    --fixtures service/fixtures/demo [--now MS]
```

* `--about` öğrenci raporunda **zorunludur**, `--teacher` öğretmen raporunda.
* `--fixtures` **zorunludur**: rapor, hattı fikstürden koşturup yazılan
  satırları bellekte yakalar (`report/capture.py`) ve raporu onlardan üretir.
  Aynı rapor kodu koşar; yalnız taşıma değişir — canlı bir dağıtımı okumak için
  bir bayrak yoktur ve olmayacaktır (rapor bir teslim biçimidir, bir yönetim
  konsolu değil).

Çıktı dosya adları öngörülebilir ve tarihlidir:

```
{okul}_{tip}[_{kim}]_{YYYY-MM-DD}.{json|html}
{okul}_{tip}[_{kim}]_{YYYY-MM-DD}_{bolum}.csv
```

Örnek: `demo-okul_okul_2023-11-14.html`,
`demo-okul_ogrenci_student-00_2023-11-14.json`,
`demo-okul_okul_2023-11-14_sube_ders.csv`.

Kimlikler dosya adına sadeleştirilerek girer (`user:01K42…` → `user-01K42…`):
iki nokta Windows'ta geçerli bir dosya adı karakteri değildir.

---

## 2. Dört rapor, bölüm bölüm

| Rapor | Kime | Bölümler (`section.id`) |
|---|---|---|
| `okul` | Yönetim | `toplu_gorunum`, `sube_ders`, `kosu_defteri`, `dikkat_listesi`, `tavsiye_dagilimi`, `uretilemeyenler` |
| `ogretmen` | Öğretmen | `siniflarim`, `dikkat_listesi`, `isi_haritasi`, `tavsiyeler`, `uretilemeyenler` |
| `ogrenci` | Öğrenci/veli | `dersler`, `calisma`, `teslim`, `yaklasan`, `segment`, `tavsiyeler` |
| `ham` | Teknik ekip | `tables` (ham satırlar, JSON gövde), `recommendation`, `student_segment_profile`, `uretilemeyenler` |

**Öğretmenin kapsamı** hakkında tavsiye aldığı öğrencilerden çözülür
(`recommendation.audience = öğretmen`, `about = öğrenci`): şube üyeliği ve
ders öğretmeni eşlemesi `Source` arayüzünden gelir ve rapor katmanının elinde
yoktur — köprüye gitmemenin bedeli budur.

**Isı haritası** hücresi «tekrar önerilir» bandındaki öğrenci payıdır. Bu bir
sıralama değildir: şube × ders hücresinin yoğunluğunu gösterir, öğrencileri
birbirine göre dizmez.

### JSON zarfı

```json
{
  "report": {"type": "okul", "school": "...", "subject": null,
             "generated_at": 1699963200000, "generated_at_date": "2023-11-14",
             "format_version": 1, "empty": false},
  "notes": ["Bu raporda sıralama yoktur…"],
  "sections": [{"id": "...", "kind": "table|cards|note|data", "...": "..."}]
}
```

Alan adları **İngilizce ve sözleşmeye sadıktır** (`rule_id`, `contrast`,
`confidence`, `expires_at`); görünen metinler Türkçedir. Ölçü hücreleri üç
alanlı bir nesnedir:

```json
{"value": 68.0, "display": "68,0", "confidence": "stable"}
```

Güven düşükse `value` **null**'dır ve `display` «yeterli veri yok» der: sayı
tek başına dolaşmasın diye (§4).

---

## 3. Dikkat listesi kapısı — neden yapısal

`CIKTI-SOZLESMESI.md` §5: `student_summary.attention[]` bir **öğretmen
aracıdır**; öğrenciye ve veliye gösterilmez (`[T§6.6]`). Bir çocuğa "dikkat
edilmesi gereken" etiketi gösterilmez.

Bu kural "önce hepsini oku, sonra öğrenci raporunda ayıkla" diye yazılsaydı,
kapının tutması **bir `if` satırının doğru yerde kalmasına** bağlı olurdu. Bir
refaktör, bir kopyala-yapıştır, yeni bir bölüm: üçü de sızıntı üretirdi.

Kapı dört katmanda **yapısaldır** (`src/report/gate.py`):

1. **Sorgu düzeyi.** Öğrenci raporunun `student_summary` SELECT'inde
   `attention` sütunu hiç geçmez (`SUMMARY_COLUMNS_STUDENT`). Satır
   veritabanından dikkat listesi taşımadan çıkar. `recommendation` sorgusu da
   `audience_role = 'student'` ile daraltılır; T4 satırı hiç getirilmez.
2. **Tip düzeyi.** Öğrenci raporunun okuduğu `StudentFacingSummary` tipinin
   `attention` diye bir **alanı yoktur**. Alan yoksa sızdırılamaz.
3. **Kalıtım yokluğu.** `StaffSummary`, `StudentFacingSummary`'den
   **türemez**; türeseydi `isinstance` denetimi personel demetini geçirir ve
   kapı kağıt üstünde kalırdı. İki bağımsız tip, tek yönlü dönüşüm.
4. **Kurucu kapısı.** `build_student_report` yalnız `StudentFacingBundle`
   kabul eder; personel demeti verilirse `ReportGateError` (bir `TypeError`)
   atar. Tersi de doğrudur: personel kurucuları öğrenci demetini reddeder.

Sabitleyen testler: `tests/test_report.py::DikkatListesiKapisi` — tipte alan
yok, kalıtım yok, kurucu reddediyor, SQL'de sütun yok, üç biçimin hiçbirinde
dikkat maddesi metni geçmiyor, ve **personel raporunda görünüyor** (kapı tek
yönlü olmalı).

Aynı bölümden gelen iki ek kapı:

* `recommendation.about` (başka bir öğrencinin kimliği) öğrenci raporuna
  girmez — kartlar `show_about=False` ile kurulur.
* `insight_run.pending_students` bir kişi listesidir; rapora yalnız **sayısı**
  girer.

---

## 4. Zorunlu kurallar ve kodda karşılıkları

| # | Kural | Kod | Test |
|---|---|---|---|
| 1 | Dikkat listesi öğrenci/veli raporunda yok | `gate.py` (§3) | `DikkatListesiKapisi` |
| 2 | Sıralama yok | `filters.visible_recommendations`, `build._class_course_rows`, `_attention_rows` — hepsi alfabetik | `SiralamaYok` |
| 3 | Kanıtsız satır girmez | `filters.has_evidence` (`limitation` kanıt sayılmaz) | `GorunurlukKapilari` |
| 4 | Güven düşükse söylenir | `text.measure`, kartlarda düşük güvende «Olgu» satırı ibareye döner | `GuvenIbaresi` |
| 5 | Kapatılmış tavsiye görünmez | `filters.is_dismissed` | `GorunurlukKapilari` |
| 6 | Süresi geçmiş görünmez | `filters.is_expired` (damga yoksa da gösterilmez) | `GorunurlukKapilari` |
| 7 | Segment = karşıtlık | `reader` SELECT'inde `accuracy` yok; `text.contrast_sentence` | `SegmentKarsitlik` |
| 8 | Öğrenci raporunda akran sıralaması yok | yalnız kendi geçmişi + **anonim** şube ortalaması | `DikkatListesiKapisi`, `SiralamaYok` |
| 9 | Şube hücresi **ham kimlik yazmaz** | `build._class_labels`: ad haritası → ad, yoksa `text.CLASS_LABEL_UNKNOWN`; sıralama görünen ada göre | `test_report_capability.RefusalTests`/`DocumentTests` |

### Neden ham doğruluk gösterilmiyor (kural 7)

`student_segment_profile.accuracy` öğrencinin **genel yeteneğini** yansıtır ve
ayrım gücü yoktur: iyi öğrenci her segmentte yüksek, zayıf öğrenci her
segmentte düşük çıkar. "Analiz sorularında %38'sin" cümlesi bu yüzden
yanıltıcıdır. Raporun kullandığı ölçü `contrast = accuracy − overall_accuracy`
— öğrencinin bir segmentteki başarısının **kendi genel düzeyinden** sapması.

Kontrast da tek başına yetmez: madde zorluğunu taşır (kohortun ortalama
`analiz` kontrastı ölçülen tohumda **−0,119**). Kurallar bu yüzden göreli
kontrast üzerinden ateşler ve karşılaştırma sayısını tavsiyenin `evidence`
nesnesine `reference_mean_contrast` olarak yazar; rapor kartı bunu
«Karşılaştırma» satırında gösterir.

Etiketlerin kendisi bir dil modelinin çıktısıdır ve hatalıdır. Ölçülmüş
performans `docs/SEGMENT-CIKTI.md` §4'tedir: ezberci arketipi kesinlik 0,765 /
duyarlılık 0,722; aceleci 0,793 / 0,719; **okuma güçlüğü 0,571 / 0,222** —
sonuncusu bu veride kullanılabilir değildir. Rapor "kesin" dili kullanmaz ve
her segment bölümüne bu sınırı not olarak koyar.

---

## 5. Biçimler

### HTML

Tek dosya. Stil `<style>` içinde gömülü, betik yok, resim yok, yazı tipi
indirilmiyor, `url(` yok. **Ağa hiçbir istek çıkmaz**: rapor kişisel veri
taşır; bir CDN'e istek çıkması o verinin varlığını üçüncü bir tarafa
bildirirdi. Baskı düzeni `@media print` ile verilir (tablo ve kartlar sayfa
ortasından bölünmez, başlıklar sayfa sonunda yalnız kalmaz, `@page` kenar
boşluğu 16 mm) — tarayıcıdan "PDF olarak kaydet" yeterlidir.

Sınama: `HtmlBicimi::test_dis_bagimlilik_yok` dört raporun HTML'inde
`http://`, `https://`, `<script`, `<link`, `src=`, `@import`, `url(`
dizgilerinin hiçbirinin geçmediğini gösterir. Bütün metinler kaçırılır
(`test_html_kacisi_yapilir`).

### CSV

Her **tablo** bölümü bir dosyadır; kart ve not bölümleri CSV'ye dönmez (beş
bölümlü "Neden?" bir tablo değildir, hücreye sıkıştırılırsa okunmaz olur).

* Kodlama **`utf-8-sig`** — BOM'suz UTF-8 dosyayı Excel yerel kod sayfasıyla
  açar ve Türkçe karakterler bozulur.
* Ayraç **`;`** — Excel'in Türkçe yerelinde varsayılan liste ayracı budur;
  virgülle yazılan dosya tek sütuna düşer.
* Ölçü hücreleri `display` metnine döner: düşük güvende orada zaten «yeterli
  veri yok» yazar, sayı CSV'ye de girmez.

### JSON

Zarf §2'dedir. `ham` raporunda satırlar olduğu gibi durur, üç
istisnayla:

* `recommendation`: kapatılmış / süresi geçmiş / kanıtsız satırlar çıkarılır —
  teknik ekip kapıyı kendi ekranında yeniden kurmak zorunda kalmasın.
* `question_segment`: `rationale` ve `trap_choice` **ihraç edilmez**. Biri
  modelin hatalı gerekçesi, diğeri doğrudan cevap ipucudur; sınav öncesi
  görülürse ölçüm geçersizleşir.
* `student_segment_profile`: `accuracy` okunmaz bile; karşılığı `contrast`'tır.

---

## 6. Boş veri

Boş rapor bir hata değildir ve **çökme değildir**: dosya yine üretilir,
`report.empty = true` işaretlenir, HTML'de "Bu rapor boş üretildi" kutusu
görünür ve nedeni not olarak yazılır (gece koşusu hiç çalışmamış olabilir,
`status = skipped` dönmüş olabilir, bütün satırlar kapılardan düşmüş
olabilir). Üretilmeyen kurallar listesi (`recommend.unavailable_rules()`)
her personel raporunda basılır: "neden boş" sorusunun cevabı koddan gelir.

`insight_run.status = partial` ise koşu defteri bölümü "bu gece bazı
öğrenciler işlenemedi" notunu taşır; eksik veri sessizce tam gibi
gösterilmez.

---

## 7. Sınırlar — bu katmanın bilmedikleri

1. **Şube/ders öğretmeni eşlemesi yoktur.** Öğretmenin kapsamı yalnız
   hakkında tavsiye aldığı öğrencilerden çözülür. Bir öğretmenin hakkında
   hiç tavsiyesi olmayan öğrencisi öğretmen raporunda **görünmez**.
2. **Öğrenci adı yoktur**, kimlik vardır: `student_summary` ad taşımaz, ad
   okul veritabanındadır ve rapor oraya gitmez.
3. **Veli raporu ayrı bir tip değildir.** `parent_link` verisi olmadığı için
   velinin kim olduğu çözülemiyor (`V1.weekly_digest` üretilemeyenler
   listesinde). Öğrenci özeti veliye de gösterilebilir; dikkat listesi
   kapısı ikisi için de aynıdır.
4. **Devam kırılımı rapora girmiyor.** Devam ucu yalnız sayaç döndürüyor,
   oturum tarihi yok; haftanın günü deseni üretilemiyor.
5. **PDF üretilmez.** HTML tarayıcıdan basılır. Bir PDF kütüphanesi eklemek
   bağımlılık kuralını bozardı.
6. **Rapor gönderilmez.** E-posta, paylaşım bağlantısı, zamanlanmış dağıtım
   yoktur; CLI dosya yazar, dağıtımı çağıran taraf yapar.
7. **Şube adı rapor katmanında bulunmaz.** Rapor `marks.classes`teki
   **kimlikleri** taşır; görünen adı çağıran verir (`insight.report`ta
   `classes: [{id, name}]`, bkz. `BACKEND-GEREKSINIMLERI.md` `## insight.report`).
   Harita yoksa her şube hücresi `Adı bilinmeyen şube` olur — ham kimlik hiçbir
   koşulda yazılmaz. Fikstür/CLI yolunda ad kaynağı yoktur, o yüzden orada
   etiket budur.
