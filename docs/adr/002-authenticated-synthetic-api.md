# ADR-002 — Sentetik API ve sunucu taraflı kapsam

Durum: kabul edildi, 1 Kasım 2026.

İkinci dilim ilk olarak HTTP güven sınırını ekler. PostgreSQL migration'ını aynı
değişikliğe katmak yerine ayrı dilimde gerçek DB testleriyle uygulayacağız. SQLite
kalıcılığı ve domain hesapları korunur; API aynı Store yetki kontrollerini kullanır.

FastAPI, POST /v1/cases ve vaka/olay/kanıt GET uçlarını sunar. İşlem senkrondur;
POST 201 döner (PDF'deki asenkron 202 sözleşmesi henüz uygulanmaz). Yeniden teslimde
aynı gövde döner. Idempotency-Key zorunlu, tenant ve subject istemci gövdesinden
alınmaz. Kaynaklar yalnız sunucu yapılandırmasından seçilir. Aynı tenant'taki read
izni tüm vakaları ve kanıtları okur; vaka bazlı ACL ve kaynak revocation planlıdır.
Kanıt okuması her seferinde güncel sunucu kapsamını yeniden kontrol eder.

Yalnız yerel sentetik kullanım için Bearer anahtarları SHA-256 kayıtlarıyla eşlenir.
Anahtar üretim aracı 32 rastgele bayt kullanır. Sabit/parolasız kimlik yoktur;
kimlik dosyası olmadan sunucu başlamaz. İzinler ve tenant sunucuda tutulur.
Bu OIDC, JWT, süreli oturum veya üretim kimlik çözümü değildir. Anahtar iptali/değişimi
sunucu yapılandırması değiştirilip süreç yeniden başlatılarak uygulanır. HTTPS,
rate limiting ve body boyutu sınırı henüz API katmanında uygulanmadı. Bu yüzden
localhost dışına veya gerçek veriyle açılmaz. Uvicorn access log kapalı çalıştırılır;
uygulama hataları token, kaynak gövdesi ve DB yolunu yanıt içinde yansıtmaz.

A02 rolünün PDF'deki JWT sözleşmesi tamamlanmadığı için rol sayıları değiştirilmez.
POST dış iş sistemine yazmaz; yerel vaka kaydını oluşturur. Onaylı işlem uçları yoktur.
