# ADR-0003: Agent Gateway przed LiteLLM

- Status: accepted
- Date: 2026-09-25
- Supersedes: ADR-0001 w zakresie topologii produkcyjnej

## Context

Ruch agentowy wymaga stanowych optymalizacji wykonywanych przed wywołaniem modelu: bezpiecznego pruning kontekstu, wykrywania pętli narzędzi, exact i semantic cache, rezerwacji budżetu oraz spójnego pomiaru oszczędności. Umieszczenie tej logiki w pluginie LiteLLM wiązałoby domenę z wersjonowanym API rozszerzeń i utrudniało kontrolę kolejności operacji, cache hitów oraz stanu sesji.

## Decision

Jedyną publiczną ścieżką inference jest:

```text
client -> Caddy -> FastAPI Agent Gateway -> LiteLLM Proxy -> provider
```

- Caddy kieruje `/v1/*` do Agent Gateway. LiteLLM jest dostępny wyłącznie w sieci wewnętrznej.
- Agent Gateway zachowuje kontrakt OpenAI, weryfikuje publiczne klucze przed cache i odpowiada za rate limit, pruning, loop protection, exact/semantic cache, politykę routingu, budget lease oraz ledger optymalizacji. Do LiteLLM przekazuje wewnętrzne uwierzytelnienie i stabilny identyfikator billingowy virtual key.
- Policy Engine pozostaje biblioteką czystej logiki domenowej używaną przez Gateway, a nie pluginem LiteLLM.
- LiteLLM pozostaje możliwie bezstanowym adapterem providerów: tłumaczy protokoły, realizuje ograniczone retry/fallback i raportuje provider usage dla virtual keys.
- PostgreSQL z rozszerzeniem pgvector jest źródłem prawdy dla konfiguracji, partycjonowanego usage ledger i semantic cache.
- Redis przechowuje stan krótkotrwały: exact cache, health/counters/locks, `loop_protection:{tenant_id}:{session_id}` oraz `budget_lease:{tenant_id}:{key_id}:{request_id}` z TTL.
- Langfuse jest wyłącznie warstwą observability. Dashboard komunikuje się tylko z Control API Gatewaya.

## Invariants

1. Uwierzytelnienie, autoryzacja, rate limit i identyfikacja tenantu poprzedzają każdy cache lookup.
2. Exact/semantic cache hit omija LiteLLM i providera, ale zawsze tworzy idempotentny wpis ledgeru.
3. Gateway przekazuje LiteLLM konkretny dozwolony deployment lub ograniczoną fallback chain; LiteLLM nie może wrócić do pełnej puli i obejść filtrów capability/budget.
4. Płatny request wymaga atomowej dzierżawy budżetu. Brak Redisa oznacza fail-closed dla płatnego ruchu; faktycznie darmowy model może pozostać dostępny.
5. Pruning nie może rozrywać par tool-call/tool-result. Przy niepewności wykonuje bypass.
6. Semantic cache jest tenant-scoped, wersjonowany i dostępny tylko dla jawnie bezpiecznych, idempotentnych żądań bez side effects.
7. Pełne prompty i diffy przed/po nie są trwale przechowywane domyślnie; opt-in wymaga redakcji, RBAC, szyfrowania i retencji.

## Consequences

- FastAPI trafia na krytyczną ścieżkę inference, więc wymaga limitów czasu, backpressure, graceful shutdown, testów streamingu i niezależnego skalowania.
- Powstaje dodatkowy hop HTTP, ale zyskujemy stabilną granicę domenową niezależną od API pluginów LiteLLM.
- Auth i billing mają dwa powiązane widoki: Gateway egzekwuje dostęp i budżet, a LiteLLM zbiera usage virtual keys. Stabilny `key_id`, `request_id` i `attempt_id` są obowiązkowe do reconciliation bez podwójnego naliczania.
- Dotychczasowy smoke test pluginu zostaje jako test wiedzy o LiteLLM, lecz nie jest testem docelowego data plane.

## Verification

Test integracyjny musi wykazać, że request i streaming przechodzą przez obie warstwy, cache hit nie wywołuje LiteLLM, fallback respektuje listę Gatewaya, usage jest idempotentne, a port LiteLLM nie jest wystawiony na hosta.
