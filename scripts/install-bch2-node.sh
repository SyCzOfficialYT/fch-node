#!/bin/bash
set -euo pipefail

# ============================================================
# BCH2 Node Interactive Installer
# - bitcoincashIId + CLI
# - isolated legacy runtime for BCH2 v27.0.2
# - systemd service
# - bch-node CLI
# - RPC credentials synchronized with config/config.yaml
# - Stratum + Dashboard support
# ============================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

VERSION="27.0.2"
BASE_URL="https://github.com/BitcoincashII/bitcoincashII-core/releases/download/v${VERSION}"
INSTALL_DIR="/usr/local/bin"
RUNTIME_DIR="/usr/local/lib/bch2"
DATA_DIR="$HOME/.bitcoincashII"
CONF_FILE="$DATA_DIR/bitcoincashII.conf"
SERVICE_NAME="bch2-node"
CLI_WRAPPER="/usr/local/bin/bch-node"
LD_CONF_FILE="/etc/ld.so.conf.d/bch2.conf"

MINIUPNPC_VERSION="2.2.2"
MINIUPNPC_URL="https://miniupnp.tuxfamily.org/files/miniupnpc-${MINIUPNPC_VERSION}.tar.gz"
NATPMP_VERSION="20230423"
NATPMP_URL="https://miniupnp.tuxfamily.org/files/libnatpmp-${NATPMP_VERSION}.tar.gz"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
YAML_EXAMPLE="$REPO_ROOT/config/config.example.yaml"
YAML_FILE="$REPO_ROOT/config/config.yaml"

printf '%b' "${CYAN}"
echo "╔════════════════════════════════════════════╗"
echo "║     BCH2 Node Installer v${VERSION}          ║"
echo "╚════════════════════════════════════════════╝"
printf '%b' "${NC}"

need_sudo() {
    if [ "$EUID" -ne 0 ]; then SUDO="sudo"; else SUDO=""; fi
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || {
        echo -e "${RED}✗ Benötigtes Kommando fehlt: $1${NC}"
        exit 1
    }
}

generate_rpc_password() {
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32
    else
        head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' | cut -c1-64
    fi
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)
            ASSET="bitcoincashII-${VERSION}-linux64.tar.gz"
            echo -e "${GREEN}✓ Architektur: x86_64${NC}"
            ;;
        aarch64|arm64)
            ASSET="bitcoincashII-${VERSION}-linux-aarch64.tar.gz"
            echo -e "${GREEN}✓ Architektur: aarch64${NC}"
            ;;
        *)
            echo -e "${RED}✗ Nicht unterstützte Architektur: $(uname -m)${NC}"
            exit 1
            ;;
    esac
    DOWNLOAD_URL="${BASE_URL}/${ASSET}"
}

download_archive() {
    local url="$1" output="$2"
    curl -fL --retry 3 --retry-delay 2 --connect-timeout 15 -o "$output" "$url"
}

install_legacy_runtime() {
    echo ""
    echo -e "${CYAN}→ Prüfe BCH2 Runtime...${NC}"

    local miniupnpc_lib="$RUNTIME_DIR/libminiupnpc.so.17"
    local natpmp_lib="$RUNTIME_DIR/libnatpmp.so.1"

    require_command curl
    require_command tar
    require_command make
    require_command cc

    $SUDO mkdir -p "$RUNTIME_DIR"

    if [ -f "$miniupnpc_lib" ] && [ -f "$natpmp_lib" ]; then
        echo -e "${GREEN}✓ Private BCH2 Runtime bereits vorhanden${NC}"
    else
        echo -e "${YELLOW}BCH2 v${VERSION} benötigt libminiupnpc.so.17 und libnatpmp.so.1.${NC}"
        echo "Die Libraries werden isoliert unter ${RUNTIME_DIR} gebaut."

        local runtime_tmp
        runtime_tmp="$(mktemp -d)"
        trap 'rm -rf "$runtime_tmp"' RETURN

        local miniupnpc_archive="$runtime_tmp/miniupnpc-${MINIUPNPC_VERSION}.tar.gz"
        local natpmp_archive="$runtime_tmp/libnatpmp-${NATPMP_VERSION}.tar.gz"

        echo -e "${CYAN}→ Lade miniupnpc ${MINIUPNPC_VERSION} herunter...${NC}"
        download_archive "$MINIUPNPC_URL" "$miniupnpc_archive"
        tar -xzf "$miniupnpc_archive" -C "$runtime_tmp"

        echo -e "${CYAN}→ Baue libminiupnpc.so.17...${NC}"
        (
            cd "$runtime_tmp/miniupnpc-${MINIUPNPC_VERSION}"
            make -j"$(nproc)"
        )

        local miniupnpc_built="$runtime_tmp/miniupnpc-${MINIUPNPC_VERSION}/libminiupnpc.so"
        if [ ! -f "$miniupnpc_built" ]; then
            echo -e "${RED}✗ miniupnpc Build erzeugte keine libminiupnpc.so.${NC}"
            exit 1
        fi
        $SUDO install -Dm755 "$miniupnpc_built" "$miniupnpc_lib"

        echo -e "${CYAN}→ Lade libnatpmp ${NATPMP_VERSION} herunter...${NC}"
        download_archive "$NATPMP_URL" "$natpmp_archive"
        tar -xzf "$natpmp_archive" -C "$runtime_tmp"

        echo -e "${CYAN}→ Baue libnatpmp.so.1...${NC}"
        (
            cd "$runtime_tmp/libnatpmp-${NATPMP_VERSION}"
            make -j"$(nproc)"
        )

        local natpmp_built="$runtime_tmp/libnatpmp-${NATPMP_VERSION}/libnatpmp.so"
        if [ ! -f "$natpmp_built" ]; then
            echo -e "${RED}✗ libnatpmp Build erzeugte keine libnatpmp.so.${NC}"
            exit 1
        fi
        $SUDO install -Dm755 "$natpmp_built" "$natpmp_lib"

        rm -rf "$runtime_tmp"
        trap - RETURN
        echo -e "${GREEN}✓ Private BCH2 Runtime installiert${NC}"
    fi

    # BCH2 v27.0.2 needs legacy SONAMEs which may differ from distro
    # libraries. Keep them isolated and use LD_LIBRARY_PATH explicitly.
    $SUDO chmod 755 "$RUNTIME_DIR"/*.so*

    if [ ! -s "$miniupnpc_lib" ]; then
        echo -e "${RED}✗ $miniupnpc_lib ist nicht vorhanden oder leer.${NC}"
        exit 1
    fi
    if [ ! -s "$natpmp_lib" ]; then
        echo -e "${RED}✗ $natpmp_lib ist nicht vorhanden oder leer.${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ BCH2 Runtime-Dateien vorhanden und einsatzbereit${NC}"
}

install_binaries() {
    echo ""
    echo -e "${CYAN}→ Lade ${ASSET} herunter...${NC}"

    local tmpdir bindir
    tmpdir="$(mktemp -d)"
    trap 'rm -rf "$tmpdir"' RETURN

    download_archive "$DOWNLOAD_URL" "$tmpdir/$ASSET"
    echo -e "${CYAN}→ Entpacke...${NC}"
    tar -xzf "$tmpdir/$ASSET" -C "$tmpdir"

    bindir="$(find "$tmpdir" -type f -name bitcoincashIId -printf '%h\n' | head -n1)"
    if [ -z "$bindir" ] || [ ! -f "$bindir/bitcoincashII-cli" ]; then
        echo -e "${RED}✗ BCH2 Binaries wurden im Release-Archiv nicht gefunden.${NC}"
        exit 1
    fi

    echo -e "${CYAN}→ Stoppe vorhandene Node vor dem Binary-Update...${NC}"
    $SUDO systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true

    echo -e "${CYAN}→ Installiere Binaries...${NC}"
    $SUDO install -Dm755 "$bindir/bitcoincashIId" "$INSTALL_DIR/bitcoincashIId"
    $SUDO install -Dm755 "$bindir/bitcoincashII-cli" "$INSTALL_DIR/bitcoincashII-cli"

    rm -rf "$tmpdir"
    trap - RETURN
    echo -e "${GREEN}✓ Binaries installiert${NC}"
}

verify_runtime() {
    echo ""
    echo -e "${CYAN}→ Prüfe BCH2 Runtime-Abhängigkeiten...${NC}"

    local runtime_ld="${RUNTIME_DIR}${LD_LIBRARY_PATH:+:${LD_LIBRARY_PATH}}"
    local deps
    deps="$(LD_LIBRARY_PATH="$runtime_ld" ldd "$INSTALL_DIR/bitcoincashIId")"

    if echo "$deps" | grep -q 'libminiupnpc.so.17 => not found'; then
        echo -e "${RED}✗ libminiupnpc.so.17 wird weiterhin nicht gefunden.${NC}"
        exit 1
    fi
    if echo "$deps" | grep -q 'libnatpmp.so.1 => not found'; then
        echo -e "${RED}✗ libnatpmp.so.1 wird weiterhin nicht gefunden.${NC}"
        exit 1
    fi

    echo -e "${GREEN}✓ BCH2 Runtime-Abhängigkeiten vorhanden${NC}"
}

create_config() {
    echo ""
    mkdir -p "$DATA_DIR"

    local existing_user existing_pass
    existing_user=""
    existing_pass=""

    if [ -f "$CONF_FILE" ]; then
        existing_user="$(grep -E '^rpcuser=' "$CONF_FILE" | head -n1 | cut -d= -f2- || true)"
        existing_pass="$(grep -E '^rpcpassword=' "$CONF_FILE" | head -n1 | cut -d= -f2- || true)"

        if [ -n "$existing_pass" ]; then
            RPC_PASS="$existing_pass"
            [ -n "$existing_user" ] && RPC_USER="$existing_user" || RPC_USER="bch2rpc"
            echo -e "${GREEN}✓ Vorhandene RPC-Zugangsdaten werden beibehalten.${NC}"
        else
            RPC_USER="bch2rpc"
            RPC_PASS="$(generate_rpc_password)"
            if grep -q '^rpcpassword=' "$CONF_FILE"; then
                sed -i "s|^rpcpassword=.*$|rpcpassword=${RPC_PASS}|" "$CONF_FILE"
            else
                printf '\nrpcpassword=%s\n' "$RPC_PASS" >> "$CONF_FILE"
            fi
            if grep -q '^rpcuser=' "$CONF_FILE"; then
                sed -i "s|^rpcuser=.*$|rpcuser=${RPC_USER}|" "$CONF_FILE"
            else
                printf 'rpcuser=%s\n' "$RPC_USER" >> "$CONF_FILE"
            fi
            echo -e "${GREEN}✓ RPC-Zugangsdaten repariert${NC}"
        fi
    else
        RPC_USER="bch2rpc"
        RPC_PASS="$(generate_rpc_password)"
        cat > "$CONF_FILE" << CONFEOF
# BCH2 Node Config – generiert vom Installer
server=1
daemon=1
listen=1
port=8339
rpcport=8342
rpcbind=127.0.0.1
rpcallowip=127.0.0.1
rpcuser=${RPC_USER}
rpcpassword=${RPC_PASS}
txindex=1
CONFEOF
        echo -e "${GREEN}✓ Node-Config erstellt${NC}"
    fi

    if ! grep -q '^rpcbind=' "$CONF_FILE"; then
        sed -i '/^rpcport=/a rpcbind=127.0.0.1' "$CONF_FILE"
    fi
    if ! grep -q '^rpcallowip=' "$CONF_FILE"; then
        sed -i '/^rpcbind=/a rpcallowip=127.0.0.1' "$CONF_FILE"
    fi
    chmod 600 "$CONF_FILE"
}

write_yaml() {
    echo ""
    echo -e "${CYAN}→ Synchronisiere RPC-Zugangsdaten mit config/config.yaml...${NC}"
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

    if grep -qE '^  password:' "$YAML_FILE"; then
        sed -i "s|^  password:.*$|  password: \"${RPC_PASS}\"|" "$YAML_FILE"
    else
        sed -i "/^rpc:/a\\  password: \"${RPC_PASS}\"" "$YAML_FILE"
    fi

    if grep -qE '^  user:' "$YAML_FILE"; then
        sed -i "s|^  user:.*$|  user: \"${RPC_USER}\"|" "$YAML_FILE"
    else
        sed -i "/^rpc:/a\\  user: \"${RPC_USER}\"" "$YAML_FILE"
    fi

    echo -e "${GREEN}✓ config/config.yaml synchronisiert${NC}"
}

create_service() {
    echo ""
    echo -e "${CYAN}→ Erstelle systemd Service für die Node...${NC}"

    local service_file="/etc/systemd/system/${SERVICE_NAME}.service"
    $SUDO tee "$service_file" >/dev/null << SVCEOF
[Unit]
Description=Bitcoin Cash II (BCH2) Node
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
User=$USER
Group=$USER
Environment="LD_LIBRARY_PATH=$RUNTIME_DIR"
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

    $SUDO tee "$CLI_WRAPPER" >/dev/null << WRAPEOF
#!/bin/bash
set -u

SERVICE="bch2-node"
CLI="bitcoincashII-cli"
CONF="\$HOME/.bitcoincashII/bitcoincashII.conf"
RUNTIME_DIR="/usr/local/lib/bch2"
REPO="$REPO_ROOT"
STRATUM_PIDFILE="/tmp/bch2-stratum.pid"
MONITOR_PIDFILE="/tmp/bch2-monitor.pid"

run_cli() {
    local rpc_user rpc_pass
    rpc_user="\$(sed -n 's/^rpcuser=//p' "\$CONF" | head -n1)"
    rpc_pass="\$(sed -n 's/^rpcpassword=//p' "\$CONF" | head -n1)"

    if [ -z "\$rpc_user" ] || [ -z "\$rpc_pass" ]; then
        echo "RPC credentials fehlen in \$CONF" >&2
        return 1
    fi

    LD_LIBRARY_PATH="\$RUNTIME_DIR\${LD_LIBRARY_PATH:+:\$LD_LIBRARY_PATH}" \\
        "\$CLI" \\
        -conf="\$CONF" \\
        -rpcconnect=127.0.0.1 \\
        -rpcport=8342 \\
        -rpcuser="\$rpc_user" \\
        -rpcpassword="\$rpc_pass" \\
        "\$@"
}

get_local_ip() {
    local ip
    ip=\$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<=NF; i++) if (\$i == "src") {print \$(i+1); exit}}')
    if [ -z "\$ip" ]; then
        ip=\$(ip -4 addr show scope global 2>/dev/null | awk '/inet / {sub(/\/.*/, "", \$2); print \$2; exit}')
    fi
    printf '%s' "\$ip"
}

start_stack() {
    echo "Starte BCH2 Node..."
    sudo systemctl start "\$SERVICE"
    sleep 2

    if [ -f "\$REPO/stratum/server.py" ]; then
        if [ -f "\$STRATUM_PIDFILE" ] && kill -0 "\$(cat "\$STRATUM_PIDFILE")" 2>/dev/null; then
            echo "Stratum läuft bereits."
        else
            echo "Starte Stratum..."
            cd "\$REPO"
            nohup python3 stratum/server.py > /tmp/bch2-stratum.log 2>&1 &
            echo \$! > "\$STRATUM_PIDFILE"
            echo "  Stratum PID \$(cat "\$STRATUM_PIDFILE") – Log: /tmp/bch2-stratum.log"
        fi
    fi

    if [ -f "\$REPO/monitor/app.py" ]; then
        if [ -f "\$MONITOR_PIDFILE" ] && kill -0 "\$(cat "\$MONITOR_PIDFILE")" 2>/dev/null; then
            echo "Dashboard läuft bereits."
        else
            echo "Starte Dashboard..."
            cd "\$REPO"
            nohup python3 monitor/app.py > /tmp/bch2-monitor.log 2>&1 &
            echo \$! > "\$MONITOR_PIDFILE"
        fi
    fi

    local_ip="\$(get_local_ip)"
    if [ -n "\$local_ip" ]; then
        echo "  Dashboard: http://\${local_ip}:5000"
    else
        echo "  Dashboard: http://<DEINE-IP>:5000"
    fi

    echo ""
    sudo systemctl status "\$SERVICE" --no-pager -l | head -n 12
}

stop_stack() {
    echo "Stoppe Stratum + Dashboard..."
    [ -f "\$STRATUM_PIDFILE" ] && kill "\$(cat "\$STRATUM_PIDFILE")" 2>/dev/null || true
    [ -f "\$MONITOR_PIDFILE" ] && kill "\$(cat "\$MONITOR_PIDFILE")" 2>/dev/null || true
    rm -f "\$STRATUM_PIDFILE" "\$MONITOR_PIDFILE"
    echo "Stoppe Node..."
    sudo systemctl stop "\$SERVICE"
    echo "Alles gestoppt."
}

case "\${1:-}" in
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
        if [ -f "\$STRATUM_PIDFILE" ] && kill -0 "\$(cat "\$STRATUM_PIDFILE")" 2>/dev/null; then
            echo "Stratum:   läuft (PID \$(cat "\$STRATUM_PIDFILE"))"
        else
            echo "Stratum:   gestoppt"
        fi

        if [ -f "\$MONITOR_PIDFILE" ] && kill -0 "\$(cat "\$MONITOR_PIDFILE")" 2>/dev/null; then
            local_ip="\$(get_local_ip)"
            if [ -n "\$local_ip" ]; then
                echo "Dashboard: läuft (PID \$(cat "\$MONITOR_PIDFILE")) → http://\${local_ip}:5000"
            else
                echo "Dashboard: läuft (PID \$(cat "\$MONITOR_PIDFILE")) → http://<DEINE-IP>:5000"
            fi
        else
            echo "Dashboard: gestoppt"
        fi

        echo ""
        if run_cli getblockchaininfo > /dev/null 2>&1; then
            echo "--- Blockchain ---"
            run_cli getblockchaininfo | grep -E '"chain"|"blocks"|"headers"|"verificationprogress"|"initialblockdownload"|"difficulty"'
        else
            echo "RPC:          nicht erreichbar oder Authentifizierung fehlgeschlagen."
        fi
        ;;
    sync|info)
        run_cli getblockchaininfo
        ;;
    balance)
        run_cli getbalance
        ;;
    newaddress)
        run_cli getnewaddress
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
        run_cli "\$@"
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
        pip3 install -q -r "$REPO_ROOT/requirements.txt" --break-system-packages && \
            echo -e "${GREEN}✓ Python-Pakete installiert${NC}" || \
            echo -e "${YELLOW}⚠ pip install fehlgeschlagen – bitte manuell installieren.${NC}"
    fi
}

main() {
    need_sudo
    detect_arch

    echo ""
    echo "Installiert wird:"
    echo "  • bitcoincashIId + CLI"
    echo "  • isolierte BCH2 Runtime (miniupnpc 2.2.2 + libnatpmp 20230423)"
    echo "  • systemd Service"
    echo "  • bch-node Kommando (startet auch Stratum + Dashboard)"
    echo "  • RPC-Passwort → config/config.yaml"
    echo ""
    read -p "Fortfahren? [Y/n] " -n 1 -r
    echo
    if [[ ${REPLY:-} =~ ^[Nn]$ ]]; then
        echo "Abgebrochen."
        exit 0
    fi

    install_legacy_runtime
    install_binaries
    verify_runtime
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
    echo "  bch-node start"
    echo "  bch-node status"
    echo "  bch-node stop"
    echo ""
    echo "Dashboard wird automatisch über die lokale IPv4-Adresse angezeigt."
    echo "Stratum Port:          3333"
    echo ""
    echo "Zuerst Node syncen lassen:"
    echo "  bch-node start"
    echo "  bch-node status"
    echo ""
}

main
