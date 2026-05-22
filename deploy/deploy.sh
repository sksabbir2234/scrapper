#!/bin/bash
# News Aggregator — Oracle Cloud Free VM Deploy Script
# Run on a fresh Ubuntu 22.04/24.04 ARM64 or AMD64 VM
# Usage: bash deploy.sh

set -e

APP_DIR="/opt/news-aggregator"
DB_NAME="newsdb"
DB_USER="newsuser"
DB_PASS="newspass"  # Change this!

echo "========================================="
echo " News Aggregator — Oracle Cloud Deploy"
echo "========================================="

# ── 1. System packages ──
echo "[1/7] Installing system packages..."
sudo apt update && sudo apt upgrade -y
sudo apt install -y python3 python3-pip python3-venv postgresql postgresql-contrib git curl

# ── 2. PostgreSQL setup ──
echo "[2/7] Setting up PostgreSQL..."
sudo systemctl enable postgresql
sudo systemctl start postgresql

# Create DB and user
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"

# ── 3. Clone repo ──
echo "[3/7] Cloning repository..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone https://github.com/sksabbir2234/scrapper.git "$APP_DIR"
fi
cd "$APP_DIR"

# ── 4. Python virtual env ──
echo "[4/7] Setting up Python environment..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r backend/requirements.txt

# ── 5. Environment file ──
echo "[5/7] Configuring environment..."
if [ ! -f .env ]; then
    cp .env.example .env
    # Generate a random secret key
    SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
    sed -i "s/change-this-to-a-long-random-string/$SECRET_KEY/" .env
    sed -i "s|postgresql://newsuser:newspass@localhost:5432/newsdb|postgresql://$DB_USER:$DB_PASS@localhost:5432/$DB_NAME|" .env
    sed -i "s/SITE_URL=http:\/\/localhost:8000/SITE_URL=http:\/\/$(curl -s ifconfig.me)/" .env
    sed -i "s/DEBUG=true/DEBUG=false/" .env
    echo ""
    echo "  .env created — edit it to add your GROQ_API_KEY and GITHUB_TOKEN:"
    echo "  nano $APP_DIR/.env"
    echo ""
fi

# ── 6. Systemd service ──
echo "[6/7] Creating systemd service..."
sudo tee /etc/systemd/system/news-aggregator.service > /dev/null <<EOF
[Unit]
Description=News Aggregator API
After=network.target postgresql.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=$APP_DIR/backend
Environment="PATH=$APP_DIR/venv/bin"
ExecStart=$APP_DIR/venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable news-aggregator

# ── 7. Start ──
echo "[7/7] Starting application..."
sudo systemctl restart news-aggregator

echo ""
echo "========================================="
echo " Deploy complete!"
echo "========================================="
echo ""
echo "  App:    http://$(curl -s ifconfig.me):8000"
echo "  Admin:  http://$(curl -s ifconfig.me):8000/admin"
echo ""
echo "  Logs:   sudo journalctl -u news-aggregator -f"
echo "  Status: sudo systemctl status news-aggregator"
echo ""
echo "  Edit .env:  nano $APP_DIR/.env"
echo "  Restart:    sudo systemctl restart news-aggregator"
echo ""
