#!/usr/bin/env bash

GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

BAUD=115200
BROKER_HOST="192.168.0.192"
BROKER_PORT=1883

# Read broker config from .env if present
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
if [ -f "$ENV_FILE" ]; then
    _h=$(grep -E '^MQTT_BROKER=' "$ENV_FILE" | cut -d= -f2)
    _p=$(grep -E '^MQTT_PORT='   "$ENV_FILE" | cut -d= -f2)
    [ -n "$_h" ] && BROKER_HOST="$_h"
    [ -n "$_p" ] && BROKER_PORT="$_p"
fi

# Detect first available serial port
detect_serial() {
    for p in /dev/ttyUSB0 /dev/ttyUSB1 /dev/ttyACM0 /dev/ttyACM1; do
        [ -c "$p" ] && echo "$p" && return
    done
}

clear
echo -e "${GREEN}==================================================${NC}"
echo -e "${GREEN}          node-sentry // log_interface            ${NC}"
echo -e "${GREEN}==================================================${NC}"
echo ""
echo -e "select data stream tracking mode:"
echo -e " [1] ${CYAN}usb hardware serial${NC} (direct read via serial port)"
echo -e " [2] ${CYAN}over-the-air mqtt${NC}   (live telemetry from ${BROKER_HOST}:${BROKER_PORT})"
echo -e " [3] quit"
echo ""
read -rp "choice [1-3]: " choice

case $choice in
    1)
        if ! command -v screen &> /dev/null; then
            echo -e "\n${YELLOW}[!] screen not found. installing...${NC}"
            sudo apt-get update -qq && sudo apt-get install -y screen
        fi

        PORT=$(detect_serial)
        if [ -z "$PORT" ]; then
            echo -e "\n${RED}[!] no serial port detected.${NC}"
            echo -e "tried: /dev/ttyUSB0, /dev/ttyUSB1, /dev/ttyACM0, /dev/ttyACM1"
            echo -e "make sure the wemos is plugged in and the ch340 driver is loaded."
            exit 1
        fi

        echo -e "\n${GREEN}[*] found device at ${PORT}, opening at ${BAUD} baud...${NC}"

        if command -v fuser &>/dev/null && fuser "$PORT" &>/dev/null; then
            echo -e "${YELLOW}[!] ${PORT} is held by another process (PID: $(fuser "$PORT" 2>/dev/null)).${NC}"
            read -rp "    kill it and continue? [y/N]: " yn
            if [[ "$yn" =~ ^[Yy]$ ]]; then
                fuser -k "$PORT" 2>/dev/null
                sleep 0.5
            else
                echo -e "${RED}[!] aborted.${NC}"
                exit 1
            fi
        fi

        echo -e "${YELLOW}[i] to exit: Ctrl+A then \\\\${NC}\n"
        screen "$PORT" "$BAUD"
        ;;

    2)
        if ! command -v mosquitto_sub &> /dev/null; then
            echo -e "\n${YELLOW}[!] mosquitto_sub not found. installing...${NC}"
            sudo apt-get update -qq && sudo apt-get install -y mosquitto-clients
        fi

        echo -e "\n${GREEN}[*] connecting to ${BROKER_HOST}:${BROKER_PORT}...${NC}"
        echo -e "${CYAN}watching: nodes/#${NC}"
        echo -e "${YELLOW}[i] to exit: Ctrl+C${NC}\n"
        mosquitto_sub -h "$BROKER_HOST" -p "$BROKER_PORT" -t "nodes/#" -v
        ;;

    3)
        echo -e "\n[!] exiting."
        exit 0
        ;;

    *)
        echo -e "\n${RED}[!] invalid option.${NC}"
        exit 1
        ;;
esac
