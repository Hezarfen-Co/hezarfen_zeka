# Hezarfen ZEKA — Bugün Sunabildiklerimiz

> **Kapsam kuralı:** Bu belge, backend ve frontend'de **hiçbir değişiklik yapılmadan**
> bugün üretilebilen analizleri anlatır. Başka ekiplerin işine bağlı hiçbir şey
> "yapabiliyoruz" diye yazılmamıştır; bağımlı olanlar ayrı bölümde listelenmiştir.

---

## 1. ZEKA nedir

Okul verisini gece okuyan, öğrenci başına analiz üreten ayrı bir servis. Podcast ve
Çelebi ile aynı desende çalışır: kendi konteynerinde durur, dışarıya port açmaz,
backend'in köprüsüne bağlanıp veriyi **okur**. Hiçbir şeye yazmaz, hiçbir kaydı
değiştirmez.

Bugün çalışır durumdadır ve bunun için backend'de tek satır değişiklik gerekmemiştir.

---

## 2. Hangi veriyi okuyoruz

Köprünün izin verdiği sekiz yol. Her birinin ne verdiği aşağıda; analiz yeteneklerimiz
tam olarak bu verinin sınırıdır.

| Kaynak | Ne geliyor | Zaman ekseni |
|---|---|---|
| Not raporu | **Sınav sınav** not: sınav adı, türü (quiz/yazılı/final), ağırlığı, alınan not, harf karşılığı, notu veren | ✅ sınav kimliğinden sıralanabiliyor |
| Ödev raporu | **Ödev ödev**: dersi, **konusu**, son teslim tarihi, teslim edildi mi, geç mi, eksik mi, notu | ✅ son teslim tarihi var |
| Devam | Ders bazında sayaç: var, yok, geç, izinli, toplam, devam oranı | ❌ yalnız sayaç, tarih yok |
| Çalışma oturumu | Her oturumun başlangıcı, bitişi, süresi, sayılıp sayılmadığı | ✅ tam zaman damgalı |
| Profil | Ad, rol, sınıf bilgisi | — |
| Ödev listesi | Yaklaşan ödevler | ✅ |

İki nokta özellikle değerli:

- **Not verisi ortalama değil, sınav sınav geliyor.** Bu, "bu öğrenci düşüşte mi" sorusunu
  gerçekten cevaplayabilmemiz demek.
- **Ödev verisi konu etiketli.** Sınav sorularının içine giremesek de, konu bazında
  performansı ödev üzerinden görebiliyoruz.

---

## 3. Ürettiğimiz analizler

Yedi analiz. Her biri için: hangi soruyu cevaplıyor, neye bakıyor, ne zaman susuyor.

### 3.1 Ders bazında not eğilimi

**Cevapladığı soru:** Bu öğrenci hangi derste yükseliyor, hangisinde düşüyor?

Her dersin sınavları kronolojik sıraya dizilir ve eğim hesaplanır. Çıktı tek bir not değil,
yönüdür: yükseliyor, sabit, düşüyor. Yanında sınav dizisi kanıt olarak verilir.

Sınav türü ağırlıklarını okulun kendi ayarlarından alır, yani bir quiz ile finali eşit
saymaz.

**Susma koşulu:** Bir derste yeterli sayıda notlanmış sınav yoksa eğilim gösterilmez,
"henüz yeterli veri yok" denir. Üç nottan çıkarılan eğilim gürültüdür.

### 3.2 Konu bazında ödev performansı

**Cevapladığı soru:** Bu öğrenci hangi konuda zorlanıyor?

Ödevler konularına göre gruplanır. Konu başına teslim oranı, gecikme oranı, eksik sayısı
ve ödev notu ortalaması çıkarılır.

Bu, elimizdeki **tek konu düzeyi sinyaldir**. Sınav sorularının konusuna erişemediğimiz
için, "hangi konuda zayıf" sorusuna bugün ödev üzerinden cevap veriyoruz.

**Susma koşulu:** Konu başına yeterli ödev yoksa bant üretilmez.

### 3.3 Teslim disiplini

**Cevapladığı soru:** Bu öğrenci ödevlerini zamanında yapıyor mu, yoksa erteliyor mu?

Zamanında teslim oranı, geç teslim oranı, hiç teslim edilmemiş ödev sayısı ve bunların
dönem içindeki seyri.

**Bilinen sınır:** Backend teslim **anını** raporlamıyor, yalnız "geç mi" bayrağını
veriyor. Bu yüzden "son gece teslim etme" gibi ince erteleme desenlerini ölçemiyoruz.
Ölçebildiğimiz şey geç ve eksik oranı.

### 3.4 Devam profili

**Cevapladığı soru:** Bu öğrencinin devamı hangi derste sorunlu?

Ders bazında devam oranı ve öğrencinin kendi şubesindeki akranlarına göre konumu.
Karşılaştırma okul geneliyle değil, **aynı şube ve aynı ders** ile yapılır; çünkü bir
dersin devamsızlık düzeyi dersten derse değişir ve havuzlanmış karşılaştırma yanıltır.

**Bilinen sınır:** Devam verisi tarihsiz geliyor, yalnız sayaç. Bu yüzden "son iki haftada
düştü" diyemiyoruz, "bu derste akranlarından düşük" diyebiliyoruz.

### 3.5 Çalışma düzeni

**Cevapladığı soru:** Bu öğrenci düzenli çalışıyor mu?

Elimizdeki en zengin zaman serisi bu. Haftalık çalışma hacmi, düzenlilik, haftanın
günlerine dağılım ve öğrencinin kendi geçmişiyle karşılaştırması.

Çıktı yargı değil ayna: "bu hafta geçen dört haftanın ortalamasının altındasın" gibi.

### 3.6 Dikkat listesi

**Cevapladığı soru:** Öğretmenin gözünden kaçmış olabilecek öğrenci var mı?

Yukarıdaki sinyalleri birleştirir ve öğretmene kısa bir liste sunar.

Üç tasarım kararı önemli:

- **Tek bir risk skoru üretmez.** Tetikleyiciler ayrı ayrı listelenir. Tek sayı hem
  açıklanamaz hem sıralama doğurur.
- **Sıralama yapmaz.** Liste alfabetik veya ders bazındadır, "en riskli" diye bir şey yoktur.
- **Öğrenciye ve veliye gösterilmez.** Bir çocuğa "riskli" etiketi takmanın pedagojik
  savunması yoktur.

Her madde tek tıkla kanıtına iner ve otuz günde kendiliğinden düşer.

### 3.7 Şube ve ders karşılaştırması

**Cevapladığı soru:** Bu şube hangi derste topluca zorlanıyor?

Öğrenci düzeyi analizlerin şube × ders kırılımında toplulaştırılması. Bireysel değil
toplu görünüm olduğu için damgalama riski taşımaz.

---

## 4. Müşteri bunu nasıl alıyor

Frontend'de değişiklik yapılmadığı için bu analizler **uygulama içinde görünmez**.
Teslim biçimi rapordur:

| Biçim | Kime | İçerik |
|---|---|---|
| Okul raporu | Yönetim | Şube ve ders kırılımı, toplu görünüm |
| Öğretmen raporu | Öğretmen | Kendi şubeleri, dikkat listesi, konu kırılımı |
| Öğrenci özeti | Öğrenci veya veli (okulun kararı) | Kendi eğilimi, çalışma düzeni, teslim durumu |
| Ham çıktı | Teknik ekip | Makine okunabilir, kendi sistemlerine bağlamak için |

Hesaplama gece koşar, rapor sabah hazırdır.

---

## 5. Bilerek kullanmadığımız veri

Teknik olarak erişilebilir olsa da modele **sokmadığımız** veriler var:

| Veri | Neden |
|---|---|
| Yemek ve kantin hareketleri | Sosyoekonomik durumun dolaylı göstergesi. Modele girerse ayrımcılığı algoritmaya gömer. |
| Ödeme ve borç kayıtları | Aynı sebep. Ayrıca bu veriyi bugün öğretmen bile göremiyor; öğretmene tavsiye üreten bir modele vermek erişim kontrolünü dolanmak olurdu. |
| Diyet ve alerji profili | Sağlık ve inanç çıkarımına açık, çocuğa ait, ve mutfak güvenliği amacıyla toplanmış. Akademik analiz bambaşka bir amaç. |
| Mesaj ve sohbet içerikleri | Öğrencinin serbest metni. Bugün kimse göremiyor; analize açmak yeni bir işleme faaliyetidir ve ayrı rıza gerektirir. |

Bu bir politika beyanı değil, **kod düzeyinde uygulanmış bir kısıt**: analiz modüllerinin
bu veriye erişebileceği bir fonksiyon yoktur ve bir test bunu her değişiklikte denetler.

---

## 6. Bugün yapamadıklarımız

Dürüst olmak gerekirse bu liste kısa değil ve hepsinin tek bir sebebi var: köprünün
izin listesinde sınav yolları yok, yani **soru bazındaki ham cevaplara erişemiyoruz**.

| Yapamadığımız | Sebep |
|---|---|
| Soru bazında zorluk ve ayırt edicilik analizi | Ham cevap yok |
| "Sınıfın takıldığı soru" raporu | Ham cevap yok |
| Öğretmene soru kalitesi geri bildirimi | Ham cevap yok |
| Sınav sonrası kişisel tekrar listesi | Ham cevap yok |
| Sınav konularına göre karne | Sınav sorularının konusuna erişilemiyor |
| Erteleme deseni (son gece teslim) | Teslim anı raporlanmıyor |
| Devamda zaman ekseni | Devam verisi tarihsiz |
| Veli haftalık özeti | Veli–öğrenci bağı köprüden çözülemiyor |

Bunlar için sahte bir uygulama yazılmamıştır. Servis kendi çıktısında bu eksikleri
gerekçesiyle raporlar.

---

## 7. Kapsamı genişletmek isterseniz

Aşağıdakiler **backend ekibinin işidir** ve bizim kontrolümüzde değildir. Her biri
ne açtığıyla birlikte listelenmiştir.

| İstenen | Ne açar |
|---|---|
| Köprünün izin listesine sınav yollarının eklenmesi | Yukarıdaki ilk dört madde. Madde analizinin tamamı. |
| ZEKA'nın yeteneklerinin backend'de tanımlanması | İstek üzerine analiz. Bugün yalnız gece toplu iş çalışıyor. |
| Okul ve öğrenci listeleme yolu | Dönem ortası kayıt olan öğrencinin otomatik görünmesi. Bugün liste elle veriliyor. |
| Frontend'de bir analiz ekranı | Raporun uygulama içinde görünmesi. |

Not: elimizdeki test verisinde 217 binden fazla sınav cevabı ve kasıtlı olarak bozuk
sorular var. Yani madde analizinin bulacağı şey mevcut, ulaşacağı yol yok.

---

## 8. Sınırlar ve dürüstlük notu

- Analizlerin çoğu **eğilim ve karşılaştırma** üretir, tahmin değil. "Bu öğrenci
  başarısız olacak" demiyoruz, "bu derste düşüş var" diyoruz.
- Dikkat listesinin öğrenme çıktısına faydası için literatürde doğrulanmış nedensel
  kanıt bulunamamıştır. Bu ürünü sınırlı ve geri alınabilir biçimde tasarladık; okulun
  hiç açmama tercihi de geçerlidir.
- Her analizin bir susma koşulu vardır. Veri azsa sayı üretmez, "yeterli veri yok" der.
  Az veriden çıkarılan sonuç, sonuç değildir.
- Köprü bağlantısı gerçek bir backend örneğine karşı henüz sınanmamıştır; protokol ve
  veri çözümlemesi testlerle doğrulanmıştır.
