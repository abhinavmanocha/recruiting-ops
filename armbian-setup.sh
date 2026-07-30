#!/usr/bin/env bash
# Recruiting Ops Centre — Armbian Setup Script
# Run this ON the Armbian box (192.168.2.137) to:
#   1. Update the app with the latest code
#   2. Restart the service
#   3. Install + configure cloudflared tunnel for public access

set -e

APP_DIR="$HOME/www/recruiting-ops"
SERVICE_NAME="recruiting-ops.service"
TUNNEL_NAME="recruiting-ops-tunnel"

echo "=== 1. Install/update Python dependencies ==="
cd "$APP_DIR"
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install flask werkzeug pymupdf python-docx gunicorn 2>&1 | tail -3

echo ""
echo "=== 2. Restart the app service ==="
sudo systemctl restart "$SERVICE_NAME" 2>/dev/null || {
  echo "Creating systemd service..."
  sudo tee /etc/systemd/system/$SERVICE_NAME > /dev/null <<-SERVICEEOF
[Unit]
Description=Recruiting Ops Centre
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/venv/bin/python $APP_DIR/app.py
Restart=always
RestartSec=5
Environment=RECRUIT_USER=admin
Environment=RECRUIT_PASS=recruitops

[Install]
WantedBy=multi-user.target
SERVICEEOF
  sudo systemctl daemon-reload
  sudo systemctl enable $SERVICE_NAME
  sudo systemctl start $SERVICE_NAME
}
sleep 2
sudo systemctl status $SERVICE_NAME --no-pager | head -5

echo ""
echo "=== 3. Verify app responds ==="
curl -s -u admin:recruitops -o /dev/null -w "HTTP %{http_code}\n" http://localhost:5001/

echo ""
echo "=== 4. Set up Cloudflare Tunnel ==="
if ! command -v cloudflared &>/dev/null; then
  echo "Installing cloudflared..."
  curl -sL https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64 -o /tmp/cloudflared
  chmod +x /tmp/cloudflared
  sudo mv /tmp/cloudflared /usr/local/bin/cloudflared
fi

if [ ! -f "$HOME/.cloudflared/cert.pem" ]; then
  echo ""
  echo "================================================================"
  echo "  Cloudflare login required!"
  echo "  Run this in a separate terminal and follow the browser link:"
  echo ""
  echo "    cloudflared tunnel login"
  echo ""
  echo "  Then re-run this script to continue."
  echo "================================================================"
  echo ""
  exit 0
fi

# Create a named tunnel (persistent URL)
cloudflared tunnel create "$TUNNEL_NAME" 2>/dev/null || true

# Create config file
mkdir -p "$HOME/.cloudflared"
cat > "$HOME/.cloudflared/config-$TUNNEL_NAME.yml" <<-TUNEOF
tunnel: $TUNNEL_NAME
credentials-file: $HOME/.cloudflared/$TUNNEL_NAME.json

ingress:
  - hostname: recruiting-ops.YOUR-DOMAIN.com
    service: http://localhost:5001
  - service: http_status:404
TUNEOF

echo ""
echo "=== 5. Install tunnel as a service ==="
sudo cloudflared service install 2>/dev/null || true

echo ""
echo "================================================================"
echo "  ✅ App running at http://localhost:5001"
echo ""
echo "  For public access with a custom domain:"
echo "    1. Set your DNS in Cloudflare dashboard"
echo "       (point recruiting-ops.YOUR-DOMAIN.com to the tunnel)"
echo "    2. Run:  cloudflared tunnel route dns $TUNNEL_NAME recruiting-ops.YOUR-DOMAIN.com"
echo "    3. Start tunnel:  cloudflared tunnel run $TUNNEL_NAME"
echo ""
echo "  For a quick temp URL (no account needed):"
echo "    cloudflared tunnel --url http://localhost:5001"
echo ""
echo "  Login: admin / recruitops"
echo "================================================================"
