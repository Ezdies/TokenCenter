# LLM FinOps Gateway — plan implementacji

Plan wykonawczy do specyfikacji [`llm-finops-gateway-implementation-guide.md`](./llm-finops-gateway-implementation-guide.md).
Ma być krótkim źródłem kontekstu dla kolejnych sesji implementacyjnych. Szczegóły produktu pozostają w specyfikacji; tutaj są decyzje, kolejność prac, kontrakty i kryteria odbioru.

## 1. Zakres i zasady

### Cel MVP

Udostępnić jeden endpoint zgodny z OpenAI, który dla `model=auto` wybiera zdrowy model z rejestru, preferuje wariant darmowy, respektuje budżet i wymagane capabilities, korzysta z exact cache, wykonuje fallback oraz zapisuje pełne uzasadnienie decyzji i telemetrykę. Administrator zarządza providerami, modelami i budżetami przez Control API oraz podstawowy dashboard Angular.

### Kolejność priorytetów

1. Niezawodność i poprawność routingu.
2. Obserwowalność i możliwość wyjaśnienia decyzji.
3. Egzekwowanie budżetów.
4. Cache i optymalizacja kosztu.
5. Ergonomia dashboardu.

### Poza MVP

Semantic cache, RAG, streszczanie rozmów, trial-aware scoring, automatyczna ocena jakości, wielostopniowa eskalacja jakościowa, batching, Kubernetes, lokalne modele, rozbudowany RBAC i zewnętrzny secrets manager. Struktura kodu i bazy ma pozwalać je dodać, ale MVP nie implementuje atrap tych funkcji.

## 2. Decyzje architektoniczne

### Przepływ danych

```text
client
  -> Caddy /v1/*
  -> LiteLLM Proxy (auth, virtual keys, zgodność OpenAI, provider adapters)
  -> Policy Engine (wybór deploymentu, health, budget, powód decyzji)
  -> provider

admin browser
  -> Caddy /api/*
  -> FastAPI Control API
  -> PostgreSQL / Redis
```

- LiteLLM jest publicznym data plane dla `/v1/*`.
- FastAPI jest control plane i nie znajduje się na krytycznej ścieżce inference.
- Policy Engine jest osobnym pakietem Pythona ładowanym przez rozszerzenie routingu LiteLLM. Nie wykonuje HTTP do Control API przy każdym żądaniu.
- Konfiguracja trwała pochodzi z PostgreSQL. Policy Engine używa krótkotrwałego snapshotu w pamięci/Redis i unieważnia go po zmianach przez Control API.
- Redis przechowuje cache, rate/quota counters, health i locki; utrata Redis nie może utracić konfiguracji.
- Langfuse służy wyłącznie do trace'ów i analiz, nigdy jako źródło konfiguracji.
- Dashboard nie łączy się bezpośrednio z bazą, Redisem ani LiteLLM admin API.

### Obowiązkowy spike przed właściwym kodem

API rozszerzeń LiteLLM zmienia się między wersjami. Najpierw przypiąć wersję i potwierdzić testem integracyjnym, że własny hook/strategia może:

1. odczytać virtual key/user/tenant i żądany alias,
2. odfiltrować deployments oraz wybrać konkretny model,
3. dodać metadata decyzji do callbacku Langfuse,
4. obsłużyć fallback bez podwójnego naliczania użycia,
5. zachować streaming i błędy zgodne z OpenAI.

Wynik opisać w `docs/adr/0001-litellm-policy-integration.md`. Jeśli rozszerzenie przypiętej wersji nie daje tych gwarancji, przyjąć jeden fallback architektoniczny: cienki FastAPI data-plane przed LiteLLM. Nie utrzymywać dwóch ścieżek inference.

### Granice danych

- W środowisku lokalnym jeden serwer PostgreSQL może hostować osobne bazy: `gateway`, `litellm` i zależności Langfuse. Schematów aplikacji nie mieszać.
- Redis otrzymuje osobne prefixy/DB dla gatewaya i zewnętrznych usług.
- Wszystkie rekordy domenowe mają UUID, `created_at`, `updated_at`; konfiguracja modyfikowalna ma `version` do optimistic locking.
- `tenant_id` istnieje od pierwszej migracji na kluczach, budżetach, politykach i wpisach cache, nawet jeśli MVP ma jeden tenant.
- Sekrety są wskazywane przez `secret_ref`; wartości trafiają tylko z env/Docker secrets.

## 3. Docelowa struktura repozytorium

```text
apps/
  control-api/                 # FastAPI: CRUD, dashboard queries, cache ops
  dashboard-angular/           # standalone components, lazy routes, strict TS
packages/
  policy-engine/               # czysta domena: filtering, scoring, decision log
  model-registry/              # repozytoria i snapshot konfiguracji
  cache/                       # canonicalizacja, exact cache, namespace/TTL
  telemetry/                   # trace metadata, koszt, redaction
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
5. `api_key_metadata`: tenant, hash/fingerprint identyfikatora, owner, status; sekret/autoryzację pozostawić LiteLLM.
6. `budgets`: scope type/id, period, limit USD, warning threshold, hard-stop mode.
7. `usage_ledger`: trace/request ID, scope, provider/model/tier, tokeny, koszt, cache status, status końcowy, timestamp. Służy do egzekwowania i dashboardu; Langfuse nie jest źródłem budżetu.
8. `provider_health_events`: wynik checku, latency, kod błędu, timestamp. Bieżący stan jest zmaterializowany w Redisie.
9. `audit_log`: actor, action, entity type/id, before/after z redakcją sekretów, timestamp.

Późniejsze migracje dodadzą trial credits, sesje, dokumenty/chunki/embeddingi, cache policies i ewaluacje jakości.

### Typy domenowe

- `TaskType`: `simple_qa`, `classification`, `summarization`, `translation`, `coding`, `reasoning`, `rag_qa`, `vision`, `structured_output`, `tool_use`, `creative`, `long_context`.
- `CapabilitySet`: tools, JSON, vision, audio, reasoning, embeddings, streaming oraz minimalne context/output tokens.
- `HealthState`: healthy, degraded, rate_limited, disabled, down.
- `RoutingDecision`: request/trace ID, policy/version, kandydaci odrzuceni z powodami, ranking i składowe score, wybrany model, fallback chain.
- `UsageRecord`: estymowane i rzeczywiste tokeny, ceny użyte do obliczeń, actual/reference cost, retry/fallback count i cache status.

## 5. Kontrakt routingu MVP

Pipeline jest deterministyczny i testowalny etapami:

```text
auth -> rate/budget pre-check -> exact cache -> classify/detect capabilities
-> estimate tokens -> load registry snapshot -> hard filters
-> score/rank -> execute -> validate -> fallback -> usage/trace/cache -> response
```

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
- Cache: `/cache/stats`, `/cache/purge` z filtrem namespace; purge jest audytowany.
- Playground: `/playground/chat`, dostępny tylko dla admina, deleguje do publicznego inference API.
- Listy mają pagination/filter/sort. Zmiany wymagają `version`/ETag i tworzą audit event.

OpenAPI jest kontraktem: CI generuje schemat i sprawdza, czy Angularowy typed client nie jest nieaktualny.

## 7. Etapy implementacji

Każdy etap kończy się działającym testem i osobnym małym commitem. Nie zaczynać następnego etapu przy czerwonym CI.

### Etap 0 — bootstrap i ADR (ukończony)

- [x] Utworzyć strukturę monorepo, konfigurację Python/Angular, lint/test/typecheck oraz `Makefile`.
- [x] Przypiąć wersje zależności i obrazów; udokumentować minimalne wymagania Docker/Node/Python.
- [x] Wykonać spike LiteLLM z jednym mock providerem i zapisać ADR-0001.
- [x] Dodać ADR-0002: własność danych i granice LiteLLM/gateway/Langfuse.
- [x] Dodać CI: backend unit/integration, frontend format/test/build, Compose config validation, secret scan.

**Odbiór:** czyste repo przechodzi lokalnie `make check`; smoke request przez LiteLLM dociera do mock providera.

### Etap 1 — lokalna infrastruktura (w toku)

- [x] Compose: Caddy, LiteLLM, Control API, dashboard, PostgreSQL, Redis i mock LLM.
- [ ] Langfuse uruchamiać profilem `observability`; użyć aktualnego oficjalnego zestawu zależności (nie legacy v2).
- [x] Health/readiness checks, trwałe named volumes, wewnętrzna sieć i minimalnie wystawione porty.
- [x] `.env.example` bez prawdziwych sekretów oraz skrypt inicjalizujący bazy.
- [ ] `make up`, `make down`, `make migrate`, `make seed`, `make smoke` (`up`, `down` i `smoke` gotowe; migracje i seed należą do Etapu 2).

**Odbiór:** świeży checkout uruchamia stack jedną komendą, migracje są idempotentne, restart zachowuje dane.

### Etap 2 — registry i Control API

- [ ] Migracje dla tenantów, providerów, modeli, polityk, budżetów i audytu.
- [ ] Repozytoria, serwisy domenowe i walidacja unikalności/capabilities/cen.
- [ ] CRUD Control API z pagination, ETag/version i redakcją `secret_ref`.
- [ ] Seed: OpenRouter + co najmniej dwa modele testowe w tierach `free` i `cheap`; danych realnego providera nie kodować w routerze.
- [ ] Publikacja invalidation event po każdej zmianie konfiguracji.

**Odbiór:** contract tests CRUD; wyłączenie modelu zmienia snapshot routera bez restartu.

### Etap 3 — Policy Engine i `model=auto`

- [ ] Czyste funkcje: klasyfikacja regułowa, capability detection, konserwatywna estymacja tokenów, hard filters, scoring i tie-break.
- [ ] Profile `economy` i `balanced` oraz aliasy `auto`, `free`, `cheap`, `fast`, `smart`, `coding`, `reasoning`, `vision`, `long-context`.
- [ ] Snapshot Model Registry z numerem wersji i kontrolowanym TTL.
- [ ] Integracja wybranego deploymentu z LiteLLM.
- [ ] Pełny `RoutingDecision`, bez treści promptu, dostępny po trace ID.

**Odbiór:** testy tabelaryczne pokrywają capabilities, context limit, health, budget, free-first, remisy i brak kandydatów; żaden provider/model nie jest zaszyty w kodzie domenowym.

### Etap 4 — fallback, health i niezawodność

- [ ] Klasyfikacja błędów retryable/non-retryable i ograniczony retry budget.
- [ ] Fallback chain tworzony z rankingu, bez ponownego użycia odrzuconego deploymentu.
- [ ] Circuit breaker w Redisie z konfigurowalnymi progami i atomicznymi zmianami stanu.
- [ ] Background worker: częsty connectivity check i rzadszy tani inference check z jitterem.
- [ ] Degraded mode przy awarii Redis/PostgreSQL/Langfuse opisany i przetestowany.

**Odbiór:** fault-injection dla timeout/429/5xx otwiera breaker, omija chorego providera, zamyka go po udanym probe i rejestruje każdą próbę.

### Etap 5 — usage, koszt, budżet i Langfuse

- [ ] Kalkulator kosztu oparty o wersjonowane ceny modelu; Decimal, nie float.
- [ ] Idempotentny `usage_ledger` po `request_id + attempt_id`.
- [ ] Atomiczna rezerwacja szacowanego kosztu przed płatnym requestem i rozliczenie po rzeczywistym usage.
- [ ] Progi warning/hard stop per API key lub user; płatny ruch fail-closed przy niepewnym budżecie.
- [ ] Langfuse trace/span z tierem, modelem, tokenami, kosztem, latency, cache, retry/fallback i decision ID; redakcja promptów domyślnie.

**Odbiór:** równoległe requesty nie przekraczają hard limitu; duplikat callbacku nie nalicza kosztu dwa razy; awaria Langfuse nie przerywa inference.

### Etap 6 — exact cache

- [ ] Kanoniczny serializer i wersjonowany cache key.
- [ ] Eligibility rules, TTL per task i ochrona tenant namespace.
- [ ] Stampede lock/single-flight dla identycznych requestów.
- [ ] Zapis dopiero po udanej walidacji; błędów i częściowych streamów nie cache'ować.
- [ ] Stats i bezpieczne purge po namespace/policy version.

**Odbiór:** golden tests kluczy; hit omija providera i koszt; zmiana promptu/polityki/tenantu daje miss; Redis outage daje kontrolowany bypass.

### Etap 7 — dashboard MVP

- [ ] Shell, routing lazy-load, logowanie/guard admina i interceptor correlation ID.
- [ ] Overview: requests, tokeny, koszt, cache hit, free/paid, p50/p95, fallback i error rate.
- [ ] Models i Providers: tabela, formularz create/edit, enable/disable, health i walidacja błędów konfliktu wersji.
- [ ] Policies/Budgets: edycja profili i limitów.
- [ ] Playground: logical alias/policy/streaming oraz actual model, tokeny, koszt, latency, cache i fallback.
- [ ] Widok szczegółów RoutingDecision dla trace ID.

**Odbiór:** admin może dodać i wyłączyć model/provider, ustawić budżet i zobaczyć efekt w następnym request; inference działa przy wyłączonym dashboardzie.

### Etap 8 — hardening i wydanie MVP

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
- każdy hard filter i każda składowa score,
- deterministyczny ranking i fallback,
- canonicalizacja/cache eligibility,
- kalkulacja kosztu i przejścia budżetu,
- redakcja danych wrażliwych.

### Integration

- PostgreSQL migrations/repositories i optimistic locking,
- Redis counters, locks, breaker i cache TTL,
- LiteLLM hook z mock providerem,
- Langfuse callback przy sukcesie i niedostępności,
- Control API auth/RBAC/audit/OpenAPI.

### E2E

1. `auto` wybiera free dla prostego requestu.
2. Wymagane tools/vision odrzucają niezgodny free model.
3. Timeout/429 uruchamia fallback i zapisuje powód.
4. Drugi identyczny request jest cache hitem.
5. Hard budget blokuje płatny model, ale pozwala na darmowy.
6. Wyłączenie modelu w UI wpływa na następny request.
7. Streaming zachowuje format OpenAI i jeden trace.
8. Restart usług nie usuwa konfiguracji; utrata Redis nie miesza tenantów.

## 9. Fazy po MVP

### Faza 2 — redukcja kosztu

Context trimming i strukturalne summaries, dynamiczne output budgets, normalized/semantic cache z pgvector, RAG, trial/expiry-aware routing, cost-avoided breakdown, profile `quality`/`realtime`, grupowe invalidation i provider prompt caching. Każda optymalizacja musi mieć metrykę bazową i test, że nie narusza freshness/tenant boundaries.

### Faza 3 — routing jakościowy

Deterministyczne validators, score per task, progressive escalation, offline eval set, A/B tests, latency/reliability-aware tuning i kontrolowane automatyczne strojenie polityk. Nie używać LLM-as-judge na każdej ścieżce produkcyjnej.

### Faza 4 — rozszerzenia

Ollama/vLLM, batch queue, per-tenant billing/export, alerting, zaawansowany RBAC, secrets manager, osobny vector DB i Kubernetes dopiero po udokumentowanej potrzebie skalowania/HA.

## 10. Definition of Done MVP

- [ ] Jeden OpenAI-compatible endpoint i logiczne aliasy bez znajomości providerów po stronie klienta.
- [ ] `model=auto` dynamicznie wybiera model z PostgreSQL i preferuje free, jeśli spełnia wymagania.
- [ ] Provider/model można dodać i wyłączyć z dashboardu.
- [ ] Capability, health, quota i budget filtering poprzedzają scoring.
- [ ] Retry/fallback działa dla zdefiniowanych błędów i jest widoczny w trace.
- [ ] Exact cache w Redisie jest bezpieczny tenantowo i mierzalny.
- [ ] Budżet per API key lub user jest egzekwowany współbieżnie.
- [ ] Usage, koszt i latency trafiają do ledger/dashboardu oraz Langfuse.
- [ ] Każda decyzja routingu ma trace ID i czytelne uzasadnienie.
- [ ] PostgreSQL jest źródłem prawdy; inference nie zależy od dostępności Angulara ani Langfuse.
- [ ] Compose uruchamia cały lokalny stack; migracje, seed, smoke, testy i backup są udokumentowane.
- [ ] Sekrety i pełne prywatne prompty nie trafiają domyślnie do repo/logów/trace'ów.

## 11. Instrukcja dla kolejnej sesji Codexa

1. Przeczytaj tylko ten plik, aktualny ADR dla wykonywanego etapu i pliki bezpośrednio objęte zmianą. Do pełnej specyfikacji wróć tylko przy niejasności produktu.
2. Sprawdź `git status`, ostatnie commity i checklistę etapu. Nie zmieniaj cudzych, niezwiązanych modyfikacji.
3. Wybierz pierwszy niezakończony punkt z najwcześniejszego rozpoczętego etapu. Nie implementuj funkcji z późniejszych faz „przy okazji”.
4. Przed kodem zapisz lub zaktualizuj test akceptacyjny dla danego slice'a.
5. Utrzymuj logikę domenową jako czyste funkcje; adaptery LiteLLM/DB/Redis/Langfuse nie mogą przenikać do scoringu.
6. Po zmianie uruchom najmniejszy trafny zestaw testów, potem `make check`; zaktualizuj checklistę tylko po faktycznym odbiorze.
7. Jeśli odkryjesz sprzeczność architektoniczną, dodaj ADR zamiast budować drugi wariant rozwiązania.

### Najbliższe zadanie

Rozpocząć **Etap 1** od podstawowego Compose: Caddy, Control API, dashboard, PostgreSQL i Redis. Langfuse dodać dopiero po uruchomieniu i przetestowaniu tego rdzenia.
