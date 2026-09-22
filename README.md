# TokenCenter

## Szybki start przez Docker

W głównym katalogu projektu wykonaj:

```bash
cp .env.example .env
docker compose up -d --build --wait
./scripts/smoke-stack.sh
```

Następnie otwórz <http://127.0.0.1:8080>. Zatrzymanie stacku bez usuwania danych:

```bash
docker compose down --remove-orphans
```

Pełna instrukcja, adresy usług i diagnostyka znajdują się w sekcji [Uruchomienie całego stacku przez Docker Compose](#uruchomienie-całego-stacku-przez-docker-compose).

TokenCenter to rozwijana brama LLM FinOps. Specyfikacja znajduje się w
[`llm-finops-gateway-implementation-guide.md`](./llm-finops-gateway-implementation-guide.md), a kolejność prac i kryteria odbioru w
[`IMPLEMENTATION_PLAN.md`](./IMPLEMENTATION_PLAN.md).

## Aktualny stan

Zaimplementowany jest Etap 0 oraz rdzeń infrastruktury z Etapu 1:

- szkielet Control API w FastAPI,
- szkielet dashboardu Angular,
- pakiet Policy Engine,
- działający spike pluginu routingu LiteLLM,
- mock providera zgodny z OpenAI Chat Completions API,
- PostgreSQL i Redis z trwałymi wolumenami,
- Caddy jako jeden publiczny punkt wejścia,
- testy i konfiguracja CI.

Główny `docker-compose.yml` uruchamia cały obecnie zaimplementowany stack. Langfuse nie jest jeszcze częścią domyślnego uruchomienia.

## Wymagania

Do pracy nad całym repozytorium potrzebne są:

- Python 3.13,
- [uv](https://docs.astral.sh/uv/) 0.12.17,
- Node.js 24.15.x z npm 11,
- Docker Engine 29+ z Docker Compose,
- `curl` i `make`.

Sprawdzenie wersji:

```bash
python3 --version
uv --version
node --version
npm --version
docker --version
docker compose version
```

## Uruchomienie całego stacku przez Docker Compose

Do zwykłego uruchomienia potrzebne są tylko Docker, Docker Compose i opcjonalnie `curl` do smoke testu. Lokalna instalacja Pythona, uv, Node.js, npm i `make` nie jest wymagana.

Wszystkie polecenia wykonuj z głównego katalogu repozytorium.

1. Utwórz lokalną konfigurację:

```bash
cp .env.example .env
```

2. Zbuduj obrazy i uruchom wszystkie usługi w tle:

```bash
docker compose up -d --build --wait
```

Pierwsze uruchomienie pobiera obrazy bazowe i buduje Control API oraz dashboard, dlatego trwa dłużej. Opcja `--wait` kończy polecenie dopiero po przejściu health checków.

3. Sprawdź cały przepływ przez reverse proxy:

```bash
./scripts/smoke-stack.sh
```

Oczekiwany wynik:

```text
Stack passed: dashboard, Control API, PostgreSQL, Redis, LiteLLM and mock provider are ready.
```

Po starcie cały system jest dostępny pod jednym adresem: <http://127.0.0.1:8080>.

| Metoda | Adres | Funkcja |
| --- | --- | --- |
| `GET` | <http://127.0.0.1:8080/> | dashboard Angular |
| `GET` | <http://127.0.0.1:8080/api/health/live> | liveness Control API |
| `GET` | <http://127.0.0.1:8080/api/health/ready> | PostgreSQL + Redis readiness |
| `GET` | <http://127.0.0.1:8080/api/docs> | Swagger UI Control API |
| `POST` | `http://127.0.0.1:8080/v1/chat/completions` | OpenAI-compatible LiteLLM API |

`/v1/chat/completions` nie jest stroną WWW. Otwarcie go w przeglądarce wykonuje request `GET` i poprawnie zwraca `405 Method Not Allowed`. Wywołaj go metodą `POST` z kluczem i JSON-em:

```bash
curl --fail-with-body --silent --show-error \
  --request POST \
  http://127.0.0.1:8080/v1/chat/completions \
  --header 'Authorization: Bearer sk-local-development-only' \
  --header 'Content-Type: application/json' \
  --data '{"model":"auto","messages":[{"role":"user","content":"Odpowiedz jednym słowem: działa?"}]}'
```

Odpowiedź z obecnego mock providera powinna zawierać:

```json
{"choices":[{"message":{"content":"mock:spike-free"}}]}
```

Status i logi:

```bash
docker compose ps
docker compose logs -f --tail=200
```

Zatrzymanie bez usuwania danych PostgreSQL i Redis:

```bash
docker compose down --remove-orphans
```

Ponowne `docker compose up -d --build --wait` wykorzysta zachowane wolumeny. Pełne wyczyszczenie lokalnych danych:

```bash
docker compose down --remove-orphans --volumes
```

Opcja `--volumes` usuwa wolumeny PostgreSQL i Redis, więc jest operacją destrukcyjną dla lokalnych danych developerskich.

### Skróty przez Makefile

Jeżeli `make` jest dostępny, powyższe polecenia mają krótsze odpowiedniki:

| Docker Compose | Makefile |
| --- | --- |
| `docker compose up -d --build --wait` | `make up` |
| `./scripts/smoke-stack.sh` | `make smoke` |
| `docker compose ps` | `make ps` |
| `docker compose logs -f --tail=200` | `make logs` |
| `docker compose down --remove-orphans` | `make down` |
| `docker compose down --remove-orphans --volumes` | `make clean` |

## Przygotowanie środowiska do pracy bezpośrednio na hoście

Wszystkie poniższe komendy należy wykonywać z głównego katalogu repozytorium.

1. Utwórz lokalny plik konfiguracyjny:

   ```bash
   cp .env.example .env
   ```

   Wartości z `.env.example` są przeznaczone wyłącznie do developmentu. Plik `.env` jest ignorowany i nie powinien trafić do repozytorium.

2. Zainstaluj przypięte zależności Pythona z `uv.lock`:

   ```bash
   make bootstrap
   ```

   Równoważna komenda:

   ```bash
   uv sync --all-packages --all-groups --frozen
   ```

3. Zainstaluj przypięte zależności dashboardu:

   ```bash
   cd apps/dashboard-angular
   npm ci
   cd ../..
   ```

Po tych krokach można uruchamiać aplikacje i pełny zestaw kontroli lokalnych.

## Ręczne uruchomienie Control API

Ta opcja jest przeznaczona do pracy nad backendem z hot reloadem. `DATABASE_URL` i `REDIS_URL` muszą wskazywać na dostępne z hosta instancje PostgreSQL i Redis. Domyślny główny Compose celowo nie wystawia ich portów publicznie.

```bash
uv run uvicorn control_api.main:app --host 127.0.0.1 --port 8000 --reload
```

Dostępne adresy:

- liveness: <http://127.0.0.1:8000/health/live>,
- readiness: <http://127.0.0.1:8000/health/ready> — wymaga działających PostgreSQL i Redis,
- Swagger UI: <http://127.0.0.1:8000/docs>,
- OpenAPI JSON: <http://127.0.0.1:8000/openapi.json>.

Szybkie sprawdzenie:

```bash
curl --fail http://127.0.0.1:8000/health/live
```

Oczekiwana odpowiedź:

```json
{"status":"ok"}
```

Proces zatrzymuje się skrótem `Ctrl+C`.

## Ręczne uruchomienie dashboardu Angular

W drugim terminalu:

```bash
cd apps/dashboard-angular
npm start
```

Dashboard będzie dostępny pod <http://127.0.0.1:4200>. Obecnie jest to ekran startowy; połączenie z Control API zostanie dodane w dalszych etapach.

Proces zatrzymuje się skrótem `Ctrl+C`.

## Uruchomienie spike'a LiteLLM

Spike sprawdza następujący przepływ:

```text
request model=auto
  -> LiteLLM v1.101.0
  -> SpikePolicyRouter
  -> wybór openai/spike-free
  -> lokalny mock providera
  -> odpowiedź w formacie OpenAI
```

Nie wymaga klucza OpenRouter, OpenAI ani innego zewnętrznego providera.

1. Uruchom LiteLLM i mock providera:

   ```bash
   make spike-up
   ```

   Compose czeka, aż oba kontenery przejdą health check. LiteLLM jest wystawiony wyłącznie lokalnie na porcie `4000`; mock nie wystawia portu na hoście.

2. Uruchom automatyczny smoke test:

   ```bash
   make spike-test
   ```

   Poprawny wynik:

   ```text
   Spike passed: model=auto was narrowed to openai/spike-free.
   ```

3. Opcjonalnie wyślij request ręcznie:

   ```bash
   curl --fail --silent --show-error \
     http://127.0.0.1:4000/v1/chat/completions \
     --header 'Authorization: Bearer sk-local-development-only' \
     --header 'Content-Type: application/json' \
     --data '{"model":"auto","messages":[{"role":"user","content":"route this request"}]}'
   ```

   W odpowiedzi pole `choices[0].message.content` powinno zawierać `mock:spike-free`.

4. Podejrzyj status lub logi:

   ```bash
   docker compose -f infrastructure/docker/compose.spike.yml ps
   docker compose -f infrastructure/docker/compose.spike.yml logs -f litellm
   docker compose -f infrastructure/docker/compose.spike.yml logs -f mock-llm
   ```

5. Po zakończeniu zatrzymaj spike:

   ```bash
   make spike-down
   ```

Komenda usuwa tymczasowe kontenery i sieć. Spike nie tworzy wolumenów z trwałymi danymi.

## Testy i kontrola jakości

Pełny zestaw kontroli, po wykonaniu kroków z sekcji „Przygotowanie środowiska”:

```bash
make check
```

Uruchamia kolejno:

- kontrolę formatowania i lint Pythona przez Ruff,
- strict typecheck przez mypy,
- testy backendu przez pytest,
- kontrolę formatowania Angulara,
- testy Angulara,
- produkcyjny build Angulara.

Poszczególne grupy można uruchomić oddzielnie:

```bash
make lint
make typecheck
make test
make frontend-check
```

Automatyczne formatowanie kodu Pythona:

```bash
make format
```

Automatyczne formatowanie dashboardu:

```bash
cd apps/dashboard-angular
npm run format
```

Walidacja konfiguracji Compose bez uruchamiania kontenerów:

```bash
docker compose config --quiet
```

Walidacja osobnego Compose używanego tylko przez spike:

```bash
docker compose -f infrastructure/docker/compose.spike.yml config --quiet
```

## Porty używane obecnie

| Port | Usługa | Sposób uruchomienia |
| ---: | --- | --- |
| 8080 | cały stack przez Caddy | `make up` |
| 4000 | LiteLLM spike | `make spike-up` |
| 4200 | dashboard Angular | `npm start` |
| 8000 | Control API | `uv run uvicorn ...` |

## Najczęstsze problemy

### `uv: command not found`

Zainstaluj uv 0.12.17 zgodnie z jego dokumentacją i ponownie wykonaj `make bootstrap`. Repozytorium wymaga wersji Pythona wskazanej w `.python-version`.

### `npm: command not found` lub niezgodna wersja Node.js

Zainstaluj Node.js 24.15.x. Angular 22 nie powinien być uruchamiany na przypadkowej, starszej wersji Node.js.

### Port 8080, 4000, 4200 lub 8000 jest zajęty

Sprawdź proces zajmujący port:

```bash
ss -ltnp | grep -E ':(8080|4000|4200|8000)\b'
```

Główny stack można wystawić na innym porcie przez `TOKEN_CENTER_PORT` w `.env`, na przykład `TOKEN_CENTER_PORT=8081`. Dla spike'a zmianę mapowania należy wprowadzić w `infrastructure/docker/compose.spike.yml` oraz odpowiednio zmienić adres smoke testu.

### Główny stack nie przechodzi health checków

```bash
make ps
docker compose logs control-api postgres redis litellm
```

Po poprawieniu problemu odtwórz stack:

```bash
make down
make up
make smoke
```

### Spike nie przechodzi

Sprawdź stan i logi:

```bash
docker compose -f infrastructure/docker/compose.spike.yml ps
docker compose -f infrastructure/docker/compose.spike.yml logs litellm mock-llm
```

Następnie odtwórz kontenery:

```bash
make spike-down
make spike-up
make spike-test
```

### Docker zgłasza brak uprawnień

Upewnij się, że daemon Docker działa i bieżący użytkownik ma prawo korzystać z jego socketu. Sposób konfiguracji zależy od systemu operacyjnego; nie uruchamiaj całego środowiska jako `root`, jeśli nie jest to konieczne.
