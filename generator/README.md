# Hezarfen Tohum Verisi Üreticisi

250 öğrencilik, gerçekçi ve **belirlenimci** bir K‑12 okulu üretir; çıktı, demo
okulunun **veri setidir** — yüklemesi backend ekibinin işidir (`paket/OKU.md`).

Girdi belgeleri: `../spec/schema.json` (otorite), `../spec/SENARYO.md` (senaryo),
`../spec/PAROLA.md` (argon2 parametreleri).

> ⚠️ **Bu veri asla üretim ortamına yüklenmemelidir.** Tüm kullanıcıların parolası
> aynı ve herkese açıktır (`Hezarfen2026!`), kayıtlar uydurmadır ve içinde
> **kasıtlı veri hataları** vardır (§"Kasıtlı hatalar"). Yalnızca yerel geliştirme,
> test ve demo ortamlarında kullanın.

---

## 1. Gereksinimler

| | |
|---|---|
| Python | 3.14 (3.11+ çalışır) |
| Bağımlılık | yalnız `argon2-cffi` (parola özeti için) |
| Başka pip paketi | **yok** — ULID üretimi ve rastgelelik standart kütüphaneyledir |

```bash
python -c "import argon2; print('argon2 hazır')"
```

## 2. Çalıştırma

```bash
cd generator
python main.py                                   # full ölçek, varsayılan tohum, ../seed
python main.py --scale smoke --out ../seed_smoke # hızlı duman testi (20 öğrenci)
python main.py --seed 12345 --date-shift-days 154
python selfcheck.py ../seed                      # üretilen çıktıyı denetle
```

### Parametreler

| Parametre | Varsayılan | Açıklama |
|---|---|---|
| `--seed` | `20260413` | Tüm rastgeleliğin tohumu. Aynı tohum + aynı ölçek = **bayt bayt aynı çıktı**. Her alan için tohumdan türetilmiş ayrı üreteç kullanılır; bir alandaki değişiklik diğerlerini kaydırmaz. |
| `--scale` | `full` | `full` = 250 öğrenci (~571.000 satır), `smoke` = 20 öğrenci (~67.000 satır). Senaryodaki oranlar korunur, yalnız öğrenciye bağlı hacim küçülür. |
| `--date-shift-days` | `0` | Tüm `int` zaman damgalarına eklenen gün sayısı. `0` kanonik veriyi verir (`T_NOW = 2026‑04‑13`). `154` (= 22 tam hafta) verilirse `T_NOW → 2026‑09‑14 Pazartesi` olur ve haftanın günü deseni bozulmaz; `152` de çalışır ama gün deseni kayar. |
| `--out` | `../seed` | Çıktı dizini. |
| `--schema` | `../spec/schema.json` | Şema otoritesi; her alan adı buna karşı doğrulanır. |
| `--keep-parts` | kapalı | Geçici `_parts/` dosyalarını silmez (hata ayıklama). |

Tipik süre (full): **~50 saniye**, ~170 MB çıktı.

## 3. Çıktılar

| Dosya | İçerik |
|---|---|
| `00_kontrol.<uzantı>` | **CONTROL** tarafı: okul satırı (`hezarfen-demo`), 21 modülün tamamı açık. Yazımı idempotenttir; okul zaten oluşturulmuşsa satırı günceller. |
| `01_…` … `12_…` | **OKUL** verisi. Numaralar `schema.json → load_order` topolojik sırasını izler; `exam_answer` kendi dosyasındadır (en büyüğü). |
| `99_…` | SENARYO §7.6'daki **48 bütünlük sorgusu**. Her sorgu **0 döndürmelidir**. |
| `MANIFEST.json` | Tablo başına satır sayısı, dosya boyutları, tohum, ölçek, üretim zamanı, `T_NOW` ve senaryo §7'deki beklenen değerlerin gerçekleşen karşılıkları + sapma gerekçeleri. |
| `_seed_manifest.json` | **Gizli gerçek** (SENARYO §7.8): madde parametreleri (`a`, `b`, `c`, çeldirici), **bilişsel boyut etiketleri** (`dims`) ve **tuzak şık kimliği** (`trap_choice`), öğrenci arketipleri ve **boyut sapmaları** (`dim_delta`), kenar durum bayrakları, değiştirilen cevap anahtarları, silinen banka şablonları. Veritabanına **yazılmaz**; doğrulama ve tavsiye sistemi değerlendirmesi bu dosyayla yapılır. |

Her veri dosyasının başında hangi tabloları içerdiği, kaç satır olduğu ve hangi
dosyadan sonra yüklenmesi gerektiği yorum bloğu olarak yazılıdır.

## 4. Teslim

Üretici **veri setini üretir, yüklemez**. Yükleme adımları bu depoda değildir:
çıktı backend ekibine verilir; okulun şemasını uygulayan ve veriyi döken taraf
backend'dir (`paket/OKU.md`).

Bu ayrım bilinçlidir: şema işi ile veri yazımı aynı pakette olmamalıdır — şema
tamamen kurulduktan **sonra** veri yazılır. Doğrulama da iki taraflıdır:
`selfcheck.py` üretilen dosyaları denetler (§6), 48 bütünlük sorgusu ise
yüklenmiş veriyi.

## 5. Kod düzeni

| Dosya | Sorumluluk |
|---|---|
| `main.py` | CLI, üretim akışı (SENARYO Ek A sırası), MANIFEST ve `_seed_manifest.json` |
| `config.py` | Tüm sabitler: takvim, ölçek profilleri, arketip parametreleri, isim havuzları, dosya düzeni. **Sihirli sayı başka dosyada yoktur.** |
| `world.py` | Üretim bağlamı (`Ctx`) ve ölçek profilleri |
| `ids.py` | ULID üretimi, kompozit anahtarlar, `table:⟨key⟩` kaçışlaması |
| `emit.py` | Akışlı veri yazıcı; her satırın her alanını `schema.json` ile doğrular |
| `timeline.py` | Yerel saat → unix‑ms, öğretim haftaları, gün numarası, tarih kaydırma |
| `dists.py` | Dağılımlar (normal, log‑normal, Beta, Poisson, ağırlıklı seçim) |
| `content_tr.py` | **Türkçe metin havuzları:** ders başına kavram listeleri, şık şablonları, soru kökü şablonları, öğrenci cevabı cümleleri ve §4.5'teki kavram yanılgısı tablosu (92 konu). Ayrıca **bilişsel boyut etiketlerinden metin üreten** katman (`make_labeled_question`, `make_labeled_stem`). Üretim kodunda gömülü metin yoktur. |
| `people.py` | Kullanıcılar, arketip dağıtımı, veli bağları, oturumlar |
| `academics.py` | Dönem, şube, ders, konu, kayıt, ders oturumu, yoklama, ders notu |
| `assessment.py` | Sınav, soru bankası, soru, deneme, cevap, sonuç, bozma adımı |
| `engagement.py` | Ödev, pomodoro, soru havuzu, sohbet, not, mesaj, tahta, rozet |
| `operations.py` | Randevu, etkinlik, yemek, ödeme, mesai |
| `counters.py` | Sayaç materyalizasyonu ve sayaç taşıyan satırların yazımı; control dosyası |
| `verify_queries.py` | 48 bütünlük sorgusunun üretimi |
| `selfcheck.py` | Üretilen çıktının bağımsız denetimi |

### Neden bu yapı

* **Akışlı yazım.** Her tablo önce kendi `_parts/<tablo>.part` dosyasına, 800 kayıtlık
  toplu `INSERT` ifadeleriyle akıtılır; üretim bitince parçalar `load_order` sırasına
  göre numaralı dosyalara birleştirilir. Böylece 217.000 satırlık `exam_answer` hiçbir
  zaman bellekte tutulmaz, ama sayaç taşıyan satırlar (ör. `course.enrollment_count`)
  her şey sayıldıktan sonra yazılabilir.
* **Şema disiplini.** Şemada tanımsız bir alan **sessizce düşer**; bu yüzden
  `emit.validate_row()` her alanı yazmadan önce `schema.json` ile karşılaştırır ve
  yazım hatasında üretimi durdurur. Dizi alanları daima açıkça yazılır (`DEFAULT []`
  tam satır yazımında tetiklenmez).
* **Kimlik kaçışlaması.** Her kayıt kimliği `table:⟨key⟩` (U+27E8/U+27E9) biçiminde
  yazılır; ULID rakamla başladığı için çıplak yazım ayrıştırılamaz.
* **Dize kaçışlaması tek yerde** (`emit.sq_string`). Ters bölülü tırnak kaçışı
  (`\'`) **kullanılmaz**: Türkçe metinde kesme işareti çok sık geçer
  (Ali'nin, 2026'da, Atatürk'ün) ve bu dizinin okuyucu tarafından kabul
  edildiği sınanarak doğrulanamadı. Risk varsayıma bırakılmak yerine
  ortadan kaldırıldı:
  tek tırnak yoksa `'…'`, tek tırnak varsa `"…"` (Türkçe metinde çift tırnak
  neredeyse hiç geçmez, kaçışa gerek kalmaz), ikisi de varsa çift tırnaklıda
  `\"` kaçışı — bu son durum sayılır ve raporlanır. Ters bölü ve kontrol
  karakterleri her iki biçimde de kaçışlanır ve sayılır.
* **ULID = kendi zaman damgası.** Her kimliğin ilk 10 karakteri satırın kendi
  `created_at` / `starts_at` değerinden türer, böylece `ORDER BY id` ile
  `ORDER BY <zaman>` aynı sırayı verir. Aynı milisaniyedeki kayıtlar için monotonluk
  garantisi vardır. `selfcheck.py` bunu 16 tabloda tek tek doğrular.

## 6. Doğrulama

```bash
python selfcheck.py ../seed
```

Denetlenenler:

* (a) her tablo adı `schema.json`'da var mı,
* (b) her alan adı o tablonun şemasında tanımlı mı (tek `FLEXIBLE` alan
  `rag_output.payload` hariç),
* (c) her enum değeri geçerli listede mi,
* (d) her `record<T>` referansı **daha önce** üretilmiş bir kimliğe mi işaret ediyor
  (tipsiz `option<record>` alanları — `meal_ledger.source`, `payment_ledger.source` —
  ileri referans olabilir ve uyarı olarak raporlanır; `schema.json → dependencies`
  bu alanları bağımlılık saymaz),
* (e) 15 sayaç gerçek satır sayımıyla uyuşuyor mu,
* (f) `T_NOW` sonrası gerçekleşmiş kayıt (oturum, cevap, teslim, pomodoro) var mı,
* (g) kimlik kaçışlaması, `seq = 1` kuralı (E3), gün numarası (E2), para ve puan
  sınırları (E18/E19), mesajlaşma rol kısıtı, kimlik tekilliği,
* (h) ULID zaman öneki ile satırın zaman damgası tutarlılığı,
* (i) MANIFEST'teki satır sayıları ile dosyadaki gerçek satır sayıları,
* (j) **metin kalitesi** — eşikler `selfcheck.py` başında durur:
  `MIN_UNIQUE_CHOICE_TEXTS = 3000` (tekil şık metni) ve
  `MAX_CHOICE_TEXT_SHARE = 0.02` (tek bir şık metninin payı),
  `MIN_UNIQUE_QUESTION_STEMS = 2500` (tekil soru kökü),
  `MAX_ANSWER_TEXT_LEN = 400` + `exam_answer.text` daima tam cümleyle biter
  (kelime ortasından kesme yok). Ayrıca aynı sorunun iki şıkkının aynı metne
  sahip olması hata sayılır.
* (k) **dize kaçışlaması ve sözdizimi** — çıktının hiçbir yerinde `\'` dizisi
  bulunmamalı (`BACKSLASH_QUOTE`), ve tüm veri dosyaları (00 ve 99 dahil)
  dize-farkında bir tarayıcıdan geçer: her dize satır sonunda kapanmış mı,
  `[ ]` / `{ }` dengeli mi, fazladan kapanış var mı. Bir veritabanı
  çalıştırmadan
  elimizdeki tek sözdizimi güvencesi budur.
* (l) **konu-kavram uyumu** — sayısal derslerde soru kökünde geçen konu adı ile
  kökte/şıklarda geçen kavram aynı `SUBJECT_CONCEPTS` havuzundan olmalı; ihlal
  oranı eşiği `MAX_TOPIC_MISMATCH_SHARE = 0.02`. Eşleştirme sözcük sınırına
  duyarlıdır ve konu adının kendisi taramadan çıkarılır.
* (m) **sınav içi kök tekilliği** — aynı sınavda aynı soru kökü iki kez
  geçemez (`MAX_SAME_EXAM_DUPLICATE_STEMS = 0`). Sınavlar ARASI yeniden
  kullanım bu denetime girmez: banka şablonunun birden çok sınavda
  kullanılması bilinçlidir (§4.8) ve madde istatistiğinin `n >= 30` kapısını
  besler.

48 bütünlük sorgusu ise aynı işi **yüklenmiş veri tarafında** yapar; ikisi
birbirinin yerine geçmez (biri dosyayı, öteki yüklenmiş veriyi denetler).

### Bilişsel boyut zincirleri (A / B / C)

Önceki sürümde soru metni ile madde zorluğu **bağımsız** üretiliyordu: metni okuyan
bir insan ya da LLM "bu soru analiz gerektiriyor" dese bile o soru gerçekten daha
zor değildi. Ölçüldü, korelasyon ≈ 0 çıktı. Artık üç zincir kuruludur:

* **A — metin ← etiket.** Her maddenin GERÇEK boyut etiketleri (`bilissel_talep`,
  `adim_sayisi`, `dikkat_tuzagi`, `okuma_yuku`) **önce** belirlenir, metin o
  etiketlerden üretilir (`content_tr.make_labeled_question`). Etiket adları ve
  değerleri `service/src/segment/rubric.py` ile **birebir** aynıdır.
  `hatirlama` kısa ve tek olgu sorar; `uygulama` verilen kuralı uygulatır;
  `analiz` karşılaştırtır ("hangisi söylenemez"); `cok_adim` kökte "önce … sonra …"
  zincirini **açıkça** gösterir; `yuksek` okuma yükü kökün önüne 3–6 cümlelik
  paragraf / tablo betimi / grafik betimi koyar (en az 400 karakter);
  `dikkat_tuzagi = var` şıklardan birini doğru şıkkın **yapısal ikizi** yapar.
* **B — zorluk ← bilişsel talep.** `b` artık banttan rastgele çekilmez:
  `ITEM_B_OFFSET + DIM_B_EFFECT toplamı + N(0, ITEM_B_NOISE_SIGMA)`. Zorluk bandı
  adı da bu değerden **okunur** (`DIFFICULTY_BAND_CUTS`). Etiketler `b`
  değişkenliğinin ~%45'ini açıklar; gerisi madde bazlı gürültüdür.
* **C — yetenek ← boyut.** Her öğrencinin genel `theta`'sına ek olarak
  **boyut sapması** vardır (`ARCHETYPE_DIM_DELTA`). Üç arketip belirgin profil
  taşır — A8 ezberci (hatırlamada +0,90, analizde −1,00), A4 aceleci (analizde
  +0,60, dikkat tuzağında −0,95), A7 okuma güçlüğü (yüksek okuma yükünde −1,10);
  beşi (A1, A2, A3, A5, A6) **kontrol grubudur**, sapmaları tam sıfırdır.
  Cevap olasılığı `theta_genel + boyut_sapmasi − b_madde` ile hesaplanır.

Etiketler madde düzeyinde bağımsız çekilir ama **sınav içinde dengelenir**
(`assessment.dim_decks`): gerçek bir öğretmen hepsi analiz olan bir yazılı yazmaz.

Desenin gerçekten oluştuğunun ölçümü: `tools/measure_pattern.py` ve
`service/docs/DESEN-DOGRULAMA.md`.

### Metin içeriği

Şık metinleri, soru kökleri ve açık uçlu cevaplar `content_tr.py`'deki **derse ve
konuya özgü** havuzlardan üretilir: sayısal derslerde sayı/birim/formül parçası,
sözel derslerde kavram/tarih/yer/eser adı. Matematik, fizik, kimya ve biyolojide
kavram havuzu **konu düzeyindedir** (`SUBJECT_CONCEPTS`): "Türev" konusunun
sorusu yalnız türev/eğim/teğet/kritik nokta gibi kavramları kullanır, ders
havuzundan rastgele kavram çekilmez. Her soru kökü şablonu bir **şık tipi
etiketi** taşır (`sayisal` / `ifade`); "kaçtır" diye soran kök sayısal şık,
"hangisi doğrudur" diye soran kök ifade şıkkı alır. Sözel derslerde havuz ders
düzeyindedir (konular birbirinin kavramını serbestçe kullanabilir).

Bir sınavın soru kökleri kendi içinde tekildir: çakışma olursa şablon ve
değişkenler yeniden çekilir (`content_tr.STEM_RETRY`), banka şablonu seçiminde
metni o sınavda zaten geçen adaylar elenir. Havuz gerçekten tükenirse ayırt
edici bir ek konur ve `content_tr.STATS` içinde sayılır — sessiz tekrar
bırakılmaz. Sınavlar arası yeniden kullanım korunur. Aynı sorunun şıkları birbirinden farklı
olacak biçimde çekilir; her şablon en az bir değişken içerdiği için hiçbir metin
şıkların %2'sinden fazlasını kaplayamaz. Açık uçlu cevaplar 1–3 cümlelik gerçek
öğrenci cevaplarıdır ve arketiple ilişkilidir (A1 dolu ve terimli, A7 ile kırılma
sonrası A6 kısa ve eksik).

## 7. Veride bilerek bırakılan hatalar

Bunlar hata değil, **test malzemesidir**; `MANIFEST.json → kasitli_hatalar` altında
sayılırlar ve `_seed_manifest.json` gerçeği tutar:

| Kod | Ne |
|---|---|
| K1 | `user.pomodoro_finished_total` %8 şişiktir (backfill hatası simülasyonu) |
| K2/K3 | `user.lessons_attended_total` ve `user.high_mark_total` hiç yazılmaz (`NONE`); bu yüzden ilgili 6 rozet kodu da hiç verilmez |
| K4 | Oturumların %4'ünde `held_counted_at = NONE` |
| K5 | 53 `bank_question.subject = NONE` (konu silinmiş) |
| K6 | 15 banka şablonu silinmiştir; 48 `exam_question.from_bank` alanı `NONE` olur |
| K7 | 12‑A şubesinin `grade` değeri `"12. Sınıf"`tır (diğerleri `"12"`) |
| K8 | 5 sorunun cevap anahtarı sonradan değiştirilmiştir; eski değer yalnız manifest'te |
| K9/K10 | Ayırt ediciliği negatif (`a < 0`) ve sıfıra yakın (`a ≈ 0`) maddeler |

Ayrıca 26 sınav hiç notlandırılmamış, 399 oturumda hiç yoklama girilmemiş, 20 öğrencinin
velisi yok, 95 öğrenci sohbeti hiç kullanmamış, 6 öğrenci dönem ortasında kaydolmuş ve
4 öğrenci okulu bırakmıştır.

## 8. Senaryo beklentilerinden sapmalar

`MANIFEST.json → sapmalar` ve `sapma_gerekceleri` alanları, SENARYO §7'deki her
beklenen değerin gerçekleşen karşılığını ve %5'ten büyük her sapmanın gerekçesini
tutar. Sapmaların çoğu senaryonun **kendi içindeki** tutarsızlıklardan gelir
(ör. §2.3'teki hacim hesabı ile §2.5'teki soru sayıları); bu durumlarda üretici
somut üretim kuralına (§2.4–§2.6, §3–§5) uyar, özet hacim tablosuna değil.

## 9. Parola

Tüm tohum kullanıcıları `Hezarfen2026!` parolasını kullanır; **her kullanıcının
salt'ı farklıdır** ve tohumdan türetilir. Özet biçimi:

```
$argon2id$v=19$m=19456,t=2,p=1$<22 karakter salt>$<43 karakter hash>
```

Bu, backend'in `Argon2::default()` çağrısının ürettiği parametrelerle aynıdır
(`argon2` 0.5.3). Depoda hazır özet yoktur; üretilen özetin Rust tarafında kabul
edildiği, tohum yüklendikten sonra bir öğrenci hesabıyla giriş denenerek
**çalışan sistemde sınanmalıdır**.
