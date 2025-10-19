# CentaurMods Web Service Setup

## Overview
The web service runs Flask on port 5000 (non-privileged) and uses nginx to proxy requests from port 80.

## Files Modified/Created

### 1. Service Configuration
- **File**: `DGTCentaurMods/etc/systemd/system/centaurmods-web.service`
- **Changes**: Updated to run Flask on port 5000 instead of port 80

### 2. Nginx Configuration
- **File**: `DGTCentaurMods/etc/nginx/sites-available/centaurmods-web`
- **Purpose**: Proxies requests from port 80 to Flask running on port 5000

### 3. Setup Script
- **File**: `DGTCentaurMods/scripts/enable-web-proxy.sh`
- **Purpose**: Enables the nginx site and reloads nginx

## Installation Steps

1. **Copy service file**:
   ```bash
   sudo cp DGTCentaurMods/etc/systemd/system/centaurmods-web.service /etc/systemd/system/
   ```

2. **Copy nginx configuration**:
   ```bash
   sudo cp DGTCentaurMods/etc/nginx/sites-available/centaurmods-web /etc/nginx/sites-available/
   ```

3. **Enable nginx site**:
   ```bash
   sudo chmod +x DGTCentaurMods/scripts/enable-web-proxy.sh
   sudo ./DGTCentaurMods/scripts/enable-web-proxy.sh
   ```

4. **Reload systemd and start services**:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable centaurmods-web.service
   sudo systemctl start centaurmods-web.service
   ```

## Benefits

- **No special privileges needed**: Flask runs on port 5000 as pi user
- **Standard port access**: Users can access via port 80 (standard HTTP)
- **Better performance**: nginx handles static files and provides better performance
- **Easy debugging**: Separate logs for nginx and Flask
- **WebSocket support**: nginx configuration includes WebSocket proxy support

## Logs

- **Flask logs**: `/var/log/centaurmods-web.log`
- **Nginx logs**: `/var/log/nginx/access.log` and `/var/log/nginx/error.log`

## Service Management

```bash
# Check service status
sudo systemctl status centaurmods-web.service

# View Flask logs
sudo tail -f /var/log/centaurmods-web.log

# View nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log

# Restart services
sudo systemctl restart centaurmods-web.service
sudo systemctl restart nginx
```
