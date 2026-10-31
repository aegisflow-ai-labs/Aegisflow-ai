# Yerel doğrulama — 1 Kasım 2026

Ortam: macOS arm64, Python 3.14.5, uv 0.13.4. Bu kayıt yalnız bu dilime aittir.

## Çalıştırılan kontroller

- `sh tools/check.sh`: kilitli dağıtım paketi kurulumu, Ruff lint ve format,
  strict mypy (6 kaynak dosyası), pytest **29 passed**.
- İkinci, boş `/private/tmp/aegisflow-clean-20261101` ortamında
  `UV_PROJECT_ENVIRONMENT=... uv sync --frozen --no-editable --offline`: 42 paket
  kuruldu; bağımlılıklar önce indirilen önbellekten alındı. Kurulum ağdan ilk indirme
  gerektirmediği için çevrimdışı temiz kurulum ayrıca doğrulandı.
- Bu ikinci ortamda CLI ile seed=42 veri üretildi, golden vaka çalıştırıldı ve aynı
  istek tekrarlandı. İki JSON çıktı `cmp` ile birebir aynı. Aynı ortamda 29 test geçti.
- `pip-audit --skip-editable --format cyclonedx-json --output ...`: exit 0,
  **No known vulnerabilities found**. Ağ erişimiyle güncel servis sorgulandı.
  SBOM yerel `work/sbom.json` dosyasında; geçici/ağaç dışı sonuç olarak commit edilmez.
- Gitleaks 8.30.1: `gitleaks dir . --redact --no-banner` ve
  `gitleaks git . --redact --no-banner`, exit 0; bu taramalarda bulgu yok.
- `git diff --check`: exit 0.

## Testlerin doğruladığı davranış

Golden sonuç 25.200 saniye, SLA ihlali; kaynak hashleri ve tüm kanıt bağlantıları;
DB yeniden açılışı; üç sıralı audit olayı; aynı isteğin ve dört eşzamanlı tekrarın
tek etkisi; içerik/kaynak/kimlik değişiminde conflict; eksik SLA/stok/SOP; bayat veya
gelecekteki stok; yinelenen/çelişkili teslimatlar; teslim edilmemiş sipariş; UTC offset
ve DST saat değişimi; tam ve kesirli saniye SLA sınırı; boş, ek, negatif, yanlış tip,
saat dilimsiz ve zaman sırası bozuk girdiler; yanlış tenant ve eksik izin; olmayan
sipariş; audit yazım hatasında rollback; audit UPDATE/DELETE reddi; bozuk referans;
geçersiz sistem saati; CLI hata kodları; şema sapması; rol durumları ve fixture manifesti.

## Doğrulanmamış veya kapsam dışı

İlk uzak CI çalışması [41251344710](https://github.com/aegisflow-ai-labs/Aegisflow-ai/actions/runs/41251344710)
başarılı: Linux üzerinde Python 3.12 ve 3.14 kod/test kontrolleri, bağımlılık taraması,
SBOM yüklemesi ve geçmiş/çalışma ağacı sır taramaları geçti. Ardından CI action
sürümleri Node 24 kullanan SHA'lara sabitlendi ve runner ubuntu-24.04 olarak sabitlendi;
bu son değişikliğin kontrol sonucu PR kontrollerinden ayrıca okunmalıdır.
PostgreSQL migration, OIDC, gerçek kaynak adaptörü, üretim yetkilendirmesi, onaylı
dış işlem, yük/chaos/yedek geri dönüş ve 300 vakalık benchmark uygulanmadı.
Güvenlik taramaları bilinen imza ve veri tabanlarıyla sınırlıdır; açık bulunmaması
sıfır güvenlik açığı anlamına gelmez. İlk entegrasyon 403'ü sonrası yerel gh sorgusuyla
cansukalkan admin yetkisi doğrulandı. Lisans seçimi açık; yerel sentetik dilimi engellemez.

## İkinci dilim — sentetik HTTP API

Yerel `gh api user` başlangıçta cansukalkan döndürdü. Kullanıcının talebiyle
`gh auth switch --user mirackeser` uygulandı ve `gh api user` mirackeser döndürdü.
Git commit kimliği de mirackeser olarak doğrulandı.

`sh tools/check.sh`: 31 test, Ruff lint/format ve strict mypy (7 kaynak dosyası)
geçti. API TestClient gerçek factory/store üzerinden kimliksiz istek, yanlış tenant,
read/investigate izin ayrımı, kanıt/olay okuma, eksik idempotency anahtarı, değişen
istek, gizlenmiş validasyon/DB hataları ve ortamdan başlatmayı doğrular.
Geliştirme kimliği üretme komutu çalıştırıldı; dosyalar 0600 ve work/ altında.
Testler kurulu Starlette'ın desteklediği httpx2 istemcisiyle uyarısız geçti.
Son bağımlılık kümesinde pip-audit exit 0, bilinen açık yok; SBOM work/api-sbom.json.
PostgreSQL, OIDC ve gerçek ağ sunucusuyla yük testi bu dilimde yapılmadı.
Uzak son commit sonuçları PR #1'in güncel kontrollerinden okunmalıdır.

## PostgreSQL persistence slice — 2026-11-01

Local PostgreSQL 18.4 ran on a private Unix socket with TCP disabled. Tests created
and dropped isolated databases and a temporary non-owner runtime role. Full
`tools/check.sh` with AEGISFLOW_TEST_DATABASE_URL completed: **40 passed**, Ruff
lint/format and strict mypy (8 source files) passed. No PostgreSQL test was skipped.
Migration/reopen/version rejection, four concurrent identical requests, conflicting
fingerprints, cross-tenant access/FKs, rollback on audit failure, UPDATE/DELETE/
TRUNCATE rejection, restricted runtime grants, HTTP evidence reads and database
failure responses were exercised. pip-audit reported no known vulnerabilities;
Gitleaks working-tree scan and git diff checks passed. These are scoped test results,
not production security or performance guarantees. The local test server is stopped
after verification. Current remote CI status is available on the PostgreSQL PR.

## PostgreSQL tenant RLS slice — 2026-11-01

Local PostgreSQL 18.4 full suite: **48 tests passed**, no skips; lint, format and
strict typing passed. New acceptance cases include unfiltered case/audit SQL under
a non-owner runtime role, missing context, wrong-tenant inserts, two-tenant same-key
requests, context clearing on commit/rollback of a reused connection, v1 data and
fingerprint preservation, atomic migration-error rollback, and rejection of unsafe
HTTP runtime roles or disabled RLS. Tests deliberately distinguish administrative
connections (which bypass RLS) from restricted runtime connections.
No dependency was added. This is a scoped application/DB boundary test, not an OIDC
implementation, arbitrary-SQL credential isolation, or production security guarantee.

## Source/evidence authorization slice — 2026-11-01

Full local PostgreSQL 18.4 suite: **61 tests passed**, none skipped; Ruff lint/format
and strict mypy (9 source files) passed. Added live revoke/regrant tests across full
case, events, evidence, POST replay and new-key paths; denied requests leave no extra
case/events. Policy corruption/removal/size overflow does not reuse prior grants.
Exact-match tenant/subject/URI grants, legacy dependencies, missing input sources,
no-store responses, schema drift, and clean demo setup/from-environment execution
were tested. Clean setup files have mode 0600 and no token is printed. PostgreSQL
revocation was exercised with restricted runtime credentials and RLS enabled.
No dependency was added; current dependency audit and secret scan results are
reported on the new PR. Older validation records above describe their own snapshots.
