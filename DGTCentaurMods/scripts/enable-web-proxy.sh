#!/bin/bash
# Enable nginx site for centaurmods-web
ln -sf /etc/nginx/sites-available/centaurmods-web /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
