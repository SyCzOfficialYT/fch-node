# fch-node – Lokaler FreeCash (FCH) Mining-Node / Private Pool

Privater FCH-Node + Stratum-Server für dein lokales Netzwerk, inspiriert von Mining-Dutch.

**Unterstützte Modi:**
- **SOLO** – Echter Solo-Mining gegen deinen eigenen FreeCash-Node
- **PPS** – Pay Per Share (simuliert + Tracking)
- **PPLNS** – Pay Per Last N Shares (simuliert + Tracking)

**Miner:** Optimiert für NerdQaxe++ (und alle SHA256 ASICs)

**Monitoring:** Python Flask Dashboard – erreichbar **nur über die IP deines Rechners** (kein Domain nötig)

**Lazy Mining:** FCH-Belohnungen werden als DOGE-Äquivalent angezeigt (manuell konfigurierbarer Kurs).

---

## Voraussetzungen

- Linux (Ubuntu 22.04/24.04 empfohlen)
- Docker + Docker Compose (empfohlen) **oder** Python 3.10+
- FreeCash Full Node (`freecashd`) – muss synchronisiert sein
- Statische IP im lokalen Netz (empfohlen)

---

## Schnellstart (Docker – empfohlen)

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node

# Konfiguration anpassen
cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

Wichtige Einstellungen in `config/config.yaml`:

```yaml
stratum:
  host: "0.0.0.0"          # lauscht auf allen Interfaces
  port: 3333

rpc:
  host: "127.0.0.1"
  port: 8332               # oder dein freecash RPC-Port
  user: "fchrpc"
  password: "dein_sicheres_passwort"

wallet:
  address: "deine_FCH_Adresse"   # für SOLO Coinbase

mode: "solo"               # solo | pps | pplns

lazy_mining:
  enabled: true
  fch_to_doge_rate: 0.0015   # 1 FCH = X DOGE (manuell anpassen)

dashboard:
  host: "0.0.0.0"
  port: 5000
```

Dann starten:

```bash
docker compose up -d
```

Dashboard öffnen:  
`http://DEINE_LOKALE_IP:5000`

Stratum für den Miner:  
`stratum+tcp://DEINE_LOKALE_IP:3333`

---

## NerdQaxe++ Einstellungen

| Einstellung       | Wert                          |
|-------------------|-------------------------------|
| Pool URL          | `stratum+tcp://192.168.x.x:3333` |
| Worker / Username | `deine_FCH_Adresse` oder `deine_FCH_Adresse.worker1` |
| Password          | `x` oder `d=1000` (niedrige Diff für NerdQaxe++) |

---

## Manueller Start (ohne Docker)

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Terminal 1 – Stratum
python stratum/server.py

# Terminal 2 – Dashboard
python monitor/app.py
```

---

## Dateistruktur

```
fch-node/
├── config/
│   └── config.example.yaml
├── stratum/
│   └── server.py          # Stratum-Server (SOLO + Share-Tracking)
├── monitor/
│   └── app.py             # Flask Dashboard
├── scripts/
│   └── start.sh
├── docker/
│   └── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

---

## Hinweise

- Für **echten SOLO**-Betrieb muss der FreeCash-Node (`freecashd`) laufen und vollständig synchronisiert sein.
- PPS und PPLNS sind im Dashboard voll nachverfolgbar (Shares, Hashrate, geschätzte Rewards). Die Auszahlung erfolgt bei SOLO direkt in der Coinbase.
- Der Lazy-Kurs FCH→DOGE ist manuell einstellbar (da FCH oft keinen stabilen Marktpreis hat).
- Das Dashboard lauscht standardmäßig auf `0.0.0.0:5000` – nur im lokalen Netz erreichbar.

---

Viel Erfolg beim Minen!  
Bei Fragen einfach Issue öffnen.
