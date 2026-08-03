# bch2-node – Bitcoin Cash II Solo Mining (lokal)

Echter lokaler Solo-Pool für **Bitcoin Cash II (BCH2)**.

Dein NerdQaxe++ verbindet sich nur mit **deiner** Node.  
Niemand anders kann dir den Block wegschnappen.

---

## Architektur

```
NerdQaxe++  →  lokaler Stratum (Port 3333)  →  bitcoincashIId  →  Blockchain
                     ↓
              Flask Dashboard (Port 5000)
```

---

## Voraussetzungen

- Linux (Ubuntu/Debian empfohlen)
- mind. 4 GB RAM, besser 8 GB
- SSD mit ca. 30–50 GB frei
- Python 3.10+

---

## 1. Node installieren

```bash
# Binary von offizieller Quelle holen
# https://github.com/BitcoincashII/bitcoincashII-core/releases

# Beispiel (anpassen an aktuelle Version):
wget https://github.com/BitcoincashII/bitcoincashII-core/releases/download/v27.0.2/bitcoincashII-27.0.2-x86_64-linux-gnu.tar.gz
tar -xvf bitcoincashII-*.tar.gz
sudo cp bitcoincashII-*/bin/* /usr/local/bin/
```

---

## 2. Node konfigurieren

```bash
mkdir -p ~/.bitcoincashII
nano ~/.bitcoincashII/bitcoincashII.conf
```

Inhalt:

```ini
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcuser=bch2rpc
rpcpassword=DEIN_SICHERES_PASSWORT_HIER
rpcallowip=127.0.0.1
txindex=1
```

Node starten:

```bash
bitcoincashIId -daemon
```

Sync-Status prüfen:

```bash
bitcoincashII-cli getblockchaininfo
```

Warten bis `"initialblockdownload": false`.

---

## 3. Wallet / Adresse erzeugen

```bash
bitcoincashII-cli createwallet "mining"
bitcoincashII-cli getnewaddress
```

→ Die Adresse beginnt mit `bitcoincashii:q...`  
Diese Adresse kommt in die Config (siehe unten).

---

## 4. Dieses Repo einrichten

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node
git checkout Test

cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

Wichtige Werte in `config.yaml`:

```yaml
rpc:
  host: 127.0.0.1
  port: 8342
  user: bch2rpc
  password: DEIN_SICHERES_PASSWORT_HIER

pool:
  payout_address: "bitcoincashii:qDEINE_ADRESSE_HIER"
  stratum_port: 3333
```

---

## 5. Abhängigkeiten & Start

```bash
pip install -r requirements.txt

# Terminal 1 – Stratum
python stratum/server.py

# Terminal 2 – Dashboard
python monitor/app.py
```

Dashboard erreichbar unter:
```
http://DEINE_LOKALE_IP:5000
```

---

## 6. NerdQaxe++ verbinden

Im Web-Interface des NerdQaxe:

| Feld     | Wert                                      |
|----------|-------------------------------------------|
| URL      | `stratum+tcp://DEINE_LOKALE_IP:3333`     |
| Username | `bitcoincashii:qDEINE_ADRESSE.nerdq1`    |
| Password | `x` oder `d=1000`                        |

---

## Wichtige Ports

| Dienst          | Port  |
|-----------------|-------|
| BCH2 P2P        | 8339  |
| BCH2 RPC        | 8342  |
| Lokaler Stratum | 3333  |
| Dashboard       | 5000  |

---

## Hinweise

- Echte Solo-Mining: Der Block geht direkt an deine Adresse (Coinbase).
- Kein Lazy-Mining / keine Umrechnung – du bekommst echte BCH2.
- Difficulty ist deutlich niedriger als bei BCH → realistische Chance mit NerdQaxe++.
- Node muss vollständig synchronisiert sein, bevor der Stratum sinnvoll läuft.

---

## Befehle zum Prüfen

```bash
# Sync-Status
bitcoincashII-cli getblockchaininfo

# Wallet-Balance
bitcoincashII-cli getbalance

# Neue Adresse
bitcoincashII-cli getnewaddress
```
