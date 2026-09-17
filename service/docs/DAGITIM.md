# ZEKA -- Dagitim

ZEKA koprusunun nasil derlendigi, nasil kostugu, neye baglandigi ve
**neyin kanitlanmadigi**.

Bu belgedeki her "kanitlandi" ifadesi gercekten kosturulmus bir komuta
dayanir; kosturulmamis olanlar [Kanitlanmayanlar](#kanitlanmayanlar)
bolumunde ayrica sayilir.

---

## 1. Servis ne yapar, ne yapmaz

ZEKA **disa arama yapan bir istemcidir**. Backend QUIC *sunucusudur*, ZEKA
ona dial-out eder (`ai/protocol.rs:3-7`).

Bunun dogrudan sonuclari:

- **Hicbir port acilmaz.** `compose.yaml` icinde `ports:` anahtari yoktur ve
  CI bunu her kosuda dogrular. Servis NAT ardinda yasayabilir.
- **Backend yokken cokmez.** Ulasilamayan bir backend bir ariza degil, bir
  bekleme halidir. ZEKA ustel geri cekilmeyle yeniden dener ve backend geri
  geldiginde **kendiliginden** toparlanir.
- **Kalici red halinde bile cikmaz.** `unsupported_protocol` ya da
  `unauthorized` alindiginda bile `exit` yapilmaz; beklemeyi tavana cekip
  sessizce yeniden dener (`src/bridge.py::run_forever`).

> **Neden bu kadar onemli:** kardes servis podcast `unsupported_protocol`
> alinca `exit 2` yapiyor. `restart: unless-stopped` ile bu sonsuz bir
> crash-loop uretir ve backend duzeltildikten sonra servis kendiliginden
> geri gelmez; operatorun elle mudahalesi gerekir. Ayni denetimde RAG'in
> konteynerinin ise **hic ayaga kalkmadigi** bulundu: komut bir metin basip
> cikiyordu. ZEKA'nin CI'si tam olarak bu iki kusuru olcer.

---

## 2. Derleme

```bash
cd service
podman build -t hezarfen-zeka:dev -f Containerfile .
```

Windows/Git Bash uzerinde yol cevirisini kapatin:

```bash
MSYS_NO_PATHCONV=1 podman build -t hezarfen-zeka:dev -f Containerfile .
```

**Kanitlandi.** Derleme kosturuldu ve basarili oldu.

| | |
|---|---|
| Imaj boyutu | **152 MB** |
| Taban | `docker.io/library/python:3.13-slim`, **digest'e pinli** (`sha256:bffeb7bd…9bb00`) |
| pip katmani | 27.8 MB (`aioquic==1.3.0` + gecisli bagimliliklari) |
| Kullanici | `zeka`, **uid 10002**, non-root |
| Ek apt paketi | yok (`slim` taban ca-certificates tasir; QUIC icin sistem kutuphanesi gerekmez) |

### Taban imaj neden digest'e pinli

`:3.13-slim` etiketi upstream'de yeniden yayimlanabilir; ayni `Containerfile`
o zaman farkli bir taban imajla derlenir. Digest icerigi sabitler. Yenilemek
icin:

```bash
podman pull docker.io/library/python:3.13-slim
podman images --digests docker.io/library/python
```

### `.containerignore`

Derleme baglami `.env`, `*.pem`, `*.key`, `fixtures/`, `tests/`, `.git/` ve
Python artiklarini **dislar**. `Containerfile` yalnizca `requirements.txt`,
`src/` ve `scripts/` kopyaladigi icin bu ikinci bir savunma hattidir: ileride
biri `COPY . .` yazarsa sir yine de imaja girmez.

---

## 3. Calistirma

### compose ile (onerilen)

```bash
cd service
export AI_SHARED_TOKEN=...        # backend ile AYNI sir
export DEEPSEEK_API_KEY=...       # segment hatti icin
podman compose up -d
```

### tek kap olarak

```bash
podman run -d --name hezarfen_zeka \
  --network hezarfen_backend_default \
  -e AI_SHARED_TOKEN=... \
  -e ZEKA_PG_DSN=postgres://<kullanici>:<parola>@<host>:5432/<okul_veritabani> \
  -e DEEPSEEK_API_KEY=... \
  hezarfen-zeka:dev
```

> `ZEKA_PG_DSN` **zorunludur ve ULASILABILIR olmalidir**: servis acilista
> `open_store()` cagirir, DSN yoksa `RuntimeError` ile **cikar**
> (`src/store_factory.py`). Kanit betigi (`scripts/ci-konteyner-kanit.sh`) bu
> yuzden gercek bir Postgres kaldirip kaba gecerli bir DSN verir; 2026-09-16 ve
> 2026-09-17 kosularinda tam bu satir eksik oldugu icin konteyner kosu kaniti
> kirmizi kaldi (`RuntimeError: Ne ZEKA_PG_DSN ne ZEKA_DB_HTTP_URL tanimli`).

**Kanitlandi.** Kap `50 saniye` boyunca gozlendi; **cikmadi**, `running`
kaldi. Backend'e bilerek cozulemeyen bir ad verildi ve gunluklerde ustel geri
cekilme gozlendi:

```
[zeka] ZEKA koprusu basliyor: servis='zeka' hedef=... token=tanimli ...
[zeka] backend'e ulasilamadi: <urlopen error [Errno -3] Temporary failure in name resolution>
[zeka] 4.0s sonra yeniden denenecek
[zeka] backend'e ulasilamadi: <urlopen error [Errno -3] Temporary failure in name resolution>
[zeka] 5.6s sonra yeniden denenecek
```

Bekleme suresi **buyuyor** (4.0s -> 5.6s) ve kap ayakta kaliyor. Aranan
davranis budur.

**Non-root kanitlandi:**

```
$ podman exec <kap> id
uid=10002(zeka) gid=10002(zeka) groups=10002(zeka)
```

---

## 4. Ortam degiskenleri

### Zorunlu

Bu ikisi `${VAR:?aciklama}` bicimindedir; **tanimli degilse `compose config`
patlar** ve servis hic ayaga kalkmaz.

| Degisken | Ne ise yarar |
|---|---|
| `AI_SHARED_TOKEN` | Backend ile paylasilan sir. Bu olmadan `Hello` cercevesi reddedilir, kayit yapilamaz. |
| `DEEPSEEK_API_KEY` | Segment hattinin LLM saglayici anahtari. |

> **Durust not:** `src/bridge.py` `DEEPSEEK_API_KEY`'i **okumaz**; yalnizca
> `src/segment/config.py` okur (oncelik: `DEEPSEEK_API_KEY` -> `LLM_API_KEY`
> -> `SEGMENT_API_KEY`). Yani anahtarsiz bir kopru teknik olarak ayaga
> kalkardi ve ancak segment hatti kosulunca patlardi. `:?` ile hata
> **dagitim anina** cekiliyor: acilista tek satir hata, uretimde saatler
> sonra sasirtici bir cokme yerine. Yalnizca kopruyu kosturmak isteyen bir
> dagitimda bu degisken bilincli olarak sahte bir degerle gecilebilir.

**Sirlar dosyaya gomulmez.** `compose.yaml` yalnizca interpolasyon icerir;
degerler operatorun ortamindan ya da `--env-file` ile verilen (gitignore'lu)
bir `.env` dosyasindan gelir. CI her kosuda bu bicimi denetler.

### Onemli istege bagli degiskenler

| Degisken | Varsayilan | Not |
|---|---|---|
| `HEZARFEN_NET` | `hezarfen_backend_default` | Katilinacak **dis** agin adi. |
| `AI_BRIDGE_HOST` / `AI_BRIDGE_PORT` | `hezarfen_backend` / `8090` | QUIC ucu. |
| `AI_BACKEND_URL` | `http://hezarfen_backend:7656` | Sertifika cekilen HTTP ucu. |
| `AI_TLS_FINGERPRINT` | *(bos)* | **Bos = TOFU.** Asagiya bakin. |
| `AI_MAX_CONCURRENT` | `4` | Backend clamp'i: `1..=AI_MAX_CONCURRENT_PER_WORKER`. |
| `AI_RECONNECT_SECS` / `AI_RECONNECT_MAX_SECS` | `3` / `120` | Geri cekilme taban ve tavani. |
| `ZEKA_SCHOOLS` | `ataturk-anadolu` | Backend'de okul **listeleme yolu yok**; kapsam disaridan verilir. |
| `LOG_LEVEL` | `info` | `debug`, `info`, `warn`, `error`. |

Tam liste `compose.yaml` icinde, her biri yorumlu.

### `AI_TLS_FINGERPRINT` -- uretimde doldurun

Bos birakilirsa **TOFU (trust-on-first-use)**: `GET /ai/certificate` ne
donerse ona sorgusuz guvenilir. Ag icinde araya giren biri kendi
sertifikasini pinletip butun QUIC trafigini okuyabilir. Bu, podcast ve
Celebi'nin bugunku hali olup denetimde **zafiyet olarak isaretlendi**.

Uretimde backend'in acilista logladigi SHA-256 parmak izini (64 karakter
kucuk harf hex) buraya yazin. Servis her acilista TOFU modunda oldugunu
**uyari olarak loglar**; sessiz bir varsayilan degildir.

---

## 5. Ag

Servis **dis** bir aga katilir; agi kendisi olusturmaz:

```yaml
networks:
  backend_net:
    external: true
    name: ${HEZARFEN_NET:-hezarfen_backend_default}
```

Ag adi **parametriktir**. Kardes servisler (podcast, Celebi) de ayni deseni
kullanir; ag farkli adla kurulduysa `HEZARFEN_NET` ile verilir. CI, bunun
gercekten gecersiz kilinabildigini kosturarak dogrular.

Ag mevcut degilse once olusturun:

```bash
podman network create hezarfen_backend_default
```

---

## 6. Saglik kontrolu

`scripts/saglik.py` -- `compose.yaml` icindeki `healthcheck:` blogu tarafindan
her 30 saniyede kosturulur.

### Ne kanitlar

Kopru surecinin (`python -m src.bridge`) **yasadigini** ve **zombi
olmadigini**. `/proc` altinda komut satiri taranir, sonra `/proc/<pid>/stat`
ile surecin `Z` durumunda olmadigi dogrulanir -- yalnizca varliga bakan bir
kontrol bir cesedi saglikli sanardi.

### Ne kanitlamaz

Backend'e **kayitli** oldugunu. Bu **bilincli bir karardir**: backend
bakimdayken ZEKA'nin geri cekilerek beklemesi bir ariza degildir. Kontrol
hazir olma (readiness) sarti arasaydi, backend'in her yeniden dagitimi
ZEKA'yi `unhealthy` isaretler ve restart politikasi sureci gereksiz yere
oldururdu -- tam da kacinmaya calistigimiz crash-loop.

### Neden bu kadar hafif

Denetimde bir servisin saglik kontrolunun **her 30 saniyede butun hatti
import ettigi** bulunmustu; her kontrol onlarca megabayt ayirip CPU yakiyor
ve agir yuk altinda kontrolun kendisi servisi zaman asimina dusuruyordu.

Buradaki kontrol **hicbir proje modulunu import etmez**; yalnizca `os` ve
`sys` kullanir.

**Olculdu:**

```
5 kosu toplam 0.063 s   (yorumlayici acilisi dahil -> kosu basina ~12 ms)
salt /proc taramasi 50 kez: 0.0015 s
```

### Calistigi kanitlandi -- iki yonlu

Pozitif (kopru yasarken):

```
$ podman exec <kap> python scripts/saglik.py
saglik: TAMAM -- kopru yasiyor (pid 1)
$ echo $?
0
```

Negatif (kopru kosmayan bir kapta):

```
$ podman run --rm hezarfen-zeka:dev python scripts/saglik.py
saglik: BASARISIZ -- 'src.bridge' sureci yasamiyor
$ echo $?
1
```

Motorun kendi degerlendirmesi:

```
$ podman inspect <kap> --format '{{.State.Health.Status}}'
healthy
```

> Negatif taraf kanitin **asil yarisidir**: her zaman 0 donen bir saglik
> kontrolu hicbir sey olcmez. CI bunu her kosuda dogrular.

### Podman ve OCI uyarisi

`Containerfile` icinde de bir `HEALTHCHECK` satiri vardir, ama `podman build`
varsayilan olarak **OCI** imaj bicimi uretir ve OCI spesifikasyonunda
`HEALTHCHECK` alani **yoktur**; satir sessizce dusurulur ve derleme su
uyariyi basar:

```
HEALTHCHECK is not supported for OCI image format and will be ignored.
Must use `docker` format
```

Bu yuzden **asil tanim `compose.yaml` icindedir**. Imajdaki satir yalnizca
imajin tek basina (Docker ya da `podman build --format docker` ile)
kullanildigi durum icin bir yedektir.

---

## 7. Surekli tumlestirme (CI)

Katmanli. Her katman ayri bir istir; bir katman kirmiziya dondugunde neyin
bozuldugu is listesinden okunur.

### `.github/workflows/ci.yml` -- pull request'ler ve `main` DIŞINDAKİ dallar

`main`'e push burada **koşmaz**: aynı beş katman `main.yml` içinde koşar ve
deploy'u kapılar (bkz. bir sonraki başlık). Böylece push başına aynı kapı iki
kez koşmaz; PR'lar ve dal push'ları tam katmanlı süiti buradan alır.

| Katman | Ne denetler |
|---|---|
| **1 -- sozdizimi** | Her `.py` ayristirilabiliyor mu. Testlerden once kosar: bozuk bir dosya, 519 testin *toplanmasini* engelleyip anlamsiz bir hata uretir. |
| **2 -- birim testleri** | `python -m unittest discover -s tests -t .` **Bagimlilik kurulmaz** -- test paketi saf `unittest` kullanir. Boylece kirmizi/yesil bilgisi paket deposu kesintilerinden bagimsizdir. |
| **3 -- sozlesme** | Model adi <-> fiyat tablosu; `source.py` yollari <-> izin listesi. Ayrinti asagida. |
| **4 -- sir taramasi** | `sk-` / `sk_` desenleri, ozel anahtar govdeleri, AWS anahtarlari, yapilandirma dosyalarina gomulmus duz degerler; compose sirlarinin `${VAR:?}` bicimini korudugu. |
| **5 -- konteyner** | Imaj derleniyor **ve kosuyor** mu; **zorunlu uc env ile gercekten aciliyor mu** (kanit betigi gercek bir Postgres kaldirir, `open_store()` ile depoyu acar); non-root mu; saglik kontrolu gercekten olcuyor mu; `compose config` gecerli mi ve port acilmiyor mu. |

### `.github/workflows/main.yml` -- `main` push'u, otomatik dağıtım

Ailedeki Çelebi deploy'uyla aynı şekil; is grafiği:

```
Katman 1..5 (paralel)  ->  Build and test  ->  Deploy (SSH)
```

| İş | Tetik | Neyi kanıtlar / ne yapar |
|---|---|---|
| `sozdizimi`, `testler`, `sozlesme`, `sirlar`, `konteyner` | push (`main`) | `ci.yml`'deki beş katmanın **aynısı** (Komutlar birebir; tek doğruluk kaynağı `scripts/ci-yerel.sh`). Beşi de yeşil olmadan imaj üretilmez. |
| `build` (adı **Build and test**) | push, beş katmanı `needs` ile bekler | İmajı `localhost/hezarfen-zeka:$GITHUB_SHA` olarak derler; imaj tarball'ı (`podman save`), `service/compose.yaml`, `deploy/hezarfen_zeka_compose.service` ve `tag` dosyasını `release` artefaktı olarak yükler (30 gün). Eksik parça burada — sunucuda değil — patlar. |
| `deploy` | push'ta yalnız `Build and test` yeşilse; `workflow_dispatch`'te en yeni yeşil build'in artefaktıyla | SSH ile: kapasite ön kontrolü (≥ 512 MB RAM, ≥ 2 GB disk) → operatörün `~/hezarfen_zeka/hezarfen_zeka.env` dosyasını kontrol (0600'e çeker, **yazmaz**) → imajı `podman load` → tag rotasyonu (`current_tag`→`previous_tag`) → `stack.env`'e `HEZARFEN_TAG` → unit kurulumu + `daemon-reload` + `enable` + `restart` → **`scripts/saglik.py` ile sağlık kapısı** (60 sn) → konteynerin imajı bu tag mi → olmazsa önceki tag'e dön (ilk dağıtımda `down`, `-v` yok) → bağımsız son doğrulama → `rm -rf ~/.ssh`. |

**Yeşil bir `main` push'u otomatik dağıtır.** Elle yeniden dağıtım (süiti tekrar
koşmadan): `gh workflow run main.yml --ref main`.

Kapı hakkında dürüst not: **sağlık kapısı köprü sürecinin yaşadığını ölçer**,
backend'e *kayıtlı* olduğunu ölçmez — `scripts/saglik.py`'nin ta kendisi
kullanılır ve nedeni orada yazılıdır (kayıt şartı aransaydı backend'in her
yeniden dağıtımı ZEKA'yı `unhealthy` işaretler ve crash-loop üretirdi). Backend
sertifika ucu deploy'da yalnızca **uyarı** olarak kontrol edilir; Celebi'deki
gibi bir ön kapı değildir, çünkü ZEKA'nın backend yokken beklemesi tasarım
gereğidir.

Bir seferlik ön koşullar:

1. Repo secret'ları `SSH_PRIVATE_KEY` / `SSH_HOST` / `SSH_USER`.
2. Sunucuda `loginctl enable-linger <kullanıcı>`.
3. Sunucuda `podman` + bir compose sağlayıcı.
4. Operatörün `~/hezarfen_zeka/hezarfen_zeka.env` dosyası (0600; şablon
   `deploy/hezarfen_zeka.env.example`, zorunlu üç sır: `AI_SHARED_TOKEN`,
   `ZEKA_PG_DSN`, `DEEPSEEK_API_KEY`).
5. Sunucuda `hezarfen_backend_default` ağı (backend compose'u kurar) ve
   backend tarafında `AI_QUIC_ADDR=0.0.0.0:8090`.

Manuel yol değişmedi: `cd service && podman compose up -d` (§3).

### Konteyner kosu kaniti -- yerel dogrulama (2026-09-17)

Kanit betigi (`scripts/ci-konteyner-kanit.sh`) artik **gercek bir Postgres**
kaldirir (kendi agi, IP ile DSN) ve kabi **zorunlu uc env ile** kosturur; boylece
kanit, servisin uretimdeki acilis yolunu (`open_store()`) olcer. Duzeltmeden
sonraki yerel kosu:

```
  [ok]   kanit Postgres'i ayakta (adres 10.89.9.2, ...)
  [ok]   kap 50 saniye sonra hala kosuyor (durum=running)
  [ok]   ZEKA_PG_DSN kabul edildi: kopru Postgres yolunu secti (acilis satiri logda)
  [ok]   zorunlu env ile depo GERCEKTEN aciliyor (open_store -> kapat)
  [ok]   ustel geri cekilme gozlendi: 2.6s -> 12.5s (6 deneme)
  [ok]   backend ulasilamazken CIKMIYOR, yeniden deniyor (RAG kusurunun tersi)
  [ok]   non-root dogrulandi (uid=10002)
  [ok]   saglik kontrolu kopru yasarken GECIYOR
  [ok]   saglik kontrolu kopru yokken BASARISIZ oluyor (yani gercekten olcuyor)
  [ok]   motor kabi 'healthy' isaretledi
KONTEYNER KOSU KANITI GECTI     (exit 0)
```

Negatif kontroller (kanit gercekten olcuyor):

```
$ podman run --rm -e AI_SHARED_TOKEN=x hezarfen-zeka:ci
RuntimeError: Ne ZEKA_PG_DSN ne ZEKA_DB_HTTP_URL tanimli — ...          (exit 1)
```

Yani duzeltme oncesi kosucudaki kirmizinin TA KENDISI yerelde yeniden uretildi;
kanit betigi o imzayi artik yakaliyor (1b iddialari).

### `.github/workflows/istege-bagli-testler.yml` -- elle tetiklenir

Her degisiklikte **kosmaz**. `aioquic` kurar ya da bir veritabani kaldirir;
yavastir ve dis etkenlere aciktir. Zorunlu kapiya konulsalardi CI guvenilmez
olurdu, guvenilmez CI da yok sayilir.

- **`kopru-canli`** -- `tests/test_bridge_live.py`: gercek UDP soketi, gercek
  TLS 1.3 el sikismasi, gercek `hab/2` cerceveleri. Karsi taraf
  `tests/fake_bridge/` altindaki **sahte** sunucudur, gercek backend
  degildir. Ag kapsami **yalnizca 127.0.0.1**.
- **`veritabani`** -- SurrealDB entegrasyon testleri (girdi ile acilir).

**Gercek LLM cagrisi hicbir iste yapilmaz.** Segment testleri `MockProvider`
kullanir; `kopru-canli` isi ayrica bir saglayici anahtarinin ortama sizmadigini
denetler ve sizmissa **durur**. Gercek saglayiciya karsi kosu parayla calisir
ve dis bir servise bagimlidir; CI'nin isi degildir.

### Sozlesme denetimi neden onemli

Bu denetim **bu projede iki kez sessiz kusur yakalardi**:

1. **Model adi uyusmazligi.** `cost_usd()` bilinmeyen bir model adi gorunce
   hata vermez; sessizce tablodaki **en pahali tarifeye duser**
   (`provider.py:124-125`). Butce raporu yanlis cikar, hicbir test kirilmaz.
   Dosya basindaki `assert` ise `python -O` ile kapanir, ona guvenilemez.

2. **Izin listesi sapmasi.** `protocol.py:AI_API_ALLOWLIST`, backend'in
   `constant.rs:656-676` listesinin **elle tutulan** kopyasidir. Backend'de
   bir yol eklenip burada eklenmezse cagri `path_not_allowed` ile **tele
   cikmadan** reddedilir; ZEKA veriyi goremez ama testler de ayni kopyayi
   dogruladigi icin yesil kalir.

Denetim `_TEMPLATES` sozlugune **guvenmez**: o yalnizca beyandir. Gercek
istekler cagri yerlerindeki ayri f-string'lerden kurulur
(`source.py:315, 350, 403, 441, 476 ...`) ve denetim bunlari AST ile toplayip
tek tek `path_allowed()`'a sorar.

**Su an kosturulan sonuc:**

```
[ok] LIVE_MODELS 'deepseek-flash'  -> PRICING['deepseek-flash'] mevcut
[ok] LIVE_MODELS 'deepseek-v4-pro' -> PRICING['deepseek-v4-pro'] mevcut
[ok] DEFAULT_MODEL_IDS['flash']    = 'deepseek-flash'  fiyatli ve canli
[ok] DEFAULT_MODEL_IDS['pro']      = 'deepseek-v4-pro' fiyatli ve canli
[ok] DEFAULT_MODEL_IDS['reasoner'] = 'deepseek-v4-pro' fiyatli ve canli
[ok] olu model adlari hicbir tabloda yok
[ok] source.py icindeki 19 yol ifadesinin tamami izin listesinde
[ok] AI_API_ALLOWLIST (19 yol) depo ici anlik goruntuyle ayni
[ok] AI_API_ALLOWLIST (19 yol) GERCEK backend constant.rs ile ayni
[not] PRICING_VERIFIED=False -- fiyatlar 2026-08-28 tarihli, elle dogrulanmamis
```

Son satir bir **not**, hata degil: fiyatlar upstream'de degisir, CI bunu
bilemez ama unutturmamalidir.

### Denetimin gercekten olctugu kanitlandi

Gecen bir denetim, hicbir sey denetlemeyen bir denetimle ayni gorunur. Bu
yuzden **negatif sinama** yapildi: depo `src/` dosyalarina **dokunulmadan**,
calisma agacinin gecici bir kopyasi cikarilip o kopyada iki kusur uretildi --
bir model adi bozuldu (`deepseek-v4-pro` -> `deepseek-v4-PRO-YENI`) ve izin
listesinden bir yol dusuruldu (`/marks/{user}`).

Denetim **sekiz ayri sapma** bildirdi ve `1` ile cikti:

```
[HATA] LIVE_MODELS icindeki 'deepseek-v4-pro' PRICING tablosunda YOK
       -- cost_usd() sessizce en pahali tarifeye duser
[HATA] DEFAULT_MODEL_IDS['pro']      = 'deepseek-v4-pro' PRICING'de YOK
[HATA] DEFAULT_MODEL_IDS['reasoner'] = 'deepseek-v4-pro' PRICING'de YOK
[HATA] source.py:108 '/marks/{user}' izin listesinde YOK
[HATA] source.py:350 '/marks/X'      izin listesinde YOK
[HATA] source.py acilis guvenligi BASARISIZ
[HATA] protocol.py ile tests/test_protocol.py:BACKEND_SNAPSHOT ayristi
[HATA] IZIN LISTESI SAPMASI -- backend constant.rs ile protocol.py ayri:
       yalniz backend'de: ['/marks/{user}']
```

Bu kosu **`python -O` ile** yapildi; yani `provider.py:68`'deki modul ici
`assert` **kapaliydi**. Kusuru yakalayan sey o `assert` degil, denetimin
kendisidir -- ki zaten var olma sebebi budur.

### Yerelde kosturma

Depo su an GitHub'da olmayabilir. Yalnizca `.github/workflows/` yazmak,
kimsenin kosturamadigi bir CI demektir. Tek dogruluk kaynagi `scripts/`
altindaki betiklerdir; **hem Makefile hem is akislari onlari cagirir**.

```bash
# CI'nin tamami, konteyner katmani dahil
bash scripts/ci-yerel.sh --konteyner

# Konteyner olmadan (hizli)
bash scripts/ci-yerel.sh

# Yalnizca sozdizimi + testler (saniyeler)
bash scripts/ci-yerel.sh --hizli
```

`make` kurulu ise ayni hedefler: `make ci`, `make ci-hizli`, `make testler`,
`make sozlesme`, `make sirlar`, `make kanit`, `make compose`.

Gercek backend'e karsi izin listesi karsilastirmasi (GitHub kosucusunda
mumkun degil, yerelde mumkun):

```bash
HEZARFEN_BACKEND=/yol/hezarfen_backend-main python scripts/ci-sozlesme.py
```

**Kanitlandi -- son tam kosu:**

```
KATMAN 1/5 sozdizimi          -> GECTI
KATMAN 2/5 testler            -> GECTI   (Ran 519 tests in 26.464s)
KATMAN 3/5 sozlesme           -> GECTI
KATMAN 4/5 sir taramasi       -> GECTI   (1453 dosya tarandi)
KATMAN 5/5 konteyner+compose  -> GECTI
BUTUN KATMANLAR GECTI
```

> **Bu kayit 519 testlik hale aittir; durum o gunden beri degisti ve 2026-09-17
> tarihinde duzeltildi.** Arada eklenen 686 testin **ucu**, depoda **olmayan**
> uretilmis tohum artefaktlarini istiyordu (`work/items_enriched.json`,
> `seed/11_exam_answer.surql`; ikisi de `.gitignore`'da -- tohum depoda degil,
> yalnizca ureticisi var) ve temiz bir kopyada kirmizi kaliyordu:
>
> ```
> ERROR  tests.test_segment_pipeline.TestRealDataLoaders.test_items_enriched_yuklenir
> ERROR  tests.test_segment_validate.TestGoldSet.test_gercek_veride_741_pozitif
> FAIL   tests.test_segment_pipeline.TestRealDataLoaders.test_cevaplar_surql_dosyasindan_okunur
> ```
>
> Ucu de artik **dosya eksikken** `skipUnless` ile atlanir, **artefakt
> uretilmisken ayni sekilde kosar ve olcer**; gerekce atlama satirinda yazilidir
> (`generator/main.py --scale full`). Eksiklik davranisi zaten
> `test_eksik_dosya_bos_liste` ile pinliydi, kaybedilen bir denetim yok.
> Temiz bir kopyada Katman 2: `Ran 686 tests ... OK (skipped=123)`.

---

## Kanitlanmayanlar

Durustluk bolumu. Asagidakiler **kosturulmadi** ya da **dogrulanamadi**;
"calisiyor" diye sayilmamalilar.

### Kanitlanmayan -- calisma zamani

1. **Gercek backend'e baglanti.** Hicbir asamada gercek bir Hezarfen
   backend'i ayakta degildi. Kanitlanan sey, backend **yokken** dogru
   davranildigidir. `Hello` -> `Greeting` el sikismasi, `hab/2` ALPN
   muzakeresi ve `worker_id` alinmasi gercek backend'e karsi **hic
   kosturulmadi**.

2. **Saglik kontrolunun hazir olma (readiness) sinyali.** Kontrol yalnizca
   surecin yasadigini olcer. Kaydin gercekten yapildigini olcmek icin
   koprunun kendi durumunu bir yere yazmasi gerekir; bu `src/` icinde bir
   degisiklik ister ve bu is kapsaminda **degildi**.

3. **`AI_TLS_FINGERPRINT` ile pinleme yolu.** Kod yolu okundu ama gercek bir
   sertifikayla **kosturulmadi**. Bugunku varsayilan dagitim TOFU'dur.

4. **Restart politikasinin davranisi.** `restart: unless-stopped` yalnizca
   yapilandirmada; bir cokme uretilip kabin gercekten yeniden basladigi
   **gozlenmedi**. (Kap zaten cokmedigi icin tetiklenemedi.)

5. **Uzun sureli kararlilik.** En uzun gozlem **50 saniye** ve iki yeniden
   deneme turudur. Bellek sizintisi, dosya tanimlayici sizintisi ya da
   saatler sonra ortaya cikan davranislar hakkinda hicbir sey bilinmiyor.

6. **`podman compose up` ile uctan uca kaldirma.** `compose config`
   dogrulandi (iki yonlu), ama servis compose ile **kaldirilmadi**: dis ag
   (`hezarfen_backend_default`) ve SurrealDB bu makinede ayakta degildi.

### Kanitlanmayan -- CI

7. **GitHub Actions is akislari artik GERCEK kosucuda kostu -- ama tam yesil
   degil.** `main`'e yapilan iki push'ta (run `35101227990`, 2026-09-16, sha
   `98b2423`; run `35218219339`, 2026-09-17, sha `1027784`) katmanlar kostu:

   | Kosu | 1 | 2 | 3 | 4 | 5 | Build and test | Deploy |
   |---|---|---|---|---|---|---|---|
   | `35101227990` | yesil | **kirmizi** | yesil | yesil | **kirmizi** | -- | -- |
   | `35218219339` | yesil | yesil | yesil | yesil | **kirmizi** | atlandi | atlandi |

   Katman 2 kirmizisi o gun tohum bagimli uc testti (bkz. yukarisi, duzeltildi);
   Katman 5 kirmizisi konteyner kanit betiginin zorunlu `ZEKA_PG_DSN`'i
   vermemesiydi (asagidaki 8. madde). `Build and test` ve `Deploy`'in
   **atlanmasi** tasarim geregidir: kapilar yesil olmadan artefakt uretilmez ve
   sunucuya dokunulmaz.

8. **`main.yml` deploy zinciri hic kosturulmadi.** SSH, `podman load`, unit
   kurulumu, saglik kapisi, tag rotasyonu ve rollback yollari **okundu ve yerel
   olarak kismen dogrulandi** (compose interpolasyonu, kapasite aritmetigi,
   saglik betiginin konteynerde iki yonlu davranisi, `podman save`/`load`
   etiket turu), ama gercek bir sunucuya karsi **hic kosmadi**. Ilk gercek kosu
   bu maddeleri kapatacaktir.

9. **Konteyner kosu kaniti kosucuda yeniden dogrulanmadi.** Betik artik gercek
   bir Postgres kaldirip zorunlu uc env ile kabin ACILDIGINI olcer ve bu yerelde
   `KONTEYNER KOSU KANITI GECTI` ile dogrulandi (bkz. asagisi), ama duzeltilmis
   haliyle GitHub kosucusunda **henuz kosmadi**.

10. **`docker compose` yolu.** `ci.yml` icindeki compose adimi
   `docker compose` cagirir; yerelde `podman compose` zaten docker-compose'a
   devrettigi icin **ayni ikili** kosturuldu, ama GitHub kosucusundaki
   surumle **dogrulanmadi**.

11. **Makefile.** Bu makinede `make` **kurulu degil**; hicbir hedef
   kosturulamadi. Hedefler `scripts/` betiklerini cagiran ince sarmalayicilar
   olsa da, Makefile'in kendisi **sinanmamistir**. Guvenilir yol dogrudan
   `bash scripts/ci-yerel.sh` kullanmaktir.

12. **`istege-bagli-testler.yml` isleri.** Ne `kopru-canli` ne `veritabani`
    isi kosturuldu. `tests/test_bridge_live.py` yerelde `aioquic` kurulu
    olmadigi icin **atlandi**; canli kopru testlerinin gectigi
    **gorulmedi**.

13. *(Bu madde kapatildi -- negatif sinama yapildi, bkz. asagisi.)*

### Kanitlanmayan -- guvenlik

14. **Fiyat tablosunun dogrulugu.** `PRICING_VERIFIED = False`. Fiyatlar
    `2026-08-28` tarihli ve saglayicinin dokumantasyonuna karsi elle
    **dogrulanmamistir**. Butce hesaplari bu tabloya dayanir.

15. **Sir taramasinin kapsami.** Tarayici `.gitignore` tarafindan korunan
    dosyalari **atlar** (ve `.env` ailesinin gercekten korundugunu ayrica
    denetler). `git check-ignore` hala kullanilmaz; yerine
    `.gitignore` desenleri **elle** yorumlanir; karmasik desenlerde (negasyon
    `!`, dizin-koku `/` ayrimi) git ile birebir ayni davranmayabilir.

16. **Gecmis tarama yok.** Tarayici yalnizca **calisma agacini** okur. Git
    gecmisine bir zamanlar islenmis bir anahtar bulunamaz.
