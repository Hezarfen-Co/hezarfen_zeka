# Segment Çıktısı — kurallar arketipleri buluyor mu?

> Ölçüm betiği: `tools/measure_segment_rules.py`
> Veri: `work/items_enriched.json` (`gold.dims`) + `seed/11_exam_answer.surql`
> + `seed/_seed_manifest.json` (`students[].dim_delta`, `archetype`, `class`)
> Çıktı: `work/segment_kural.json`, `work/segment_kural_gurultu.json`
> **Harcanan: 0,00 USD** — bu ölçümde hiçbir LLM çağrısı yapılmadı.
> Bu belge **ölçülen** sayıları taşır. Ölçülmemiş hiçbir iddia yoktur.

---

## 0. Ne ölçüldü, ne ölçülmedi

**Ölçülen soru:**

> Segment tabanlı tavsiye kuralları, etiketler **doğruyken**, tohum verisine
> tasarımla yerleştirilmiş üç bilişsel arketipi buluyor mu — ve bulmaması
> gereken yerde susuyor mu?

**Ölçülmeyen soru:**

> LLM soruyu doğru etiketliyor mu?

İkincisi ayrı bir ölçümdür ve bu belgenin konusu **değildir**. Bu ölçümde
etiketler tohum üretecinin altın etiketleridir (`gold.dims`), bir dil modelinin
çıktısı değildir. Yani buradaki kesinlik/duyarlılık **kuralın** performansıdır;
uçtan uca (LLM + kural) performans **bundan düşüktür** ve ayrıca ölçülmelidir.

§6'daki ikinci koşu, ölçülmüş LLM hata oranlarını altın etiketlere uygulayarak
kuralların etiket gürültüsüne dayanıklılığını **modeller**. O bir simülasyondur,
gerçek bir LLM koşusu değildir.

| | |
|---|---|
| Etiketli çoktan seçmeli madde | 3.870 |
| İşlenen cevap satırı | 216.633 |
| Öğrenci | 250 (8 arketip, 11 şube) |
| Üretilen `student_segment_profile` satırı | 1.750 |

---

## 1. Ölçülen şey neden `contrast` — ve neden o bile yetmiyor

Üç ölçü vardır ve üçü farklı şey söyler:

| Ölçü | Tanım | Ne söyler |
|---|---|---|
| `accuracy` | segmentteki doğruluk | **Hiçbir şey.** Öğrencinin genel yeteneğini yansıtır; iyi öğrenci her segmentte yüksek çıkar |
| `contrast` | `accuracy − overall_accuracy` | Öğrencinin genel düzeyi sadeleşir. Satıra yazılan ölçü budur |
| `relative_contrast` | `contrast − kohort ortalaması` | **Kuralın baktığı ölçü.** Madde zorluğu da sadeleşir |

İkinci çıkarma zorunludur, çünkü `contrast` hâlâ **madde zorluğunu** taşır.
Ölçülen kohort ortalamaları (250 öğrenci):

| Segment | ortalama `contrast` | SD |
|---|---:|---:|
| bilissel_talep = analiz | **−0,1191** | 0,0535 |
| bilissel_talep = uygulama | −0,0117 | 0,0243 |
| bilissel_talep = hatirlama | +0,0854 | 0,0378 |
| dikkat_tuzagi = var | −0,0186 | 0,0276 |
| dikkat_tuzagi = yok | +0,0149 | 0,0222 |
| okuma_yuku = yuksek | −0,0689 | 0,0333 |
| okuma_yuku = dusuk | +0,0248 | 0,0122 |

Yani **her** öğrencinin `analiz` kontrastı ortalama −0,12'dir. Ham kontrasta
eşik koyan bir kural 250 öğrencinin neredeyse tamamında ateşlerdi — yani hiçbir
şey söylemezdi. Bu, `docs/DESEN-DOGRULAMA.md` §5'teki "kontrole göre" sütununun
aynı hesabıdır; orada referans kontrol grubuydu, burada (üretimde kimin kontrol
olduğu bilinmediği için) kohortun tamamıdır.

---

## 2. Eşikler nereden geldi

**Hiçbiri seçilmedi, hepsi ölçüldü.**

### 2.1 Göreli kontrast eşiği

Kontrol grubu = `dim_delta` tablosu **boş** olan arketipler (A1, A2, A3, A5, A6)
= **182 öğrenci**. Bu öğrencilerde tasarım gereği hiçbir boyut sapması yoktur;
ölçülen dağılım saf gürültüdür.

| Segment (kontrol, n=182) | ortalama | SD | en düşük | ort − 2·SD |
|---|---:|---:|---:|---:|
| bilissel_talep = analiz | −0,0012 | **0,0392** | −0,0983 | **−0,0797** |
| bilissel_talep = hatirlama | −0,0032 | 0,0247 | −0,0655 | −0,0526 |
| bilissel_talep = uygulama | +0,0045 | 0,0210 | −0,0909 | −0,0375 |
| dikkat_tuzagi = var | +0,0076 | **0,0199** | −0,0587 | **−0,0322** |
| dikkat_tuzagi = yok | −0,0058 | 0,0163 | −0,0763 | −0,0384 |
| okuma_yuku = yuksek | +0,0026 | **0,0315** | −0,0653 | **−0,0604** |
| okuma_yuku = dusuk | −0,0005 | 0,0115 | −0,0570 | −0,0235 |

Kural: **eşik = kontrol ortalaması − 2·SD**, boyutun **en geniş dağılımlı**
etiketi üzerinden (muhafazakâr taraf). Sonuç, `compute/segments.py`
`RELATIVE_CONTRAST_GATE`:

```
bilissel_talep  -0,080      dikkat_tuzagi  -0,032      okuma_yuku  -0,060
```

2 katsayısı **önceden** seçildi: tek yönlü 2·SD kuyruğu segment başına ~%2,3
yanlış pozitif bekletir. Veriye bakarak ayarlanmadı; ama iki yönün maliyeti
ölçüldü ve ikisi de burada yazılıdır:

| katsayı | eşik (analiz / tuzak / okuma) | A8 doğru poz. | A4 doğru poz. | A7 doğru poz. | kontrol yanlış poz. (satır) |
|---:|---|---:|---:|---:|---:|
| 1,5 | −0,060 / −0,022 / −0,045 | 15/18 | 27/32 | 5/18 | 33 |
| **2,0** | **−0,080 / −0,032 / −0,060** | **13/18** | **23/32** | **4/18** | **10** |
| 2,5 | −0,099 / −0,042 / −0,076 | 7/18 | 21/32 | 3/18 | 1 |
| 3,0 | −0,119 / −0,052 / −0,092 | 5/18 | 14/32 | 2/18 | 1 |

2,5'e çıkmak yanlış pozitifi 10'dan 1'e indiriyor, ama ezberci arketibinin
duyarlılığını 0,72'den 0,39'a düşürüyor. Seçim 2,0'dır ve bedeli §4'te açıkça
yazılıdır.

### 2.2 Güven kapısı (segment başına asgari cevap)

`MIN_ANSWERS_PER_SEGMENT = 100`. Bu sayı `[L-5]` Linacre'ın "stable" eşiğiyle
aynıdır (proje `question_stat` için de 100 kullanıyor) ve iki duvar arasında
ölçülerek doğrulandı:

| eşik | sonuç |
|---:|---|
| 30–75 | kontrol yanlış pozitifi 20–23 satır; güven kademesi 'exploratory' bile değil |
| **100** | **kontrol yanlış pozitifi 19 satır (tüm segmentler), kurala giren üçünde 10** |
| 150 | okuma güçlüğü arketibi **tümüyle** kaybolur |
| 200 | `bilissel_talep=analiz` segmenti **hiç** ateşlemez — kural ölür |

İki duvarın sebebi ölçüldü: analiz maddesi azdır (segment başına medyan **178**
cevap) ve okuma güçlüğü olan öğrenciler zor maddeleri **boş bırakır** — boş
madde paydaya girmez, dolayısıyla tam da yakalamak istediğimiz öğrencinin `n`'i
düşüktür. 150'lik bir "daha güvenli" eşik, güvenliği yakalamak istediği
öğrenciyi silerek satın alırdı.

---

## 3. Kurallar

| `rule_id` | kime | segment | koşul |
|---|---|---|---|
| `O2.segment_cognitive_gap` | öğrenci | `bilissel_talep`, `okuma_yuku` (tüm etiketler) | n ≥ 100 **ve** göreli kontrast ≤ boyut eşiği |
| `O2.segment_trap_prone` | öğrenci | `dikkat_tuzagi = var` | n ≥ 100 **ve** göreli kontrast ≤ −0,032 |
| `T3.segment_class_gap` | öğretmen | sınıf × boyut × etiket | kapıyı geçen ≥ 8 öğrenci **ve** sınıf ortalama göreli kontrast ≤ −0,040 |

Üçü de **ham doğruluğa bakmaz**. `tests/test_segments.py::
test_ham_dogruluk_tek_basina_atesLEMEZ` bunu tip düzeyinde değil davranış
düzeyinde sabitler: genel doğruluğu %25 olan ama segmenti kohortla aynı olan
öğrenci için **hiçbir** kart üretilmez.

---

## 4. Ölçüm — üç arketip

Altın pozitif tanımı: manifestodaki `dim_delta[boyut][etiket] ≤ −0,50 logit`.
Üç arketibin tasarım sapmaları −0,93 … −1,05 logit olduğu için üçü de bu
eşiğin açık ara üstündedir. `−0,50 < delta ≤ −0,15` aralığı **gri bölge**
sayılır (A4'ün `bilissel_talep=hatirlama` sapması, −0,29): ne doğru ne yanlış
pozitif olarak sayılır. Bu ölçümde gri bölgede **hiç** ateşleme olmadı.

Kurallar gerçekten çalıştırıldı (`recommend.for_student_segments`), 250 öğrenci
için toplam **54 tavsiye** üretildi ve **0'ı kanıtsızdı**.

| Arketip | Profil | Segment | Kural | Altın poz. | DP | YP | YN | **Kesinlik** | **Duyarlılık** | F1 |
|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A8** | ezberci | `bilissel_talep=analiz` | `O2.segment_cognitive_gap` | 18 | 13 | 4 | 5 | **0,765** | **0,722** | 0,743 |
| **A4** | aceleci | `dikkat_tuzagi=var` | `O2.segment_trap_prone` | 32 | 23 | 6 | 9 | **0,793** | **0,719** | 0,754 |
| **A7** | okuma güçlüğü | `okuma_yuku=yuksek` | `O2.segment_cognitive_gap` | 18 | 4 | 3 | 14 | **0,571** | **0,222** | 0,320 |

### Kontrol grubu

| | |
|---|---|
| Kontrol öğrencisi (sapması olmayan) | **182** |
| **Yanlış pozitif öğrenci** | **10** (%5,5) |
| **Yanlış pozitif satır** | **10** |
| Dağılım | `bilissel_talep=analiz` 4 · `dikkat_tuzagi=var` 5 · `okuma_yuku=yuksek` 1 |

Bu sayı beklenenle uyumludur: tek yönlü 2·SD kuyruğu segment başına ~%2,3, üç
segment birlikte ~%6,8 bekletir; ölçülen %5,5'tir. Yani yanlış pozitifler
kuralın bir kusuru değil, **seçilen eşiğin ilan edilmiş bedelidir**.

### A7 hakkında dürüstlük notu

**Okuma güçlüğü arketibi büyük ölçüde bulunamıyor: 18 öğrencinin 14'ü
kaçırılıyor.** Bu abartılmamalıdır ve nedeni ölçülmüştür:

* `DESEN-DOGRULAMA.md` §5 zaten A7'nin etkisinin en zayıf olduğunu ölçmüştü
  (kontrole göre −0,045; kontrol gürültüsünün 3,7 katı, diğerlerinde 5,2–7,6).
* A7 öğrencilerinin `okuma_yuku=yuksek` segmentindeki göreli kontrast dağılımı:
  ortalama **−0,0332**, SD **0,0490**. Eşik −0,060. Yani arketibin **ortalaması
  eşiğin üstünde**; yalnız dağılımın alt kuyruğu yakalanıyor.
* Kök sebep tasarımdadır: A7 zor maddeleri boş bırakır, boş madde paydaya
  girmez, etki ölçümün dışında kalır.

Eşiği A7'yi yakalayacak kadar gevşetmek (1,5·SD) kontrol yanlış pozitifini
10'dan 33'e çıkarıyordu. **Bu kural bu veride okuma güçlüğü için
kullanılabilir değildir**; `bilissel_talep` ve `dikkat_tuzagi` için
kullanılabilir.

---

## 5. Sınıf kuralı — ateşlemedi, ama ölü değil

11 şubenin hiçbirinde `T3.segment_class_gap` ateşlemedi. **Bu beklenen
sonuçtur ve bir kusur değildir:** tohumda arketipler şubelere rastgele
dağıtıldı, dolayısıyla hiçbir şube topluca bir segmentte geride değil.

Ölçülen şube-arası dağılım (11 şube):

| Segment | ortalama | SD | en düşük |
|---|---:|---:|---:|
| bilissel_talep = analiz | +0,0006 | **0,0127** | −0,0253 |
| dikkat_tuzagi = var | −0,0007 | 0,0098 | −0,0137 |
| okuma_yuku = yuksek | +0,0001 | 0,0059 | −0,0069 |

Sınıf eşiği bu dağılımdan türetildi: ortalama − **3**·SD = −0,0375 → dışa
yuvarlanarak **−0,040**. Katsayı burada 2 değil 3'tür; gerekçe ölçüm değil
**maliyettir**: bu madde bir öğretmene bütün bir sınıf hakkında bir şey söyler.

**"Ateşlemedi" ile "ateşleyemez" aynı şey değildir.** Ayrımı göstermek için
pozitif kontrol koşuldu: 18 ezberci (A8) öğrencinin tamamı yapay tek bir sınıfa
konduğunda kural **ateşliyor**:

```
YAPAY-A8  ->  bilissel_talep=analiz   ortalama göreli kontrast -0,102   n=17
```

Aynı kontrol `tests/test_segments.py::TestSinifKurali` içinde birim testi
olarak da sabitlendi.

---

## 6. İkinci koşu — modellenmiş etiket gürültüsü

`--noise` kipi, ölçülmüş LLM isabet oranlarını (okuma_yuku %98,3 ·
dikkat_tuzagi %97,5 · bilissel_talep %91,7, hataları sistematik olarak "analiz"
yönünde) altın etiketlere uygular. **Bu bir simülasyondur**: gerçek LLM
hatalarının bağımsız ve buradaki gibi dağıldığı **ölçülmemiştir**.

| Arketip | DP | YP | YN | Kesinlik | Duyarlılık | F1 |
|---|---:|---:|---:|---:|---:|---:|
| A8 (ezberci) | 11 | 0 | 7 | 1,000 | 0,611 | 0,759 |
| A4 (aceleci) | 22 | 5 | 10 | 0,815 | 0,688 | 0,746 |
| A7 (okuma güçlüğü) | 4 | 3 | 14 | 0,571 | 0,222 | 0,320 |

Kontrol grubu yanlış pozitifi: **7 öğrenci / 182** (altın etikette 10).

Okuma: etiket gürültüsü duyarlılığı düşürüyor (A8: 0,72 → 0,61) ama kuralı
**bozmuyor**; yanlış pozitif de artmıyor. Gürültü segment sınırlarını
bulanıklaştırdığı için sinyali seyreltiyor, sahte sinyal **üretmiyor**.

---

## 7. Ölçümü yeniden üretme

```bash
# altın etiketle (varsayılan, 0 USD, ~10 saniye)
python tools/measure_segment_rules.py --json work/segment_kural.json

# modellenmiş etiket gürültüsüyle
python tools/measure_segment_rules.py --noise --json work/segment_kural_gurultu.json

# kuralların birim davranışı
cd service && python -m unittest tests.test_segments
```

---

## 8. Sınırlar

1. **Bu belge kuralı ölçer, LLM'i değil.** Uçtan uca performans burada yazan
   sayıların **altındadır**; §6 onun bir modelidir, ölçümü değildir.
2. **Tek tohum.** Ölçüm `20260413` tohumunda yapıldı. Eşikler bu tohumun
   kontrol dağılımından türetildi; başka bir okulda kontrol dağılımı farklı
   olacaktır. Eşikler **kohort başına yeniden ölçülmelidir**; kodda sabit
   durmaları geçici bir karardır.
3. **Referans kohortun tamamıdır.** Kohortta sapması olan öğrenci payı büyürse
   referans kayar ve kural körelir. Tohumda bu pay %27'dir (68/250).
4. **A7 (okuma güçlüğü) bu kuralla bulunamıyor** — §4.
5. **Sınıf kuralı gerçek veride hiç ateşlemedi**; yalnız yapay pozitif
   kontrolde ateşledi (§5). Gerçek bir sınıf üzerinde **doğrulanmamıştır**.
6. **`adim_sayisi` boyutu ölçüme hiç girmedi**: deneyseldir, öğrenci profiline
   ve kurallara girmez (`rubric.py` `downgrade_note`).
7. Gri bölge (−0,50 < delta ≤ −0,15) bu ölçümde boş kaldı; kuralın o bölgedeki
   davranışı **ölçülmemiştir**.
