# Mettere ADA online

ADA è un piccolo server web (Python/FastAPI) che serve una pagina con microfono
e fa da ponte verso Gemini Live. I browser danno accesso al microfono **solo su
HTTPS** (o su `localhost`), quindi per usarla da un vero link serve un server con
certificato HTTPS. Qui sotto due strade.

> **Demo vs completa.** Senza `BLANC_MCP_API_KEY` ADA parte in **modalità demo**:
> parla e ha la sua personalità, ma non accede ai dati aziendali. Con la chiave
> del gateway MCP configurata (e il gateway online) diventa completa e può usare
> GHL, Meta, n8n, ecc. a voce.

---

## Strada A — Render (la più rapida, senza un server tuo)

Ottieni un link HTTPS in ~10 minuti, quasi tutto a clic.

1. Vai su <https://render.com> e accedi (puoi usare GitHub).
2. **New +** → **Blueprint** → collega il repository **`blanc-group/ada`**
   (dovrai autorizzare Render ad accedere ai repo dell'organizzazione).
   Render legge il file `render.yaml` e configura tutto da solo.
3. Ti chiederà i valori dei segreti: compila
   - `GEMINI_API_KEY` — chiave gratuita da <https://aistudio.google.com/apikey>
   - `ADA_WEB_PASSWORD` — la password che sceglierai per entrare nella pagina
   - (opzionali) `BLANC_MCP_URL` e `BLANC_MCP_API_KEY` per collegare il company brain
4. **Deploy**. Al termine avrai un URL tipo `https://ada-voice.onrender.com`.
5. Aprilo, inserisci la password, autorizza il microfono e parla.

> Nota: il piano free va in sleep quando inattivo, quindi il primo accesso dopo
> una pausa è lento (~30s). Per un uso stabile si passa a un piano a pagamento.

---

## Strada B — Il tuo VPS, con link brandizzato `ada.blanc-group.it`

È la casa "vera" di ADA: gira sulla tua infrastruttura, dominio tuo, nessun
limite di sleep. Serve un server con Docker e i **DNS** puntati.

**Prerequisiti**
- Un VPS (es. Hostinger) con **Docker** e **docker compose** installati.
- Porte **80** e **443** aperte sul firewall.
- Un record DNS **A**: `ada.blanc-group.it` → IP del VPS.

**Passi** (da eseguire via SSH sul server):

```sh
git clone https://github.com/blanc-group/ada.git
cd ada
cp .env.example .env
nano .env          # compila GEMINI_API_KEY e ADA_WEB_PASSWORD
                   # (opz.) ADA_DOMAIN=ada.blanc-group.it e le BLANC_MCP_*
cd deploy
docker compose up -d --build
```

Caddy richiede da solo il certificato HTTPS a Let's Encrypt (ci vogliono pochi
secondi la prima volta). Poi apri **https://ada.blanc-group.it**, inserisci la
password e parla.

**Comandi utili**
```sh
docker compose logs -f ada      # log dell'app
docker compose logs -f caddy    # log del proxy / certificato
docker compose restart ada      # riavvio dopo un cambio di .env
docker compose down             # spegni tutto
```

---

## Suggerimento sull'ordine

Se vuoi solo **sentirla parlare** e testare la pagina: **Strada A** (Render),
lasci vuote le `BLANC_MCP_*` e sei online in modalità demo in pochi minuti.

Se vuoi ADA **collegata ai dati aziendali** e col dominio tuo: **Strada B**, ma
prima deve essere online anche il gateway MCP (repo `blanc-group/mcp`), così le
`BLANC_MCP_URL` / `BLANC_MCP_API_KEY` puntano a qualcosa di reale.
