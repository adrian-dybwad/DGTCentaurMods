#!/bin/bash
# Enable nginx site for centaurmods-web
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/centaurmods-web /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
