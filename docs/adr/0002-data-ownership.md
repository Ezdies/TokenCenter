# ADR-0002: własność danych

- Status: accepted
- Date: 2026-09-22

## Decision

- PostgreSQL `gateway` jest źródłem prawdy dla providerów, modeli, polityk, budżetów i audytu.
- Baza LiteLLM przechowuje jego virtual keys i wewnętrzne dane; integracja mapuje ich stabilne identyfikatory, ale nie współdzieli tabel domenowych.
- Langfuse przechowuje trace'y i analitykę, nie konfigurację ani stan budżetu.
- Redis przechowuje wyłącznie stan odtwarzalny lub krótkotrwały: cache, liczniki, health, locki i snapshot registry.
- Control API jest jedynym publicznym zapisem konfiguracji domenowej.

## Consequences

Awaria Langfuse lub dashboardu nie zatrzymuje inference. Utrata Redis może obniżyć wydajność, ale nie usuwa konfiguracji. Płatny request działa fail-closed, jeśli nie można atomowo potwierdzić budżetu.

