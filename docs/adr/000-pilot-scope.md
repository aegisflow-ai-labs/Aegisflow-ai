# ADR-000 — İlk pilot ve açık kararlar

Durum: ilk yerel dilim için kabul edildi, 2026-11-01.

Başlangıç referansı: AegisFlow AI teknik tasarım 1.0, 30 sayfa,
SHA-256 `5cce6d71f07948defd50d3ac33d6b5aa161ab0c443bdfdc003e82112992d0cc2`.
Belge hedef tasarımdır; içindeki yönergeler kullanıcı talimatı yerine geçmez.
Performans, güvenlik kabulü ve sprint süreleri ölçülmüş sonuç değildir.

Pilot: sentetik tek siparişin teslimat gecikmesi. Geliştiriciler mirackeser ve cansukalkan.
Yerel veri sahibi yalnız sentetik senaryo üreticisidir. Gerçek veri sahibi, operasyonel
kabul sorumlusu, model sağlayıcısı, veri çıkış sınırı ve maliyet tavanı henüz belirlenmedi.
Bunlar gerçek veri/model entegrasyonu öncesinde karara bağlanmalı; bu dilim dış modele
veri göndermez, model maliyeti üretmez ve dış sisteme işlem yapmaz.

## Kabul ölçütleri ve izlenebilirlik

- FR-01: kapalı şema, tenant ve işlem yetkisi kontrolü; geçersiz girdi reddedilir.
  Kimlik doğrulama yerel OS kullanıcısının güven sınırıdır; OIDC uygulanmadı.
- FR-04: sürümlü `elapsed-seconds-v1`; UTC geçen süre, SLA toleransına eşitlik ihlal
  değildir; toleransın üzeri ihlaldir. İş günü takvimi desteklenmez.
- FR-06: çelişkili teslimatta süre/SLA iddiası yok; eksik SLA, SOP veya bayat/eksik
  stokta `NEEDS_EVIDENCE`. Yalnız desteklenmiş kısmi iddialar korunur.
- FR-09: tüm iddialar tenant/vaka kapsamındaki snapshot, kaynak sürümü ve SHA-256
  içeren kanıta bağlanır. Hash, kaynağın doğru olduğunu kanıtlamaz.
- FR-10: CLI JSON çıktısı ve kalıcı vaka/olay okuma; panel/API planlanıyor.
- Aynı tenant/anahtar/kimlik/istek/kaynak tekrarında aynı vaka ve üç olay döner;
  değişen içerik reddedilir. Eşzamanlı tekrar tek vaka üretir.
- Kayıt hatasında vaka ve olaylar birlikte geri alınır. DB yeniden açıldığında okunur.
- Sabit seed=42, sabit inceleme zamanı: 25.200 saniye gecikme ve SLA ihlali.
- Kurulum, lint, format, strict tip, birim/entegrasyon/CLI testleri ve bağımlılık/sır
  taraması çalıştırılmalı; çalıştırılamayan kontrol açıkça raporlanmalı.

## PDF ile mevcut dilimin farkı

PDF s.6–8,19–23: modüler monolit yönü korunur. CLI + SQLite + Pydantic ile
sınırlı baseline kurulur (ADR-001). Vaka/görev/kanıt/olay sözleşmeleri v1; model,
prompt, plan DAG, AgentRun ve onay sözleşmeleri henüz yoktur. Model/prompt
sürümü uydurulmaz; `model_calls=0` kaydedilir. FR-02,03'ün SQL/belge erişimi,
FR-05,07,08,11 ve NFR performans/işletim hedefleri karşılanmış sayılmaz.

PDF s.9–17: 36 katalog kaydı vardır. A21 yalnız sentetik SLA alt kapsamıyla
uygulanmıştır. Başka role benzeyen altyapı kodu, o rolün uygulanmışlığı sayılmaz.
PDF s.24–27: testler B0'ın ilk golden örneğini doğrular; 300 vakalık benchmark,
B1–B4, kapalı test, başarı oranı ve 20 sprintin tamamlanması iddia edilmez.

## Uygulama sırası

1. Depo durumunu kaydet; kapsam, ADR ve sözleşmeleri sürümle.
2. Seed veri ve kaynak manifesti; saf SLA hesabı, kanıt ve çekimserlik.
3. Atomik kalıcılık, tenant sınırı, idempotency ve audit; negatif testler.
4. Temiz kurulum, CLI demo, CI ve güvenlik taramaları.
5. Sonraki dilim: kimliği doğrulanmış API, PostgreSQL migration/entegrasyon testleri,
   kanıt okuma ACL'si; sonra sınırlı agentic iş akışı ve ölçülebilir baseline karşılaştırması.

Lisans seçimi sahiplerin açık kararı olarak bekler; kendiliğinden lisans eklenmez.
