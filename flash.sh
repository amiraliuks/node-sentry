#!/usr/bin/env bash

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FIRMWARE_DIR="$SCRIPT_DIR/nodes/firmware"

detect_serial() {
    for p in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyACM0 /dev/ttyACM1; do
        [ -c "$p" ] && echo "$p" && return
    done
}

clear
echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}          node-sentry // flash_firmware           ${NC}"
echo -e "${GREEN}==================================================${NC}\n"

# Check for credentials.h
if [ ! -f "$FIRMWARE_DIR/credentials.h" ]; then
    echo -e "${RED}[!] nodes/firmware/credentials.h not found.${NC}"
    echo -e "    copy credentials.h.example and fill in your WiFi/MQTT details."
    exit 1
fi

# Check for pio
if ! command -v pio &>/dev/null; then
    echo -e "${RED}[!] PlatformIO CLI (pio) not found.${NC}"
    echo -e "    install it: pip install platformio"
    exit 1
fi

# Check device is plugged in
PORT=$(detect_serial)
if [ -z "$PORT" ]; then
    echo -e "${RED}[!] no device detected.${NC}"
    echo -e "    tried: /dev/ttyUSB0, /dev/ttyUSB1, /dev/ttyACM0, /dev/ttyACM1"
    echo -e "    plug in the WeMos and try again."
    exit 1
fi
echo -e "${GREEN}[*] device found at ${PORT}${NC}"

# Free the port if something else has it open
if command -v fuser &>/dev/null && fuser "$PORT" &>/dev/null; then
    echo -e "${YELLOW}[!] ${PORT} is held by PID $(fuser "$PORT" 2>/dev/null) — releasing...${NC}"
    fuser -k "$PORT" 2>/dev/null
    sleep 0.5
fi

echo -e "${CYAN}[*] building and flashing...${NC}\n"
cd "$FIRMWARE_DIR" && pio run -e d1_mini_pro -t upload

if [ $? -eq 0 ]; then
    echo -e "\n${GREEN}[*] done. firmware flashed successfully.${NC}"
else
    echo -e "\n${RED}[!] flash failed. check the output above.${NC}"
    exit 1
fi
