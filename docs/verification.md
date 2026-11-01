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

## English README, Apache-2.0 and HTTP input hardening — 2026-11-01

The project owner delegated license selection; Apache-2.0 was prepared with the
unchanged official text, project NOTICE, package metadata and synthetic fixture
manifest. Maintainer review must confirm licensing authority for existing work.
README was rewritten in English and its repository-relative links were verified.

Full suite with PostgreSQL 18.4: **78 tests passed**, none skipped, in both the working
venv and a separately created clean environment. Ruff lint/format and strict mypy
(10 source files) passed. Added input-boundary tests cover actual streamed bytes,
declared/mismatched/duplicate/invalid lengths, exact limits, zero-padded large length
headers, body-read deadline, disconnect and lifespan handling, plus actual HTTP API
rejection before persistence. Repeated demo setup is tested for non-overwriting and
absence of partial credentials. New credential/header files are mode 0600.

The README CLI/replay and header-file curl examples were run with fresh temporary
files against a real localhost Uvicorn process and passed. Both temporary servers
are stopped after checks. A wheel was built and LICENSE/NOTICE bytes, Apache-2.0
License-Expression and README metadata inclusion were verified. No extra third-party
package was added: AnyIO was promoted from transitive to explicit dependency without
changing its locked version.

pip-audit reported no known vulnerabilities; Gitleaks working-tree and commit-history
scans found no leaks; git diff checks passed. GitHub secret scanning and push
protection were enabled and read back, private vulnerability reporting read back as
enabled, and dependency vulnerability alerts returned HTTP 204 (enabled). At that
snapshot open dependency/secret alerts were empty; newly enabled scans may still be
processing. Main review/status protection remains enabled. This is scoped validation,
not an independent comprehensive security audit or a production-security guarantee.

## Signed access-token foundation — 2026-11-01

Full local suite against PostgreSQL 18.4: **119 tests passed**, none skipped; Ruff
lint/format and strict mypy (11 source files) passed. Required claims, exact time
boundaries, wrong issuer/audience, unsigned/HMAC/tampered tokens, ID-token type,
untrusted key/URL/deeply nested headers, weak/private/duplicate keys, principal/JTI removal,
key rotation and malformed/missing configuration were exercised. Server-side scope
mapping ignores token tenant/admin claims. The JWT HTTP mode was tested with SQLite
and restricted PostgreSQL/RLS, including replay and subsequent subject revocation.
Identity and key JSON Schemas are exported and checked for drift.

The one-command disposable demo was run against real localhost Uvicorn/curl:
successful signed request, identical replay and live subject revocation (401) all
passed; captured output did not contain the Bearer token. The temporary demo server
was stopped. Demo files have mode 0600 and no private signing key is persisted.

pip-audit reported no known vulnerabilities for the new PyJWT/cryptography dependency
set; Gitleaks working-tree scan and diff checks passed. This is a narrow local JWT
resource-server verifier, not completed OIDC login or production identity acceptance.
Docker Desktop exists on the workstation but the Docker daemon socket is absent,
so no live Keycloak realm/login was configured or tested. The current main README
was confirmed English after PR #6 merged. Current remote checks belong to the new PR.


## Local Keycloak browser login — 2026-11-01

Full local PostgreSQL 18 suite: **140 tests passed**, none skipped, both in the
working environment and a freshly created environment installed from the frozen lock.
Ruff lint/format and strict mypy (13 source files) passed. Twenty-one added tests
cover Keycloak access/ID token separation, nonce/subject/audience/time/hash validation,
PKCE challenge, browser-bound single-use state, expiry/capacity, CSRF/Origin, cookie
flags, source/principal revocation, unavailable policy, idempotent browser replay,
host restrictions and private setup preservation. Existing RFC 9068 tests still pass.

Real Docker Keycloak 26.8.1 and Google Chrome were exercised through the committed
browser checker: password login on the local provider, opaque HttpOnly/SameSite
session, synthetic investigation (25,200 seconds, SLA breach, five snapshots),
application logout and provider confirmation. Keyboard entry and no horizontal
mobile overflow were checked; 1280px desktop and 375px mobile screenshots were
visually inspected. This is limited UI verification, not full WCAG certification.
The test exposed and corrected a focus-induced layout shift, Chrome's null Origin
under no-referrer on normal form pages, and CSP-blocked cross-origin logout redirects.
The callback retains no-referrer; normal pages use same-origin; logout now displays
an explicit provider link after ending the application session.

pip-audit reported no known vulnerabilities in the locked environment. Gitleaks
reported no leaks in the source candidate snapshot (tracked plus nonignored new
files) or commit history. A full local directory scan correctly found generated
credentials in ignored work/ demo files and an older scratch PR description; these
are not tracked and were not copied into source, CI artifacts or this record. No
blanket secret-scan suppression was added. The Docker import volume is also private
local test state. These findings are not evidence of exposed production credentials.

An additional CI job runs the real Keycloak/browser flow; remote check results are
recorded on the PR. Production identity lifecycle, TLS/session isolation, provider
revocation propagation, automatic key refresh and operational limits remain open.
Role counts remain 36 registered, one implemented/tested subset (A21), one active in
the golden case and zero model calls. No external business actions were introduced.


## Bounded local identity lifecycle — 2026-11-01

Full suite with a disposable Docker PostgreSQL 18 instance: **160 tests passed**,
none skipped, in both the working venv and a fresh frozen-lock environment. Ruff
lint/format and strict mypy (13 source files) passed. Twenty additional tests cover
exact key-cache expiry, rotation/removal, malformed/private/weak/duplicate keys,
concurrent refresh, failed-fetch cooldown/recovery, unknown-kid fetch suppression,
generic HTTP 503, explicit key-source selection, startup failure, persisted cutoff
boundaries and browser-session invalidation. Operator tests verify grant preservation,
monotonic cutoff under clock rollback, private atomic replacement and write failures.
The exported IdentityPolicy schema was regenerated and its drift test passes.

The committed checker passed against real Docker Keycloak 26.8.1 and Google Chrome:
login and source-linked result, operator revocation of the active session, immediate
401 on its next API request, successful subsequent SSO login with a different opaque
cookie, rejection of the old cookie, application logout and provider confirmation.
The same check is part of the existing required browser-login CI job. No Keycloak
administration-console rotation was performed; RSA rotation/removal/failure and
cache-time boundaries use controlled test providers. The browser uses the real
provider's fixed certificate endpoint. This distinction is intentional.

No dependency was added or upgraded. pip-audit reported no known vulnerabilities.
Gitleaks source-candidate and history scans found no leaks; generated ignored local
credentials were excluded from the source snapshot as explained in the prior record.
The operator tool and its advisory lock currently target macOS/Linux. There is no
remote administration endpoint, full administrator audit trail or provider-side
instant logout propagation. A fresh key cache can remain usable up to 60 seconds;
a failed refresh cannot use expired keys. Local HTTP/session limitations remain.

Role counts and deterministic findings are unchanged: 36 registered roles, one
implemented/tested A21 subset, one active golden-case role, zero model calls and no
external business actions. Production identity acceptance is a separate deployment
gate; the next pilot slice is bounded task routing and deterministic budgets.
