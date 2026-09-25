# ADR-0002: własność danych

- Status: accepted
- Date: 2026-09-22

## Decision

- PostgreSQL `gateway` z rozszerzeniem pgvector jest źródłem prawdy dla providerów, modeli, polityk, budżetów, audytu, partycjonowanego `usage_ledger` oraz wpisów semantic cache.
- Baza LiteLLM przechowuje jego virtual keys i wewnętrzne dane; integracja mapuje ich stabilne identyfikatory, ale nie współdzieli tabel domenowych.
- Langfuse przechowuje trace'y i analitykę, nie konfigurację ani stan budżetu.
- Redis przechowuje wyłącznie stan odtwarzalny lub krótkotrwały: exact cache, liczniki, health, locki, snapshot registry, okna loop protection i budget leases z TTL.
- Control API Agent Gatewaya jest jedynym publicznym zapisem konfiguracji domenowej; publiczne inference `/v1/*` również przechodzi przez Agent Gateway zgodnie z ADR-0003.

## Consequences

Awaria Langfuse lub dashboardu nie zatrzymuje inference. Utrata Redis może obniżyć wydajność i wyłączyć ochronę stanową, ale nie usuwa konfiguracji ani ledgeru. Płatny request działa fail-closed, jeśli nie można atomowo uzyskać dzierżawy budżetu; ruch faktycznie darmowy może działać dalej według polityki degraded mode.
