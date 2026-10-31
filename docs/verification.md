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

GitHub Actions henüz uzak sunucuda çalıştırılmadı. Python 3.12 yerel çalıştırılmadı;
CI matrisi tanımlıdır. Pipeline'ın Linux çalışması henüz kanıtlanmadı.
PostgreSQL migration, OIDC, gerçek kaynak adaptörü, üretim yetkilendirmesi, onaylı
dış işlem, yük/chaos/yedek geri dönüş ve 300 vakalık benchmark uygulanmadı.
Güvenlik taramaları bilinen imza ve veri tabanlarıyla sınırlıdır; açık bulunmaması
sıfır güvenlik açığı anlamına gelmez. cansukalkan erişimi entegrasyon 403'ü nedeniyle
doğrulanamadı. Lisans seçimi açık; bu konular yerel sentetik dilimi engellemez.
