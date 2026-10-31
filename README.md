# AegisFlow AI

Evidence-driven multi-agent decision support and controlled workflow automation.

AegisFlow AI, kurumsal operasyon vakalarını kanıtlarla araştırmayı ve insan tarafından
onaylanmış eylemleri kontrollü yürütmeyi hedefleyen erken aşama bir mühendislik projesidir.
Teknik PDF hedef tasarımdır; performans değerleri ölçülmüş sonuç değildir.

## Mevcut çalışan dilim

**Yerel, sentetik, LLM içermeyen B0 başlangıç akışı:** vaka oluşturma → sipariş,
teslimat, stok, SLA ve prosedür snapshotlarını okuma → UTC gecikme/SLA hesabı →
kaynağa bağlı iddialar veya açık çekimserlik → atomik SQLite vaka ve audit kaydı.

- Kapalı Pydantic v1 sözleşmeleri ve sürümlenen JSON Schema dosyaları.
- Seed=42 ile aynı veri; fixture checksum ve golden beklenti.
- Kaynak sürümü, snapshot ve SHA-256 ile her iddianın kanıt bağlantısı.
- Aynı anahtarlı aynı istekte aynı vaka; değişen istek/kaynak/kimlikte açık hata.
- Eşzamanlı tekrarlar, rollback, tenant/işlem kapsamı ve append-only audit testleri.
- Yerel CLI JSON raporu. Model çağrısı 0; dış iş sisteminde yan etki yok.

## Kurulum ve demo

Python 3.12+ ve uv 0.13.4 gerekir. Yerel olarak Python 3.14.5 doğrulandı.
Depoyu klonlayıp köküne geçin:

```sh
git clone https://github.com/aegisflow-ai-labs/Aegisflow-ai.git
cd Aegisflow-ai
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
mkdir -p work
.venv/bin/python -m aegisflow generate --seed 42 > work/scenario.json
.venv/bin/python -m aegisflow run --scenario work/scenario.json --db work/demo.db --key demo-001 --as-of 2026-11-01T18:00:00Z
```

Beklenen: `COMPLETED`, `DELIVERY_DELAY=25200`, `SLA_BREACH=true`, üç audit olayı,
`active_roles=["A21"]`. Aynı son komutu tekrar çalıştırmak aynı vaka/olayları döndürür.
Aynı anahtarla farklı `--as-of` veya kaynak kullanmak `IDEMPOTENCY_CONFLICT` üretir.
Yeni inceleme için yeni anahtar kullanın. Vaka ID ve kayıt zamanı çalıştırmaya özgüdür;
sabit seed, kaynak ve inceleme zamanı iş sonuçlarını tekrar üretir.

`.env.example` açıklama amaçlıdır; sır veya çevre değişkeni gerekmiyor. CLI kapsamı
bilerek `demo/local-demo` ile sabittir. `--db` yerel dosyaya yazar; kaynağı değiştirmez.
CLI hatada sıfırdan farklı çıkış kodu ve sabit hata kodu döndürür.

## Doğrulama

```sh
sh tools/check.sh
.venv/bin/pip-audit --skip-editable --format cyclonedx-json --output work/sbom.json
gitleaks dir . --redact --no-banner
```

`tools/check.sh` paketi yeniden kurar; böylece testler değiştirdiğiniz kodu kullanır.
Şemaları değiştirdiğinizde kurulumdan sonra `.venv/bin/python tools/export_schemas.py`
çalıştırın; testler şema sapmasını yakalar. Gitleaks yerel ayrı araçtır (8.30.1 ile
kontrol edildi). Güvenlik taraması internet gerektirir. CI aynı kontrolleri Python
3.12/3.14'te, ayrıca geçmiş/çalışma ağacı sır taramasını çalıştıracak şekilde tanımlıdır.
Uzak CI sonucu ancak GitHub'da gerçekten çalışınca doğrulanmış sayılır.

Gerçek yerel sonuçlar ve sınırlılıklar [doğrulama kaydında](docs/verification.md).
Bunlar benchmark başarı oranı veya üretim güvenlik garantisi değildir.

## Rol durumu

[36 rol kataloğu](docs/roles.json): **36 kayıtlı; 1 sınırlı yetenek uygulanmış;
1 sınırlı yetenek test edilmiş.** A21 SLA uzmanı yalnız `elapsed-seconds-v1` sentetik
alt kapsamıyla mevcuttur; PDF'deki tam rol kabulü tamamlanmadı. Golden vakada
**1 etkin rol: A21**. Her vakanın gerçek etkin listesi kendi `active_roles` alanındadır.
Audit, erişim ve hesaplama altyapısının varlığı diğer rollerin tamamlandığı anlamına gelmez.

## Sınırlar ve planlanan özellikler

Bu bir yerel geliştirme aracıdır. Scope güvenilir çağıran bağlamıdır, kimlik doğrulama
sistemi değildir. Ağ API'si, OIDC, üretim tenant izolasyonu, PostgreSQL/RLS, gerçek
SQL/belge adaptörleri, UI, iş günü takvimi, kısmi sevkiyat, kök neden çıkarımı ve
alternatif maliyet/risk kıyası henüz uygulanmadı.

SLA toleransının **üzeri** ihlaldir. Teslim edilmemiş siparişte `as_of` kullanılır;
gelecekteki teslimat hesaplanmaz. Tekrarlanan aynı olay tekilleştirilir, çelişkili
olayda SLA iddiasından kaçınılır. Stok 24 saatten eskiyse veya gelecekteyse belirsizlik
üretilir. SOP yalnız kanıt olarak raporlanır; eskalasyon görevi açılmaz.

SQLite dosya sahibi audit geçmişini değiştirebilir; üretim audit mühürleme, yedekleme,
şifreleme ve yetki ayrımı yoktur. İnsan onayı, payload hash bağlı işlem, dış sistem
idempotency'si, işlem sonrası doğrulama ve telafi ileride uygulanacak. Bunlar olmadan
dış sistemde yazma işlemi eklenmemelidir.

Sonraki dilim: kimliği doğrulanmış API, PostgreSQL ve kaynak/kanıt ACL testleri;
ardından sınırlı agentic yönlendirme ve B0 karşılaştırması. 300 vakalık benchmark,
B1–B4 sonuçları, 36 tam rol ve PDF'nin 20 sprintlik yol haritası planlıdır.

## Belgeler

- [Pilot kapsamı, kabul ölçütleri ve açık kararlar](docs/adr/000-pilot-scope.md)
- [Yerel baseline mimari kararı ve güven sınırları](docs/adr/001-local-baseline.md)
- [Başlangıç depo/erişim doğrulaması](docs/repository-status.md)
- [Sözleşmeler](schemas/) ve [veri manifesti](fixtures/manifest.json)

Depoda lisans seçilmemiştir; açık kaynak lisansı varsaymayın.

## Geliştiriciler

- [Miraç Keser — mirackeser](https://github.com/mirackeser)
- [Cansu Kalkan — cansukalkan](https://github.com/cansukalkan)
