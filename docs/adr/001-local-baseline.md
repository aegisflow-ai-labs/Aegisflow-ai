# ADR-001 — Yerel deterministik baseline

Durum: kabul edildi, 2026-11-01.

Başlangıç deposunda yalnız README bulunduğu için minimum modüler Python paketi
seçildi. Pydantic kapalı ve sürümlü sözleşmeleri, standart sqlite3 yerel kalıcılığı
sağlar. Harici veri ve LLM bağımlılığı yoktur. uv.lock çalışma ve test bağımlılıklarını
sabitler. Python >=3.12; ilk yerel doğrulama 3.14.5 ile yapılır.

PDF'nin FastAPI/SQLAlchemy/PostgreSQL önerisi ilk CLI dilimi için ertelendi.
Gerekçe: salt okunur kaynakla tek süreç/tek makine baseline'ını dış servis kurmadan
tekrar üretmek ve iş kurallarını önce sınamak. Bu seçim PostgreSQL davranışının,
OIDC'nin, RLS'nin, ölçeklenmenin veya üretim kabulünün doğrulandığı anlamına gelmez.
Sonraki API dilimi öncesi PostgreSQL adaptörü ve gerçek DB testleri gereklidir.

`Store.run` işlem sınırıdır: yetki → kaynak kapsamı → BEGIN IMMEDIATE → tekrar
kontrolü → hesap → vaka/olay ekleme → kayıt sonrası okuma doğrulaması → commit.
`cases` JSON belgesi vaka, görev, iddia ve kanıt snapshotlarını birlikte saklar.
Olaylar ayrı append-only tabloda revision ile sıralanır. `PRAGMA user_version=1`
boş DB kurulumudur; başka sürüm reddedilir. Henüz yükseltme migration'ı yoktur.

İstek parmak izi kimlik, UTC inceleme zamanı ve tüm kaynak paketine bağlıdır.
Aynı anahtarla farklı kaynak/özne/istek 409 anlamındaki sabit hata koduyla reddedilir.
Dış sistem için idempotent yürütme veya exactly-once garantisi verilmez.
Vaka ID, trace ID ve kayıt saati çalıştırmaya özgüdür; domain sonuçları sabit veri ve
inceleme zamanında yeniden üretilebilir. Testlerde saat enjekte edilir.

SLA: teslim edilmişse teslimat, edilmemişse `as_of` kullanılır; gelecekteki teslimat
hesaba katılmaz. Tam teslimat olayı varsayılır; kısmi sevkiyat desteklenmez. Aynı
olayın aynı içeriği tekilleştirilir; farklı içerik veya birden çok teslimat zamanı
çelişkidir. Stok yaşı [0,86400] saniye aralığında olmalıdır. SOP yalnız kaynak kuralı
olarak raporlanır; eskalasyon görevi açılmaz, kök neden çıkarılmaz.

## Güven sınırları

CLI yalnız `demo/local-demo` kapsamıyla sentetik dosya okur; Scope nesnesi kimlik
doğrulama değildir. Kütüphane çağıranı güvenilirdir ve kapsamı oluşturur. Ağ API'si
bu yapıyı doğrudan sunamaz; sunucu kimlik doğrulaması eklenmelidir. Salt read-only
kaynak dosyasından yeni yetki çıkarılmaz. Kaynak boyutu CLI'da 1 MB ile sınırlıdır.
Audit payload'ı yalnız referans taşır; hata çıktısı girdi içeriğini yansıtmaz.
SQLite dosyasının sahibi tetikleyicileri/veriyi değiştirebilir. Ayrı audit deposu,
şifreleme, saklama/silme politikası, imzalı mühür ve işletim yetki ayrımı planlıdır.
`COMPLETED` yalnız yerel araştırma tamamlandı demektir, dış işlem başarısı değildir.

## Geliştirme kurulumu

Yerel Python ortamında editable .pth yolu işlenmedi; dağıtım paketi kurulumu çalıştı.
Bu nedenle belgelenen komut `uv sync --frozen --no-editable --reinstall-package aegisflow-ai`.
Kod değiştikten sonra bu komut yeniden çalıştırılır; eski kurulu paketi test etmemek
için `tools/check.sh` bunu her seferinde uygular. Temiz kurulum ayrıca izole ortamda sınanır.
