# BCH2 Solo Node – Lokales Solo-Mining

Echter lokaler Solo-Pool für **Bitcoin Cash II (BCH2)**.

Dein NerdQaxe++ verbindet sich nur mit **deiner** Node.  
Niemand anders kann dir den Block wegschnappen.

---

## Inhaltsverzeichnis

1. [Was du brauchst](#was-du-brauchst)
2. [Node installieren](#1-node-installieren)
3. [Node konfigurieren & starten](#2-node-konfigurieren--starten)
4. [Wallet / Adresse](#3-wallet--adresse)
5. [Dieses Repo einrichten](#4-dieses-repo-einrichten)
6. [Stratum + Dashboard starten](#5-stratum--dashboard-starten)
7. [NerdQaxe++ verbinden](#6-nerdqaxe-verbinden)
8. [BCH2 verkaufen (Exchange)](#7-bch2-verkaufen-exchange)
9. [Nützliche Befehle](#nützliche-befehle)
10. [Ports Übersicht](#ports-übersicht)

---

## Was du brauchst

- Linux (Ubuntu 22.04 oder neuer empfohlen)
- mind. 4 GB RAM (besser 8 GB)
- SSD mit ca. 40–60 GB frei
- Python 3.10+
- NerdQaxe++ (oder anderer SHA256-ASIC)

---

## 1. Node installieren

Lade die aktuelle Binary von:

https://github.com/BitcoincashII/bitcoincashII-core/releases

Beispiel:

```bash
cd /tmp
wget https://github.com/BitcoincashII/bitcoincashII-core/releases/download/v27.0.2/bitcoincashII-27.0.2-x86_64-linux-gnu.tar.gz
tar -xvf bitcoincashII-*.tar.gz
sudo cp bitcoincashII-*/bin/* /usr/local/bin/
bitcoincashIId --version
```

---

## 2. Node konfigurieren & starten

```bash
mkdir -p ~/.bitcoincashII
nano ~/.bitcoincashII/bitcoincashII.conf
```

Inhalt der Config:

```ini
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcuser=bch2rpc
rpcpassword=HIER_EIN_SEHR_SICHERES_PASSWORT
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

Warte, bis `"initialblockdownload": false` angezeigt wird.  
Das kann je nach Internet und Hardware einige Stunden dauern.

---

## 3. Wallet / Adresse

```bash
bitcoincashII-cli createwallet "mining"
bitcoincashII-cli getnewaddress
```

Deine aktuelle Auszahlungsadresse ist bereits hinterlegt:

```
bitcoincashii:qqssqww4u4rldtl04gshuqvrledjhuwy95ytdyw0xa
```

Falls du eine neue Adresse willst, einfach `getnewaddress` ausführen und in der Config anpassen.

---

## 4. Dieses Repo einrichten

```bash
git clone https://github.com/SyCzOfficialYT/fch-node.git
cd fch-node
git checkout Test

cp config/config.example.yaml config/config.yaml
nano config/config.yaml
```

In der `config.yaml` musst du **nur noch das RPC-Passwort** eintragen (das gleiche wie in der `bitcoincashII.conf`).

Die Adresse ist schon korrekt gesetzt.

---

## 5. Stratum + Dashboard starten

```bash
pip install -r requirements.txt

# Terminal 1
python stratum/server.py

# Terminal 2
python monitor/app.py
```

Oder mit dem Start-Skript:

```bash
chmod +x scripts/start.sh
./scripts/start.sh
```

- **Stratum** läuft auf Port **3333**
- **Dashboard** unter `http://DEINE_LOKALE_IP:5000`

---

## 6. NerdQaxe++ verbinden

Im Web-Interface deines NerdQaxe:

| Feld       | Wert                                                                 |
|------------|----------------------------------------------------------------------|
| **URL**    | `stratum+tcp://DEINE_LOKALE_IP:3333`                                |
| **Username** | `bitcoincashii:qqssqww4u4rldtl04gshuqvrledjhuwy95ytdyw0xa.nerdq1` |
| **Password** | `x`  oder  `d=1000`                                               |

Nach dem Speichern sollte der Miner Shares an deinen lokalen Stratum schicken.

---

## 7. BCH2 verkaufen (Exchange)

### Aktuelle Börsenlage (Stand Aug 2026)

BCH2 hat **geringe Liquidität**. Es wird hauptsächlich hier gehandelt:

| Börse          | Paar       | Anmerkung                     |
|----------------|------------|-------------------------------|
| **NonKYC.io**  | BCH2/USDT  | Derzeit der aktivste Markt    |
| **Nestex**     | BCH2/USDT  | Ebenfalls gelistet            |

Große Börsen (Binance, KuCoin, Gate, MEXC usw.) listen BCH2 aktuell **nicht**.

### So verkaufst du deine BCH2

1. **Auf der Node den Kontostand prüfen**
   ```bash
   bitcoincashII-cli getbalance
   ```

2. **BCH2 an die Börse schicken**
   - Bei NonKYC.io oder Nestex eine Einzahlungsadresse für BCH2 erzeugen
   - Dann senden:
     ```bash
     bitcoincashII-cli sendtoaddress "EINZAHLUNGSADRESSE_DER_BÖRSE" BETRAG
     ```

3. **Auf der Börse verkaufen**
   - BCH2 → USDT verkaufen
   - Danach kannst du USDT in DOGE, BTC oder Euro tauschen und auszahlen

4. **Auszahlung**
   - USDT/DOGE auf deine Wallet (z. B. TrustWallet) auszahlen
   - Von dort aus manuell in Euro umwandeln

### Wichtiger Hinweis zur Liquidität

Das Handelsvolumen ist gering. Bei größeren Beträgen kann der Spread hoch sein.  
Kleinere Mengen lassen sich in der Regel vernünftig verkaufen.

---

## Nützliche Befehle

```bash
# Sync-Status
bitcoincashII-cli getblockchaininfo

# Kontostand
bitcoincashII-cli getbalance

# Neue Adresse erzeugen
bitcoincashII-cli getnewaddress

# Transaktion senden
bitcoincashII-cli sendtoaddress "adresse" 10.5

# Letzte Transaktionen
bitcoincashII-cli listtransactions
```

---

## Ports Übersicht

| Dienst              | Port  | Bemerkung                  |
|---------------------|-------|----------------------------|
| BCH2 P2P            | 8339  | Blockchain-Netzwerk        |
| BCH2 RPC            | 8342  | Nur lokal (127.0.0.1)     |
| Lokaler Stratum     | 3333  | NerdQaxe verbindet sich hier |
| Dashboard           | 5000  | Nur im lokalen Netzwerk    |

---

## Zusammenfassung des Ablaufs

```
NerdQaxe++ 
    → lokaler Stratum (Port 3333)
        → bitcoincashIId
            → Block wird gefunden
                → BCH2 landen auf deiner Adresse
                    → du schickst sie an NonKYC / Nestex
                        → verkaufst gegen USDT
                            → zahlst auf TrustWallet aus
```

Viel Erfolg beim Solo-Mining.
