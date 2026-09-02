#!/usr/bin/env bash
# Eenmalig te draaien op een verse Ubuntu-VPS (als root, via SSH).
# Installeert Docker, schakelt automatische beveiligingsupdates in, en zet
# een firewall op die alleen SSH/HTTP/HTTPS toelaat.
#
# Gebruik:
#   ssh root@<server-ip>
#   curl -fsSL https://raw.githubusercontent.com/<repo>/main/deploy/setup-vps.sh | bash
# (of: dit bestand kopieren naar de server en `bash setup-vps.sh` draaien)
set -euo pipefail

echo "==> Systeem bijwerken"
apt-get update && apt-get upgrade -y

echo "==> Docker installeren"
curl -fsSL https://get.docker.com | sh

echo "==> Automatische beveiligingsupdates inschakelen"
apt-get install -y unattended-upgrades
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "==> Firewall instellen (alleen SSH, HTTP, HTTPS toegestaan)"
apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "==> Klaar. Versies:"
docker --version
docker compose version
