# LLM FinOps Gateway — Implementation Guide

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

System należy traktować jako **LLM FinOps Gateway**, a nie tylko prosty proxy do OpenRoutera.

---

# 2. Docelowy stack

## Backend / infrastruktura

- **LiteLLM Proxy** — centralny gateway LLM
- **OpenRouter** — agregator modeli i jeden z providerów
- **Redis** — cache, quota counters, rate limiting, temporary state, locks, health state
- **PostgreSQL** — źródło prawdy dla konfiguracji, modeli, providerów, triali, polityk i historii
- **pgvector** — embeddingi, semantic cache i prosty RAG
- **Langfuse** — tracing, usage, cost, latency, sesje, dashboardy LLM
- **Python / FastAPI** — własna warstwa Policy Engine / Control API
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
│             LiteLLM Proxy            │
│                                      │
│ auth                                 │
│ virtual keys                         │
│ budgets                              │
│ basic routing                        │
│ retries                              │
│ provider fallbacks                   │
│ usage collection                     │
└─────────────┬──────────────┬─────────┘
              │              │
              │              ▼
              │      ┌───────────────────┐
              │      │       Redis       │
              │      │                   │
              │      │ exact cache       │
              │      │ semantic cache    │
              │      │ quota counters    │
              │      │ rate limiting     │
              │      │ provider health   │
              │      │ session state     │
              │      └───────────────────┘
              │
              ▼
┌──────────────────────────────────────┐
│      Policy Engine / Smart Router    │
│                                      │
│ task classification                  │
│ capability matching                  │
│ budget-aware routing                 │
│ free-first routing                   │
│ trial-aware routing                  │
│ context-aware routing                │
│ provider-health routing              │
│ escalation                           │
└─────────────┬────────────────────────┘
              │
     ┌────────┼───────────────┐
     │        │               │
     ▼        ▼               ▼
 OpenRouter  Direct APIs    Local models
             OpenAI         Ollama
             Google         vLLM
             Groq
             Anthropic
             others

              │
              ▼
       ┌───────────────┐
       │   Langfuse    │
       │ traces/cost   │
       │ latency       │
       │ dashboards    │
       └───────────────┘
```

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

## LiteLLM

LiteLLM powinien odpowiadać przede wszystkim za:

- jednolity endpoint API,
- auth,
- virtual API keys,
- podstawowe limity,
- provider adapters,
- retries,
- fallbacki,
- usage reporting,
- integrację z Langfuse,
- podstawowe budżety.

## Policy Engine

Własny Policy Engine powinien odpowiadać za logikę biznesową:

- czy w ogóle trzeba użyć LLM,
- jaki typ zadania otrzymano,
- jakich capabilities wymaga request,
- czy można użyć darmowego modelu,
- czy istnieje trial/promo, który warto zużyć,
- który provider ma zdrowy endpoint,
- jaki jest bieżący koszt,
- jaki jest oczekiwany poziom jakości,
- czy należy eskalować do mocniejszego modelu,
- ile tokenów można przeznaczyć na odpowiedź.

## Redis

Redis powinien obsługiwać:

- exact cache,
- normalized cache,
- semantic cache metadata,
- rate limiting,
- quota counters,
- model/provider health state,
- locks,
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
- cache policies.

Redis nie może być głównym źródłem konfiguracji.

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
Authentication
   │
   ▼
Rate limit
   │
   ▼
Exact cache
   │
   ├── hit → return
   │
   ▼
Normalized cache
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
LLM request
   │
   ├── success → cache + metrics + return
   │
   └── error/429/timeout
            │
            ▼
         fallback
            │
            ▼
         escalation
```

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
- działań agentowych,
- requestów powodujących side effects.

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

---

# 25. Angular Admin Dashboard

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
- error rate per provider.

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
```

---

# 27. API dla Angulara

Własny Control API może być zbudowany w FastAPI.

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

GET    /api/cache/stats
POST   /api/cache/purge

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
llm:cache:semantic:<id>

llm:ratelimit:user:<id>
llm:ratelimit:key:<id>

llm:quota:provider:<id>
llm:quota:model:<id>

llm:health:provider:<id>
llm:health:model:<id>

llm:session:<id>:summary
llm:session:<id>:state

llm:lock:<resource>
```

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
control-api
angular-dashboard
postgres
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
    control-api/
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

1. LiteLLM Proxy
2. OpenRouter integration
3. Redis
4. PostgreSQL
5. Langfuse
6. Control API
7. Angular dashboard
8. logical model aliases
9. basic free-first routing
10. exact cache
11. budget tracking
12. provider health
13. basic fallback

Nie wdrażać jeszcze wszystkiego naraz.

---

# 43. Faza 2 — optymalizacja kosztu

Dodać:

- context trimming,
- conversation summarization,
- semantic cache,
- dynamic output limits,
- trial-aware routing,
- cost avoided metrics,
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
    if exact_cache_hit(request):
        return cached_response()

    normalized = normalize_request(request)

    if normalized_cache_hit(normalized):
        return cached_response()

    if semantic_cache_allowed(request):
        hit = semantic_cache_lookup(request)
        if hit:
            return hit

    task = classify_task(request)
    capabilities = detect_capabilities(request)
    estimated_tokens = estimate_tokens(request)

    request = maybe_reduce_context(request, estimated_tokens)

    candidates = registry.find_candidates(
        task=task,
        capabilities=capabilities,
        policy=policy,
    )

    candidates = filter_by_health(candidates)
    candidates = filter_by_quota(candidates)
    candidates = filter_by_budget(candidates, policy)

    ranked = rank_candidates(candidates, policy)

    for candidate in ranked:
        result = execute(candidate, request)

        if result.success and validate(result):
            store_cache(request, result)
            record_metrics(result)
            return result

    raise NoAvailableModelError()
```

---

# 50. Definition of Done dla MVP

MVP można uznać za ukończone, gdy:

- klient korzysta z jednego OpenAI-compatible endpointu,
- można dodać/wyłączyć providera z dashboardu,
- można dodać/wyłączyć model z dashboardu,
- `model=auto` wybiera model dynamicznie,
- free tier jest preferowany dla prostych requestów,
- fallback działa przy błędzie providera,
- exact cache działa przez Redis,
- wykorzystanie i koszt trafiają do Langfuse,
- Angular dashboard pokazuje requesty, koszt i modele,
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
1. sprawdzić cache,
2. sklasyfikować zadanie jako coding,
3. oszacować context,
4. odrzucić modele bez wymaganych capabilities,
5. sprawdzić free/trial capacity,
6. uwzględnić health providera,
7. wybrać najlepszy kandydat wg policy,
8. wykonać request,
9. w razie potrzeby zrobić fallback,
10. zapisać trace,
11. policzyć koszt,
12. policzyć cost avoided,
13. zapisać cache,
14. zwrócić odpowiedź klientowi.
```

To jest docelowa definicja systemu: **inteligentna, obserwowalna i kosztowo zoptymalizowana brama do wielu modeli LLM**.
