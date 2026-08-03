#!/bin/bash
set -e

# ============================================================
#  BCH2 Node Interactive Installer
#  Installiert bitcoincashIId + systemd Service + bch-node CLI
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

VERSION="27.0.2"
BASE_URL="https://github.com/BitcoincashII/bitcoincashII-core/releases/download/v${VERSION}"
INSTALL_DIR="/usr/local/bin"
DATA_DIR="$HOME/.bitcoincashII"
CONF_FILE="$DATA_DIR/bitcoincashII.conf"
SERVICE_NAME="bch2-node"
CLI_WRAPPER="/usr/local/bin/bch-node"

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════╗"
echo "║     BCH2 Node Installer v${VERSION}          ║"
echo "╚════════════════════════════════════════════╝"
echo -e "${NC}"

need_sudo() {
    if [ "$EUID" -ne 0 ]; then
        echo -e "${YELLOW}Für die Installation werden sudo-Rechte benötigt.${NC}"
        SUDO="sudo"
    else
        SUDO=""
    fi
}

detect_arch() {
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64|amd64)
            ASSET="bitcoincashII-${VERSION}-linux64.tar.gz"
            echo -e "${GREEN}✓ Architektur: x86_64${NC}"
            ;;
        aarch64|arm64)
            ASSET="bitcoincashII-${VERSION}-linux-aarch64.tar.gz"
            echo -e "${GREEN}✓ Architektur: aarch64${NC}"
            ;;
        *)
            echo -e "${RED}✗ Nicht unterstützte Architektur: $ARCH${NC}"
            echo "Unterstützt: x86_64, aarch64"
            exit 1
            ;;
    esac
    DOWNLOAD_URL="${BASE_URL}/${ASSET}"
}

install_binaries() {
    echo ""
    echo -e "${CYAN}→ Lade ${ASSET} herunter...${NC}"
    TMPDIR=$(mktemp -d)
    cd "$TMPDIR"

    if ! wget -q --show-progress "$DOWNLOAD_URL" -O "$ASSET"; then
        echo -e "${RED}Download fehlgeschlagen.${NC}"
        echo "URL: $DOWNLOAD_URL"
        exit 1
    fi

    echo -e "${CYAN}→ Entpacke...${NC}"
    tar -xzf "$ASSET"

    BINDIR=$(find . -type d -name "bin" | head -n1)
    if [ -z "$BINDIR" ]; then
        BINDIR=$(find . -maxdepth 2 -type d | head -n2 | tail -n1)
    fi

    echo -e "${CYAN}→ Installiere Binaries nach ${INSTALL_DIR}...${NC}"
    $SUDO cp "$BINDIR"/bitcoincashIId "$INSTALL_DIR/" 2>/dev/null || $SUDO cp bitcoincashIId "$INSTALL_DIR/"
    $SUDO cp "$BINDIR"/bitcoincashII-cli "$INSTALL_DIR/" 2>/dev/null || $SUDO cp bitcoincashII-cli "$INSTALL_DIR/"
    $SUDO chmod +x "$INSTALL_DIR"/bitcoincashIId "$INSTALL_DIR"/bitcoincashII-cli

    cd /
    rm -rf "$TMPDIR"

    echo -e "${GREEN}✓ Binaries installiert${NC}"
    bitcoincashIId --version || true
}

create_config() {
    echo ""
    if [ -f "$CONF_FILE" ]; then
        echo -e "${YELLOW}Config existiert bereits: $CONF_FILE${NC}"
        read -p "Überschreiben? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo "Behalte bestehende Config."
            return
        fi
    fi

    mkdir -p "$DATA_DIR"
    RPC_PASS=$(openssl rand -base64 24 2>/dev/null || head -c 24 /dev/urandom | base64)

    cat > "$CONF_FILE" << CONFEOF
# BCH2 Node Config – generiert vom Installer
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcuser=bch2rpc
rpcpassword=${RPC_PASS}
rpcallowip=127.0.0.1
txindex=1
CONFEOF

    chmod 600 "$CONF_FILE"
    echo -e "${GREEN}✓ Config erstellt: $CONF_FILE${NC}"
    echo -e "${YELLOW}  RPC User:     bch2rpc${NC}"
    echo -e "${YELLOW}  RPC Password: ${RPC_PASS}${NC}"
    echo -e "${YELLOW}  → Bitte dieses Passwort in config/config.yaml vom Solo-Stratum eintragen!${NC}"
}

create_service() {
    echo ""
    echo -e "${CYAN}→ Erstelle systemd Service...${NC}"

    SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

    $SUDO tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=Bitcoin Cash II (BCH2) Node
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=$USER
Group=$USER
ExecStart=${INSTALL_DIR}/bitcoincashIId -daemon -conf=${CONF_FILE} -datadir=${DATA_DIR}
ExecStop=${INSTALL_DIR}/bitcoincashII-cli -conf=${CONF_FILE} stop
PIDFile=${DATA_DIR}/bitcoincashIId.pid
Restart=on-failure
RestartSec=30
TimeoutStartSec=300
TimeoutStopSec=120
Nice=5

[Install]
WantedBy=multi-user.target
SVCEOF

    $SUDO systemctl daemon-reload
    $SUDO systemctl enable "$SERVICE_NAME" > /dev/null 2>&1 || true

    echo -e "${GREEN}✓ systemd Service erstellt und aktiviert${NC}"
}

create_cli_wrapper() {
    echo ""
    echo -e "${CYAN}→ Installiere 'bch-node' Befehl...${NC}"

    $SUDO tee "$CLI_WRAPPER" > /dev/null << 'WRAPEOF'
#!/bin/bash
# bch-node – einfache Steuerung für die BCH2 Node

SERVICE="bch2-node"
CLI="bitcoincashII-cli"
CONF="$HOME/.bitcoincashII/bitcoincashII.conf"

case "$1" in
    start)
        echo "Starte BCH2 Node..."
        sudo systemctl start "$SERVICE"
        sleep 2
        sudo systemctl status "$SERVICE" --no-pager -l
        ;;
    stop)
        echo "Stoppe BCH2 Node..."
        sudo systemctl stop "$SERVICE"
        ;;
    restart)
        echo "Starte BCH2 Node neu..."
        sudo systemctl restart "$SERVICE"
        sleep 2
        sudo systemctl status "$SERVICE" --no-pager -l
        ;;
    status)
        sudo systemctl status "$SERVICE" --no-pager -l
        echo ""
        if $CLI -conf="$CONF" getblockchaininfo > /dev/null 2>&1; then
            echo "--- Blockchain Info ---"
            $CLI -conf="$CONF" getblockchaininfo | grep -E '"chain"|"blocks"|"headers"|"verificationprogress"|"initialblockdownload"|"difficulty"'
        else
            echo "Node antwortet noch nicht auf RPC (noch am Starten oder nicht synced)."
        fi
        ;;
    sync|info)
        $CLI -conf="$CONF" getblockchaininfo
        ;;
    balance)
        $CLI -conf="$CONF" getbalance
        ;;
    newaddress)
        $CLI -conf="$CONF" getnewaddress
        ;;
    log|logs)
        journalctl -u "$SERVICE" -f --no-pager
        ;;
    cli)
        shift
        $CLI -conf="$CONF" "$@"
        ;;
    *)
        echo "BCH2 Node Steuerung"
        echo ""
        echo "Verwendung: bch-node <Befehl>"
        echo ""
        echo "  start       Node starten"
        echo "  stop        Node stoppen"
        echo "  restart     Node neu starten"
        echo "  status      Status + Sync-Info"
        echo "  sync        getblockchaininfo"
        echo "  balance     Kontostand anzeigen"
        echo "  newaddress  Neue Adresse erzeugen"
        echo "  log         Live-Logs anzeigen"
        echo "  cli <cmd>   Beliebigen bitcoincashII-cli Befehl ausführen"
        echo ""
        echo "Beispiele:"
        echo "  bch-node start"
        echo "  bch-node status"
        echo "  bch-node cli getnewaddress"
        ;;
esac
WRAPEOF

    $SUDO chmod +x "$CLI_WRAPPER"
    echo -e "${GREEN}✓ 'bch-node' Befehl installiert${NC}"
}

main() {
    need_sudo
    detect_arch

    echo ""
    echo "Es wird installiert:"
    echo "  • bitcoincashIId + bitcoincashII-cli"
    echo "  • Config unter $DATA_DIR"
    echo "  • systemd Service: $SERVICE_NAME"
    echo "  • Kommando: bch-node"
    echo ""
    read -p "Fortfahren? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "Abgebrochen."
        exit 0
    fi

    install_binaries
    create_config
    create_service
    create_cli_wrapper

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Installation abgeschlossen!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo "Nächste Schritte:"
    echo ""
    echo "  1. Node starten:"
    echo "       bch-node start"
    echo ""
    echo "  2. Sync abwarten:"
    echo "       bch-node status"
    echo "       (Warten bis initialblockdownload = false)"
    echo ""
    echo "  3. RPC-Passwort aus der Config in dein"
    echo "     Solo-Stratum config/config.yaml eintragen."
    echo ""
    echo "  4. Danach Stratum + Dashboard starten."
    echo ""
    echo "Hilfe:  bch-node"
    echo ""
}

main
