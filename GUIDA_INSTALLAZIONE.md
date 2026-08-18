# Guida semplice: ADA sul tuo computer

Questa guida è pensata per chi **non è tecnico**. Alla fine avrai una pagina
nel browser con una sfera blu: la tocchi, parli in italiano, e Ada ti risponde.

Tempo stimato: 15–20 minuti la prima volta. Le volte successive: 30 secondi.

---

## Fase 0 — Cosa ti serve

1. **Un computer** con microfono (Mac o Windows) e Google Chrome (o Edge).
2. **Una chiave Gemini (gratuita)**:
   - vai su <https://aistudio.google.com/apikey>
   - accedi con un account Google → clicca **"Create API key"**
   - copia la chiave (inizia con `AIza...`) e tienila da parte.

## Fase 1 — Installa Python (solo la prima volta)

- **Mac**: apri l'app **Terminale** e incolla:
  ```sh
  xcode-select --install
  ```
  poi scarica Python da <https://www.python.org/downloads/> e installalo.
- **Windows**: scarica Python da <https://www.python.org/downloads/>.
  Durante l'installazione **spunta la casella "Add Python to PATH"** (importante!).

## Fase 2 — Scarica ADA

1. Vai sulla pagina GitHub del repository `blanc-group/ada`.
2. Bottone verde **Code** → **Download ZIP**.
3. Estrai lo ZIP (doppio clic) — ad esempio sulla Scrivania.
4. La cartella estratta si chiama `ada-main`: è già la cartella di ADA.

## Fase 3 — Installa ADA (solo la prima volta)

Apri il **Terminale** (Mac) o il **Prompt dei comandi** (Windows: tasto
Windows → scrivi `cmd` → Invio) e incolla, una riga alla volta:

**Mac:**
```sh
cd ~/Desktop/ada-main
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-web.txt
```

**Windows:**
```bat
cd %USERPROFILE%\Desktop\ada-main
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-web.txt
```

(Se hai estratto lo ZIP altrove, sostituisci il percorso nella prima riga.)

## Fase 4 — Configura le chiavi

Nella cartella `ada-main` c'è un file chiamato `.env.example`:

1. Fanne una copia e rinominala `.env` (solo `.env`, senza `.example`).
2. Aprila con un editor di testo (TextEdit / Blocco note).
3. Compila queste righe:
   - `GEMINI_API_KEY=` → incolla la chiave `AIza...` della Fase 0
   - `ADA_WEB_PASSWORD=` → inventa una password (te la chiederà la pagina web)
   - `BLANC_MCP_API_KEY=` → **lasciala vuota per ora** (vedi Fase 6)
4. Salva.

## Fase 5 — Avvia ADA e parlaci

Nel terminale (sempre dentro la cartella `ada-main`, con il venv attivo):

**Mac:**
```sh
set -a; source .env; set +a
python -m ada_bridge.webapp
```

**Windows:**
```bat
for /f "usebackq tokens=*" %i in (".env") do set %i
python -m ada_bridge.webapp
```

Quando vedi `Uvicorn running on http://0.0.0.0:8000`:

1. apri Chrome e vai su **http://localhost:8000**
2. inserisci la password che hai scelto
3. autorizza il **microfono** quando il browser lo chiede
4. tocca la **sfera** e parla: *«Ciao Ada, mi senti?»*

Senza la chiave del company brain sei in **modalità demo**: Ada conversa in
italiano con la personalità Jarvis, ma non ha ancora accesso ai dati aziendali.

Per spegnerla: nel terminale premi `Ctrl+C`.

## Fase 6 — Collega il company brain

Serve che il gateway Blanc MCP sia in esecuzione e una sua API key dedicata:

```sh
pnpm apikey:create --name "ada-voice" --scopes "<solo gli scope necessari>"
```

Poi nel file `.env` compila:
- `BLANC_MCP_API_KEY=blanc_pk_...` (la chiave appena creata)
- `BLANC_MCP_URL=` l'indirizzo del gateway (es. `http://localhost:3000/mcp`
  se gira sullo stesso computer)

Riavvia ADA (Fase 5): nella pagina vedrai *«Collegata al company brain — N
strumenti disponibili»*. Questa fase è l'unica davvero tecnica: se il gateway
non è ancora attivo da nessuna parte, fatti aiutare da chi lo gestisce.

---

## Problemi comuni

| Sintomo | Soluzione |
|---|---|
| `python: command not found` | Python non installato o (Windows) manca "Add to PATH": reinstalla |
| La pagina non chiede il microfono | Usa `http://localhost:8000` (non l'IP), oppure controlla i permessi del sito in Chrome |
| «Password errata» | Deve essere identica a `ADA_WEB_PASSWORD` nel file `.env` |
| Ada non risponde | Controlla che `GEMINI_API_KEY` sia giusta; guarda gli errori nel terminale |
| «Sessione terminata» dopo ~10-15 min | Limite delle sessioni Gemini Live: tocca la sfera per ricominciare |
