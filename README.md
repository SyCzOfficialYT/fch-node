# fch-node – FreeCash Lazy Mining (lokal)

Lokaler Solo/Lazy-Pool für FreeCash mit Wert-Umrechnung in DOGE.

## Konzept

1. NerdQaxe++ minet an deinem lokalen Pool
2. Gefundene Blöcke landen auf der **Pool-Wallet** (Sammelstelle)
3. Dashboard zeigt FCH-Stand + ungefähren DOGE-Wert
4. Ab ca. **5 DOGE** Gegenwert → du verkaufst die FCH und schickst DOGE auf deine TrustWallet

---

## Generierte Pool-Wallet (Sammelstelle)

| Feld | Wert |
|------|------|
| **FCH-Adresse** | `FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf` |
| **Private Key (WIF)** | `Kz7wY5wsvHcf1Y2ujkvKEhzxfY7D59KdE7YXUsxJ1QBGWQve53C9` |

### Private Key importieren (einmalig)

```bash
freecash-cli importprivkey "Kz7wY5wsvHcf1Y2ujkvKEhzxfY7D59KdE7YXUsxJ1QBGWQve53C9" "pool-wallet" false
freecash-cli validateaddress "FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf"
```

### Kontostand prüfen

```bash
freecash-cli getbalance
freecash-cli listunspent 0 9999999 "[\"FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf\"]"
```

---

## Deine DOGE Auszahlung

- Adresse (TrustWallet): `DUNSBrrro71Yu9j7h7aGd3au9cUwydWuZn`
- Ziel: ab ca. **5 DOGE** Gegenwert auszahlen

---

## Kompletter Ablauf – Schritt für Schritt

### 1. Mining
NerdQaxe++ verbindet sich mit:
```
stratum+tcp://DEINE_LOKALE_IP:3333
User: nerdqaxe1 (beliebig)
Password: x   oder   d=1000
```

### 2. FCH sammeln sich
Blöcke gehen auf: `FNBM516c6Erb5Zp5VxyzCG67z5fw3xNHRf`

### 3. Stand prüfen
- Dashboard: `http://DEINE_LOKALE_IP:5000`
- Oder per CLI (siehe oben)

### 4. FCH an Börse schicken
```bash
freecash-cli sendtoaddress "EINZAHLUNGSADRESSE_DER_BÖRSE" BETRAG
```

### 5. FCH verkaufen → DOGE
Auf der Börse:
1. FCH gegen USDT (oder BTC) verkaufen
2. USDT/BTC in DOGE tauschen
3. DOGE auszahlen an: `DUNSBrrro71Yu9j7h7aGd3au9cUwydWuZn`

### 6. TrustWallet → Euro
Von der TrustWallet aus kannst du DOGE manuell in Euro auszahlen (z. B. über eine Börse oder P2P).

---

## Wo kann man FCH aktuell handeln? (Recherche Aug 2026)

**Ehrliche Lage:**  
FreeCash (FCH) hat **sehr geringe Liquidität**. Die meisten großen Börsen haben es bereits delistet.

| Börse     | Status                          | Anmerkung                          |
|-----------|----------------------------------|------------------------------------|
| **CoinEx**   | 2023 offiziell delistet         | Nicht mehr handelbar              |
| **XeggeX**   | Scheint noch FCH/USDT zu haben  | Sehr kleine Börse, hohes Risiko   |
| Binance / KuCoin / Gate / MEXC | Nicht gelistet             | -                                 |
| Andere    | Meist inaktiv / stale Daten     | Vorsicht vor Fake-Listings        |

**Empfehlung:**
- Prüfe aktuell auf [CoinLore FCH Exchanges](https://www.coinlore.com/coin/freecash/exchanges) oder dem FreeCash Explorer.
- Bei sehr kleiner Menge lohnt sich der Verkauf oft kaum (Gebühren + Spread).
- Alternative: FCH einfach halten oder Peer-to-Peer suchen (Telegram/Community).

---

## Setup

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node
cp config/config.example.yaml config/config.yaml
# RPC-Passwort + ggf. andere Werte anpassen
nano config/config.yaml

# starten
python stratum/server.py   # Terminal 1
python monitor/app.py      # Terminal 2
```

Dashboard: `http://DEINE_LOKALE_IP:5000`
