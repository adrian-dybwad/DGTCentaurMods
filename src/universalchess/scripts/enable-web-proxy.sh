#!/bin/bash
# Enable nginx site for universal-chess-web
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/universal-chess-web /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
