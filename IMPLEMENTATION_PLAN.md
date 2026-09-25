# Agentic FinOps Gateway — plan implementacji

Plan wykonawczy do specyfikacji [`llm-finops-gateway-implementation-guide.md`](./llm-finops-gateway-implementation-guide.md).
Ma być krótkim źródłem kontekstu dla kolejnych sesji implementacyjnych. Szczegóły produktu pozostają w specyfikacji; tutaj są decyzje, kolejność prac, kontrakty i kryteria odbioru.

## 1. Zakres i zasady

### Cel MVP

Udostępnić jeden endpoint zgodny z OpenAI, zoptymalizowany pod ruch agentowy. Stanowy FastAPI Agent Gateway przed LiteLLM ma przycinać bezpieczne fragmenty kontekstu, wykrywać pętle wywołań narzędzi, obsługiwać exact i semantic cache, egzekwować budżet oraz wybierać politykę free-first. LiteLLM pozostaje bezstanowym adapterem protokołów i wykonawcą retry/fallback do providerów. Każda optymalizacja ma być mierzalna w ledgerze i widoczna w dashboardzie Angular.

### Kolejność priorytetów

1. Bezpieczeństwo transformacji promptu i poprawność odpowiedzi.
2. Niezawodność, ochrona przed pętlami i poprawność routingu.
3. Obserwowalność oraz możliwość wyjaśnienia oszczędności i decyzji.
4. Egzekwowanie budżetów bez wyścigów i sierocych rezerwacji.
5. Cache i ergonomia dashboardu.

### Poza MVP

RAG, automatyczne streszczanie rozmów, trial-aware scoring, automatyczna ocena jakości, wielostopniowa eskalacja jakościowa, batching, Kubernetes, lokalne modele, rozbudowany RBAC i zewnętrzny secrets manager. Trimming deterministyczny i semantic cache o ograniczonej kwalifikacji należą do MVP; generatywne podsumowania pozostają poza MVP.

## 2. Decyzje architektoniczne

### Przepływ danych

```text
client
  -> Caddy /v1/*
  -> FastAPI Agent Gateway (auth context, trimming, loop protection,
                            exact/semantic cache, budget lease, routing policy)
  -> LiteLLM Proxy (provider adapters, retry, fallback, usage dla virtual keys)
  -> provider

admin browser
  -> Caddy /api/*
  -> FastAPI Agent Gateway / Control API
  -> PostgreSQL / Redis
```

- FastAPI Agent Gateway jest jedynym publicznym data plane dla `/v1/*` i jednocześnie wystawia Control API pod `/api/*` (moduły pozostają rozdzielone w kodzie).
- Caddy kończy TLS, stosuje limity sieciowe/rozmiaru i routuje `/v1/*` oraz `/api/*`; limity per tenant/key pozostają w Gatewayu.
- LiteLLM nie jest wystawiony publicznie. Jest bezstanowym downstreamem odpowiedzialnym za translację protokołów, provider adapters, retry, fallback, circuit breakers oraz raportowanie usage dla virtual keys.
- Policy Engine jest czystym pakietem domenowym używanym bezpośrednio przez Agent Gateway. Nie jest ładowany jako hook LiteLLM i nie wykonuje HTTP do Control API przy każdym żądaniu.
- Gateway musi uwierzytelnić i zautoryzować request przed każdym cache lookup; tożsamość virtual key/tenant jest mapowana na stabilny `key_id` i przekazywana do LiteLLM. Cache hit nie może omijać auth, rate limitu ani budget accounting.
- Konfiguracja trwała pochodzi z PostgreSQL. Gateway używa krótkotrwałego snapshotu w pamięci/Redis i unieważnia go po zmianach przez Control API.
- PostgreSQL działa z rozszerzeniem `vector`; przechowuje embeddingi semantic cache. Redis przechowuje exact cache, rate/quota counters, health, locki, okna detekcji pętli i dzierżawy budżetu; utrata Redis nie może utracić konfiguracji ani zaksięgowanego usage.
- Langfuse służy wyłącznie do trace'ów i analiz, nigdy jako źródło konfiguracji.
- Dashboard nie łączy się bezpośrednio z bazą, Redisem ani LiteLLM admin API.

### Obowiązkowy spike topologii proxy-first

Przed rozwijaniem domeny potwierdzić testem integracyjnym pełny przepływ `Caddy -> Agent Gateway -> LiteLLM -> mock provider`:

1. Gateway waliduje tożsamość, zachowuje OpenAI request/response shape i przekazuje wybrany deployment do LiteLLM.
2. LiteLLM wykonuje retry/fallback bez powrotu do modelu wykluczonego przez politykę Gatewaya.
3. Metadata decyzji i optymalizacji docierają do callbacku Langfuse, a usage nie jest naliczane podwójnie.
4. Streaming, disconnect klienta i błędy zachowują kontrakt OpenAI przez obie warstwy.
5. LiteLLM nie jest osiągalny z sieci publicznej, a cache hit nie omija auth, rate limitu ani wpisu w ledgerze.

Decyzję opisuje ADR-0003; ADR-0001 pozostaje zapisem historycznego spike'a i jest superseded. Nie utrzymywać alternatywnej ścieżki inference przez publiczny LiteLLM.

### Granice danych

- W środowisku lokalnym jeden serwer PostgreSQL z obrazem zawierającym pgvector może hostować osobne bazy: `gateway`, `litellm` i zależności Langfuse. Rozszerzenie `vector` włączyć migracją tylko w bazie `gateway`; schematów aplikacji nie mieszać.
- Redis otrzymuje osobne prefixy/DB dla gatewaya i zewnętrznych usług.
- Wszystkie rekordy domenowe mają UUID, `created_at`, `updated_at`; konfiguracja modyfikowalna ma `version` do optimistic locking.
- `tenant_id` istnieje od pierwszej migracji na kluczach, budżetach, politykach i wpisach cache, nawet jeśli MVP ma jeden tenant.
- Sekrety są wskazywane przez `secret_ref`; wartości trafiają tylko z env/Docker secrets.

## 3. Docelowa struktura repozytorium

```text
apps/
  agent-gateway/               # FastAPI: publiczne /v1 + Control API /api
  dashboard-angular/           # standalone components, lazy routes, strict TS
packages/
  policy-engine/               # czysta domena: pruning, loops, routing, decision log
  model-registry/              # repozytoria i snapshot konfiguracji
  cache/                       # exact + semantic eligibility/search, namespace/TTL
  telemetry/                   # trace metadata, koszt, oszczędności, redaction
infrastructure/
  docker/
  litellm/config.yaml
  reverse-proxy/Caddyfile
  langfuse/                    # konfiguracja zgodna z przypiętym wydaniem
migrations/                    # Alembic dla bazy gateway
scripts/                       # seed, smoke test, generowanie klienta API
tests/
  integration/
  e2e/
docs/
  adr/
  architecture.md
  routing.md
  operations.md
docker-compose.yml
.env.example
Makefile
README.md
```

Python: jedna wersja zadeklarowana w repo, `uv`, FastAPI, Pydantic, SQLAlchemy async, Alembic, redis-py, pytest, Ruff i mypy. Frontend: Angular standalone + Material, Signals dla stanu widoku, RxJS dla I/O, klient generowany z OpenAPI. Wersje obrazów i zależności przypinać; nie używać `latest`.

## 4. Model domenowy MVP

### Tabele gatewaya

1. `tenants`: nazwa, status.
2. `providers`: typ, base URL, `secret_ref`, priorytet, limity, status administracyjny.
3. `models`: provider, provider model ID, logical tier, ceny, limity kontekstu/outputu, capability flags, quality/latency/reliability score, priority, weight, enabled.
4. `routing_policies`: tenant, nazwa, start/fallback tier, prefer-free, limity kosztu i tokenów, wymagania jakości/latency, wagi scoringu, enabled, version.
5. `api_key_metadata`: tenant, hash/fingerprint klucza, owner, status i mapowanie do `litellm_virtual_key_id`. Agent Gateway jest autorytatywnym verifierem publicznego klucza przed cache; do LiteLLM przekazuje wyłącznie wewnętrzne uwierzytelnienie i stabilną identyfikację billingową.
6. `budgets`: scope type/id, period, limit USD, warning threshold, hard-stop mode.
7. `usage_ledger`: partycjonowany miesięcznie po `occurred_at`; trace/request/attempt ID, scope, provider/model/tier, actual tokens/cost, `raw_prompt_tokens`, `pruned_prompt_tokens`, `saved_tokens_count`, `estimated_cost_saved`, cache status/type, `optimization_flags`, status końcowy i timestamp. Służy do egzekwowania i dashboardu; Langfuse nie jest źródłem budżetu.
8. `provider_health_events`: wynik checku, latency, kod błędu, timestamp. Bieżący stan jest zmaterializowany w Redisie.
9. `audit_log`: actor, action, entity type/id, before/after z redakcją sekretów, timestamp.
10. `semantic_cache_entries`: tenant/namespace, hash źródła, embedding `vector(n)`, odpowiedź lub bezpieczny odnośnik, model embeddingowy i jego wersja, próg podobieństwa, policy/source version, `created_at`/`expires_at`. Indeks wektorowy dobrać po pomiarze; dla małego MVP dopuszczalny exact scan.

Późniejsze migracje dodadzą trial credits, trwałe sesje, dokumenty/chunki RAG, rozbudowane cache policies i ewaluacje jakości.

### Typy domenowe

- `TaskType`: `simple_qa`, `classification`, `summarization`, `translation`, `coding`, `reasoning`, `rag_qa`, `vision`, `structured_output`, `tool_use`, `creative`, `long_context`.
- `CapabilitySet`: tools, JSON, vision, audio, reasoning, embeddings, streaming oraz minimalne context/output tokens.
- `HealthState`: healthy, degraded, rate_limited, disabled, down.
- `RoutingDecision`: request/trace ID, policy/version, kandydaci odrzuceni z powodami, ranking i składowe score, wybrany model, fallback chain.
- `UsageRecord`: surowe/przycięte/rzeczywiste tokeny, ceny użyte do obliczeń, actual/reference/saved cost, retry/fallback count, cache status/type i flagi optymalizacji (`TOOL_PRUNED`, `CONTEXT_PRUNED`, `LOOP_BLOCKED`, `EXACT_HIT`, `SEMANTIC_HIT`).

## 5. Kontrakt routingu MVP

Pipeline jest deterministyczny i testowalny etapami:

```text
auth -> rate limit -> session/loop check -> raw token estimate
-> deterministic pruning -> exact cache -> semantic-cache eligibility/lookup
-> classify/detect capabilities -> registry snapshot -> hard filters -> score/rank
-> acquire budget lease -> LiteLLM execute/retry/fallback -> validate
-> settle/release lease -> cache write -> ledger/trace -> response
```

Kolejność jest kontraktem: cache działa na bezpiecznie przyciętym wejściu, lecz po auth i loop protection; żadna odpowiedź cache nie omija ledgeru. Dla streamingu lease rozliczyć po finalnym usage lub zwolnić po timeout/disconnect zgodnie z idempotentną procedurą odzyskiwania.

### Trimming i pruning

- Najpierw policzyć `raw_prompt_tokens`, a po transformacji `pruned_prompt_tokens`; różnica tworzy `saved_tokens_count`.
- MVP usuwa tylko treści sklasyfikowane przez deterministyczne reguły: stare, zastąpione wyniki narzędzi, nadmiarowy HTML i historyczny JSON poza skonfigurowanym limitem. System prompt, ostatnie wiadomości, aktywne argumenty/results tool calls oraz dane wymagane przez bieżące zadanie są chronione.
- Każda transformacja zapisuje typ reguły, hash przed/po i liczbę tokenów. Pełny diff promptu jest domyślnie wyłączony; jeśli tenant go włączy, podlega redakcji, szyfrowaniu, RBAC i krótkiemu TTL.
- Jeżeli transformacja nie może dowieść zachowania spójności par `tool_call`/`tool_result`, wykonuje bypass zamiast modyfikacji.

### Ochrona przed pętlami

- Gateway wymaga lub wyprowadza stabilny `session_id`; brak identyfikatora wyłącza detekcję między requestami i jest jawnie raportowany.
- Kanoniczny hash obejmuje nazwę narzędzia, znormalizowane argumenty i istotny stan/kod wyniku, bez sekretów. Redis przechowuje krótkie okno pod `loop_protection:{tenant_id}:{session_id}` z TTL.
- Polityka określa próg identycznych wywołań oraz naprzemienne wzorce A/B. Przekroczenie progu zwraca kontrolowany błąd zgodny z OpenAI, zapisuje `LOOP_BLOCKED` i alert; nie trafia do LiteLLM ani providera.

### Twarde filtry, zawsze przed scoringiem

Odrzucić model, gdy jest wyłączony, provider ma otwarty circuit breaker, brakuje capability, kontekst/output przekracza limit, quota jest wyczerpana, model narusza hard budget albo polityka nie pozwala na jego tier. Brak kandydata zwraca kontrolowany błąd zgodny z OpenAI z correlation ID.

### Ranking

Normalizować każdą składową do `[0,1]` i zapisywać ją w decyzji:

```text
score = cost*w_cost + quality*w_quality + latency*w_latency
      + reliability*w_reliability + quota*w_quota
```

MVP dostarcza profile `economy` i `balanced`. `prefer_free` daje darmowym kandydatom pierwszą grupę rankingu, ale nigdy nie omija filtrów. Remisy rozstrzyga: wyższy `priority`, potem stabilne `model.id`, aby testy były powtarzalne.

### Fallback i retry

- Retry raz tylko dla timeout, 429, przejściowego błędu sieciowego i wybranych 5xx.
- Następnie kolejny kandydat tego samego tieru/providera alternatywnego, potem skonfigurowany fallback tier.
- Bez retry dla 4xx walidacyjnych/auth i błędów deterministycznych.
- Każda próba ma osobny span, a całe żądanie jeden trace/correlation ID.
- MVP waliduje: niepustą odpowiedź, poprawny JSON/JSON Schema, gdy zażądano structured output, oraz poprawną strukturę tool calls.

### Exact cache

- Hash z kanonicznego JSON: tenant/cache namespace, logiczny tier, system/messages, tools, temperature, response format oraz wersja polityki.
- Usunąć wyłącznie transportowe metadata (`request_id`, trace headers); nie normalizować treści semantycznie w MVP.
- Cache tylko dla jawnie bezpiecznych żądań bez tool side effects. Streaming może odtworzyć zapisany wynik zgodnie z kontraktem albo zostać wyłączony dla hitów do czasu testu kompatybilności.
- TTL zależy od task type; wpis zawiera schema version i policy version.
- Awaria Redis: bypass cache i kontynuacja, ale awaria atomicznego budget countera działa fail-closed dla płatnego modelu.

### Semantic cache

- Lookup następuje po exact cache, wyłącznie dla polityk z jawnym opt-in i zapytań bez aktywnych tool calls, side effects, danych czasowych oraz prywatnych danych wykraczających poza tenant namespace.
- Embedding i wyszukiwanie odbywają się w PostgreSQL + pgvector; wpis wiąże wersję modelu embeddingowego, polityki, źródła i próg podobieństwa. Wynik po TTL lub zmianie którejkolwiek wersji jest miss.
- Hit musi przejść kontrolę freshness i compatibility (task, response format, locale/capabilities). Zapisuje `SEMANTIC_HIT`, similarity score, ominięty model i konserwatywnie oszacowany koszt uniknięty.
- Awaria pgvector lub usługi embeddingowej daje bypass do routingu, nie błąd requestu. Semantic cache nie obsługuje streamingu w MVP, dopóki test kontraktowy nie potwierdzi poprawnego odtwarzania chunków.

### Dzierżawa budżetu

- Przed płatnym wywołaniem atomowo rezerwować estymowany koszt w `budget_lease:{tenant_id}:{key_id}:{request_id}` z TTL 60 s oraz licznikiem scope. Lease ma `lease_id` i stan pozwalający na idempotentne settle/release.
- Po odpowiedzi rozliczyć actual cost i zwolnić różnicę; retry/fallback należą do tego samego requestu, lecz każda próba ma osobny `attempt_id` w ledgerze.
- Worker reconciliacyjny wykrywa wygasłe lease'y i porównuje je z ledgerem. Awaria Redisa działa fail-closed dla płatnego ruchu, ale może dopuścić model faktycznie darmowy.

## 6. Kontrakty API

### Publiczne inference API

- `POST /v1/chat/completions` — minimum wymagane w MVP, stream i non-stream.
- `GET /v1/models` — zwraca logiczne aliasy dostępne dla klucza.
- Profile/politykę przekazywać przez dozwolone `metadata` lub nagłówki `X-LLM-Policy-*`; nie łamać standardowego payloadu.
- Odpowiedź zachowuje format OpenAI. Informacje diagnostyczne są w nagłówkach (`X-Trace-ID`, opcjonalnie `X-Actual-Model` dla admin/playground), nie w treści odpowiedzi.

### Control API `/api/v1`

- CRUD: `/providers`, `/models`, `/policies`, `/budgets`.
- Operacje: `/providers/{id}/enable|disable`, `/models/{id}/enable|disable`, `/providers/{id}/health-check`.
- Odczyty: `/dashboard/overview`, `/dashboard/costs`, `/dashboard/providers`, `/traces/{trace_id}/decision`.
- Agent FinOps: `/dashboard/savings`, `/traces/{trace_id}/pruning`, `/loop-alerts`.
- Cache: `/cache/stats`, `/cache/purge` z filtrem namespace; purge jest audytowany.
- Playground: `/playground/chat`, dostępny tylko dla admina, deleguje do publicznego inference API.
- Listy mają pagination/filter/sort. Zmiany wymagają `version`/ETag i tworzą audit event.

OpenAPI jest kontraktem: CI generuje schemat i sprawdza, czy Angularowy typed client nie jest nieaktualny.

## 7. Etapy implementacji

Każdy etap kończy się działającym testem i osobnym małym commitem. Nie zaczynać następnego etapu przy czerwonym CI.

### Etap 0 — bootstrap i historyczny spike (ukończony)

- [x] Utworzyć strukturę monorepo, konfigurację Python/Angular, lint/test/typecheck oraz `Makefile`.
- [x] Przypiąć wersje zależności i obrazów; udokumentować minimalne wymagania Docker/Node/Python.
- [x] Wykonać spike LiteLLM z jednym mock providerem i zapisać ADR-0001.
- [x] Dodać ADR-0002: własność danych i granice LiteLLM/gateway/Langfuse.
- [x] Dodać CI: backend unit/integration, frontend format/test/build, Compose config validation, secret scan.

**Odbiór:** czyste repo przechodzi lokalnie `make check`; historyczny smoke request przez LiteLLM dociera do mock providera. Ten test nie potwierdza jeszcze docelowej topologii.

**Weryfikacja 2026-09-25:** `make check`, oba `docker compose ... config --quiet`, Gitleaks oraz sekwencja `make spike-up && make spike-test && make spike-down` zakończone powodzeniem. CI uruchamia ten sam spike jako osobny job z cleanupem `if: always()`.

### Etap 1 — migracja do Agent Gateway i lokalna infrastruktura (w toku)

- [x] Bazowy Compose: Caddy, LiteLLM, Control API, dashboard, PostgreSQL, Redis i mock LLM.
- [ ] Przekształcić `apps/control-api` w `apps/agent-gateway` (lub zachować ścieżkę przejściowo, lecz zmienić nazwę modułu/usługi) i dodać passthrough `/v1/chat/completions` oraz `/v1/models`.
- [ ] Przełączyć Caddy `/v1/*` na Agent Gateway; LiteLLM pozostawić wyłącznie w sieci wewnętrznej i zablokować bezpośredni port hosta.
- [x] Dodać ADR-0003 dla wiążącej topologii proxy-first i oznaczyć ADR-0001 jako superseded.
- [ ] Zmienić obraz PostgreSQL na wariant z pgvector oraz dodać idempotentne `CREATE EXTENSION vector` w migracji bazy gateway.
- [ ] Langfuse uruchamiać profilem `observability`; użyć aktualnego oficjalnego zestawu zależności (nie legacy v2).
- [x] Health/readiness checks, trwałe named volumes, wewnętrzna sieć i minimalnie wystawione porty.
- [x] `.env.example` bez prawdziwych sekretów oraz skrypt inicjalizujący bazy.
- [ ] `make up`, `make down`, `make migrate`, `make seed`, `make smoke` (`up`, `down` i `smoke` gotowe; migracje i seed należą do Etapu 2).

**Odbiór:** świeży checkout uruchamia stack jedną komendą; request przechodzi wyłącznie ścieżką `Caddy -> Agent Gateway -> LiteLLM -> mock`; bezpośredni LiteLLM jest niedostępny z hosta; migracje z `vector` są idempotentne, a restart zachowuje dane.

### Etap 2 — registry i Control API

- [ ] Migracje dla tenantów, providerów, modeli, polityk, budżetów i audytu.
- [ ] Repozytoria, serwisy domenowe i walidacja unikalności/capabilities/cen.
- [ ] CRUD Control API z pagination, ETag/version i redakcją `secret_ref`.
- [ ] Seed: OpenRouter + co najmniej dwa modele testowe w tierach `free` i `cheap`; danych realnego providera nie kodować w routerze.
- [ ] Publikacja invalidation event po każdej zmianie konfiguracji.

**Odbiór:** contract tests CRUD; wyłączenie modelu zmienia snapshot routera bez restartu.

### Etap 3 — agentowy pre-processing i ochrona pętli

- [ ] Stabilny kontrakt `session_id`, kanoniczny hash tool call i okno Redis `loop_protection:*` z TTL.
- [ ] Detekcja powtórzeń i wzorca A/B, kontrolowany błąd OpenAI oraz alert `LOOP_BLOCKED`.
- [ ] Deterministyczny pruner dla starych tool outputs, HTML i JSON z ochroną spójności historii.
- [ ] Liczenie raw/pruned/saved tokens oraz dziennik reguł bez pełnej treści promptu domyślnie.
- [ ] Feature flags i per-policy bypass/limity, aby każdą transformację można było bezpiecznie wyłączyć.

**Odbiór:** golden tests dowodzą, że pruning nie rozrywa par tool-call/result ani chronionych wiadomości; powtarzana pętla zostaje zatrzymana przed LiteLLM, a niezależne sesje/tenanty nie współdzielą stanu.

### Etap 4 — Policy Engine i `model=auto`

- [ ] Czyste funkcje: klasyfikacja regułowa, capability detection, konserwatywna estymacja tokenów, hard filters, scoring i tie-break.
- [ ] Profile `economy` i `balanced` oraz aliasy `auto`, `free`, `cheap`, `fast`, `smart`, `coding`, `reasoning`, `vision`, `long-context`.
- [ ] Snapshot Model Registry z numerem wersji i kontrolowanym TTL.
- [ ] Integracja wybranego deploymentu z LiteLLM.
- [ ] Pełny `RoutingDecision`, bez treści promptu, dostępny po trace ID.

**Odbiór:** testy tabelaryczne pokrywają capabilities, context limit, health, budget, free-first, remisy i brak kandydatów; żaden provider/model nie jest zaszyty w kodzie domenowym.

### Etap 5 — fallback, health i niezawodność

- [ ] Klasyfikacja błędów retryable/non-retryable i ograniczony retry budget.
- [ ] Fallback chain tworzony z rankingu, bez ponownego użycia odrzuconego deploymentu.
- [ ] Circuit breaker w Redisie z konfigurowalnymi progami i atomicznymi zmianami stanu.
- [ ] Background worker: częsty connectivity check i rzadszy tani inference check z jitterem.
- [ ] Degraded mode przy awarii Redis/PostgreSQL/Langfuse opisany i przetestowany.

**Odbiór:** fault-injection dla timeout/429/5xx otwiera breaker, omija chorego providera, zamyka go po udanym probe i rejestruje każdą próbę.

### Etap 6 — usage, oszczędności, budget lease i Langfuse

- [ ] Kalkulator kosztu oparty o wersjonowane ceny modelu; Decimal, nie float.
- [ ] Partycjonowany miesięcznie `usage_ledger`, idempotentny po `request_id + attempt_id`, z raw/pruned/saved tokens, cache type i optimization flags.
- [ ] Atomiczna rezerwacja szacowanego kosztu przez `budget_lease:*` z TTL 60 s, idempotentne settle/release i reconciler wygasłych lease'ów.
- [ ] Kalkulacja `estimated_cost_saved` oddzielnie dla pruning, exact/semantic cache i free-first bez podwójnego zliczania.
- [ ] Progi warning/hard stop per API key lub user; płatny ruch fail-closed przy niepewnym budżecie.
- [ ] Langfuse trace/span z tierem, modelem, tokenami, kosztem, latency, cache, retry/fallback i decision ID; redakcja promptów domyślnie.

**Odbiór:** równoległe requesty nie przekraczają hard limitu; crash po rezerwacji nie pozostawia środków zablokowanych po TTL/reconciliation; duplikat callbacku nie nalicza kosztu dwa razy; suma breakdown oszczędności zgadza się z ledgerem; awaria Langfuse nie przerywa inference.

### Etap 7 — exact i semantic cache

- [ ] Kanoniczny serializer i wersjonowany cache key.
- [ ] Eligibility rules, TTL per task i ochrona tenant namespace.
- [ ] Stampede lock/single-flight dla identycznych requestów.
- [ ] Zapis dopiero po udanej walidacji; błędów i częściowych streamów nie cache'ować.
- [ ] Stats i bezpieczne purge po namespace/policy version.
- [ ] Migracja `semantic_cache_entries` z pgvector, wersjonowanie modelu embeddingowego i polityki oraz tenant-scoped similarity search.
- [ ] Eligibility/freshness rules, konfigurowalny próg, TTL i fallback do normalnego routingu przy awarii embeddingów/PostgreSQL.

**Odbiór:** golden tests kluczy; exact/semantic hit omija LiteLLM i provider, ale nadal przechodzi auth, rate limit i ledger; zmiana promptu/polityki/tenantu lub wersji embeddingu daje miss; Redis/pgvector outage daje kontrolowany bypass; request z tool side effects nigdy nie daje semantic hit.

### Etap 8 — dashboard Agentic FinOps

- [ ] Shell, routing lazy-load, logowanie/guard admina i interceptor correlation ID.
- [ ] Overview: requests, tokeny, koszt, cache hit, free/paid, p50/p95, fallback i error rate.
- [ ] Models i Providers: tabela, formularz create/edit, enable/disable, health i walidacja błędów konfliktu wersji.
- [ ] Policies/Budgets: edycja profili i limitów.
- [ ] Playground: logical alias/policy/streaming oraz actual model, tokeny, koszt, latency, cache i fallback.
- [ ] Widok szczegółów RoutingDecision dla trace ID.
- [ ] Efficiency: saved tokens i cost saved w czasie oraz breakdown pruning/exact/semantic/free-first.
- [ ] Pruning trace: raw vs sent w formie zredagowanego diffu/metryk, z RBAC i krótką retencją treści.
- [ ] Loop Alerts: sesja/tenant, wzorzec, licznik, czas blokady i trace ID bez ujawniania argumentów zawierających sekrety.

**Odbiór:** admin może dodać i wyłączyć model/provider, ustawić budżet i zobaczyć efekt w następnym request; inference działa przy wyłączonym dashboardzie.

### Etap 9 — hardening i wydanie MVP

- [ ] Hashowane identyfikatory kluczy, RBAC admin/user, restrykcyjne CORS, TLS przez Caddy i rate limits per key/tenant.
- [ ] Redakcja PII/secrets w logach, błędach, audycie i telemetryce; testy negatywne.
- [ ] Timeouts, limity rozmiaru requestu, graceful shutdown i readiness zależne tylko od krytycznych usług.
- [ ] Backup/restore bazy gateway, runbook awarii i rotacji sekretów.
- [ ] Load test dla stream/non-stream/cache hit/fallback oraz podstawowe SLO.
- [ ] E2E i macierz Definition of Done ze specyfikacji.

**Odbiór:** wszystkie punkty sekcji 10 są zaliczone; znane ograniczenia zapisane w release notes.

## 8. Testy wymagane przez CI

### Unit

- klasyfikacja/capability detection/token estimation,
- pruning HTML/JSON/tool outputs z inwariantami historii oraz liczeniem raw/pruned/saved,
- kanoniczne hashe i progi detekcji pętli, w tym wzorce naprzemienne,
- każdy hard filter i każda składowa score,
- deterministyczny ranking i kontrakt przekazania wybranego deploymentu do LiteLLM,
- canonicalizacja oraz exact/semantic cache eligibility i freshness,
- kalkulacja kosztu/oszczędności i przejścia budget lease,
- redakcja danych wrażliwych.

### Integration

- PostgreSQL migrations/repositories i optimistic locking,
- Redis counters, locks, breaker, loop windows, budget lease i cache TTL,
- pgvector migrations, tenant-scoped similarity lookup i wygasanie semantic cache,
- Agent Gateway -> LiteLLM -> mock provider, bez pluginu routującego LiteLLM,
- Langfuse callback przy sukcesie i niedostępności,
- Control API auth/RBAC/audit/OpenAPI.

### E2E

1. `auto` wybiera free dla prostego requestu.
2. Stary, zastąpiony tool output jest bezpiecznie przycięty i raportuje oszczędność tokenów.
3. Powtarzana sekwencja tool calls blokuje sesję przed LiteLLM, bez wpływu na inny tenant.
4. Wymagane tools/vision odrzucają niezgodny free model.
5. Timeout/429 uruchamia fallback w LiteLLM i zapisuje powód bez obejścia polityki Gatewaya.
6. Drugi identyczny request jest exact hitem; podobne kwalifikujące się pytanie jest semantic hitem.
7. Request narzędziowy lub zależny od czasu omija semantic cache.
8. Hard budget blokuje płatny model, ale pozwala na darmowy; crash nie pozostawia lease'a po TTL.
9. Wyłączenie modelu w UI wpływa na następny request.
10. Streaming zachowuje format OpenAI, jeden trace i poprawne rozliczenie lease'a po disconnect.
11. Restart usług nie usuwa konfiguracji; utrata Redis nie miesza tenantów.
12. Bezpośredni dostęp do LiteLLM z zewnątrz jest niemożliwy.

## 9. Fazy po MVP

### Faza 2 — rozszerzona redukcja kosztu

Strukturalne summaries, dynamiczne output budgets, normalized cache, RAG, trial/expiry-aware routing, profile `quality`/`realtime`, grupowe invalidation i provider prompt caching. MVP zawiera już deterministyczny trimming, podstawowy semantic cache z pgvector i cost-avoided breakdown; faza 2 może je rozszerzać dopiero po pomiarach jakości. Każda optymalizacja musi mieć metrykę bazową i test, że nie narusza freshness/tenant boundaries.

### Faza 3 — routing jakościowy

Deterministyczne validators, score per task, progressive escalation, offline eval set, A/B tests, latency/reliability-aware tuning i kontrolowane automatyczne strojenie polityk. Nie używać LLM-as-judge na każdej ścieżce produkcyjnej.

### Faza 4 — rozszerzenia

Ollama/vLLM, batch queue, per-tenant billing/export, alerting, zaawansowany RBAC, secrets manager, osobny vector DB i Kubernetes dopiero po udokumentowanej potrzebie skalowania/HA.

## 10. Definition of Done MVP

- [ ] Jeden OpenAI-compatible endpoint i logiczne aliasy bez znajomości providerów po stronie klienta.
- [ ] Caddy kieruje `/v1/*` wyłącznie do FastAPI Agent Gateway, a LiteLLM nie jest publicznie osiągalny.
- [ ] Deterministyczny pruning bezpiecznie redukuje stare tool outputs/HTML/JSON i raportuje raw/pruned/saved tokens.
- [ ] Detekcja pętli w Redisie blokuje powtarzalne tool calls per tenant/session i generuje alert.
- [ ] `model=auto` dynamicznie wybiera model z PostgreSQL i preferuje free, jeśli spełnia wymagania.
- [ ] Provider/model można dodać i wyłączyć z dashboardu.
- [ ] Capability, health, quota i budget filtering poprzedzają scoring.
- [ ] Retry/fallback działa dla zdefiniowanych błędów i jest widoczny w trace.
- [ ] Exact cache w Redisie jest bezpieczny tenantowo i mierzalny.
- [ ] Semantic cache w PostgreSQL + pgvector ma opt-in, freshness rules i nigdy nie obsługuje requestów z side effects.
- [ ] Budżet per API key lub user jest egzekwowany współbieżnie przez dzierżawy z TTL i reconciliation.
- [ ] Partycjonowany usage ledger zapisuje usage, koszt, saved tokens, cost saved, cache type i optimization flags; dane trafiają do dashboardu oraz Langfuse.
- [ ] Dashboard pokazuje efficiency, bezpieczny pruning trace i loop alerts.
- [ ] Każda decyzja routingu ma trace ID i czytelne uzasadnienie.
- [ ] PostgreSQL jest źródłem prawdy; inference nie zależy od dostępności Angulara ani Langfuse.
- [ ] Compose uruchamia cały lokalny stack; migracje, seed, smoke, testy i backup są udokumentowane.
- [ ] Sekrety i pełne prywatne prompty nie trafiają domyślnie do repo/logów/trace'ów.

## 11. Instrukcja dla kolejnej sesji Codexa

1. Przeczytaj tylko ten plik, aktualny ADR dla wykonywanego etapu i pliki bezpośrednio objęte zmianą. Do pełnej specyfikacji wróć tylko przy niejasności produktu.
2. Sprawdź `git status`, ostatnie commity i checklistę etapu. Nie zmieniaj cudzych, niezwiązanych modyfikacji.
3. Wybierz pierwszy niezakończony punkt z najwcześniejszego rozpoczętego etapu. Nie implementuj funkcji z późniejszych faz „przy okazji”.
4. Przed kodem zapisz lub zaktualizuj test akceptacyjny dla danego slice'a.
5. Utrzymuj logikę domenową jako czyste funkcje; adaptery LiteLLM/DB/Redis/Langfuse nie mogą przenikać do pruning, loop detection ani scoringu.
6. Po zmianie uruchom najmniejszy trafny zestaw testów, potem `make check`; zaktualizuj checklistę tylko po faktycznym odbiorze.
7. Jeśli odkryjesz sprzeczność architektoniczną, dodaj ADR zamiast budować drugi wariant rozwiązania.

### Najbliższe zadanie

Kontynuować **Etap 1** od pionowego slice'a proxy-first zgodnie z ADR-0003: przepiąć Caddy `/v1/*` na FastAPI Agent Gateway, skierować Gateway do wewnętrznego LiteLLM i potwierdzić ścieżkę smoke testem. Następnie włączyć pgvector i dopiero później Langfuse.
