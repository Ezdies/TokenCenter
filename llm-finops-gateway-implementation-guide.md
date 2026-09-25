# Agentic FinOps Gateway — Implementation Guide

## 1. Cel projektu

Celem systemu jest zbudowanie centralnej bramy LLM, która:

- udostępnia jeden, zgodny z OpenAI API endpoint dla aplikacji i agentów,
- dynamicznie wybiera model i providera,
- preferuje modele darmowe oraz pule trial/promotional credits,
- minimalizuje koszt wejścia i wyjścia tokenowego,
- korzysta z cache, redukcji kontekstu, RAG i innych mechanizmów optymalizacyjnych,
- zapewnia fallbacki i automatyczne omijanie niedostępnych providerów,
- mierzy koszt, oszczędności, jakość, błędy i opóźnienia,
- posiada własny panel administracyjny w Angularze,
- pozwala zarządzać modelami, providerami, budżetami, politykami routingu i limitami,
- jest możliwy do uruchomienia lokalnie przez Docker Compose, a później rozszerzenia o Kubernetes.

System należy traktować jako **Agentic FinOps Gateway**, a nie tylko prosty proxy do OpenRoutera. Jego wyróżnikiem jest optymalizacja i ochrona wielokrokowych przepływów agentowych przed wywołaniem providera.

---

# 2. Docelowy stack

## Backend / infrastruktura

- **Python / FastAPI** — publiczny, stanowy Agent Gateway i Control API
- **LiteLLM Proxy** — wewnętrzny, bezstanowy adapter protokołów/providerów
- **OpenRouter** — agregator modeli i jeden z providerów
- **Redis** — exact cache, quota/rate counters, loop windows, budget leases, locks i health state
- **PostgreSQL** — źródło prawdy dla konfiguracji, modeli, providerów, triali, polityk i historii
- **pgvector** — embeddingi, semantic cache i prosty RAG
- **Langfuse** — tracing, usage, cost, latency, sesje, dashboardy LLM
- **Caddy lub Traefik** — reverse proxy

## Frontend

- **Angular**
- Angular Material lub PrimeNG
- RxJS
- Angular Signals tam, gdzie upraszczają stan
- ECharts / ngx-echarts albo Apache ECharts dla dashboardów
- opcjonalnie Tailwind CSS do layoutu i custom UI

## Deployment

Na początek:

- Docker Compose

Dopiero później, gdy faktycznie będzie potrzebne skalowanie:

- Kubernetes

Nie należy zaczynać projektu od Kubernetes.

---

# 3. Architektura wysokiego poziomu

```text
┌──────────────────────────────────────┐
│        Web / Apps / Agents / CLI     │
│         OpenAI-compatible API        │
└──────────────────┬───────────────────┘
                   │
                   ▼
┌──────────────────────────────────────┐
│       FastAPI Agent Gateway          │
│                                      │
│ auth/rate limit + OpenAI contract     │
│ context trimming and pruning          │
│ loop protection                       │
│ exact cache (Redis)                    │
│ semantic cache (PostgreSQL/pgvector)   │
│ budget lease + free-first policy       │
│ usage/savings ledger + tracing         │
└──────────────┬───────────────────────┘
               │ concrete allowed model/fallbacks
               ▼
┌──────────────────────────────────────┐
│       LiteLLM Proxy (internal)       │
│ protocol/provider adapters           │
│ bounded retry and fallback            │
│ circuit breakers                      │
│ virtual-key usage collection          │
└──────────────┬───────────────────────┘
               │
       ┌───────┼──────────┐
       ▼       ▼          ▼
  OpenRouter  Direct APIs  Local models (later)

Agent Gateway ──► PostgreSQL + pgvector
       │          configuration, ledger, semantic cache
       ├────────► Redis
       │          exact cache, loops, leases, health
       └────────► Langfuse
                  traces and analysis only
```

Caddy publikuje `/v1/*` wyłącznie z Agent Gatewaya. LiteLLM nie może być bezpośrednio osiągalny przez klientów, ponieważ ominęłoby to pruning, ochronę pętli, budżety i ledger.

---

# 4. Główna zasada projektowa

Aplikacje klienckie **nie powinny znać fizycznych modeli ani providerów**.

Zamiast:

```text
openrouter/qwen/...
openrouter/google/...
openai/gpt-...
groq/...
```

klient powinien używać logicznych aliasów:

```text
free
cheap
fast
smart
reasoning
coding
vision
long-context
auto
```

Przykład requestu:

```json
{
  "model": "auto",
  "messages": [
    {
      "role": "user",
      "content": "Wyjaśnij różnicę między Redis a PostgreSQL"
    }
  ]
}
```

Fizyczny model wybiera router.

Dzięki temu backend może zmienić model bez aktualizacji klientów.

---

# 5. Podział odpowiedzialności

## Caddy

Caddy kończy TLS, egzekwuje limity sieciowe i rozmiaru requestu oraz kieruje `/v1/*` i `/api/*` do Agent Gatewaya. Nie podejmuje decyzji domenowych; rate limit per tenant/key pozostaje w Gatewayu.

## LiteLLM

LiteLLM powinien odpowiadać przede wszystkim za:

- provider adapters,
- translację OpenAI/Anthropic/Gemini,
- ograniczone retries i fallbacki w obrębie listy dopuszczonej przez Gateway,
- circuit breakers,
- usage reporting dla virtual keys,
- integrację z Langfuse,
- techniczne limity providerów.

LiteLLM nie zawiera domenowej logiki pruning, loop detection, semantic cache ani free-first scoringu i nie jest publicznym ingress.

## FastAPI Agent Gateway / Policy Engine

Agent Gateway jest publicznym data plane i control plane. Korzysta z czystego pakietu Policy Engine i odpowiada za:

- uwierzytelnienie/autoryzację przed cache oraz mapowanie tenant/key do virtual key LiteLLM,
- zachowanie kontraktu OpenAI dla stream i non-stream,
- trimming starych tool outputs, HTML i JSON według deterministycznych reguł,
- wykrywanie powtarzalnych i naprzemiennych pętli tool calls,
- exact oraz bezpieczny semantic cache,
- dzierżawy budżetu z TTL i końcowe rozliczenie,
- czy w ogóle trzeba użyć LLM,
- jaki typ zadania otrzymano,
- jakich capabilities wymaga request,
- czy można użyć darmowego modelu,
- czy istnieje trial/promo, który warto zużyć,
- który provider ma zdrowy endpoint,
- jaki jest bieżący koszt,
- jaki jest oczekiwany poziom jakości,
- czy należy eskalować do mocniejszego modelu,
- ile tokenów można przeznaczyć na odpowiedź,
- zapis usage, oszczędności, flag optymalizacji i alertów.

## Redis

Redis powinien obsługiwać:

- exact cache,
- normalized cache,
- rate limiting,
- quota counters,
- model/provider health state,
- locks,
- okna `loop_protection:{tenant_id}:{session_id}` z TTL,
- dzierżawy `budget_lease:{tenant_id}:{key_id}:{request_id}` z TTL,
- tymczasowy stan sesji,
- liczniki użycia,
- krótkoterminowe summary sesji.

## PostgreSQL

PostgreSQL powinien być źródłem prawdy dla:

- providerów,
- modeli,
- aliasów modeli,
- polityk routingu,
- triali,
- credits,
- planów użytkowników,
- budżetów,
- konfiguracji,
- historii zmian,
- API keys metadata,
- persistent sessions,
- custom metrics,
- cache policies,
- partycjonowany `usage_ledger` z metrykami actual i saved,
- embeddingi oraz wpisy semantic cache przez rozszerzenie pgvector.

Redis nie może być głównym źródłem konfiguracji.
Rozszerzenie `vector` jest włączane idempotentną migracją wyłącznie w bazie gateway. Publiczne klucze są weryfikowane przez Agent Gateway przed cache i mapowane na stabilne identyfikatory billingowe LiteLLM.

---

# 6. Logical model tiers

Należy zdefiniować logiczne pule modeli.

Przykład:

```yaml
tiers:
  free:
    - provider: openrouter
      model: free-router
    - provider: google
      model: free-tier-model

  cheap:
    - provider: provider-a
      model: cheap-model-1
    - provider: provider-b
      model: cheap-model-2

  fast:
    - provider: provider-c
      model: fast-model

  smart:
    - provider: provider-d
      model: premium-model

  coding:
    - provider: provider-e
      model: code-model

  reasoning:
    - provider: provider-f
      model: reasoning-model

  vision:
    - provider: provider-g
      model: vision-model
```

Każdy model powinien mieć osobne metadata i capability flags.

---

# 7. Model Registry

Rekomendowana tabela PostgreSQL:

```text
models
--------------------------------------------------
id
provider_id
provider_model_id
name
alias
logical_tier

input_price_per_million
output_price_per_million
cached_input_price_per_million

is_free
is_trial
trial_expires_at
trial_tokens_left
trial_credit_left

rpm_limit
tpm_limit
daily_request_limit

context_window
max_output_tokens

supports_tools
supports_json
supports_vision
supports_audio
supports_reasoning
supports_embeddings
supports_streaming

quality_score
latency_score
reliability_score

priority
weight

enabled
last_healthcheck_at
created_at
updated_at
```

Nie wszystkie pola muszą być w MVP, ale schema powinien umożliwiać ich późniejsze dodanie.

---

# 8. Provider Registry

Tabela:

```text
providers
--------------------------------------------------
id
name
provider_type
base_url
api_key_secret_ref
priority
enabled

free_credit
credit_currency
credit_expires_at

rpm_limit
tpm_limit

health_status
last_error_at
last_429_at
p50_latency_ms
p95_latency_ms
error_rate

created_at
updated_at
```

Klucze API nie powinny być trzymane jawnie w bazie.

Preferowane:

- Docker secrets,
- environment variables,
- Vault / Infisical / Doppler w późniejszej fazie.

---

# 9. Pipeline routingu

Docelowy request pipeline:

```text
Request
   │
   ▼
Authentication + tenant/key mapping
   │
   ▼
Rate limit
   │
   ▼
Loop protection (session/tool-call window in Redis)
   │
   ├── loop → block + ledger + alert
   │
   ▼
Raw token estimation
   │
   ▼
Deterministic context pruning
   │
   ▼
Exact cache
   │
   ├── hit → return
   │
   ▼
Semantic cache eligibility
   │
   ├── hit → return
   │
   ▼
Task classification
   │
   ▼
Capability detection
   │
   ▼
Context/token estimation
   │
   ▼
Budget policy
   │
   ▼
Free/trial candidate selection
   │
   ▼
Health and quota filtering
   │
   ▼
Candidate scoring
   │
   ▼
Budget lease with TTL (paid traffic)
   │
   ▼
LiteLLM request
   │
   ├── success → settle lease + cache + ledger/metrics + return
   │
   └── error/429/timeout
            │
            ▼
     bounded LiteLLM fallback
            │
            ▼
     release/settle lease + ledger
```

Auth, rate limit i loop protection zawsze poprzedzają cache. Cache hit omija LiteLLM i providera, ale nie może ominąć wpisu usage/optimization w ledgerze.

---

# 10. Candidate scoring

Model można wybierać za pomocą funkcji scoringowej.

Przykład:

```text
score =
    cost_score        * 0.35 +
    quality_score     * 0.25 +
    latency_score     * 0.15 +
    reliability_score * 0.15 +
    quota_score       * 0.10
```

Wagi muszą być konfigurowalne.

Dla trybu `prefer_free=true` koszt może mieć większą wagę.

Dla trybu `quality_first=true` większą wagę powinien mieć quality score.

Dla requestów czasu rzeczywistego większą wagę ma latency.

---

# 11. Routing free-first

Dla większości zwykłych requestów:

```text
cache
  ↓
free model
  ↓
cheap paid model
  ↓
premium model
```

Nie każdy request powinien automatycznie trafiać do najlepszego modelu.

Free model należy pominąć, gdy:

- nie obsługuje wymaganych tools,
- nie obsługuje vision,
- ma zbyt małe okno kontekstu,
- został rate limited,
- provider jest degraded,
- historyczny quality score jest zbyt niski dla danego task type.

---

# 12. Progressive escalation

Warto wdrożyć wielopoziomową eskalację.

Przykład:

```text
free model
    │
    ├── acceptable → return
    │
    └── low confidence / invalid output
             ↓
       cheap paid model
             │
             ├── acceptable → return
             │
             └── fail
                  ↓
             premium model
```

Kryteria eskalacji mogą obejmować:

- błąd providera,
- HTTP 429,
- timeout,
- invalid JSON,
- niezgodność z JSON Schema,
- tool-call failure,
- refusal niepasujący do polityki aplikacji,
- bardzo krótka / pusta odpowiedź,
- self-evaluation score poniżej progu,
- validator rules.

Nie należy używać dodatkowego LLM do walidacji każdej odpowiedzi, jeśli da się zastosować tani deterministyczny validator.

---

# 13. Trial-aware routing

System powinien umieć aktywnie wykorzystywać triale i promocyjne kredyty.

Przykład:

```text
Provider A
credit: $10
expires: 2026-10-01

Provider B
credit: $100
expires: never
```

Provider A powinien mieć większy priorytet, jeżeli jego credit wygaśnie szybciej.

Przykładowa funkcja:

```text
effective_cost =
    monetary_cost
    + quality_penalty
    + latency_penalty
    + reliability_penalty
    + expiration_penalty
```

Dla expiring credits `expiration_penalty` może być ujemne, czyli zachęcać router do zużycia środków przed wygaśnięciem.

---

# 14. Cache strategy

Caching ma mieć kilka warstw.

## 14.1 Exact cache

Klucz generowany z:

```text
model tier
system prompt
messages
tools
temperature
response format
relevant policy
```

Przykład:

```text
SHA256(canonical_json(request))
```

TTL powinien być zależny od typu zapytania.

Przykładowe wartości:

```text
classification    7d
FAQ               24h
RAG query          1h
code explanation   2h
general chat       10m
```

---

## 14.2 Normalized cache

Przed hashowaniem można normalizować:

- whitespace,
- case tam, gdzie ma to sens,
- request_id,
- tracking metadata,
- timestampy,
- kolejność nieistotnych metadata,
- techniczne parametry niezmieniające odpowiedzi.

Należy uważać, żeby normalizacja nie zmieniła znaczenia requestu.

---

## 14.3 Semantic cache

Pipeline:

```text
query
  ↓
embedding
  ↓
vector similarity search
  ↓
reusable cached response?
```

Na początek można użyć pgvector zamiast osobnego vector DB.

Wpis semantic cache powinien zawierać co najmniej `tenant_id`, namespace, embedding `vector(n)`, hash wejścia, zredagowaną odpowiedź lub bezpieczny odnośnik, identyfikator i wersję modelu embeddingowego, policy/source version, próg podobieństwa oraz `created_at`/`expires_at`. Zmiana którejkolwiek wersji powoduje miss. Dla małego MVP wystarczy dokładne porównanie; HNSW/IVFFlat należy dodać dopiero po pomiarach liczności i opóźnień.

Semantic cache jest dobry dla:

- FAQ,
- supportu,
- dokumentacji,
- knowledge base,
- powtarzalnych pytań.

Nie należy używać semantic cache dla:

- aktualności,
- cen,
- pogody,
- informacji zależnych od czasu,
- danych użytkownika,
- operacji narzędziowych,
- kroków agentowych z tool calls, zmiennym stanem lub side effects,
- requestów powodujących side effects.

Można użyć semantic cache dla idempotentnej, końcowej odpowiedzi agenta, jeśli polityka ma jawny opt-in, tenant/namespace są zgodne, freshness jest potwierdzona, a format odpowiedzi i capabilities są kompatybilne. Awaria pgvector albo generowania embeddingu powoduje cache bypass, nie błąd inference.

---

# 15. Cache invalidation

Cache entries powinny mieć metadata:

```json
{
  "created_at": "...",
  "expires_at": "...",
  "source_version": "...",
  "knowledge_base_version": "...",
  "model_tier": "cheap",
  "cache_policy": "faq-v1"
}
```

Dzięki temu można unieważniać odpowiedzi po:

- aktualizacji dokumentacji,
- zmianie system promptu,
- zmianie polityki,
- zmianie danych źródłowych.

---

# 16. Redukcja kontekstu

Nie wolno automatycznie wysyłać całej rozmowy do modelu.

MVP zaczyna od deterministycznego pruning: usuwa stare, zastąpione wyniki narzędzi, redukuje nadmiarowy HTML i historyczny JSON według limitów polityki. System prompt, ostatnie wiadomości i aktywne pary `tool_call`/`tool_result` są chronione. Jeżeli nie da się dowieść spójności historii, pruner wykonuje bypass.

Przed i po transformacji należy zapisać liczniki `raw_prompt_tokens`, `pruned_prompt_tokens` i `saved_tokens_count`, a także zastosowane reguły i hashe wejścia/wyjścia. Pełne treści oraz diff „agent vs model” są domyślnie wyłączone; opt-in wymaga redakcji, szyfrowania, RBAC i krótkiej retencji.

Docelowy context builder:

```text
system prompt
+
conversation summary
+
last N messages
+
relevant memories
+
RAG context
```

Przykład:

```text
system prompt           500 tokens
conversation summary   1000 tokens
last messages          2000 tokens
RAG context            1500 tokens
---------------------------------
total                  5000 tokens
```

zamiast np. 30k–100k tokenów całej historii.

---

# 17. Dynamic conversation summarization

Po przekroczeniu progu należy streszczać starszą część rozmowy.

Przykład:

```python
if estimated_context_tokens > 8000:
    summarize_old_messages()
```

Lepsze od zwykłego tekstowego summary jest summary strukturalne:

```json
{
  "facts": [],
  "user_preferences": [],
  "constraints": [],
  "decisions": [],
  "open_questions": [],
  "important_results": []
}
```

Summary może być przechowywane w Redis dla aktywnej sesji i okresowo synchronizowane do PostgreSQL.

---

# 18. RAG

Nie należy wrzucać całych dokumentów do promptu.

Pipeline:

```text
documents
   ↓
chunking
   ↓
embeddings
   ↓
pgvector
   ↓
retrieval
   ↓
top-k relevant chunks
   ↓
LLM
```

Początkowe wartości do testów:

```text
chunk size:       500-1000 tokenów
overlap:          50-150 tokenów
top-k:            3-6
```

Warto testować hybrid search:

- vector similarity,
- full-text search PostgreSQL,
- re-ranking dla ważniejszych use case'ów.

---

# 19. Prompt optimization

Należy unikać bardzo dużych system promptów.

Zamiast jednego promptu 3000-5000 tokenów:

```text
base prompt
+
task-specific prompt
+
only required policy fragments
+
dynamic context
```

System prompt powinien być modularny.

Przykład:

```text
base              400 tokens
coding rules      300 tokens
response format   150 tokens
dynamic context   200 tokens
```

---

# 20. Output token budgeting

`max_tokens` nie powinno być jednakowe dla wszystkich requestów.

Przykład:

```text
classification       20
short_answer        300
chat                 800
code                2500
complex_analysis    4000
```

API może wspierać dodatkowy policy object:

```json
{
  "model": "auto",
  "policy": {
    "prefer_free": true,
    "max_cost_usd": 0.002,
    "latency_target_ms": 2000,
    "quality_profile": "balanced",
    "output_budget_tokens": 700
  }
}
```

Jeżeli kompatybilność z OpenAI API musi być pełna, policy można przekazywać przez headers lub metadata.

---

# 21. Provider health management

Każdy provider powinien mieć stan:

```text
healthy
degraded
rate_limited
disabled
down
```

Redis może trzymać bieżące metryki:

```text
provider:<id>:error_rate
provider:<id>:p50_latency
provider:<id>:p95_latency
provider:<id>:last_429
provider:<id>:consecutive_errors
provider:<id>:health_state
```

Circuit breaker:

```text
5 errors in 30s
→ degraded

10 errors in 60s
→ temporary disabled

successful health checks
→ healthy
```

Progi muszą być konfigurowalne.

---

# 22. Retry policy

Nie należy ślepo ponawiać wszystkich requestów.

Retry można wykonać dla:

- timeout,
- 429,
- wybranych 5xx,
- transient network error.

Nie retry dla:

- 400,
- invalid prompt,
- invalid request schema,
- auth failure,
- deterministic validation error.

Preferowany model:

```text
retry same provider once
→ fallback same tier
→ fallback alternate provider
→ escalation
```

---

# 23. Observability — Langfuse

Langfuse powinien być głównym narzędziem do observability LLM.

Każdy request powinien raportować:

- trace id,
- user id / tenant id,
- logical model tier,
- actual provider,
- actual model,
- input tokens,
- output tokens,
- cache hit status,
- cache type,
- cost,
- estimated avoided cost,
- latency,
- fallback count,
- retry count,
- task type,
- status,
- validation result.

---

# 24. Cost avoided

System powinien liczyć nie tylko koszt faktyczny, ale też oszczędność.

Przykład:

```text
requested tier: smart
reference cost: $0.0041
actual model: free model
actual cost: $0.0000
saved: $0.0041
```

Metryki:

```text
total_cost
estimated_reference_cost
cost_avoided
cache_savings
free_tier_savings
trial_savings
context_reduction_savings
```

To powinno być jednym z głównych KPI dashboardu.

Źródłem tych KPI jest miesięcznie partycjonowany `usage_ledger`, a nie agregaty Langfuse. Minimalny rekord zawiera:

```text
request_id, attempt_id, trace_id, tenant_id, key_id
provider_id, model_id, logical_tier
input_tokens, output_tokens, actual_cost
raw_prompt_tokens, pruned_prompt_tokens, saved_tokens_count
estimated_reference_cost, estimated_cost_saved
cache_status, cache_type, optimization_flags
status, occurred_at
```

Idempotency key to `request_id + attempt_id`. `optimization_flags` obejmuje co najmniej `TOOL_PRUNED`, `CONTEXT_PRUNED`, `LOOP_BLOCKED`, `EXACT_HIT` i `SEMANTIC_HIT`. Breakdown oszczędności musi zapobiegać podwójnemu przypisaniu tych samych tokenów lub kosztu do kilku mechanizmów.

---

# 25. Angular Agentic FinOps Dashboard

Frontend ma być zbudowany w Angularze.

Proponowana struktura aplikacji:

```text
/src/app

  core/
    api/
    auth/
    guards/
    interceptors/
    services/

  shared/
    components/
    pipes/
    directives/
    models/

  features/
    overview/
    providers/
    models/
    routes/
    policies/
    free-tiers/
    trials/
    budgets/
    users/
    api-keys/
    cache/
    traces/
    efficiency/
    loop-alerts/
    playground/
    settings/
```

Preferowany Angular:

- standalone components,
- lazy-loaded routes,
- Signals dla lokalnego stanu UI,
- RxJS dla streamów HTTP i eventów,
- typed API clients,
- strict TypeScript.

---

# 26. Ekrany dashboardu

## Overview

KPI:

```text
Requests today
Tokens today
Cost today
Cost avoided
Tokens saved
Cache hit ratio
Free model usage
Trial usage
Paid model usage
p50 latency
p95 latency
Fallback rate
Error rate
```

Wykresy:

- koszt w czasie,
- tokeny w czasie,
- requests/model,
- requests/provider,
- cache hit ratio,
- free vs paid,
- latency per provider,
- error rate per provider,
- saved tokens i cost saved w czasie,
- breakdown oszczędności: pruning, exact cache, semantic cache i free-first,
- liczba i trend intercepcji pętli.

## Agent efficiency

Dedykowany widok pokazuje `saved_tokens_count`, `estimated_cost_saved`, koszt rzeczywisty oraz breakdown według mechanizmu, polityki, tenantu i modelu referencyjnego. Wartości estymowane muszą być oznaczone jako estymaty i wskazywać przyjętą cenę referencyjną.

## Pruning traces

Widok trace'a pokazuje zastosowane reguły, raw/pruned/saved token counts i zredagowany diff „agent input vs provider input”. Pełna treść jest widoczna tylko przy tenant opt-in, odpowiednim RBAC i przed upływem retencji.

## Loop alerts

Lista zawiera tenant/session, rodzaj wykrytego wzorca, licznik, czas blokady i trace ID. Argumenty narzędzi są hashowane lub redagowane; dashboard nie ujawnia sekretów.

---

## Models

Tabela:

```text
Model
Provider
Tier
Input price
Output price
Free/Trial
Context
Tools
Vision
JSON
Health
Priority
Enabled
```

Widok szczegółowy modelu:

- priority,
- weight,
- capability flags,
- limits,
- fallback chain,
- usage,
- cost history,
- latency,
- errors,
- trial state.

---

## Providers

Dane:

- status,
- API connectivity,
- current credit,
- trial expiration,
- RPM,
- TPM,
- error rate,
- latency,
- last 429,
- enabled/disabled.

---

## Routing Policies

GUI do konfiguracji reguł.

Przykład:

```text
Rule: simple-chat

Task type: simple_qa
Prefer free: yes
Max input tokens: 8k
Max output tokens: 600
Required capabilities: none
Fallback tier: cheap
Escalation tier: smart
```

---

## Free tiers

Tabela:

```text
Provider
Model
Limit type
Remaining quota
Reset time
Health
Last used
```

---

## Trials

Tabela:

```text
Provider
Credit left
Expires at
Days remaining
Usage today
Recommended priority
```

Powinny istnieć warningi dla triali, które zaraz wygasają.

---

## Cache

Dashboard:

- exact cache hit rate,
- semantic cache hit rate,
- cache size,
- saved requests,
- estimated savings,
- TTL distribution,
- manual purge,
- purge by namespace,
- purge by knowledge base version.

---

## Playground

Panel testowy podobny do prostych chat playgroundów.

Opcje:

```text
logical model
provider override
model override
temperature
max tokens
system prompt
policy profile
streaming
```

Po odpowiedzi pokazać:

```text
actual provider
actual model
input tokens
output tokens
cost
latency
cache hit
fallbacks
estimated savings
raw/pruned/saved prompt tokens
optimization flags
```

---

# 27. API dla Angulara

Control API jest modułem tego samego FastAPI Agent Gateway, ale ma oddzielne routery, auth/RBAC i kontrakty od publicznego `/v1/*`.

Przykładowe endpointy:

```text
GET    /api/providers
POST   /api/providers
PATCH  /api/providers/:id
DELETE /api/providers/:id

GET    /api/models
POST   /api/models
PATCH  /api/models/:id

GET    /api/policies
POST   /api/policies
PATCH  /api/policies/:id

GET    /api/dashboard/overview
GET    /api/dashboard/costs
GET    /api/dashboard/providers
GET    /api/dashboard/savings

GET    /api/cache/stats
POST   /api/cache/purge

GET    /api/traces/:trace_id/pruning
GET    /api/loop-alerts

GET    /api/trials
GET    /api/free-tiers

POST   /api/playground/chat
```

Frontend nie powinien komunikować się bezpośrednio z Redisem ani PostgreSQL.

---

# 28. Redis key naming

Przyjąć spójny namespace.

Przykład:

```text
llm:cache:exact:<hash>
llm:cache:normalized:<hash>
llm:ratelimit:user:<id>
llm:ratelimit:key:<id>

llm:quota:provider:<id>
llm:quota:model:<id>

llm:health:provider:<id>
llm:health:model:<id>

llm:session:<id>:summary
llm:session:<id>:state

llm:loop_protection:<tenant_id>:<session_id>
llm:budget_lease:<tenant_id>:<key_id>:<request_id>

llm:lock:<resource>
```

Loop protection przechowuje kanoniczne hashe `(tool_name, normalized_arguments, relevant_result_state)` w ograniczonym oknie z TTL oraz wykrywa powtórzenia i wzorce A/B. Budget lease ma nieprzekraczalny TTL (dla MVP 60 s), unikalny `lease_id` i stan umożliwiający idempotentne settle/release. Worker reconciliacyjny porównuje wygasłe dzierżawy z ledgerem. Awaria Redisa oznacza fail-closed dla płatnego modelu, ale może pozostawić dostępny model faktycznie darmowy.

---

# 29. Security

Minimalne wymagania:

- osobne API keys dla klientów,
- hashed API key identifiers w bazie,
- secrets poza repo,
- RBAC dla dashboardu,
- admin/user roles,
- audit log zmian konfiguracji,
- brak pełnego logowania prywatnych promptów domyślnie,
- możliwość maskowania PII,
- TLS,
- CORS ograniczony do znanych origins,
- rate limiting per user / key / tenant.

Dla danych w Langfuse należy rozważyć redaction przed wysłaniem trace.

---

# 30. Multi-tenancy

Jeżeli system będzie używany przez więcej niż jeden zespół/klienta, warto od początku dodać:

```text
tenant_id
```

do:

- API keys,
- users,
- budgets,
- policies,
- traces metadata,
- cache namespace tam, gdzie odpowiedzi nie mogą być współdzielone.

Nie wolno współdzielić semantic cache pomiędzy tenantami bez jawnie zdefiniowanej polityki.

---

# 31. Request policy profiles

Warto stworzyć kilka gotowych profili.

## economy

```yaml
prefer_free: true
max_cost_usd: 0.001
quality_profile: acceptable
latency_target_ms: 5000
allow_escalation: true
max_escalation_tier: cheap
```

## balanced

```yaml
prefer_free: true
max_cost_usd: 0.01
quality_profile: balanced
latency_target_ms: 3000
allow_escalation: true
max_escalation_tier: smart
```

## quality

```yaml
prefer_free: false
quality_profile: high
latency_target_ms: 8000
allow_escalation: true
max_escalation_tier: premium
```

## realtime

```yaml
prefer_free: false
quality_profile: balanced
latency_target_ms: 1200
prioritize_latency: true
```

---

# 32. Task classification

Na początku klasyfikacja powinna być możliwie tania.

Najpierw reguły deterministyczne:

```text
tools present        → tool task
image input          → vision
response_format json → structured output
large context        → long-context
```

Dopiero jeżeli nie da się ustalić klasy zadania regułami, można użyć małego i taniego modelu klasyfikującego.

Przykładowe task types:

```text
simple_qa
classification
summarization
translation
coding
reasoning
rag_qa
vision
structured_output
tool_use
creative
long_context
```

---

# 33. Capability matching

Router musi filtrować modele przed scoringiem.

Przykład:

```python
if request.requires_tools and not model.supports_tools:
    reject_candidate()

if request.requires_vision and not model.supports_vision:
    reject_candidate()

if input_tokens > model.context_window:
    reject_candidate()
```

Dopiero po capability filtering należy liczyć score.

---

# 34. Token estimation

Przed requestem należy estymować token usage.

Potrzebne do:

- limitów,
- routingu,
- oceny kosztu,
- wyboru long-context model,
- decyzji o summarization.

Nie musi być idealnie dokładne. Ważne, żeby było konserwatywne.

---

# 35. Budget enforcement

Budżety mogą działać per:

- API key,
- user,
- tenant,
- project,
- provider,
- logical model tier,
- dzień,
- miesiąc.

Przykład:

```text
Tenant A
monthly budget: $50
warning: 80%
hard stop: 100%
```

Można też zastosować degradation policy:

```text
0-80% budget   → normal
80-95%         → prefer free
95-100%        → free + cheap only
100%           → free only / reject
```

---

# 36. Prompt caching providerów

Oprócz Redis cache należy wykorzystywać natywne mechanizmy prompt caching providerów tam, gdzie występują.

Warstwa routingowa powinna przechowywać metadata:

```text
supports_prompt_cache
prompt_cache_strategy
cached_input_price
```

Długi stały prefix powinien być ułożony tak, aby provider mógł go skutecznie cache'ować.

---

# 37. Batching

Dla zadań offline warto dodać batch queue.

Przykłady:

- masowe klasyfikacje,
- embeddings,
- analizowanie dokumentów,
- generowanie tagów,
- summarization batch.

Możliwe rozszerzenie:

- Celery + Redis,
- Dramatiq,
- Arq,
- RabbitMQ w większym wdrożeniu.

W MVP nie jest wymagane.

---

# 38. Background jobs

Zadania cykliczne:

- provider health check,
- quota refresh,
- trial expiration checks,
- pricing refresh,
- model availability refresh,
- cache cleanup,
- aggregation metrics,
- stale session cleanup.

Do MVP można użyć APScheduler / Celery Beat / prostego workera.

---

# 39. Health checks

Każdy provider powinien mieć dwa poziomy health checków.

## Level 1

HTTP/API connectivity.

## Level 2

Tani minimalny inference test, uruchamiany rzadziej.

Nie należy wykonywać drogiego inference health checku co kilka sekund.

---

# 40. Minimalny Docker Compose

Kontenery:

```text
reverse-proxy
litellm
agent-gateway
angular-dashboard
postgres-with-pgvector
redis
langfuse-web
langfuse-worker
langfuse-db / dependencies
```

W zależności od aktualnego sposobu deploymentu Langfuse część usług może się różnić.

---

# 41. Suggested repository structure

```text
repo/

  apps/
    agent-gateway/
    dashboard-angular/

  infrastructure/
    docker/
    litellm/
    redis/
    postgres/
    reverse-proxy/
    langfuse/

  packages/
    policy-engine/
    model-registry/
    cache/
    routing/
    telemetry/

  migrations/

  scripts/

  docs/
    architecture.md
    routing.md
    caching.md
    deployment.md

  docker-compose.yml
  .env.example
  README.md
```

---

# 42. Faza 1 — MVP

Zakres:

1. FastAPI Agent Gateway jako jedyny publiczny `/v1/*` oraz Control API
2. wewnętrzny LiteLLM Proxy i OpenRouter integration
3. Redis: exact cache, loop windows, budget leases, health i counters
4. PostgreSQL + pgvector: konfiguracja, partycjonowany ledger i semantic cache
5. deterministyczny context/tool-output pruning
6. loop protection per tenant/session
7. logical model aliases i basic free-first routing
8. budget lease z TTL i reconciliation
9. exact cache oraz ograniczony semantic cache
10. provider health, retry i fallback
11. Langfuse
12. Angular Agentic FinOps dashboard
13. saved-token/cost metrics, pruning traces i loop alerts

Nie wdrażać jeszcze wszystkiego naraz.

---

# 43. Faza 2 — rozszerzona optymalizacja kosztu

Dodać:

- strukturalne conversation summarization,
- rozszerzenie semantic cache po pomiarach jakości,
- dynamic output limits,
- trial-aware routing,
- dokładniejsze modele referencyjne cost avoided,
- policy profiles,
- advanced dashboardy,
- cache invalidation groups.

---

# 44. Faza 3 — quality-aware routing

Dodać:

- validators,
- per-task model scores,
- automatic escalation,
- A/B tests modeli,
- quality evaluation,
- latency-aware scoring,
- reliability-aware scoring,
- automated policy tuning.

---

# 45. Faza 4 — rozszerzenia

Opcjonalnie:

- lokalne modele przez vLLM,
- Ollama dla developmentu,
- Kubernetes,
- dedicated vector DB,
- batch processing,
- per-tenant billing,
- invoice/export,
- alerting,
- advanced RBAC,
- secrets manager.

---

# 46. KPI projektu

Najważniejsze metryki:

```text
cost/request
cost/1k requests
input tokens/request
output tokens/request
cache hit ratio
free-tier usage %
trial usage %
paid usage %
cost avoided
fallback rate
error rate
p50 latency
p95 latency
quality score
```

Celem systemu nie jest tylko minimalny koszt.

Docelowa optymalizacja:

```text
minimal cost
subject to:
  acceptable quality
  acceptable latency
  reliability constraints
```

---

# 47. Najważniejsza reguła FinOps

Kolejność oszczędności:

1. Nie wywołuj LLM, jeśli nie trzeba.
2. Użyj cache, jeśli wynik można bezpiecznie wykorzystać ponownie.
3. Ogranicz kontekst.
4. Użyj RAG zamiast całych dokumentów.
5. Wybierz najmniejszy model spełniający wymagania.
6. Preferuj free/trial capacity.
7. Ogranicz output tokens.
8. Eskaluj tylko wtedy, gdy tańszy model nie wystarczył.
9. Używaj provider prompt caching.
10. Batchuj zadania offline.

---

# 48. Przykładowa polityka `auto`

```yaml
name: auto-balanced

prefer_cache: true
prefer_free: true
allow_trial: true
allow_paid: true

max_cost_usd: 0.01
latency_target_ms: 3000

context:
  summarize_above_tokens: 8000
  keep_last_messages: 6
  rag_top_k: 4

routing:
  start_tier: free
  fallback_tier: cheap
  escalation_tier: smart

validation:
  require_valid_json_when_requested: true
  reject_empty_response: true

output:
  default_max_tokens: 800
  classification_max_tokens: 30
  coding_max_tokens: 2500
```

---

# 49. Przykładowy decision flow

```python
def select_model(request, user, policy):
    authenticate_and_rate_limit(request, user)

    session = resolve_session(request)
    if loop_detected(session, request):
        record_optimization("LOOP_BLOCKED")
        raise AgentLoopError()

    raw_tokens = estimate_tokens(request)
    request, pruning_log = safely_prune_context(request, policy)
    pruned_tokens = estimate_tokens(request)

    if exact_cache_hit(request):
        record_cache_usage_and_savings("EXACT_HIT", raw_tokens, pruned_tokens)
        return cached_response()

    if semantic_cache_allowed(request):
        hit = semantic_cache_lookup(request)
        if hit:
            record_cache_usage_and_savings("SEMANTIC_HIT", raw_tokens, pruned_tokens)
            return hit

    task = classify_task(request)
    capabilities = detect_capabilities(request)

    candidates = registry.find_candidates(
        task=task,
        capabilities=capabilities,
        policy=policy,
    )

    candidates = filter_by_health(candidates)
    candidates = filter_by_quota(candidates)
    candidates = filter_by_budget(candidates, policy)

    ranked = rank_candidates(candidates, policy)
    lease = acquire_budget_lease(ranked, request, ttl_seconds=60)

    try:
        result = execute_via_litellm(ranked, request)
        if result.success and validate(result):
            settle_budget_lease(lease, result.usage)
            store_eligible_caches(request, result)
            record_usage_and_savings(result, pruning_log)
            return result
    finally:
        release_or_reconcile_lease(lease)

    raise NoAvailableModelError()
```

---

# 50. Definition of Done dla MVP

MVP można uznać za ukończone, gdy:

- klient korzysta z jednego OpenAI-compatible endpointu,
- Caddy kieruje inference do FastAPI Agent Gateway, a LiteLLM nie jest publicznie dostępny,
- można dodać/wyłączyć providera z dashboardu,
- można dodać/wyłączyć model z dashboardu,
- `model=auto` wybiera model dynamicznie,
- free tier jest preferowany dla prostych requestów,
- fallback działa przy błędzie providera,
- exact cache działa przez Redis,
- semantic cache działa przez PostgreSQL + pgvector tylko dla bezpiecznych żądań,
- pruning raportuje raw/pruned/saved tokens bez naruszania spójności tool calls,
- loop protection blokuje zapętloną sesję przed LiteLLM,
- budżet jest rezerwowany dzierżawą Redis z TTL i rozliczany idempotentnie,
- wykorzystanie i koszt trafiają do Langfuse,
- partycjonowany ledger przechowuje usage, oszczędności i optimization flags,
- Angular dashboard pokazuje requesty, koszt, modele, efficiency, pruning traces i loop alerts,
- PostgreSQL przechowuje konfigurację,
- budżet można ustawić per API key lub user,
- provider health wpływa na routing,
- logi pozwalają ustalić dlaczego wybrano konkretny model.

---

# 51. Zasady dla agenta implementującego system

Agent powinien przestrzegać następujących zasad:

1. Nie implementować logiki biznesowej bezpośrednio w komponentach Angulara.
2. Nie przechowywać trwałej konfiguracji wyłącznie w Redisie.
3. Nie kodować providerów i modeli na sztywno w routerze.
4. Wszystkie modele mają pochodzić z Model Registry.
5. Wszystkie decyzje routingu powinny być możliwe do wyjaśnienia w logach.
6. Każdy request powinien mieć correlation/trace ID.
7. Każdy fallback powinien być rejestrowany.
8. Każda decyzja cache powinna być mierzalna.
9. Wszystkie koszty powinny być liczone według metadata modelu.
10. Polityki powinny być konfigurowalne, nie zaszyte w kodzie.
11. Capability filtering ma następować przed scoringiem.
12. Free model nie może być użyty, jeśli nie spełnia wymaganych capabilities.
13. Provider z aktywnym circuit breakerem nie może być wybierany.
14. Semantic cache musi respektować tenant boundaries i freshness rules.
15. UI musi rozróżniać logical model od actual provider/model.
16. Angular dashboard powinien być administracyjnym control plane, a nie częścią inference path.
17. Inference API musi działać nawet wtedy, gdy dashboard jest niedostępny.
18. Langfuse ma być observability layer, a nie źródłem konfiguracji.
19. PostgreSQL ma być źródłem prawdy dla konfiguracji.
20. Redis ma być warstwą szybkiego, nietrwałego stanu.
21. Auth, rate limit i loop protection muszą poprzedzać każdy cache lookup.
22. Cache hit musi tworzyć ledger entry mimo ominięcia LiteLLM.
23. LiteLLM może wykonać fallback tylko w zbiorze dopuszczonym przez Gateway.
24. Pruning przy niepewności ma wykonać bypass, nie ryzykowną transformację.
25. Pełny diff promptów wymaga opt-in, redakcji, RBAC, szyfrowania i retencji.

---

# 52. Priorytety implementacyjne

Jeśli agent musi wybierać pomiędzy dodatkowymi funkcjami, kolejność priorytetów jest następująca:

```text
1. reliability
2. correct routing
3. observability
4. budget enforcement
5. caching
6. context optimization
7. trial/free optimization
8. dashboard ergonomics
9. advanced quality routing
10. infrastructure scaling
```

---

# 53. Docelowy efekt

Klient powinien móc wysłać:

```json
{
  "model": "auto",
  "messages": [
    {
      "role": "user",
      "content": "Przeanalizuj ten kod i znajdź problem"
    }
  ]
}
```

A system powinien samodzielnie:

```text
1. uwierzytelnić request i sprawdzić rate limit,
2. wykryć pętlę narzędzi w sesji,
3. policzyć raw tokens i bezpiecznie przyciąć kontekst,
4. sprawdzić exact, a następnie kwalifikowany semantic cache,
5. sklasyfikować zadanie jako coding,
6. odrzucić modele bez wymaganych capabilities,
7. sprawdzić free/trial capacity, health i budżet,
8. wybrać najlepszy kandydat według policy,
9. zarezerwować budget lease dla płatnego ruchu,
10. wykonać request przez LiteLLM i w razie potrzeby bounded fallback,
11. rozliczyć lub zwolnić lease,
12. zapisać trace i partycjonowany ledger,
13. policzyć koszt, saved tokens i cost avoided,
14. zapisać kwalifikowany cache,
15. zwrócić odpowiedź klientowi.
```

To jest docelowa definicja systemu: **stanowa, obserwowalna i kosztowo zoptymalizowana brama Agentic FinOps do wielu modeli LLM**.
