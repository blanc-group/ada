# ADA Voice Bridge

Ponte vocale fra **[ADA v2](https://github.com/nazirlouis/ada_v2)** (assistente
vocale basato su Gemini Live) e il **Blanc MCP gateway** (il company brain).

Tutti i tool esposti dal gateway (GHL, n8n, Meta, e ogni modulo futuro)
diventano **comandi vocali in italiano**: il bridge legge `tools/list` dal
gateway, li traduce in function declarations per Gemini Live e inoltra le
chiamate del modello al gateway. Nessun tool è cablato a mano: **ogni modulo
aggiunto al MCP diventa automaticamente disponibile a voce**, senza toccare
questo codice.

```
┌─────────────┐  audio it-IT   ┌──────────────┐  function call  ┌────────────┐  MCP HTTP  ┌───────────┐
│   Utente    │◀──────────────▶│ Gemini Live  │◀──────────────▶│ ada_bridge │◀─────────▶│ Blanc MCP │
│ (mic/casse) │                │ native audio │                 │  (questo)  │  Bearer key │  gateway  │
└─────────────┘                └──────────────┘                 └────────────┘            └───────────┘
```

## Contenuto

| File | Cosa fa |
|---|---|
| `ada_bridge/bridge.py` | `AdaMcpBridge`: connessione, elenco tool, esecuzione chiamate |
| `ada_bridge/mcp_client.py` | Client Streamable HTTP verso il gateway (Bearer + `X-Blanc-Tenant`) |
| `ada_bridge/tool_mapper.py` | Sanitizza gli JSON Schema (Zod) nel sottoinsieme accettato da Gemini |
| `ada_bridge/confirmation.py` | Conferma vocale a due fasi per i tool di scrittura |
| `ada_bridge/persona.py` | Persona "Jarvis" in italiano (istruzioni di sistema) |
| `ada_bridge/standalone.py` | Loop vocale minimale: prova il company brain a voce senza la UI di ADA |
| `ada_bridge/webapp.py` + `web/` | **Interfaccia web**: pagina con microfono, apribile dal browser |
| `GUIDA_INSTALLAZIONE.md` | Guida passo-passo non tecnica per usare ADA in locale |
| `Dockerfile` | Immagine per hostare la versione web su un server |
| `tests/` | Unit test di mapper e policy di conferma (`pytest`) |

## Interfaccia web (consigliata)

Pagina con sfera "Jarvis" e microfono del browser: il server relaya l'audio a
Gemini Live e i tool call al gateway. Per l'uso non tecnico vedi
[GUIDA_INSTALLAZIONE.md](./GUIDA_INSTALLAZIONE.md); in breve:

```sh
cd agents/ada-voice-bridge
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements-web.txt
cp .env.example .env             # compila GEMINI_API_KEY e ADA_WEB_PASSWORD
set -a && source .env && set +a
python -m ada_bridge.webapp      # poi apri http://localhost:8000
```

Senza `BLANC_MCP_API_KEY` parte in **modalità demo** (voce e persona, nessun
tool aziendale). Note:

- I browser danno il microfono solo su HTTPS **o su `localhost`**: per esporla
  in rete serve un reverse proxy TLS (Caddy: `ada.example.it { reverse_proxy
  localhost:8000 }`).
- La pagina è protetta da `ADA_WEB_PASSWORD` (password condivisa, WebSocket
  chiuso con codice 4401 se errata).
- Deploy container: `docker build -t ada-web . && docker run --env-file .env -p 8000:8000 ada-web`.

## Quickstart (standalone, senza ADA v2)

Su una macchina con microfono e casse:

```sh
cd agents/ada-voice-bridge
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt        # pyaudio richiede portaudio (brew/apt)
cp .env.example .env                   # compila BLANC_MCP_API_KEY e GEMINI_API_KEY
set -a && source .env && set +a
python -m ada_bridge.standalone
```

Poi parla: *«Ada, quanti contatti abbiamo su GoHighLevel?»*. Per le azioni di
scrittura Ada riassume cosa sta per fare e chiede conferma prima di eseguire.

## Integrazione dentro ADA v2 (UI completa)

ADA v2 registra i tool come dict `function_declarations` nella
`LiveConnectConfig` e li smista in `receive_audio()`. Tre modifiche a
`backend/ada.py`:

**1. Avvio del bridge** (dopo la creazione dell'event loop):

```python
from ada_bridge import AdaMcpBridge

bridge = AdaMcpBridge()          # legge BLANC_MCP_* dall'ambiente
await bridge.start()
```

**2. Registrazione dei tool** (dove ADA costruisce `tools`):

```python
tools = [
    {"google_search": {}},
    {"function_declarations": [generate_cad, run_web_agent, ..., *bridge.declarations]},
]
```

**3. Dispatch** (nel loop che gestisce `response.tool_call.function_calls`,
come ramo di fallback dopo i tool nativi di ADA):

```python
elif bridge.handles(fc.name):
    result = await bridge.execute(fc.name, dict(fc.args or {}))
    function_responses.append(
        types.FunctionResponse(id=fc.id, name=fc.name, response=result)
    )
```

**4. Italiano + voce**: nella `LiveConnectConfig` di ADA sostituisci la
`system_instruction` inglese con `ada_bridge.system_instruction()` (o integra
il testo nella persona esistente) e imposta `voice_name` — vedi sotto.

## Voce "Jarvis"

Non esiste una voce Jarvis ufficiale (è proprietà Marvel). L'approssimazione:

- **Voce**: default `Charon` (profonda e pacata, la più vicina al registro
  Jarvis fra le voci prebuilt di Gemini). Alternative da provare con
  `ADA_VOICE`: `Iapetus`, `Alnilam`, `Schedar`, `Enceladus`.
- **Registro**: la persona in `persona.py` è un maggiordomo inglese d'altri
  tempi che parla italiano e si rivolge a te con «Signore» (configurabile con
  `ADA_USER_TITLE`).
- **Lingua**: i modelli native-audio rilevano la lingua automaticamente; parli
  italiano → risponde in italiano. `ADA_LANGUAGE_CODE` esiste solo per
  forzature particolari.

## Sicurezza

- **API key dedicata e scoped**: genera una chiave solo per ADA con i minimi
  scope necessari (`pnpm apikey:create --name "ada-voice" --scopes "..."`).
  Tutto ciò che ADA fa passa dal gateway e finisce nell'**audit log
  immutabile** come qualsiasi altro client.
- **Conferma a due fasi sulle scritture**: i tool il cui nome non contiene un
  verbo di lettura (`get`, `list`, `search`, ...) sono trattati come
  scritture. La prima invocazione NON esegue: restituisce
  `confirmation_required` e la persona impone ad Ada di riassumere l'azione e
  chiedere conferma a voce; solo la stessa identica chiamata ripetuta entro
  `ADA_CONFIRMATION_TTL` (default 120 s) viene eseguita. Verbi sconosciuti =
  scrittura (fail closed).
- **Output limitato**: le risposte dei tool sono troncate a ~20k caratteri per
  restare in un budget adatto alla voce.

## Test

```sh
pip install pytest && pytest   # 17 test: tool_mapper + confirmation
```

## Limiti noti

- Il runner standalone richiede hardware audio: non è testabile in CI (i test
  coprono la logica pura; il client MCP e il loop vocale vanno provati contro
  il gateway di dev).
- Se il gateway aggiunge/rimuove tool a sessione ADA aperta, serve
  `await bridge.reload_tools()` e una riconnessione della sessione Live per
  aggiornare le declarations.
- La classificazione read/write è basata sul nome del tool: quando il gateway
  esporrà gli scope nelle annotazion MCP, conviene passare a quelli.
