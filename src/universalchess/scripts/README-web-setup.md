# Universal Chess Web Service Setup

## Overview
The web service runs Flask on port 5000 (non-privileged) and uses nginx to proxy requests from port 80.

## Files Modified/Created

### 1. Service Configuration
- **File**: `packaging/deb-root/etc/systemd/system/universal-chess-web.service`
- **Changes**: Updated to run Flask on port 5000 instead of port 80

### 2. Nginx Configuration
- **File**: `packaging/deb-root/etc/nginx/sites-available/universal-chess-web`
- **Purpose**: Proxies requests from port 80 to Flask running on port 5000

### 3. Setup Script
- **File**: `src/universalchess/scripts/enable-web-proxy.sh`
- **Purpose**: Enables the nginx site and reloads nginx

## Installation Steps

1. **Copy service file**:
   ```bash
   sudo cp packaging/deb-root/etc/systemd/system/universal-chess-web.service /etc/systemd/system/
   ```

2. **Copy nginx configuration**:
   ```bash
   sudo cp packaging/deb-root/etc/nginx/sites-available/universal-chess-web /etc/nginx/sites-available/
   ```

3. **Enable nginx site**:
   ```bash
   sudo chmod +x src/universalchess/scripts/enable-web-proxy.sh
   sudo ./src/universalchess/scripts/enable-web-proxy.sh
   ```

4. **Reload systemd and start services**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable universal-chess-web.service
   sudo systemctl start universal-chess-web.service
   ```

## Benefits

- **No special privileges needed**: Flask runs on port 5000 as pi user
- **Standard port access**: Users can access via port 80 (standard HTTP)
- **Better performance**: nginx handles static files and provides better performance
- **Easy debugging**: Separate logs for nginx and Flask
- **WebSocket support**: nginx configuration includes WebSocket proxy support

## Logs

- **Flask logs**: `/var/log/universal-chess-web.log`
- **Nginx logs**: `/var/log/nginx/access.log` and `/var/log/nginx/error.log`

## Service Management

```bash
# Check service status
sudo systemctl status universal-chess-web.service

# View Flask logs
sudo tail -f /var/log/universal-chess-web.log

# View nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Restart services
sudo systemctl restart universal-chess-web.service
sudo systemctl restart nginx
```
