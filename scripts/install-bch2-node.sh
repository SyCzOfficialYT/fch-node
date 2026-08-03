#!/bin/bash
set -e

# ============================================================
#  BCH2 Node Interactive Installer
#  - bitcoincashIId + systemd
#  - bch-node CLI
#  - RPC-Passwort automatisch in config/config.yaml
#  - Stratum + Dashboard Start-Unterstützung
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
YAML_EXAMPLE="$REPO_ROOT/config/config.example.yaml"
YAML_FILE="$REPO_ROOT/config/config.yaml"

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════╗"
echo "║     BCH2 Node Installer v${VERSION}          ║"
echo "╚════════════════════════════════════════════╝"
echo -e "${NC}"

need_sudo() {
    if [ "$EUID" -ne 0 ]; then
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
        echo -e "${RED}Download fehlgeschlagen: $DOWNLOAD_URL${NC}"
        exit 1
    fi

    echo -e "${CYAN}→ Entpacke...${NC}"
    tar -xzf "$ASSET"

    BINDIR=$(find . -type d -name "bin" | head -n1)
    if [ -z "$BINDIR" ]; then
        BINDIR="."
    fi

    echo -e "${CYAN}→ Installiere Binaries...${NC}"
    $SUDO cp "$BINDIR"/bitcoincashIId "$INSTALL_DIR/" 2>/dev/null || true
    $SUDO cp "$BINDIR"/bitcoincashII-cli "$INSTALL_DIR/" 2>/dev/null || true
    [ -f bitcoincashIId ] && $SUDO cp bitcoincashIId "$INSTALL_DIR/"
    [ -f bitcoincashII-cli ] && $SUDO cp bitcoincashII-cli "$INSTALL_DIR/"
    $SUDO chmod +x "$INSTALL_DIR"/bitcoincashIId "$INSTALL_DIR"/bitcoincashII-cli

    cd /
    rm -rf "$TMPDIR"
    echo -e "${GREEN}✓ Binaries installiert${NC}"
    bitcoincashIId --version 2>/dev/null || true
}

create_config() {
    echo ""
    mkdir -p "$DATA_DIR"

    if [ -f "$CONF_FILE" ]; then
        echo -e "${YELLOW}Node-Config existiert bereits.${NC}"
        read -p "Überschreiben? [y/N] " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            RPC_PASS=$(grep -E '^rpcpassword=' "$CONF_FILE" | cut -d= -f2- | tr -d '[:space:]')
            echo "Behalte bestehende Config. RPC-Passwort wird in YAML übernommen."
            return
        fi
    fi

    RPC_PASS=$(openssl rand -base64 24 2>/dev/null || head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 32)

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
    echo -e "${GREEN}✓ Node-Config erstellt${NC}"
}

write_yaml() {
    echo ""
    echo -e "${CYAN}→ Schreibe RPC-Passwort in config/config.yaml...${NC}"

    mkdir -p "$REPO_ROOT/config"

    if [ ! -f "$YAML_FILE" ]; then
        if [ -f "$YAML_EXAMPLE" ]; then
            cp "$YAML_EXAMPLE" "$YAML_FILE"
        else
            cat > "$YAML_FILE" << YAMLEOF
rpc:
  host: "127.0.0.1"
  port: 8342
  user: "bch2rpc"
  password: "CHANGE_ME"
  timeout: 30

pool:
  payout_address: "bitcoincashii:qqssqww4u4rldtl04gshuqvrledjhuwy95ytdyw0xa"
  stratum_port: 3333
  stratum_host: "0.0.0.0"
  start_difficulty: 1000
  job_interval: 30

monitor:
  host: "0.0.0.0"
  port: 5000
YAMLEOF
        fi
    fi

    if grep -q 'password:' "$YAML_FILE"; then
        sed -i "s|password:.*|password: \"${RPC_PASS}\"|" "$YAML_FILE"
    else
        sed -i "/rpc:/a\  password: \"${RPC_PASS}\"" "$YAML_FILE"
    fi

    sed -i 's|user:.*|user: "bch2rpc"|' "$YAML_FILE" 2>/dev/null || true

    echo -e "${GREEN}✓ config/config.yaml aktualisiert (RPC-Passwort eingetragen)${NC}"
}

create_service() {
    echo ""
    echo -e "${CYAN}→ Erstelle systemd Service für die Node...${NC}"

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
    $SUDO systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
    echo -e "${GREEN}✓ systemd Service aktiviert${NC}"
}

create_cli_wrapper() {
    echo ""
    echo -e "${CYAN}→ Installiere 'bch-node' Befehl...${NC}"

    $SUDO tee "$CLI_WRAPPER" > /dev/null << WRAPEOF
#!/bin/bash
# bch-node – Steuerung für Node + Stratum + Dashboard

SERVICE="bch2-node"
CLI="bitcoincashII-cli"
CONF="$HOME/.bitcoincashII/bitcoincashII.conf"
REPO="$REPO_ROOT"
STRATUM_PIDFILE="/tmp/bch2-stratum.pid"
MONITOR_PIDFILE="/tmp/bch2-monitor.pid"

start_stack() {
    echo "Starte BCH2 Node..."
    sudo systemctl start "\$SERVICE"
    sleep 2

    if [ -f "\$REPO/stratum/server.py" ]; then
        if [ -f "\$STRATUM_PIDFILE" ] && kill -0 \$(cat "\$STRATUM_PIDFILE") 2>/dev/null; then
            echo "Stratum läuft bereits."
        else
            echo "Starte Stratum..."
            cd "\$REPO"
            nohup python3 stratum/server.py > /tmp/bch2-stratum.log 2>&1 &
            echo \$! > "\$STRATUM_PIDFILE"
            echo "  Stratum PID \$(cat \$STRATUM_PIDFILE) – Log: /tmp/bch2-stratum.log"
        fi
    fi

    if [ -f "\$REPO/monitor/app.py" ]; then
        if [ -f "\$MONITOR_PIDFILE" ] && kill -0 \$(cat "\$MONITOR_PIDFILE") 2>/dev/null; then
            echo "Dashboard läuft bereits."
        else
            echo "Starte Dashboard..."
            cd "\$REPO"
            nohup python3 monitor/app.py > /tmp/bch2-monitor.log 2>&1 &
            echo \$! > "\$MONITOR_PIDFILE"
            echo "  Dashboard PID \$(cat \$MONITOR_PIDFILE) – http://0.0.0.0:5000"
        fi
    fi

    echo ""
    sudo systemctl status "\$SERVICE" --no-pager -l | head -n 12
}

stop_stack() {
    echo "Stoppe Stratum + Dashboard..."
    [ -f "\$STRATUM_PIDFILE" ] && kill \$(cat "\$STRATUM_PIDFILE") 2>/dev/null || true
    [ -f "\$MONITOR_PIDFILE" ] && kill \$(cat "\$MONITOR_PIDFILE") 2>/dev/null || true
    rm -f "\$STRATUM_PIDFILE" "\$MONITOR_PIDFILE"

    echo "Stoppe Node..."
    sudo systemctl stop "\$SERVICE"
    echo "Alles gestoppt."
}

case "\$1" in
    start)
        start_stack
        ;;
    stop)
        stop_stack
        ;;
    restart)
        stop_stack
        sleep 1
        start_stack
        ;;
    status)
        sudo systemctl status "\$SERVICE" --no-pager -l | head -n 15
        echo ""
        if [ -f "\$STRATUM_PIDFILE" ] && kill -0 \$(cat "\$STRATUM_PIDFILE") 2>/dev/null; then
            echo "Stratum:   läuft (PID \$(cat \$STRATUM_PIDFILE))"
        else
            echo "Stratum:   gestoppt"
        fi
        if [ -f "\$MONITOR_PIDFILE" ] && kill -0 \$(cat "\$MONITOR_PIDFILE") 2>/dev/null; then
            echo "Dashboard: läuft (PID \$(cat \$MONITOR_PIDFILE)) → http://\$(hostname -I | awk '{print \$1}'):5000"
        else
            echo "Dashboard: gestoppt"
        fi
        echo ""
        if \$CLI -conf="\$CONF" getblockchaininfo > /dev/null 2>&1; then
            echo "--- Blockchain ---"
            \$CLI -conf="\$CONF" getblockchaininfo | grep -E '"chain"|"blocks"|"headers"|"verificationprogress"|"initialblockdownload"|"difficulty"'
        else
            echo "Node antwortet noch nicht auf RPC."
        fi
        ;;
    sync|info)
        \$CLI -conf="\$CONF" getblockchaininfo
        ;;
    balance)
        \$CLI -conf="\$CONF" getbalance
        ;;
    newaddress)
        \$CLI -conf="\$CONF" getnewaddress
        ;;
    log|logs)
        echo "=== Node Logs (Ctrl+C zum Beenden) ==="
        journalctl -u "\$SERVICE" -f --no-pager
        ;;
    stratum-log)
        tail -f /tmp/bch2-stratum.log
        ;;
    dash-log|monitor-log)
        tail -f /tmp/bch2-monitor.log
        ;;
    cli)
        shift
        \$CLI -conf="\$CONF" "\$@"
        ;;
    *)
        echo "BCH2 Solo Stack Steuerung"
        echo ""
        echo "  bch-node start        Node + Stratum + Dashboard starten"
        echo "  bch-node stop         Alles stoppen"
        echo "  bch-node restart      Alles neu starten"
        echo "  bch-node status       Status von allem"
        echo "  bch-node sync         Blockchain-Info"
        echo "  bch-node balance      Kontostand"
        echo "  bch-node newaddress   Neue Adresse"
        echo "  bch-node log          Node Live-Logs"
        echo "  bch-node stratum-log  Stratum Logs"
        echo "  bch-node dash-log     Dashboard Logs"
        echo "  bch-node cli <cmd>    bitcoincashII-cli Befehl"
        echo ""
        ;;
esac
WRAPEOF

    $SUDO chmod +x "$CLI_WRAPPER"
    echo -e "${GREEN}✓ 'bch-node' Befehl installiert${NC}"
}

install_python_deps() {
    echo ""
    echo -e "${CYAN}→ Python-Abhängigkeiten für Stratum/Dashboard...${NC}"
    if [ -f "$REPO_ROOT/requirements.txt" ]; then
        pip3 install -q -r "$REPO_ROOT/requirements.txt" && \
            echo -e "${GREEN}✓ Python-Pakete installiert${NC}" || \
            echo -e "${YELLOW}⚠ pip install fehlgeschlagen – bitte manuell: pip3 install -r requirements.txt${NC}"
    fi
}

main() {
    need_sudo
    detect_arch

    echo ""
    echo "Installiert wird:"
    echo "  • bitcoincashIId + CLI"
    echo "  • systemd Service"
    echo "  • bch-node Kommando (startet auch Stratum + Dashboard)"
    echo "  • RPC-Passwort → config/config.yaml"
    echo ""
    read -p "Fortfahren? [Y/n] " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "Abgebrochen."
        exit 0
    fi

    install_binaries
    create_config
    write_yaml
    create_service
    create_cli_wrapper
    install_python_deps

    echo ""
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Installation fertig!${NC}"
    echo -e "${GREEN}════════════════════════════════════════════${NC}"
    echo ""
    echo "Alles steuern mit:"
    echo ""
    echo "  bch-node start     ← startet Node + Stratum + Dashboard"
    echo "  bch-node status"
    echo "  bch-node stop"
    echo ""
    echo "Dashboard dann unter:  http://DEINE_IP:5000"
    echo "Stratum Port:          3333"
    echo ""
    echo "Zuerst Node syncen lassen:"
    echo "  bch-node start"
    echo "  bch-node status    # warten bis initialblockdownload = false"
    echo ""
}

main
