# fch-node – FreeCash Lazy Mining (lokal)

Lokaler Solo/Lazy-Pool für FreeCash mit automatischer Umrechnung in DOGE.

## Konzept (wie Mining-Dutch Lazy)

1. Miner (NerdQaxe++) verbindet sich per Stratum
2. Gefundene Blöcke gehen auf die **Pool-Wallet** (Sammelstelle)
3. Interner Stand wird in FCH geführt
4. Live-Umrechnung FCH → DOGE
5. Bei Erreichen von **5 DOGE** → Auszahlung an deine DOGE-Wallet markiert

---

## Generierte Pool-Wallet (Sammelstelle)

| Feld | Wert |
|------|------|
| **FCH Adresse** | `FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf` |
| **WIF (Private Key)** | `Kz7wY5wsvHcf1Y2ujkvKEhzxfY7D59KdE7YXUsxJ1QBGWQve53C9` |

**Wichtig:** Importiere den Private Key in deinen FreeCash-Node:

```bash
freecash-cli importprivkey "Kz7wY5wsvHcf1Y2ujkvKEhzxfY7D59KdE7YXUsxJ1QBGWQve53C9" "pool-wallet" false
freecash-cli validateaddress "FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf"
```

Danach gehört die Adresse deinem Node und kann die Coinbase empfangen.

---

## Deine DOGE Auszahlung

- Adresse: `DUNSBrrro71Yu9j7h7aGd3au9cUwydWuZn`
- Mindestauszahlung: **5 DOGE**

---

## Setup

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node
cp config/config.example.yaml config/config.yaml

# RPC-Zugangsdaten in config.yaml anpassen
nano config/config.yaml
```

Dann starten:

```bash
# freecashd muss laufen + synchronisiert sein
docker compose up -d --build
# oder manuell:
python stratum/server.py   # Terminal 1
python monitor/app.py      # Terminal 2
```

## Miner (NerdQaxe++)

```
URL:      stratum+tcp://DEINE_LOKALE_IP:3333
User:     beliebiger_name   (z.B. nerdqaxe1)
Password: x   oder   d=1000
```

Dashboard: `http://DEINE_LOKALE_IP:5000`

---

## Hinweis zur Umrechnung

Der aktuelle Kurs wird wenn möglich live von CoinGecko geholt.  
Fallback-Kurs steht in der Config (`fch_to_doge_rate`).

Die echte DOGE-Überweisung musst du vorerst manuell auslösen, sobald das Dashboard „Auszahlung bereit“ anzeigt. Später kann Auto-Payout ergänzt werden.
