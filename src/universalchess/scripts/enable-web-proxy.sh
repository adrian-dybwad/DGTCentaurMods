#!/bin/bash
# Enable nginx site for universal-chess-web
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/universal-chess-web /etc/nginx/sites-enabled/

# Test config and reload/start nginx
if nginx -t; then
    # Use restart instead of reload - works whether nginx is running or not
    systemctl restart nginx || systemctl start nginx || true
fi
