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
İlk uzak CI, Linux üzerinde Python 3.12/3.14 ve sır taraması işlerinde geçti;
güncel dalın son durumunu PR kontrollerinden izleyin.

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
sistemi değildir. OIDC, üretim tenant izolasyonu, RLS, gerçek
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

Sonraki dilim: OIDC ve kaynak/tenant erişim sınırlarının güçlendirilmesi;
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

## Sentetik HTTP API (ikinci dilim)

Sunucu taraflı geliştirme anahtarıyla kimlik/kapsam doğrulanır. Bu OIDC değildir;
yalnız localhost ve sentetik veri içindir. PostgreSQL adaptörü aşağıdaki ayrı kurulumla kullanılabilir.

```sh
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
.venv/bin/python tools/setup_demo_api.py
export AEGISFLOW_AUTH_FILE=work/api-auth.json
export AEGISFLOW_SCENARIO_FILE=fixtures/supply-delay-v1.json
export AEGISFLOW_DB=work/api.db
.venv/bin/uvicorn aegisflow.api:from_environment --factory --host 127.0.0.1 --port 8000 --no-access-log
```

Başka terminalde:

```sh
curl --fail-with-body http://127.0.0.1:8000/v1/cases \
  -H "Authorization: Bearer $(cat work/api-token)" \
  -H 'Idempotency-Key: api-demo-001' -H 'Content-Type: application/json' \
  -d '{"order_id":"PO-001","as_of":"2026-11-01T18:00:00Z"}'
```

POST senkron 201 ve vaka döndürür; aynı istek aynı vaka/olayları verir.
GET `/v1/cases/{case_id}`, `/v1/cases/{case_id}/events` ve
`/v1/cases/{case_id}/evidence/{evidence_id}` aynı Bearer kimliği gerektirir.
Tenant veya izin istemciden seçilemez. Başka tenant kaydı ve olmayan kayıt aynı
404 yanıtını verir; izinsiz işlem 403, kimliksiz istek 401, bozuk şema 422,
anahtar çakışması 409, DB hatası 503 döndürür. Ayrıntılar [ADR-002](docs/adr/002-authenticated-synthetic-api.md).

## PostgreSQL persistence

PostgreSQL 18 is supported for this synthetic pilot. SQLite remains available for
the local CLI. Configure credentials outside the repository. First set
`AEGISFLOW_DATABASE_URL` to a **schema-owner** connection and run:

```sh
uv sync --frozen --no-editable --reinstall-package aegisflow-ai
.venv/bin/python -m aegisflow.postgres
```

The command applies migration 1 transactionally; repeating it is safe. Startup
never migrates implicitly. Configure a separate runtime role using your database
administrator account (replace `aegisflow_runtime` with your provisioned role):

```sql
GRANT USAGE ON SCHEMA public TO aegisflow_runtime;
GRANT SELECT ON aegis_schema_version TO aegisflow_runtime;
GRANT SELECT, INSERT ON aegis_cases, aegis_events TO aegisflow_runtime;
```

Switch `AEGISFLOW_DATABASE_URL` to the **non-owner runtime** connection, retain the
API auth/source configuration described above, then start the same Uvicorn factory.
When this variable is set, PostgreSQL failure never falls back to SQLite.
Tenant checks are application controls; PostgreSQL RLS is **not implemented**.
Use only synthetic data and localhost. See [ADR-003](docs/adr/003-postgresql-persistence.md).

For the full test suite, set `AEGISFLOW_TEST_DATABASE_URL` to an administrative
connection on a **disposable** PostgreSQL instance, then run `sh tools/check.sh`.
Tests create/drop isolated databases and temporary runtime roles. Without this
variable, nine PostgreSQL tests explicitly skip; that is not a validated database
integration run. CI provides PostgreSQL 18 and runs the complete suite.

PR titles, descriptions, and review/approval text use English; see
[Contributing](CONTRIBUTING.md). Historical Turkish design references are retained.
