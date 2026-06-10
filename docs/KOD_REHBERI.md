# SentinelAI — Kod Rehberi (Hangi Dosya Ne Yapar)

Bu belge, projeyi bir hocaya/değerlendiriciye sunarken kullanılmak üzere hazırlanmıştır.
Her klasörün ve dosyanın **ne işe yaradığını** sade Türkçe ile, sunum sırasına uygun
biçimde açıklar. Teknik derinlik için ilgili konu dokümanlarına (ör. `AUTH.md`,
`DETECTION.md`) atıf verilmiştir.

> **Tek cümleyle proje:** Ağ trafiği akışlarını alır, CIC-IDS2017 üzerinde eğitilmiş bir
> makine öğrenmesi modeliyle saldırı tespiti yapar ve her uyarıyı beş ajanlı bir iş
> akışından (Tespit → Önceliklendirme → Müdahale → Soruşturma → Raporlama) geçirir.
> **Tüm müdahaleler varsayılan olarak simüledir** — gerçek bir sisteme dokunmaz.

---

## 1. Mimari özet

**Modüler monolit.** Tek bir FastAPI backend, tek React arayüzü, PostgreSQL veritabanı,
Redis (hız sınırlama + WebSocket yayını + görev kuyruğu), bir arq worker ve çevrimdışı bir
ML paketi. İsteğe bağlı, lab-only bir log-okuyucu sensör de vardır.

```
React (TS) arayüz ──REST + WebSocket──> FastAPI backend ──> PostgreSQL
                                              │  ├── Redis (limit + pub/sub + kuyruk)
                                              │  └── arq worker (uzun işler)
ml/ (çevrimdışı eğitim) ──model.joblib──> backend yükler
sensor/ (opsiyonel, lab) ──akış metadatası──> /ingest/flows
```

## 2. Üst düzey klasörler

| Klasör | Ne yapar |
| --- | --- |
| `backend/` | FastAPI uygulaması, ORM modelleri, ajanlar, servisler, testler, Alembic göçleri. |
| `frontend/` | React + TypeScript + Vite kontrol paneli (SOC konsolu). |
| `ml/` | Çevrimdışı eğitim/değerlendirme hattı (CIC-IDS2017). |
| `sensor/` | Opsiyonel canlı akış sensörü (Zeek/Suricata loglarını okur, lab-only). |
| `infra/` | Yardımcı betikler (bootstrap, seed, smoke, yedek), Postgres init, tek-container. |
| `docs/` | Mimari, etik, kalite ve konu bazlı kılavuzlar. |
| Kök | `docker-compose.yml`, `Makefile`, `Dockerfile`, `.env.example`, `PROJECT_ARCHITECTURE.md`. |

---

## 3. Backend (`backend/app/`)

### 3.1 Giriş noktaları
| Dosya | Ne yapar |
| --- | --- |
| `main.py` | FastAPI uygulama fabrikası + yaşam döngüsü (lifespan): ayarları okur, DB/Redis/kuyruk/broadcaster'ı kurar, ajanları kaydeder, modeli yükler, bootstrap admin'i oluşturur, tüm router'ları bağlar. |
| `worker.py` | arq worker ayarları (`WorkerSettings`) — uzun süren işleri çalıştıran ayrı süreç. |

### 3.2 Çekirdek altyapı (`core/`)
| Dosya | Ne yapar |
| --- | --- |
| `config.py` | Tüm uygulama ayarları (pydantic-settings, `SENTINEL_*` env değişkenleri). Güvenli varsayılanlar burada. |
| `db.py` | SQLAlchemy async motor + oturum (session) + `Base`; `ping_db`, `session_scope`. |
| `security.py` | JWT üretme/çözme + API anahtarı + parola hash'leme yardımcıları. |
| `cookies.py` | httpOnly refresh / okunabilir CSRF / access çerezlerinin set/clear mantığı. |
| `csrf.py` | Çift-gönderim (double-submit) CSRF ara katmanı — çerezle kimlik doğrulanan mutasyonları korur. |
| `errors.py` | `AppError` + global hata yakalayıcılar + standart hata zarfı (`{error, request_id}`). |
| `events.py` | Süreç-içi olay dağıtıcısı (ajanlar buna abone olur) + `publish_event`. |
| `broadcast.py` | WebSocket olaylarının worker'lar arası dağıtımı (Redis pub/sub; Redis yoksa yerel). |
| `ws_manager.py` | Aktif WebSocket bağlantılarını yöneten yönetici (broadcast hedefleri). |
| `ratelimit.py` | Redis tabanlı kayan-pencere hız sınırlayıcı (+ bellek/no-op yedekleri). |
| `queue.py` | Görev kuyruğu soyutlaması (arq) — işleri enqueue eder; Redis yoksa no-op. |
| `metrics.py` | Prometheus metrikleri + `MetricsMiddleware` (HTTP/ingest/detection/drift/WS). |
| `tracing.py` | OpenTelemetry izleme (opsiyonel, varsayılan kapalı/no-op). |
| `logging.py` | structlog kurulumu — JSON loglar, istek-id + kullanıcı/rol bağlama. |
| `middleware.py` | Her isteğe `request_id` ekleyen ara katman (`X-Request-ID`). |
| `password_policy.py` | Parola politikası (≥12 karakter, 4 kategoriden 3'ü, kullanıcı adı içermez). |
| `security_headers.py` | Güvenlik başlıkları (CSP, nosniff, frame-deny, HSTS) + CORS doğrulama. |

### 3.3 Veritabanı modelleri (`models/`)
| Dosya | Tablo / amaç |
| --- | --- |
| `network_event.py` | `network_events` — alınan ham akışlar (5'li, `features` JSONB, etiket). |
| `alert.py` | `alerts` — şüpheli akış başına bir uyarı (tahmin, güven, severity, durum, disposition, `archived_at`). |
| `agent_decision.py` | `agent_decisions` — **denetim izi**: her ajan adımı + her analist eylemi (kararlar JSONB). |
| `alert_artifact.py` | `alert_artifacts` — soruşturma paketleri vb. ekler. |
| `response_action.py` | `response_actions` — müdahale aksiyonları; `simulated`/`execution_mode`/rollback; LAB dışı `simulated=TRUE` zorunlu (DB CHECK). |
| `incident_report.py` | `incident_reports` — olay raporları (markdown + JSONB paket; `pdf_path` ayrılmış). |
| `ingestion_job.py` | `ingestion_jobs` — replay/stream alma işleri ve sayaçları. |
| `task.py` | `tasks` — arka plan işleri (durum/ilerleme/sonuç). |
| `user.py` | `users` — kullanıcı, rol, parola hash, `token_version`, hesap kilidi alanları. |
| `auth_session.py` | `auth_sessions` — refresh oturumları (hash'li) — döndürme + iptal için. |
| `model_version.py` | `model_versions` — model kayıt defteri; tek aktif sürüm (kısmi tekil indeks). |
| `model_drift.py` | `model_drift_snapshots` — PSI drift + güven istatistikleri + analist geri-bildirim proxy'si. |
| `model_activation.py` | `model_activations` — aktivasyon/geri-alma denetim kaydı (kim, hangi sürüm, neden). |
| `model_shadow_eval.py` | `model_shadow_evals` — aday vs aktif model karşılaştırması (uyum oranı, metrikler). |
| `enums.py` | Tüm enum'lar (Role, Severity, AlertStatus, Disposition, TaskKind, DriftStatus, …). |
| `mixins.py` | Ortak sütun karışımları (`created_at`/`updated_at`). |

### 3.4 Şemalar (`schemas/`)
Pydantic DTO'ları — API'nin giriş/çıkış sözleşmeleri. Kaynak başına bir dosya:
`alert`, `auth`, `common`, `detection`, `ingestion`, `investigation`, `model_registry`,
`reporting`, `response`, `task`, `telemetry`. (Frontend tipleri bunlardan OpenAPI ile üretilir.)

### 3.5 API katmanı (`api/`)
| Dosya | Ne yapar |
| --- | --- |
| `deps.py` | Ortak bağımlılıklar: DB oturumu, JWT/kimlik, **RBAC** (`enforce_rbac`), hız limiti, `require_admin`. |
| `pagination.py` | `X-Total-Count` başlığı + `count_for` yardımcıları (gerçek sayfalama için). |
| `routers/auth.py` | `/auth/*` — login, refresh, logout, logout-all, me, kullanıcı oluştur/pasifleştir. |
| `routers/alerts.py` | `/alerts/*` — listele/filtrele, detay, triage, disposition, investigate, report, close. |
| `routers/response.py` | `/response/*` — listele, bekleyen kuyruk, approve/reject/rollback. |
| `routers/reports.py` | `/reports/*` — liste, paket, markdown, günlük özet üret. |
| `routers/ingest.py` | `/ingest/*` — CSV upload/replay, tek akış, sensör batch (`/flows`), işler, sensör durumu. |
| `routers/detection.py` | `/detection/*` — model bilgisi, predict, event/batch/run tespiti, drift. |
| `routers/dashboard.py` | `/dashboard/overview` — panodaki tüm KPI/agregasyonları tek istekte verir. |
| `routers/models.py` | `/models/*` — model sürümleri, aktivasyon/geri-alma (ADMIN), shadow değerlendirme. |
| `routers/tasks.py` | `/tasks/*` — arka plan işi enqueue + durum sorgulama. |
| `routers/stream.py` | `/stream` — token-doğrulamalı WebSocket olay akışı. |
| `routers/telemetry.py` | `/telemetry/client-error` — frontend ErrorBoundary hatalarını alır (public, rate-limited). |
| `routers/health.py` | `/`, `/health`, `/readyz` (DB/Redis/kuyruk/model), `/metrics`. |

### 3.6 Ajanlar (`agents/`) — beş aşamalı iş akışı
| Dosya | Ne yapar |
| --- | --- |
| `base.py` | Ajanlar için ortak temel sınıf. |
| `runtime.py` | `register_agents()` — ajanları olay otobüsüne (event bus) bağlar (lifespan'de çağrılır). |
| `detection.py` | **Tespit:** modeli çalıştırır, eşiği geçen şüpheli akışlardan `Alert` üretir. |
| `triage.py` | **Önceliklendirme:** severity + öncelik skoru atar. |
| `response.py` | **Müdahale:** severity'ye göre aksiyon önerir (simüle); LAB aksiyonları onay ister. |
| `investigation.py` | **Soruşturma:** ilişkili uyarı/olay + feature katkısı paketini üretir. |
| `reporting.py` | **Raporlama:** olay raporu + günlük özet (markdown) üretir. |

### 3.7 Servisler (`services/`) — iş mantığı
| Dosya | Ne yapar |
| --- | --- |
| `detection_service.py` | Çıkarım mantığı: feature hizalama, **feature coverage** kontrolü, alert/karar kaydı. |
| `model_registry.py` | Bellek-içi model paketi (bundle) yükleme/önbellek; `load_bundle`, `load_from_dir`. |
| `model_lifecycle_service.py` | Model sürüm listesi, aktivasyon/geri-alma (denetimli), shadow değerlendirme. |
| `drift_service.py` | PSI drift hesabı + analist-geri-bildirim kalite proxy'si + snapshot kaydı. |
| `triage_service.py` / `triage_rules.py` | Severity/öncelik hesabı ve kuralları. |
| `response_service.py` / `response_rules.py` | Aksiyon önerisi, onay/ret/geri-alma; öneri kuralları. |
| `response_executors/` | Aksiyon yürütücüleri: `simulated` (varsayılan), `mock_lab`, `nftables_lab`, `base`. |
| `investigation_service.py` | Soruşturma paketi oluşturma (ilişkili kanıt + feature önemleri). |
| `reporting_service.py` / `reporting_renderer.py` | Rapor verisini üretir ve markdown'a render eder. |
| `ingestion_service.py` | CSV/akış alımı, doğrulama, iş kaydı. |
| `task_service.py` | Görev (task) yaşam döngüsü: oluştur, çalışıyor, başarılı/başarısız. |
| `retention_service.py` | Veri saklama politikası: eski olayları sil / uyarı-rapor arşivle (varsayılan kapalı, dry-run). |
| `session_service.py` | Refresh oturumu oluşturma/döndürme/iptal. |
| `user_service.py` | Kullanıcı oluşturma, aktif kullanıcı sorgu, bootstrap admin, hesap kilidi. |

### 3.8 Diğer backend
| Yol | Ne yapar |
| --- | --- |
| `ingestion/feature_schema.py` | CIC-IDS2017 kolon adı normalizasyonu (alias + snake_case). |
| `ingestion/parser.py` | CSV satırını kanonik feature sözlüğüne çevirir. |
| `ingestion/csv_loader.py` | CSV dosyasını okur/yükler. |
| `tasks/jobs.py` | arq iş çekirdekleri: detection, rapor, günlük özet, drift, retention cleanup, retrain. |
| `scripts/dump_openapi.py` | Deterministik `openapi.json` üretir (frontend tip üretimi için). |
| `scripts/retention.py` | Komut satırından saklama politikası (dry-run / `--apply`). |

### 3.9 Göçler (`migrations/versions/`) — şema tarihçesi
`0001` ilk şema · `0002` event.detected_at · `0003` triage + disposition · `0004` response
aksiyon tipleri · `0005` kullanıcılar + roller · `0006` drift snapshot'ları · `0007` lab
müdahale kontrolleri (simulated-unless-lab CHECK) · `0008` auth oturumları · `0009` hesap
kilidi · `0010` görev kuyruğu tablosu · `0011` soft-delete (`archived_at`) · `0012` model
yaşam döngüsü (drift feedback + activation + shadow). Yükseltme **ve** geri-alma entegrasyon
testlerinde doğrulanır.

---

## 4. ML paketi (`ml/`)

| Dosya | Ne yapar |
| --- | --- |
| `train.py` | Eğitim CLI'ı: veri → temizle → eğit → metrik → artefakt yaz (`--profile/--search/--calibrate`). |
| `evaluate.py` | Kaydedilmiş modeli etiketli veri üzerinde değerlendirir. |
| `synthetic.py` | Sentetik CIC-IDS2017 benzeri veri + örnek CSV üretici (`--sample`). |
| `profiles.py` | Veri seti profilleri (ör. `cic2017` etiket eşleme). |
| `hpo.py` | Hiperparametre arama (random/grid) — opsiyonel. |
| `calibration.py` | Olasılık kalibrasyonu (sigmoid/isotonic) + Brier skoru + güvenilirlik eğrisi. |
| `baseline.py` | Drift için eğitim-baz dağılımı (PSI bin'leri) — `metadata.baseline`. |
| `pipeline.py` | sklearn Pipeline fabrikası (imputer + sınıflandırıcı). |
| `preprocess.py` | Temizleme + feature seçimi + X/y oluşturma. |
| `feature_list.py` | Kanonik kolon normalizasyonu + hariç tutulan kolonlar. |
| `data_loader.py` | CSV (dosya/dizin) yükleme. |
| `metrics.py` | precision/recall/F1 + karışıklık matrisi. |
| `artifacts.py` | Sürümlü artefakt kaydet/yükle + `latest/` aynası. |

> Artefaktlar: `ml/artifacts/<sürüm>/{model.joblib, metadata.json, metrics.json,
> confusion_matrix.json}`. `metadata.json`: sınıflar, feature_order, baseline, calibration, hpo,
> expected_feature_coverage. (Ham veri ve artefaktlar git'e konmaz.)

---

## 5. Frontend (`frontend/src/`)

### 5.1 Giriş + sağlayıcılar (provider)
| Dosya | Ne yapar |
| --- | --- |
| `main.tsx` | Uygulama kökü: ErrorBoundary + Query + Router + Toast + Confirm + Auth + Stream sağlayıcıları. |
| `App.tsx` | Rota tablosu (login + korumalı sayfalar + AppShell). |

### 5.2 `lib/` — veri/yardımcı katman
| Dosya | Ne yapar |
| --- | --- |
| `api/client.ts` | fetch sarmalayıcı: temel URL, 401'de refresh, `request`/`requestList` (X-Total-Count), `ApiError`. |
| `api/*.ts` | Kaynak başına tipli API: `alerts, auth, dashboard, detection, health, ingestion, investigation, models, reports, response, tasks, telemetry`. |
| `api/schema.d.ts` | OpenAPI'den **otomatik üretilen** TypeScript tipleri. |
| `api/errors.ts` | Hata mesajı çıkarma + 4xx'te yeniden-deneme yok kuralı. |
| `auth/AuthContext.tsx` | Oturum durumu: login/logout, `hasRole`, /me ile oturum geri yükleme. |
| `auth/token.ts` | Erişim token'ını **yalnız bellekte** tutar (localStorage yok). |
| `auth/passwordPolicy.ts` | İstemci tarafı parola politikası kontrolü. |
| `stream/StreamProvider.tsx` | WebSocket bağlamı + `useLiveInterval`/`useStreamStatus`. |
| `stream/invalidate.ts` | Gelen olayı ilgili TanStack Query anahtarlarına eşler (otomatik yenileme). |
| `stream/types.ts` | Olay tipleri. |
| `ws.ts` | Düşük seviye WebSocket bağlantı yardımcısı. |
| `toast/ToastContext.tsx` | Global toast (success/error/info/warning) sağlayıcısı + `useToast`. |
| `confirm/ConfirmProvider.tsx` | Söz (promise) tabanlı onay modalı: `useConfirm` (gerekçe + "CONFIRM yaz"). |
| `types.ts` | Elle yazılmış DTO tipleri (kaynak: üretilen `schema.d.ts`). |
| `drift.ts` / `response.ts` / `readiness.ts` / `format.ts` / `cn.ts` | Drift/yanıt/hazırlık yardımcıları, biçimlendirme, sınıf birleştirme. |

### 5.3 Bileşenler (`components/`)
| Grup | Ne yapar |
| --- | --- |
| `ui/` | Tasarım primitive'leri: `Button, Card, Badge, Table, Select, Spinner, Modal, Toaster, PageHeader, EmptyState, ErrorState`. |
| `layout/` | `AppShell` (kenar çubuğu + üst bar + içerik), `Sidebar` (menü), `Topbar` (sağlık pilleri + çıkış). |
| `charts/` | Recharts grafikleri: zaman serisi, severity donut, top saldırı türleri (+ ekran-okuyucu özetleri). |
| `alerts/` | Uyarı detayı kartları: aksiyon çubuğu, tespit, triage, soruşturma, müdahale tablosu, karar zinciri, ilişkili kanıt. |
| `dashboard/ModelHealthPanel.tsx` | Drift + analist-geri-bildirim kalite paneli (+ "Run drift check"). |
| `models/ModelVersionsPanel.tsx` | Model sürüm listesi + aktivasyon/geri-alma (ADMIN, onay modallı). |
| `tasks/TasksPanel.tsx` | Arka plan işleri paneli (canlı durum). |
| `ErrorBoundary.tsx` | Beklenmeyen hatada güvenli fallback (Reload / Dashboard'a dön). |
| `*Pill.tsx`, `StatCard.tsx`, `MarkdownView.tsx`, `icons.tsx` | Durum/severity rozetleri, KPI kartı, markdown render, ikonlar. |

### 5.4 Sayfalar (`pages/`)
| Sayfa | Ne gösterir |
| --- | --- |
| `LoginPage.tsx` | Giriş formu (kullanıcı/parola), hata uyarısı. |
| `DashboardPage.tsx` | SOC genel bakış: KPI'lar, model sağlığı, grafikler, en öncelikli uyarılar, model kartı. |
| `AlertsPage.tsx` | Filtrelenebilir uyarı listesi (URL-tabanlı) + gerçek sayfalama. |
| `AlertDetailPage.tsx` | Tek uyarı: aksiyon çubuğu, tespit/triage/soruşturma kartları, müdahale tablosu, karar zinciri. |
| `ResponseCenterPage.tsx` | Bekleyen onay kuyruğu (gerçek toplam) + eylem geçmişi. |
| `ReportsPage.tsx` | Rapor listesi + markdown görüntüleyici (kopyala/indir) + günlük özet. |
| `IngestionPage.tsx` | 3 adımlı akış: CSV yükle/replay → tespit → uyarılara geç; iş tablosu. |
| `SystemPage.tsx` | Hazırlık (DB/Redis/worker/model) + model sürümleri + arka plan işleri + gözlemlenebilirlik. |
| `AdminUsersPage.tsx` | (ADMIN) Kullanıcı oluşturma (canlı parola politikası). |

---

## 6. Sensör (`sensor/sentinelai_sensor/`) — opsiyonel, lab-only

| Dosya | Ne yapar |
| --- | --- |
| `__main__.py` | Sensör giriş noktası (`python -m sentinelai_sensor`). |
| `config.py` | Sensör ayarları (etkin mi, izinli CIDR'ler, API token/URL). |
| `runner.py` | Log'u takip eder, akışları toplu olarak `/ingest/flows`'a gönderir. |
| `parsers.py` | Zeek `conn.log` / Suricata `eve.json` ayrıştırma (yalnız metadata). |
| `safety.py` | Güvenlik kapıları: kapalıysa/izinsiz CIDR ise reddet; payload asla okunmaz. |
| `client.py` | Backend'e kimlik doğrulamalı HTTP istemcisi. |

> **Varsayılan kapalı.** `SENTINEL_SENSOR_ENABLED=true` + izinli CIDR olmadan başlamaz; NIC'e
> bağlanmaz, paket yakalamaz, payload saklamaz. Detay: `LIVE_SENSOR.md`.

---

## 7. Altyapı (`infra/`) ve kök dosyalar

| Yol | Ne yapar |
| --- | --- |
| `scripts/bootstrap.sh` | Tek komut kurulum: compose ayağa kaldır → sağlık bekle → model eğit/yerleştir → hazır. |
| `scripts/demo_seed.sh` | Demo verisi: örnek replay + tespit + disposition + rapor + günlük özet. |
| `scripts/smoke_demo.sh` | 11 adımlı uçtan uca duman testi (auth dahil). |
| `scripts/e2e.sh` | Tam kapı: ayağa kaldır → model → smoke → `down -v`. |
| `scripts/backup_db.sh` / `restore_db.sh` | `pg_dump` / `psql` ile yedek al / geri yükle. |
| `scripts/run_single_container.sh` | Her şeyi tek imajda çalıştırma (basit demo yolu). |
| `scripts/seed.sh` / `wait_for_db.sh` | Model yeniden eğit / DB hazır bekle. |
| `postgres/init.sql` | İlk DB kurulumu. |
| `single-container/` | Tek-container giriş betiği + SPA sunucusu. |
| `docker-compose.yml` (kök) | Çoklu-servis: postgres, redis, backend, worker, frontend (+ opsiyonel sensor). |
| `Makefile` (kök) | Kısayollar: `up/down/bootstrap/smoke/e2e/test/backup-db/openapi/...` (`make help`). |
| `Dockerfile` (kök) | Tek-container imaj derlemesi (frontend build + backend). |
| `.env.example` | Tüm ortam değişkenlerinin güvenli varsayılanları. |

---

## 8. Dokümanlar (`docs/`) — hangi belge ne anlatır

`PROJECT_ARCHITECTURE.md` (kök) tüm tasarım · `DEPLOYMENT.md` dağıtım runbook'u ·
`DEPLOYMENT_SECURITY.md` TLS/başlık/CORS/çerez güvenliği · `AUTH.md` kimlik/çerez/CSRF/RBAC ·
`ETHICS.md` etik/simüle/lab kuralları · `API.md` uçtan uca API · `DETECTION.md` tespit/drift ·
`TRIAGE.md`/`RESPONSE.md`/`INVESTIGATION.md`/`REPORTING.md` ajan kılavuzları ·
`MODEL_DRIFT.md`/`MODEL_LIFECYCLE.md`/`ML_TRAINING.md` ML konuları ·
`DATA_RETENTION.md` saklama · `RATE_LIMITING.md` hız limiti · `TASK_QUEUE.md` kuyruk ·
`LIVE_SENSOR.md`/`LAB_RESPONSE.md` lab özellikleri · `BACKUP_DR.md` yedek/kurtarma ·
`INGESTION.md` CSV şeması · `DATASET.md` veri seti · `QUALITY.md` test envanteri/CI ·
`DEMO_GUIDE.md`/`DEMO_SCRIPT.md` sunum betikleri · **`KOD_REHBERI.md` (bu belge).**

---

## 9. Testler

| Yer | Ne kapsar |
| --- | --- |
| `backend/tests/` | Hızlı, DB'siz birim testleri (servis mantığı, RBAC, şemalar). |
| `backend/tests/integration/` | Gerçek PostgreSQL (testcontainers): göç yükselt/geri-al, CHECK/FK/tekil kısıtları, model yaşam döngüsü, retention, drift feedback. |
| `frontend/src/**/*.test.tsx` | Birim + bileşen + sayfa render testleri (Modal/Confirm/sayfalar). |
| `frontend/e2e/` | Playwright uçtan uca (login, ingest→tespit→uyarı, approve, LAB modal). |
| `ml/tests/` | Feature parity, profil, HPO, kalibrasyon. |
| `infra/scripts/smoke_demo.sh` | Çalışan yığına karşı uçtan uca duman testi. |

---

## 10. Uçtan uca akış (sunumda anlatım)

```
CSV/sensör akışı → ingestion (parse + network_events)
   → detection (model predict_proba; eşik üstü → Alert + DETECTION kararı)
   → triage (severity/öncelik)  → response (öneri; HIGH/CRITICAL otomatik simüle, diğerleri analist onayı)
   → (analist approve/reject; LAB ise geri-alınabilir)  → investigation (kanıt paketi)
   → reporting (markdown rapor)  → analist CLOSE
Her commit sonrası olay → Redis pub/sub → tüm worker'lar → WebSocket → arayüz canlı yenilenir.
Her adım agent_decisions'a denetim olarak yazılır.
```

## 11. Güvenlik & etik (özet)

- **Müdahale = simüle (varsayılan).** LAB dışı `simulated=FALSE` satır **yapısal olarak imkânsız**
  (Postgres CHECK `ck_response_actions_simulated_unless_lab`).
- **Lab müdahale, canlı sensör, veri saklama** → hepsi **varsayılan kapalı** ve korumalı.
- **Auth zorunlu** (login/refresh/telemetry/health hariç); RBAC `VIEWER < ANALYST < ADMIN`.
- **Sırlar üretimde fail-closed**; **varsayılan kullanıcı yok**; **token yalnız bellekte**.
- **Denetlenebilir:** `agent_decisions` (ajan + analist), `model_activations` (model değişimi).
