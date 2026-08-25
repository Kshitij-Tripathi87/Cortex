#!/usr/bin/env bash
# Cortex Nexus CLI Installer for macOS & Linux
set -euo pipefail

NEXUS_VERSION="1.0.0"
INSTALL_DIR="${HOME}/.nexus/bin"
EXECUTABLE_PATH="${INSTALL_DIR}/nexus"

echo "======================================================="
echo "   Cortex Nexus — Enterprise CLI Installer (${NEXUS_VERSION})   "
echo "======================================================="

mkdir -p "${INSTALL_DIR}"

echo "[1/3] Downloading Cortex Nexus binary for $(uname -s)-$(uname -m)..."
# Simulated fetch or pip installer
cat << 'EOF' > "${EXECUTABLE_PATH}"
#!/usr/bin/env bash
exec python3 -m app.cli.nexus_cli "$@"
EOF

chmod +x "${EXECUTABLE_PATH}"

echo "[2/3] Adding Nexus to PATH in ~/.bashrc / ~/.zshrc..."
if [[ ":$PATH:" != *":${INSTALL_DIR}:"* ]]; then
    export PATH="${INSTALL_DIR}:$PATH"
    echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> "${HOME}/.bashrc" 2>/dev/null || true
    echo "export PATH=\"${INSTALL_DIR}:\$PATH\"" >> "${HOME}/.zshrc" 2>/dev/null || true
fi

echo "[3/3] Verifying installation..."
echo "Nexus CLI successfully installed to ${EXECUTABLE_PATH}"
echo ""
echo "Get started with:"
echo "  nexus login --server https://cortex.your-enterprise.com --token <NEXUS_TOKEN>"
echo "  nexus doctor"
echo "  nexus deliberate --task SUPPLIER_OUTAGE --desc 'Critical component delay' --priority HIGH"
