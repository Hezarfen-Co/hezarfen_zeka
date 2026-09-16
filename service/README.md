# hezarfen-ZEKA servisi

Öğrenci analizi ve tavsiye servisi. Podcast ve Çelebi ile **aynı desende** çalışır:
kendi konteynerinde durur, port açmaz, backend'in QUIC köprüsüne dışa arama yapar.

~8.500 satır Python, 628 test, tek çalışma zamanı bağımlılığı `aioquic`.

> **Frontend / backend ekibi:** üretilen her tablo, alan ve kural kimliği için
> tek belge `docs/CIKTI-SOZLESMESI.md`. Segment kurallarının ölçülmüş isabeti
> `docs/SEGMENT-CIKTI.md`.

---

## Veriyi nasıl çeker

**REST'e bağlanmaz.** Yapay zekâ servisleri sistemden veri çekerken REST'i taklit eden
köprü yapısını kullanır: servis kendi açtığı bir QUIC akışına `ApiRequest` yazar, backend
o yolu kendi içinde dağıtır ve `ApiResponse` döner. Ortada HTTP yoktur.

```
ZEKA ──QUIC hab/2──> backend
      ApiRequest{school, path, query, on_behalf_of}
      ApiResponse{outcome, body}
```

Önemli bir ayrıntı: **veri okuma akışlarını servis başlatır**, üstelik kontrol akışından
sonra istediği zaman. Bu yüzden ZEKA, backend kendisine iş göndermesini beklemeden kendi
takvimiyle çalışabilir.

Protokol sürümü `hab/2`'dir (`backend/src/constant.rs:530`). Podcast ve Çelebi `hab/1`
kullanıyor ve bu yüzden **hiç bağlanamıyorlar**; ZEKA o hatayı tekrarlamaz ve bir test
sabiti pinler.

---

## Veri erişim cephesi

Hesap modülleri veritabanını da köprüyü de görmez. Yalnız `Source` arayüzünü görür:

| Yöntem | Köprü yolu | Döndürdüğü |
|---|---|---|
| `profile` | `/users/{id}/profile` | profil nesnesi |
| `marks` | `/marks/{user}` | ders bazında not (`courses`) |
| `attendance` | `/attendance/{user}` | ders bazında devam **sayacı** (`courses`) |
| `pomodoro` | `/pomodoro/{user}` | çalışma oturumları (`items`) |
| `homework_report` | `/homework/report/{user}` | ödev raporu sayfası |
| `homework_list` | `/homework` | ödev listesi |
| `notes` | `/notes` | kişisel notlar |
| `course_notes` | `/course-notes?course=` | ders notları |

Bu arayüzde **yemek, ödeme, diyet, mesaj ve sohbet verisine erişen hiçbir yöntem yoktur.**
Bu bir kural değil, yapısal kapıdır: hesap modülü o veriyi isteyemez çünkü çağıracağı
fonksiyon mevcut değildir. `test_guard.py` yasaklı terimleri hem arayüzde hem iki
uygulamada hem de `compute/` altındaki tüm modüllerde tarar.

Gerekçe etik: diyet profili özel nitelikli veridir, ödeme defteri sosyoekonomik vekildir.
Kantin borcunu bugün öğretmen bile göremiyor; öğretmene tavsiye üreten bir modele o veriyi
vermek erişim kontrolünü modelin içinden dolanmak olurdu.

İki uygulama vardır: `BridgeSource` (köprü üzerinden) ve `FileSource` (JSON fikstürlerden,
test ve geliştirme için). İmzaları aynıdır.

---

## Çalıştırma

```bash
# testler
python -m unittest discover -s tests -t .

# hattı fikstürle uçtan uca koştur (köprü gerekmez)
python -m src.cli run --school demo-okul --source file \
    --fixtures fixtures/demo --dry-run
```

Konteyner olarak `compose.yaml` ile kalkar. Port açmaz; `hezarfen_backend_default`
ağına katılır ve `AI_SHARED_TOKEN` zorunludur (boşsa açılışta reddeder).

**HTTP sunucusu yoktur ve olmayacaktır.** Çelebi'nin geliştirme amaçlı HTTP sunucusu
üretim imajında duruyor ve denetimde kimlik doğrulamasız yüzey olarak işaretlendi;
burada geliştirme yüzeyi komut satırı aracıdır.

---

## Bugün ne üretiyor

| Ürün | Durum |
|---|---|
| Not karnesi | ✅ **ders** düzeyinde (konu kırılımı yok) |
| Çalışma düzeni aynası | ✅ |
| Teslim takvimi | ✅ kısmi (erteleme profili yok) |
| Sınıf ısı haritası | ✅ ders × şube |
| Dikkat listesi | ✅ 4 tetikleyiciden 3'ü |

Dikkat listesi tasarım gereği **tek bir risk skoru üretmez**. Tetikleyiciler ayrı ayrı
listelenir, sıralama yapılmaz, her madde kanıtına bağlıdır. Bir çocuğa "riskli" etiketi
takmanın pedagojik savunması yoktur ve literatür turu bu ürünün etkisi için doğrulanmış
nedensel kanıt bulamamıştır.

Tavsiyeler kanıtsız kurulamaz: `Recommendation` nesnesi `evidence`, `rule_id` ve
`computed_at` olmadan `ValueError` fırlatır.

---

## Bugün ne üretemiyor ve neden

Servis bunları **sahte uygulamayla doldurmaz**; çıktısında eksik olduğunu gerekçesiyle
birlikte raporlar (`unavailable_triggers`, `unavailable_rules`).

| Eksik | Sebep |
|---|---|
| Madde analizinin tamamı | İzin listesinde sınav yolu yok → ham cevap alınamıyor |
| Konu kırılımı | Aynı sebep |
| Erteleme profili | Ödev raporunda `submitted_at` yok |
| Devamda zaman ekseni | Uç satır değil **sayaç** döndürüyor |
| Veli haftalık özeti | `parent_link` yok, velinin kim olduğu çözülemiyor |
| Ölçme kalitesi panosu | Sayaçlar ve sınav listesi yok |

Tohum verisinde 217.498 sınav cevabı ve kasıtlı olarak bozuk maddeler var. Yani
**bulunacak şey mevcut, bulunacak yol yok.**

---

## Backend ekibinden beklenenler

`docs/BACKEND-GEREKSINIMLERI.md` üç maddelik listeyi gerekçeleriyle içerir:

1. **ZEKA'nın yetenekleri backend'de tanımlı değil.** Backend yalnız `chat.reply` ve
   `rag.index` tanır ve eşleşme tamdır. ZEKA bağlansa bile hiç iş almaz — podcast'in
   yaşadığı sorunun aynısı. Bu olmadan istek üzerine çalışan her senaryo kapalıdır.
2. **Sınav yolları izin listesinde yok.** Madde analizi için gereken 9 yol listelenmiştir.
3. **Okul ve kullanıcı listeleme yolu yok.** ZEKA kimleri işleyeceğini köprüden
   öğrenemiyor; bugün yapılandırmadan çözülüyor. Dönem ortası kayıt olan öğrenci
   görünmez, ayrılan silinmez.

Bu maddeler **başka bir ekibin sorumluluğundadır.** ZEKA onlarsız da kendi takvimiyle
çalışır, yalnız kapsamı dardır.

---

## Sınırlar

- Köprü, backend'in protokolünü taklit eden **sahte bir sunucuya** karşı kanıtlandı
  (35 canlı test, gerçek QUIC bağlantısı). Ancak **gerçek backend'e hiç bağlanılmadı**:
  sahte sunucu Rust kaynağı okunarak yazıldı, kaynak yanlış okunduysa test yanlış
  davranışı doğrular. Backend ayağa kalktığında yeniden sınanmalıdır.
- Sertifika düz HTTP ile çekiliyor (podcast ve Çelebi ile aynı). `AI_TLS_FINGERPRINT`
  verilirse parmak izi doğrulanır; verilmezse her açılışta uyarı basılır.
- Okul ve öğrenci kimlikleri yapılandırmadan gelir.
