# Desen Doğrulama — tohum verisinde bilişsel desen gerçekten var mı?

> Ölçüm betiği: `tools/measure_pattern.py`
> Veri: `seed/*.surql` (üretilen çıktı) + `seed/_seed_manifest.json` (altın etiket)
> Tohum: `20260413`, ölçek `full`, `T_NOW = 2026‑04‑13`
> Bu belge **ölçülen** sayıları taşır. Ölçülmemiş hiçbir iddia yoktur.

---

## 0. Neden bu belge var

Önceki tohum sürümünde **desen yoktu**:

* Soru metni ile madde zorluğu **bağımsız** üretiliyordu (`assessment.py` zorluk
  bandını hedef oranlara göre dağıtıyor, `b`'yi banttan rastgele çekiyordu; bant
  metin üretimine hiç geçmiyordu).
* Her öğrencinin **tek** bir genel `theta`'sı vardı; bilişsel boyut bazında
  farklılık yoktu.

Sonuç: LLM bir soruyu okuyup "bu analiz gerektiriyor" dese bile o soru gerçekten
daha zor değildi. Daha önce ölçülen değerler: **LLM etiketi ↔ ampirik zorluk
korelasyonu ≈ 0**, öğrenci segment karşıtlıkları **r ≈ −0,03**. Bunlar yöntemin
değil, **verinin kurgusunun** sonucuydu; segmentasyon bu veride doğrulanamıyordu.

Tohum üç zincir kurulacak biçimde yeniden üretildi:

| Zincir | Ne | Nerede |
|---|---|---|
| **A** | Soru metni ← bilişsel etiketler | `generator/content_tr.py::make_labeled_question` |
| **B** | Madde zorluğu (`b`) ← bilişsel talep | `generator/config.py::DIM_B_EFFECT`, `assessment.py::dim_difficulty` |
| **C** | Öğrenci yeteneği ← **boyut bazında** sapma | `config.py::ARCHETYPE_DIM_DELTA`, `people.py::User.dim_ability` |

Boyut adları ve etiket değerleri `service/src/segment/rubric.py` ile **birebir**
aynıdır (`bilissel_talep`, `adim_sayisi`, `dikkat_tuzagi`, `okuma_yuku`).

---

## 1. Ölçüm kapsamı

| | |
|---|---|
| Toplam çoktan seçmeli madde (cevap almış) | 3.870 |
| p‑değeri hesaplanan madde (n ≥ 30 gözlem) | **3.748** |
| Toplam cevap satırı | 216.633 |
| Öğrenci | 250 (8 arketip) |

Madde başına p‑değeri, o maddeye verilen **işaretli** cevaplar üzerinden
hesaplanır (boş bırakma satır yazılmadığı için paydaya girmez). Anlamlılık
sınamaları ek bağımlılık olmadan yapılır: sürekli karşılaştırmalarda Welch *t*
(normal yaklaşımla iki yönlü *p*), oran karşılaştırmalarında iki‑oran *z*.

---

## 2. Ölçüm 1 — Bilişsel talep ↔ ampirik zorluk

**Soru:** Analiz soruları hatırlama sorularından anlamlı biçimde daha düşük
p‑değerine sahip mi?

| `bilissel_talep` | madde | ortalama p |
|---|---:|---:|
| hatirlama | 1.323 | **0,663** |
| uygulama | 1.546 | **0,565** |
| analiz | 879 | **0,458** |

| karşılaştırma | fark | Welch *t* | *p* | Cohen *d* |
|---|---:|---:|---|---:|
| analiz − hatirlama | **−0,205** | −33,89 | < 1e‑12 | **−1,48** |
| analiz − uygulama | −0,108 | −17,84 | < 1e‑12 | −0,75 |
| uygulama − hatirlama | −0,098 | −18,44 | < 1e‑12 | −0,69 |

**Sonuç: evet.** Sıralama `hatirlama > uygulama > analiz` biçiminde tam olarak
beklenen yönde ve etki büyüklüğü analiz↔hatırlama ekseninde *çok büyük*
(*d* = −1,48). Önceki sürümde bu fark ölçülebilir değildi (korelasyon ≈ 0).

Ek ölçüm — `adim_sayisi` (deneysel boyut, yine de üretiliyor):

| `adim_sayisi` | madde | ortalama p |
|---|---:|---:|
| tek_adim | 3.132 | 0,594 |
| cok_adim | 616 | 0,477 |

fark **−0,117**, *t* = −17,76, *p* < 1e‑12, *d* = −0,76.

---

## 3. Ölçüm 2 — Dikkat tuzağı ↔ tuzak şıkkın çekiciliği

**Soru:** Dikkat tuzağı olan maddelerde tuzak şıkkın seçilme oranı, tuzağı
olmayan maddelerdeki **en çekici** çeldiriciden yüksek mi?

| | madde | ortalama pay |
|---|---:|---:|
| `dikkat_tuzagi = var` → **tuzak şıkkın** payı | 1.707 | **0,293** |
| `dikkat_tuzagi = yok` → **en çekici çeldiricinin** payı | 2.041 | **0,181** |

fark **+0,112**, Welch *t* = 35,19, *p* < 1e‑12, *d* = **1,20**.

Ayrıca tuzaklı maddelerin **%98,8**'inde tuzak şık, o maddedeki *en çok seçilen*
çeldiricidir.

**Sonuç: evet.** Karşılaştırma bilerek katı tutuldu: tuzaksız maddelerde tek bir
sabit çeldirici değil, **en çekici olan** alındı; tuzaklı maddelerde ise
manifestoda kayıtlı tuzak şıkkın payı alındı. Tuzak yine de belirgin biçimde
öndedir.

Bunu üreten mekanizma: `dikkat_tuzagi = yok` maddelerde çeldiriciler **eşit**
ağırlıklıdır (`w_m = 1/(k−1)`), `var` maddelerde tuzak şık ağırlığı 0,62'dir
(`config.DIM_W_M`). Tuzak şıkkın **metni** de rastgele değildir: doğru şıkkın
yapısal ikizidir (`content_tr.MISCONCEPTIONS`, 14 konudan **92** konuya
genişletildi; tabloda karşılığı olmayan konularda `GENERIC_TRAPS_*` kalıpları
konunun kendi kavramlarıyla doldurulur).

---

## 4. Ölçüm 3 — Okuma yükü ↔ ampirik zorluk

| `okuma_yuku` | madde | ortalama p |
|---|---:|---:|
| dusuk | 2.715 | **0,600** |
| yuksek | 1.033 | **0,508** |

fark **−0,092**, Welch *t* = −16,49, *p* < 1e‑12, *d* = **−0,59**.

**Sonuç: evet, ama etki bilişsel talepten küçük** (orta büyüklükte). Bu kasıtlıdır:
`DIM_B_EFFECT` içinde okuma yükünün katkısı ±0,34 logit, bilişsel talebin katkısı
−0,75 … +0,85 logittir.

Yüksek okuma yüklü kökler gerçekten uzundur: 3–6 cümlelik paragraf, tablo betimi
ya da grafik betimi eklenir ve kök **en az 400 karakter** olur
(`content_tr.READING_HIGH_MIN_CHARS`); düşük okuma yüklü kökler ~60–180
karakterdir.

---

## 5. Ölçüm 4 — Arketip × boyut kesişim tablosu

**Soru:** Boyut sapması olan arketipler, o boyuttaki sorularda gerçekten farklı
performans gösteriyor mu?

Ham kontrast (ör. "hatırlama doğruluğu − analiz doğruluğu") **madde zorluğunu da
taşır**: analiz maddesi herkes için zordur. Öğrenci tarafındaki sapmayı yalıtmak
için her arketibin kontrastından **kontrol grubunun ortalama kontrastı**
çıkarılır (fark‑farkları). "Kontrole göre" sütunu budur.

Kontrol grubu (sapma tablosu **boş**): A1, A2, A3, A5, A6.
Kontrol ortalama kontrastları: hatirlama−analiz **+0,196**;
dikkat_tuzagi var−yok **−0,021**; okuma_yuku yuksek−dusuk **−0,091**.

| Arketip | Profil | hatirlama − analiz | dikkat_tuzagi var − yok | okuma_yuku yuksek − dusuk |
|---|---|---:|---:|---:|
| A1 | kontrol | +0,157 (**−0,039**) | −0,015 (**+0,006**) | −0,098 (**−0,007**) |
| A2 | kontrol | +0,228 (**+0,032**) | −0,020 (**+0,001**) | −0,092 (**−0,001**) |
| A3 | kontrol | +0,207 (**+0,011**) | −0,034 (**−0,013**) | −0,097 (**−0,006**) |
| **A4** | aceleci: analizde güçlü, tuzağa yakalanan | +0,107 (**−0,089**) | −0,119 (**−0,099**) | −0,083 (+0,008) |
| A5 | kontrol | +0,192 (**−0,003**) | −0,024 (**−0,003**) | −0,089 (**+0,002**) |
| A6 | kontrol | +0,195 (**−0,001**) | −0,011 (**+0,010**) | −0,079 (**+0,012**) |
| **A7** | okuma güçlüğü | +0,192 (−0,004) | −0,035 (−0,014) | −0,136 (**−0,045**) |
| **A8** | ezberci: hatırlamada güçlü, analizde zayıf | +0,400 (**+0,204**) | −0,017 (+0,004) | −0,099 (−0,008) |

Parantez içi = kontrole göre sapma. Kalın = beklenen yöndeki etki.

Ham kontrastların hepsi *z* sınamasında anlamlıdır (A6'nın dikkat_tuzagi
kontrastı dışında: *p* = 0,144). Gözlem sayıları büyüktür (arketip × boyut
hücresi başına 1.949 – 39.990 cevap).

**Sonuç: evet, üç profilin üçü de kendi boyutunda ayrışıyor.**

* **A8 (ezberci)** hatırlama ↔ analiz farkını kontrol grubunun **iki katına**
  çıkarıyor (+0,400 / kontrol +0,196; kontrole göre **+0,204**). Tasarımdaki
  sapma: hatırlamada +0,90, analizde −1,00 logit.
* **A4 (aceleci)** iki boyutta birden ayrışıyor: analizde göreli olarak **iyi**
  (kontrole göre **−0,089**: hatırlama–analiz uçurumu kapanıyor) ve dikkat
  tuzağında belirgin biçimde **kötü** (kontrole göre **−0,099**). Tasarımdaki
  sapma: analiz +0,60, hatırlama −0,35, tuzaklı maddede −0,95 logit
  (+ tuzak şık çekimi ×1,45).
* **A7 (okuma güçlüğü)** yalnız okuma yükünde ayrışıyor (kontrole göre
  **−0,045**), diğer iki boyutta kontrolden ayırt edilemiyor. Tasarımdaki sapma:
  yüksek okuma yükünde −1,10 logit.

**Dürüstlük notu.** A7'nin okuma etkisi tasarımdaki 1,10 logite göre orantısal
olarak küçük görünüyor (−0,045 oran farkı). Nedeni A7'nin zaten düşük genel
yeteneği ve yüksek boş bırakma oranıdır: zor maddeleri sık sık **boş bırakıyor**,
boş bırakılan madde paydaya girmediği için etki kısmen ölçümün dışında kalıyor.
Etki yine de kontrol gürültüsünün (azami 0,012) **3,7 katıdır** ve yönü doğrudur.

---

## 6. Ölçüm 5 — Kontrol grubu

**Soru:** Sapması olmayan arketiplerde fark ~0 çıkıyor mu?

| Boyut kontrastı | Kontrol ortalaması | Kontrol grubunda **azami** mutlak sapma |
|---|---:|---:|
| bilissel_talep: hatirlama − analiz | +0,1956 | **0,039** (A1) |
| dikkat_tuzagi: var − yok | −0,0209 | **0,013** (A3) |
| okuma_yuku: yuksek − dusuk | −0,0910 | **0,012** (A6) |

**Sonuç: evet.** Kontrol grubunun kendi içindeki dağılımı ±0,04'ün altındadır ve
profil taşıyan arketiplerin sapmaları bunun **3,7 – 5,2 katıdır**:

| Profil | sapma | kontrol gürültüsü | oran |
|---|---:|---:|---:|
| A8 / bilissel_talep | +0,204 | 0,039 | **5,2×** |
| A4 / dikkat_tuzagi | −0,099 | 0,013 | **7,6×** |
| A4 / bilissel_talep | −0,089 | 0,039 | **2,3×** |
| A7 / okuma_yuku | −0,045 | 0,012 | **3,7×** |

A4'ün bilişsel sapması kontrol gürültüsünün yalnız 2,3 katıdır — üç profil
içinde **en zayıf** ayrım budur; abartılmamalıdır. Diğer üçü net ayrışır.

---

## 7. Bozulmadığı doğrulanan şeyler

| Denetim | Sonuç |
|---|---|
| `seed/99_dogrula.surql` — 48 bütünlük sorgusu | **48 geçti / 0 ihlal / 0 hata** |
| `generator/selfcheck.py` (şema, enum, referans, sayaç, kimlik, metin, sözdizimi) | **TEMİZ** |
| Belirlenimcilik — aynı tohum, iki koşu, `cmp` | **14/14 dosya bayt bayt aynı** |
| Satır hacmi | 569.808 (önce 573.027, **−%0,6**) |
| Kaçış kuralı (`\'` dizisi) | **0** — kesme işaretli metin çift tırnaklı |
| Tekil şık metni (eşik 3.000) | 8.094 |
| En sık şık metninin payı (eşik %2) | **%0,18** |
| Tekil soru kökü (eşik 2.500) | 3.867 |
| Sınav içi kök tekrarı (eşik 0) | **0** |
| Konu–kavram uyumsuzluğu (eşik %2) | **%0,00** |

---

## 8. Ölçümü yeniden üretme

```bash
# 1) tohumu üret
cd generator && python main.py && python selfcheck.py ../seed

# 2) beş desen ölçümü (yalnız .surql + manifest; veritabanı gerekmez)
python tools/measure_pattern.py --json work/desen.json

# 3) bütünlük sorguları (yüklenmiş tohum gerekir)
python tools/load_seed.py --seed-dir seed
python tools/check_integrity.py
```

Ölçümün tamamı yaklaşık 2 saniye sürer; `--json` verilirse çıktının tamamı
makine okunur biçimde de yazılır.

---

## 9. Sınırlar

* Bu belge **verinin** desen taşıdığını gösterir; bir LLM'in bu deseni **bulup
  bulamadığını** göstermez. O ölçüm segmentasyon hattının işidir
  (`service/src/segment/`), ve artık yapılabilir: `work/items_enriched.json`
  içindeki `gold.dims` alanı her maddenin gerçek etiketini taşır.
* `adim_sayisi` boyutu `rubric.py` içinde **deneysel** işaretlidir (LLM
  etiketlemesinde intra‑alpha 0,70 kapısını geçemedi). Tohumda yine de üretilir
  ve yukarıda ölçülür; aşağı akış hesaplarına girmez.
* Etiketler madde düzeyinde bağımsız çekilir ama **sınav içinde dengelenir**
  (`assessment.dim_decks`): gerçek bir öğretmen hepsi analiz olan bir yazılı
  yazmaz. Bu dengeleme olmadan sınıf notları sınavdan sınava savruluyor ve
  `mark_trend` tetikleyicisi yanlış ateşleyerek dikkat listesini SENARYO §7.5
  P21 bandının (32–48) dışına taşıyordu.
* Ölçüm tek bir tohumda (`20260413`) yapılmıştır. Başka tohumda sayılar
  değişecektir; yönler ve büyüklük sıralaması tasarımdan geldiği için
  korunmalıdır, ama bu **ölçülmemiştir**.
