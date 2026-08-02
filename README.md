# fch-node – Production Local FreeCash (FCH) Solo Pool

Echter lokaler Solo-Mining-Stratum-Server für FreeCash inkl. Flask-Monitoring.

**Kein Demo. Kein Fake.**  
Der Server holt echte Block-Templates per `getblocktemplate` von deinem `freecashd`, baut Jobs, validiert Shares und reicht gefundene Blöcke per `submitblock` ein.

---

## Features

- Echter **SOLO**-Betrieb gegen lokalen FreeCash-Node
- Stratum V1 (kompatibel mit NerdQaxe++ und allen gängigen SHA256-ASICs)
- Variable Start-Difficulty (Standard 1000 – ideal für ~5 TH/s Geräte)
- Share-Validierung + automatische Block-Submission
- Live-Dashboard (nur über die IP deines Rechners erreichbar)
- Lazy FCH → DOGE Umrechnung im Dashboard
- Docker & manuelle Installation
- Stats-Persistenz

---

## Voraussetzungen

1. **FreeCash Full Node** (`freecashd`) muss laufen und **vollständig synchronisiert** sein.
2. In der `freecash.conf` / Startparametern:

```conf
server=1
rpcuser=fchrpc
rpcpassword=DEIN_SICHERES_PASSWORT
rpcallowip=127.0.0.1
rpcport=8332
```

3. Python 3.10+ **oder** Docker

---

## Installation

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node

cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

**Wichtig in der Config:**

```yaml
rpc:
  host: "127.0.0.1"
  port: 8332
  user: "fchrpc"
  password: "DEIN_SICHERES_PASSWORT"

wallet:
  address: "DEINE_ECHTE_FCH_ADRESSE"

mode: "solo"

stratum:
  start_difficulty: 1000   # gut für NerdQaxe++
```

### Start mit Docker

```bash
docker compose up -d --build
```

### Manueller Start

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Terminal 1
python stratum/server.py

# Terminal 2
python monitor/app.py
```

---

## Miner einstellen (NerdQaxe++)

| Feld          | Wert                                      |
|---------------|-------------------------------------------|
| Pool URL      | `stratum+tcp://DEINE_LOKALE_IP:3333`     |
| Username      | `deine_FCH_Adresse` oder `Adresse.worker1` |
| Password      | `x` oder `d=1000`                         |

Dashboard: `http://DEINE_LOKALE_IP:5000`

---

## Architektur

```
NerdQaxe++  →  Stratum :3333  →  JobManager  →  freecashd (RPC)
                     ↓
              Share Validation
                     ↓
              submitblock (bei Netzwerk-Diff)
                     ↓
              logs/stats.json  ←  Flask Dashboard :5000
```

---

## Hinweise / Bekannte Grenzen

- Die Coinbase zahlt aktuell an eine Placeholder-ScriptPubKey. Für den produktiven Dauerbetrieb sollte die Adresse korrekt in ein P2PKH/P2SH-Script encodiert werden (kann erweitert werden).
- Merkle-Tree-Aufbau ist vereinfacht. Für maximale Korrektheit bei vielen Transaktionen kann der volle Tree implementiert werden.
- PPS / PPLNS sind als Tracking-Modi vorbereitet, der Kern ist echter SOLO.
- Das System ist für **privates / lokales** Nutzen gedacht. Bei öffentlicher Freigabe brauchst du zusätzliche Absicherung (Rate-Limits, Auth, Firewall).

---

Viel Erfolg beim echten Solo-Minen.
