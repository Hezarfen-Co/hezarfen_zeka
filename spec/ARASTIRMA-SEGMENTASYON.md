# Arastirma — LLM Soru Segmentasyonu ve Cok Ajanli Mimariler

## Istatistik

```
{
 "angles": 5,
 "sourcesFetched": 26,
 "claimsExtracted": 127,
 "claimsVerified": 25,
 "confirmed": 12,
 "killed": 13,
 "unverified": 0,
 "afterSynthesis": 11,
 "urlDupes": 0,
 "budgetDropped": 4,
 "agentCalls": 108
}
```

## Ozet

Doğrulamadan geçen 12 iddia üç net sonuca işaret ediyor. (1) Bilişsel etiketleme için tek modelli iyi bir istem gerçekçi ve savunulabilir bir taban çizgisidir: güçlü bir LLM ile sıfır-örnekli ~0,75, uzman seçimi örnek + derse özgü eylem fiilleriyle ~0,84 ağırlıklı F1 (İngilizce Bloom görevlerinde); buna karşılık göreve özel ince-ayarlı sınıflandırıcılar bağlam değiştiğinde ortalama 0,25–0,28 F1 kaybediyor, yani bizim Türkçe K-12 bankamıza aktarılamaz. (2) Çok ajanlı (multi-agent) mimarilerin popüler kıyaslamalarda tek ajanlı çerçevelere kıyasla kazancı asgari düzeydedir; başarısızlıklar rastgele değil yapısaldır (14 mod / 3 kategori, MAST) ve hataların ~%21'i doğrulayıcı katmanının kendisinden gelir; sikofantik uyum (modal benimseme %85,5'e kadar) uzlaşma yanılsamasını ölçülebilir kılar; rol tanımı ve orkestrasyon iyileştirmeleri yalnızca +%9,4…+%15,6 kazanç verip sistemik güvenilirliği sağlamaz. Dolayısıyla 5.960 soruyu çok ajanla işlemek varsayılan değil, eşit token bütçesinde A/B ile kanıtlanması gereken bir seçenektir. (3) Altın küme yokluğunda ZORUNLU ve elde olan tek ucuz ön koşul kararlılık ölçümüdür: Prompt Stability Score (PSS) + `promptstability` paketi, insan etiketi olmadan intra-/inter-istem Krippendorff alpha üretir; ancak PSS kararlılığı ölçer, GEÇERLİLİĞİ ölçmez — geçerlilik yalnızca 217.498 cevaptan gelen ampirik p-değeri/ayırt edicilikle kurulabilir. Kritik boşluk: madde zorluğu tahmini, ampirik dış geçerlilik protokolü ve öğrenci profilleme etiği açılarında doğrulamadan geçen hiçbir iddia yok; bu üç açı bu sentezde kanıtlanmamış sayılmalıdır.

## Dogrulanmis Bulgular (11)

### 1 — guven: high | oy: 3-0

**Iddia:** Göreve/bağlama özel ince-ayarlı (fine-tuned) bilişsel düzey sınıflandırıcıları bağlam değiştiğinde ciddi biçimde bozulur; bizim kurulumumuzda ÇALIŞMAZ — hazır bir Bloom sınıflandırıcısı satın almak/eğitmek yerine istem tabanlı LLM yolu tercih edilmelidir.

**Kanit:** 5 veri kümesi, 4.179 soru üzerinde çok-veri-kümeli karşılaştırma: BERT veri kümesi içinde 0,76–0,91 ağırlıklı F1, görülmemiş veri kümesinde ortalama −0,28 düşerek 0,31–0,76; TFPOSIDF+SVM 0,68–0,82'den ortalama −0,25 ile 0,40–0,70'e iniyor. Aynı makalede istem tabanlı LLM'ler (GPT-5/GPT-5-mini) veri kümesi kaymasına karşı çok daha kararlı (~0,75 sıfır-örnekli, 0,84'e kadar). UYGULANABİLİRLİK: bizde çalışır yönü 'ince ayar yapma, istem kullan'. KAYIT: bozulma heterojen (bir çiftte SVM +0,02 kazanmış), beş veri kümesi de İngilizce — Türkçe'ye aktarım ekstrapolasyondur ama muhafazakâr yönde. Kanıt gücü: tek makale, çok veri kümeli, ön baskı (AIED 2026 kabul beyanı).

- https://arxiv.org/pdf/2606.13684

### 2 — guven: medium | oy: 2-1

**Iddia:** Tek modelli iyi bir istem, bilişsel sınıflandırmada makul ve kararlı bir taban çizgisidir: sıfır-örnekli ~0,75, en iyi istemle 0,76–0,84 ağırlıklı F1. Bizde ÇALIŞIR ama sayılar birebir aktarılamaz — DeepSeek için beklenti ~0,75±0,05'e çekilmeli.

**Kanit:** Tablo 3 (GPT-5, selected-questions-verbs): Yahya 0,84 / Gani 0,83 / Scaria 0,82 / Mohammed 0,81 / Sangodiah 0,76; GPT-5-mini her hücrede ~0,03 altta. ZORUNLU KAYITLAR: (a) modeller GPT-5 ailesi, DeepSeek değil; (b) beş veri kümesi de İngilizce, Türkçe için kanıt YOK; (c) en iyi sonuç uzman seçimi bağlam örnekleri + derse özgü eylem fiilleri gerektiriyor — bizde uzman/altın küme yok, yani 0,84 koşulu aynen sağlanamaz; (d) görev 6 sınıflı Bloom; bizim özel segmentlerimiz (dikkat, çeldirici tuzağı, çok adımlılık) için doğrudan geçerli değil; (e) makale çok ajanlı mimariyle KARŞILAŞTIRMA YAPMIYOR — bu kaynak 'çok ajan gereksiz' tezinin kanıtı olarak kullanılamaz; (f) ~0,84 tavanı, kendisi öznel olan altın etiketlere karşıdır, yani ~%16 artık etiket gürültüsü aşağı akışa taşınır.

- https://arxiv.org/pdf/2606.13684

### 3 — guven: medium | oy: 2-1

**Iddia:** İstem mühendisliği kazancı küçük ama tutarlıdır ve 'uzman seçimi örnek + düzeye özgü eylem fiili listesi' ham örnek sayısını artırmaktan daha değerlidir; bu ucuz tasarım dersi bizde ÇALIŞIR (ek ajan/token gerektirmez, yalnızca daha uzun istem).

**Kanit:** Bloom görevinde en iyi-vs-sıfır-örnekli delta: +0,09/+0,05/+0,05/+0,08/+0,07; seçilmiş ≤10 örnek, rastgele 10-shot'a 5/5 veri kümesinde eşit veya üstün. Marathi çalışmasında few-shot altı modelin tamamında ORTALAMA doğruluğu artırıyor ama yalnızca +0,5…+5,3 puan (GPT-4o +0,8) ve ince-ayarlı BERT'in altında kalıyor. DÜZELTME: 'her veri kümesinde geçer' ifadesi yanlış — 3-shot Mohammed ve Gani'de, 10-shot Gani'de berabere. KARŞI KANIT: eğitsel soru sınıflandırmasında (10 kategori) sıfır-örnekli+tanımlar few-shot ve few-shot+CoT'yi geçmiş; yani few-shot üstünlüğü bir yasa değil, göreve bağlıdır — bizde ölçülmeli. Marathi sayıları GPT-4o/Gemini 1.0 kuşağından ve duygu/haber/nefret söylemi görevlerinden; Türkçe bilişsel etiketlemeye sayısal transfer yapılamaz, yalnızca niteliksel sinyaldir.

- https://arxiv.org/pdf/2606.13684
- https://arxiv.org/pdf/2411.17637

### 4 — guven: medium | oy: 2-1

**Iddia:** Bilişsel düzey etiketlemede insan uzman taban çizgisi düşük–orta ve çok değişkendir (ham uyum ~%54; Krippendorff alpha 0,25'ten Fleiss kappa 0,765'e kadar). Dolayısıyla 'altın küme yok' bizde mutlak bir engel değildir; LLM uyumu insan taban çizgisine göre değerlendirilmeli ve kategori sayısı azaltılıp rubrik kalibre edilerek kappa 0,6+ hedeflenebilir.

**Kanit:** Medical Science Educator (2026): 4 deneyimli öğretim üyesi, 50 madde, 6 Bloom düzeyi — AI müdahalesi öncesi medyan uyum %54,1. Destekleyen bağımsız kaynaklar: eczacılık fakültesi Bloom kodlamasında Krippendorff alpha=0,25 (kategoriler birleştirilince doğruluk %46,0'dan %68,3'e); SIGCSE çalışmasında 8 değerlendirici/42 soru Fleiss kappa=0,189; Cambridge Assessment ikili uyum %34–77, Cohen kappa 0,12–0,60. KARŞIT UÇ: Türkiye DUS sorularında 3 uzmanla Fleiss kappa=0,765 ve %74,6 tam uyum — yani 'insan taban çizgisi her zaman düşüktür' mutlaklaştırılırsa YANLIŞ olur. UYARI: %54,1 şans-düzeltmesiz ham yüzde, kappa ile kıyaslanamaz; örneklem 4 hakem/50 İngilizce tıp maddesi. PRATİK SONUÇ: hedef eşik olarak tek sayı kullanma; boyut sayısını 6 yerine 3–4'e indir, rubrik kalibrasyonu yap.

- https://pmc.ncbi.nlm.nih.gov/articles/PMC13356134/
- https://www.sciencedirect.com/science/article/pii/S1877129715301921
- https://dl.acm.org/doi/10.1145/3441636.3442305

### 5 — guven: high | oy: 3-0

**Iddia:** LLM etiketleri anlamca eşdeğer istem varyasyonlarına karşı kırılgandır ve bu tekrarlanabilirliği (replicability) doğrudan tehdit eder; 5.960 sorunun etiketleri tek bir istem sürümüne dayanırsa etiket dağılımı kayabilir. Bizde ZORUNLU ölçüm.

**Kanit:** Barrie, Palaiologou & Törnberg (arXiv 2407.02039, son revizyon 15 May 2026): ~3,1 milyon satır, ~300 milyon girdi token, 6 veri kümesi, 12 çıktı değişkeni. Yakınsayan bağımsız kaynaklar: LLM Hacking (2509.08825), Inter-Prompt Reliability (2604.16413), WASSA 2026 parafraz duyarlılığı — yalnızca cümle yapısının yeniden düzenlenmesi etiket dağılımını 8,38–28,10 yüzde puanı kaydırıyor. NİTELEME: kırılganlık görev- ve model-bağımlıdır, yasa değildir; PSS>=0,80 sağlam kabul edilir ve birçok istem bunu geçer. BİZİM İÇİN OLUMLU: parafraz testlerinde DeepSeek Reasoner en kararlı uçta çıkmış. Önerilen çözüm tek 'optimal istem' aramak değil, istem topluluğu (prompt ensemble) + PSS raporlamasıdır.

- https://arxiv.org/pdf/2407.02039
- https://arxiv.org/abs/2509.08825
- https://aclanthology.org/2026.wassa-1.5/

### 6 — guven: high | oy: 3-0

**Iddia:** Altın küme olmadan hesaplanabilen, bizde DOĞRUDAN KULLANILABİLİR tek hazır araç Prompt Stability Score'dur (PSS + `promptstability` Python paketi): aynı istemin tekrarıyla intra-PSS, anlamsal eşdeğer istem varyantlarıyla inter-PSS, Krippendorff alpha üzerinden. Ancak PSS kararlılığı ölçer, GEÇERLİLİĞİ ölçmez — ampirik p-değeri doğrulamasının yerine geçmez, onu tamamlar.

**Kanit:** PSS, alpha = 1 - D_o/D_e ile hesaplanıyor; intra-PSS aynı istemin 30 çalıştırmasıyla, inter-PSS PEGASUS ile üretilen eşdeğer istem varyantlarıyla. Karşılaştırma model çıktıları arasında yapıldığı için insan referansı gerekmez — 'altın küme olmadan hesaplanabilir' ifadesi doğru. Paket gerçek: Apache-2.0, son sürüm 14 May 2026, Python >=3.8,<3.11. Makalenin kendi sınırı: stability != accuracy/validity; alpha<0,8 'incelenmeli' eşiği öneriliyor (mutlak kabul eşiği değil). BİZE ÖZGÜ KAYIT: inter-PSS'in parafraz adımı PEGASUS'a bağlı ve İngilizce odaklı; Türkçe istemler için parafraz üretimi DeepSeek ile ikame edilmeli. intra-PSS bu kısıttan etkilenmez. PRATİK: tam etiketleme öncesi 150–500 soruluk alt kümede istem başına PSS ölç; alpha<0,70 ise istemi revize et.

- https://arxiv.org/pdf/2407.02039
- https://pypi.org/project/promptstability/
- https://github.com/palaiole13/promptstability

### 7 — guven: high | oy: 3-0

**Iddia:** Çok ajanlı sistemlerin (MAS) popüler kıyaslamalarda tek ajanlı çerçevelere kıyasla kazancı asgari düzeydedir; çok ajanlı mimari OTOMATİK kazanç getirmez. Bizde kural: tek modelli iyi istem zorunlu kontrol grubudur ve karşılaştırma EŞİT TOKEN BÜTÇESİNDE yapılmalıdır.

**Kanit:** Cemri ve ark. (NeurIPS 2025): 'performance gains across popular benchmarks remain minimal compared to single-agent frameworks'. Bağımsız çok-veri-kümeli doğrulama: 2502.08788, 5 MAD yöntemi x 9 kıyaslama x 4 temel model — MAD, eşit hesaplama bütçesinde chain-of-thought ve self-consistency çoğunluk oylamasının GERİSİNDE. En güçlü karşıt kaynak (2510.20963) bile mevcut MAD protokollerinin tek ajanlı taban çizgisinin altında kaldığını TEYİT ediyor; yalnızca yeni önerdiği işbirlikçi protokol ColMAD eşit bütçede ~4 puan (86,29 vs 81,98 Avg F2) üstünlük sağlıyor — küçük ve göreve özgü. SINIR: MAST'ın incelediği sistemler ajan-yürütme çerçeveleri (ChatDev, MetaGPT, AppWorld), bizim gibi tek-atımlı sınıflandırma değil; bu bir ekstrapolasyondur. 'Çok ajan asla işe yaramaz' biçiminde kullanılırsa AŞIRI YORUM olur.

- https://arxiv.org/abs/2503.13657
- https://arxiv.org/abs/2502.08788
- https://arxiv.org/abs/2310.01798
- https://arxiv.org/abs/2510.20963

### 8 — guven: high | oy: 3-0

**Iddia:** MAS başarısızlıkları yapısal ve sınıflandırılabilirdir (14 mod / 3 kategori); en önemlisi 'görev doğrulaması' ayrı bir hata ekseni olduğundan, planladığımız doğrulayıcı-ajan (verifier) tasarımının KENDİSİ bir hata kaynağıdır — doğrulayıcı eklemek hata oranını otomatik düşürmez.

**Kanit:** 7 MAS çerçevesinden 1.642 etiketli yürütme izi; 150 iz üzerinde uzman anotasyonu, anotatörler arası kappa=0,88 (yani hatalar güvenilir biçimde tekrar eden desenler halinde kodlanabiliyor). Kategori dağılımı: sistem tasarımı/şartname %41,8, ajanlar arası hizalanmama %36,9, görev doğrulama %21,3. FC3 kategorisi doğrudan 'incorrect verification', 'no or incomplete verification' ve 'premature termination' modlarını içeriyor — hataların ~1/5'i doğrulama katmanından geliyor. Sonraki literatür (LumiMAS, 2508.12412) MAST'ı çürütmüyor, genişletiyor. DİPNOT: kategoriler istatistiksel olarak ortogonal kanıtlanmış değil, tümevarımsal kodlamadan türetilmiş; izler kodlama/matematik/genel ajan görevlerinden ve GPT-4/Claude 3/Qwen2.5 neslinden.

- https://arxiv.org/abs/2503.13657
- https://arxiv.org/abs/2508.12412

### 9 — guven: high | oy: 3-0

**Iddia:** Yüzeysel müdahaleler (daha iyi rol tanımı, daha iyi orkestrasyon) MAS'ı güvenilir hale getirmez: ölçülen kazanç +%9,4…+%15,6 ile sınırlı. 'Daha iyi istem yazarsak çok ajanlı yapı düzelir' varsayımı kanıtlanmamıştır; çok ajanlı boru hattına yatırımdan önce maliyet/fayda ölçülmelidir.

**Kanit:** Yazarların kendi müdahale deneyi: 'these interventions often provided only limited improvements, indicating that superficial fixes are insufficient for achieving robust reliability'. MAS çerçevelerinde başarısızlık oranları %41–86,7. Bağımsız örüntü: paralelleştirilebilir görevlerde kazanç (Finance-Agent +%81), sıralı/bağımlı görevlerde %70'e varan BOZULMA (PlanCraft) — yani kazanç görev topolojisine bağlı. KALİBRASYON UYARISI: müdahaleler SIFIR kazanç vermedi; raporda 'istem iyileştirmesi hiç işe yaramaz' denirse aşırı yorum olur. Doğru ifade: 'gerçek ama sistemik güvenilirlik için yetersiz kazanç'. Bizim görevimiz (sabit şemalı, tek-atımlı, uzun-ufuklu araç kullanımı olmayan sınıflandırma) MAST'ın incelediği açık-uçlu ajan iş akışlarından farklı olduğundan bulgu 'varsayılan olarak çok ajan alma, A/B ölç' biçiminde geçerlidir.

- https://arxiv.org/abs/2503.13657

### 10 — guven: medium | oy: 2-1

**Iddia:** Uzlaşma yanılsaması ölçülebilir bir hata modudur: sikofantik uyum ile ajanlar çoğunluk cevabını eleştirmeden benimsiyor, modal benimseme %85,5'e kadar çıkıyor. Bizde risk: birbirini onaylayan ajanlardan gelen 'yüksek uzlaşma', doğruluk değil homojenlik göstergesi olabilir.

**Kanit:** Bertalanič & Fortuna (29 Nis 2026): 10 homojen ajan, 3 tur tartışma, Qwen2.5-7B / Llama-3.1-8B / Ministral-3-8B, GSM-Hard ve MMLU-Hard. Aynı çalışma bağlamsal kırılganlık (%70,0'a kadar) ve uzlaşma çöküşü (oracle gap 32,3 puan) modlarını da bildiriyor; debate 2,1–3,4x token karşılığında izole öz-düzeltmeye eşit veya daha kötü. Bağımsız yakınsama: 2604.02668 (sycophancy propagation), 2606.02646 (Ringelmann etkisi). ZORUNLU ÇERÇEVELEME: hakem denetiminden geçmemiş ön baskı; yalnızca 7–8B açık ağırlıklı KÜÇÜK modellerde, YÖNLENDİRİLMEMİŞ HOMOJEN tartışma kurgusunda; %85,5 tipik değil ÜST SINIR; görev alanı matematik/çoktan seçmeli, bizim öznel çok-etiketli sınıflandırmamız değil. DeepSeek pro/reasoner sınıfında veya heterojen/rol-ayrıştırılmış generator-critic kurgusunda aynı oran GÖSTERİLMEDİ.

- https://arxiv.org/abs/2605.00914
- https://arxiv.org/abs/2604.02668
- https://arxiv.org/abs/2606.02646

### 11 — guven: low | oy: çıkarım (oylanmadı)

**Iddia:** ÇIKARIM (kanıttan türetilen operasyonel protokol, doğrudan bir çalışma bulgusu DEĞİL): Doğrulama sırası 'kararlılık önce, geçerlilik sonra' olmalı — (1) 300–500 soruluk alt kümede 5–10 parafraz istemle intra/inter-PSS, (2) tek modelli iyi istemi taban çizgi olarak sabitleme, (3) ancak bundan sonra eşit token bütçesinde çok ajanlı varyantla A/B, (4) geçerlilik yalnızca 217.498 cevaptan hesaplanan p-değeri/ayırt edicilikle kurulur.

**Kanit:** Bu protokol, doğrulanmış üç bulgunun (PSS'in altın-küme gerektirmemesi; MAS kazancının asgari ve eşit-bütçe ölçümü gerektirmesi; tek istemin kararlı taban çizgi oluşturması) birleştirilmesinden türetilmiştir. Adım 4'ün (ampirik öğrenci verisiyle dış geçerlilik: 'akıl yürütme' etiketli soruların gerçekten düşük p-değerine sahip olup olmadığı, çok boyutlu madde tepki kuramı, faktör analizi, asgari örneklem büyüklüğü) hiçbir bileşeni için bu turda doğrulamadan geçen kaynak YOKTUR — bu adım literatürle desteklenmiş değil, yalnızca mantıksal olarak zorunludur. Sayısal eşik önerileri (alpha<0,70 revizyon, PSS>=0,80 sağlam) kaynaklardan alınmıştır; 300–500 soruluk alt küme büyüklüğü ise kanıtlanmış değil, pratik bir tahmindir.

- https://arxiv.org/pdf/2407.02039
- https://arxiv.org/abs/2503.13657
- https://arxiv.org/pdf/2606.13684

## Curutulen

- {"claim": "Bloom 'gold' labels themselves are subjective and instructor-dependent, which the authors use to explain cross-dataset failure — meaning agreement-with-human-experts is an unstable validation target and external criteria (e.g. empirical student response data) are needed instead.", "vote": "0-3", "source": "https://arxiv.org/pdf/2606.13684"}
- {"claim": "Uzman altın standardına karşı doğrulanan bir GenAI (ChatGPT-4 tabanlı) sınıflandırıcı, 100 bağımsız test maddesinde Bloom taksonomisi etiketlemesinde %95,0 doğruluk ve κ = 0,85 (95% GA 0,73–0,96) uyum elde etti — yani LLM ile bilişsel düzey etiketleme, iyi tasarlanmış tek bir modelle çok yüksek uyum verebilir.", "vote": "0-3", "source": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13356134/"}
- {"claim": "Öğretim üyeleri AI önerisine %75,2 oranında uydu; AI önerisine uymadıkları (itiraz ettikleri) durumlarda kendi nihai kararlarının medyan doğruluğu yalnızca %29,4 çıktı — yani 'insan son sözü söyler' türü doğrulama, etiket kalitesini düşürebilir.", "vote": "0-3", "source": "https://pmc.ncbi.nlm.nih.gov/articles/PMC13356134/"}
- {"claim": "LLM'lerin Bloom taksonomisine göre bilişsel düzey etiketlemesinde uzman konsensüsüyle uyumu yalnızca orta düzeydedir (κ ≈ 0.27–0.42); en iyi model Gemini 2.5 Flash κ = 0.424, Claude Sonnet 4 κ = 0.415, Llama 3.3 70B κ = 0.266. Bizim kurulumumuz için gerçekçi bir üst sınır beklentisi: tek bir LLM'den κ > 0.45 beklenmemeli.", "vote": "0-3", "source": "https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2026.1866674/full"}
- {"claim": "İnsan uzmanların kendi aralarındaki Bloom sınıflandırma uyumu LLM-uzman uyumundan belirgin biçimde DÜŞÜKTÜR (Fleiss κ = 0.117; 85 maddenin yalnızca 11'inde üç uzman oybirliği). Yani 'altın küme' yokluğu bizde bir eksiklik değil, alanın yapısal bir özelliğidir ve insan etiketi taban çizgisi zaten gürültülüdür.", "vote": "0-3", "source": "https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2026.1866674/full"}
- {"claim": "Öğrenme kazanımı hizalaması gibi daha yoruma açık, soyut boyutlarda hem LLM-uzman uyumu (ICC = 0.121–0.380) hem uzmanlar arası uyum (tek ölçüm ICC = 0.089, %95 GA −0.010 ile 0.210) neredeyse sıfırdır; yani öznel bilişsel boyutlar güvenilir biçimde etiketlenemiyor.", "vote": "0-3", "source": "https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2026.1866674/full"}
- {"claim": "Buna karşılık nesnel/kural tabanlı teknik ölçütlerde LLM-uzman uyumu neredeyse mükemmeldir: olumsuz ifadeli kök tespitinde κ = 0.897, tutarsız sayısal veri tespitinde κ = 0.661. Bu, segmentasyon şemamızın mümkün olduğunca operasyonel ve gözlemlenebilir ölçütlere (çok adımlılık, sayısal işlem içerir mi, olumsuz kök, metin uzunluğu) indirgenmesi gerektiğini gösterir.", "vote": "0-3", "source": "https://www.frontiersin.org/journals/medicine/articles/10.3389/fmed.2026.1866674/full"}
- {"claim": "Düşük kaynaklı bir dilde (Marathi) en güçlü LLM'ler bile göreve özel ince ayarlı BERT temel çizgisinin altında kalıyor: GPT-4o 10,2 puan, Llama 3.1 405B 14,1 puan daha düşük doğruluk. Bu, Türkçe gibi İngilizce dışı dillerde LLM etiketleyici başarımının düştüğü savını doğrudan destekler (Türkçe, Marathi'ye göre daha iyi temsil edilse de aynı riskin varlığına işaret eder).", "vote": "0-3", "source": "https://arxiv.org/pdf/2411.17637"}
- {"claim": "LLM etiketleme kalitesindeki açık görev karmaşıklığıyla birlikte büyür: basit duygu analizinde BERT ile fark küçükken, 4 sınıflı nefret söylemi ve haber sınıflandırması gibi çok sınıflı/karmaşık görevlerde fark belirgin biçimde artar. Kapalı kaynak LLM'ler ile ince ayarlı BERT arasındaki ortalama fark %13,9'dur.", "vote": "0-3", "source": "https://arxiv.org/pdf/2411.17637"}
- {"claim": "Homojen çok ajanlı tartışma (multi-agent debate), izole öz-düzeltmeye (isolated self-correction) kıyasla 2.1-3.4 kat daha fazla token tüketirken eşit ya da DAHA DÜŞÜK doğruluk üretiyor; yani maliyet çarpanı karşılığında kazanç yok (negatif fayda). Bu, 6.000 soruyu çok ajanlı işlemenin maliyet gerekçesini doğrudan çürütüyor.", "vote": "0-3", "source": "https://arxiv.org/abs/2605.00914"}
- {"claim": "Çoğunluk oylaması (plurality voting) üretim havuzunda zaten var olan doğru cevapları eliyor; 'consensus collapse' nedeniyle oracle boşluğu 32.3 yüzde puanına kadar ulaşıyor. Yani ensemble/oylama deseni bilgi kaybettiriyor.", "vote": "0-3", "source": "https://arxiv.org/abs/2605.00914"}
- {"claim": "Akran gerekçeleri (peer rationales) önceden doğru olan akıl yürütmeyi bozuyor: bağlamsal kırılganlık (contextual fragility) kırılganlık oranı %70.0'a kadar çıkıyor — hata yayılımı ajanlar arası gerçek ve büyük.", "vote": "0-3", "source": "https://arxiv.org/abs/2605.00914"}
- {"claim": "Modern güçlü LLM'lerde self-consistency (çoklu akıl yürütme yolu örnekleme + çoğunluk oyu) kazancı ihmal edilebilir düzeydedir: Gemini 2.5 ile 20 örnekte HotpotQA'da yalnızca %0.4, MATH-500'de %1.6 doğruluk artışı ölçülmüştür.", "vote": "0-3", "source": "https://arxiv.org/abs/2511.00751"}

## Uyarilar

BÜYÜK KANIT BOŞLUKLARI: Beş araştırma açısından ÜÇÜ bu turda kanıtsız kaldı. (a) Madde zorluğu ve ayırt ediciliğin metinden tahmini (açı 3) için doğrulamadan geçen TEK BİR iddia yok — LLM zorluk tahminlerinin ampirik p-değeriyle korelasyonu, kalibrasyon sorunu ve çeldirici kalitesi değerlendirmesi hakkında bu sentez hiçbir şey söyleyemez. (b) Doğrulama metodolojisi (açı 4 — sizin için en kritik olan) için de kanıtlanmış bulgu yok: yapı geçerliliği testleri, faktör analizi, çok boyutlu madde tepki kuramı, etiket gürültüsünün aşağı akış etkisi ve asgari örneklem büyüklüğü konularında verilen her sayı tahmindir. (c) Öğrenci profilleme ve etik (açı 5) — öğrenme stilleri efsanesi benzerliği, damgalama riski, çocuk verisi ve yurt dışı sağlayıcıya veri aktarımının KVKK/GDPR boyutu — hiç kanıtlanmadı. Bu üç açı için ayrı bir araştırma turu gereklidir.

REDDEDİLEN İDDİALARIN ANLAMI: 13 iddia 0-3 oyla düştü. Bunların çoğu 'çok ajanlı yapı zararlıdır' yönünde GÜÇLÜ sayısal iddialardı (debate 2,1–3,4x token karşılığı negatif fayda; çoğunluk oylamasının bilgi kaybettirmesi, oracle gap 32,3 puan; akran gerekçelerinin %70 kırılganlık üretmesi; self-consistency kazancının Gemini 2.5'te %0,4–1,6'ya inmesi). Düşmeleri bu bulguların YANLIŞ olduğu anlamına gelmez — doğrulayıcılar kaynak/kapsam gerekçeleriyle üç oyu vermedi. Pratik sonuç: 'çok ajanlı yapı kesin zararlıdır' TEZİ KANITLANMAMIŞTIR; kanıtlanan tez yalnızca 'otomatik kazanç getirmez, eşit bütçede ölçülmelidir'. Aynı şekilde Bloom etiketlemede κ=0,85 gibi yüksek uyum iddiası da, κ≈0,27–0,42 gibi düşük uyum iddiaları da düştü — yani LLM-uzman uyumu için güvenilir bir beklenti aralığı elimizde YOK.

DİL VE MODEL UYUŞMAZLIĞI (en yaygın sınır): Ayakta kalan sayısal bulguların neredeyse tamamı İngilizce veri kümelerinden ve GPT-5/GPT-4o/Gemini/Llama kuşağı modellerden geliyor. Türkçe için doğrudan kanıt SIFIR; DeepSeek pro/flash/reasoner ailesi için de sınıflandırma başarımı kanıtı yok (tek olumlu sinyal: parafraz kararlılığında DeepSeek Reasoner iyi çıkmış). 0,84 F1 bir tavan, taban değil.

GÖREV UYUŞMAZLIĞI: Bloom bulguları 6 sınıflı, altın etiketli, tek boyutlu sınıflandırmaya aittir. Bizim hedefimiz çok etiketli, özel şemalı (dikkat, çeldirici tuzağı, çok adımlılık) ve altın kümesiz. MAS bulguları ise açık-uçlu, araç kullanan ajan iş akışlarından; tek-atımlı etiketleme görevine ekstrapolasyondur.

ZAMAN DUYARLILIĞI: Kaynaklar Mart 2025 – Mayıs 2026 arası; MAS literatürü hızlı değişiyor. Ayrıca iki temel kaynak (arXiv 2606.13684 ve 2605.00914) hakem denetiminden geçmemiş ön baskıdır. Bloom altın etiketlerinin kendisi öznel olduğundan ~0,84 tavanı, ~%16 artık etiket gürültüsünün öğrenci profiline taşınacağı anlamına gelir — bu gürültünün aşağı akış etkisi ölçülmemiştir.

## Acik Sorular

- Ampirik dış geçerlilik protokolü: LLM'in 'akıl yürütme gerektirir' dediği soruların gerçekten düşük p-değerine sahip olup olmadığını sınamak için hangi istatistiksel tasarım (karma etkili model, çok boyutlu madde tepki kuramı, doğrulayıcı faktör analizi) uygundur ve 5.960 soru / 250 öğrenci / 217.498 cevap bu tasarımlar için yeterli güç sağlar mı? Asgari soru ve öğrenci sayısı nedir? (Bu turda hiç kanıt bulunamadı.)
- LLM'lerin madde zorluğunu metinden tahmin etme başarımı nedir — ampirik p-değeriyle korelasyon büyüklüğü (r) hangi aralıkta, 'soruyu kendisi çözerek zorluk kestirme' yaklaşımı çoktan seçmeli Türkçe maddelerde işe yarıyor mu ve LLM'ler kendi zorluk tahminlerinde aşırı güvenli mi?
- DeepSeek ailesi (pro/flash/reasoner) Türkçe K-12 soru metinlerinde bilişsel etiketlemede hangi PSS/kappa düzeyini veriyor? Reasoner'ın ek akıl yürütme maliyeti flash'a göre etiket kalitesinde ölçülebilir kazanç sağlıyor mu — yoksa maliyet çarpanı karşılıksız mı?
- Bilişsel segment bazında öğrenci profillemenin eğitim literatüründeki geçerliliği: 'öğrenme stilleri efsanesi' ile yapısal benzerlik riski gerçek mi, bu tür etiketlerin damgalayıcı kullanımına dair kanıt var mı, ve Türkiye'de çocuk verisinin yurt dışı LLM sağlayıcısına gönderilmesi KVKK açısından hangi koşullarda mümkündür (anonimleştirme, yalnızca soru metni gönderme yeterli mi)?

