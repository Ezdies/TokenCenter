# ADR-0001: integracja Policy Engine z LiteLLM

- Status: accepted for spike, production constraints pending
- Date: 2026-09-22
- LiteLLM: `v1.101.0`, image digest `sha256:d295634e09c648dcdb72c4cc2dd226f5fb87823a73e88cbbed6f205e4deb044b`

## Context

Publiczny endpoint ma pozostać w LiteLLM, ale routing `model=auto` wymaga własnych filtrów capability, health, quota i budget oraz wyjaśnialnej decyzji. Starsze wydania Proxy nie oferowały stabilnego custom routingu. LiteLLM dodał router plugins w serii 1.94.

## Decision

Używamy publicznego interfejsu `router_settings.plugins` z LiteLLM v1.101.0. Plugin jest pakietem Pythona ładowanym w procesie Proxy i implementuje:

```python
async def run(context: RoutingContext) -> RoutingContext: ...
```

Plugin może zawęzić `context.candidate_models` oraz dodać dane diagnostyczne do `context.signals`. LiteLLM stosuje wynik przed końcowym wyborem zdrowego deploymentu i odmawia fallbacku do pełnej puli, gdy plugin zwróci pustą listę.

Control API pozostaje poza ścieżką inference. Plugin korzysta docelowo z lokalnego snapshotu registry; nie wykonuje synchronicznego HTTP do Control API.

## Verified in the spike

- dotted path z YAML ładuje instancję pluginu,
- interfejs wymusza asynchroniczne `run`,
- `candidate_models` zawiera fizyczne identyfikatory modeli,
- zawężenie listy steruje wyborem deploymentu dla logicznego aliasu `auto`,
- `signals` są kopiowane do request metadata,
- request non-stream zachowuje OpenAI chat-completions response shape.

Komenda odbiorowa: `make spike-up && make spike-test && make spike-down`.

## Constraints to verify before stage 3

- Tożsamość virtual key/user/tenant dostępna w metadata pluginu.
- Widoczność `signals` w callbacku Langfuse i decision log.
- Idempotentne usage/cost przy retry i fallback.
- Streaming, disconnect klienta i błędy w formacie OpenAI.
- Rozróżnienie dwóch deployments wskazujących ten sam fizyczny model; obecny plugin filtruje po `litellm_params.model`.

Jeżeli którykolwiek warunek okaże się niemożliwy przy publicznym API pluginu, data plane zostanie przeniesiony do cienkiego FastAPI przed LiteLLM. Nie będą utrzymywane dwa warianty.

## Consequences

- Zachowujemy auth, virtual keys i provider adapters LiteLLM na publicznym ingressie.
- Policy Engine musi być instalowany lub montowany w obrazie LiteLLM.
- Aktualizacja LiteLLM wymaga uruchomienia contract testów pluginu.
- Domena routingu nie może zależeć od typów LiteLLM; adapter pluginu tłumaczy `RoutingContext` na typy domenowe.

