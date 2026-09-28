#!/usr/bin/env bash
# 상장 페이지 https 설정 (최초 1회). 저장소 루트에서 실행: sudo bash deploy/setup_https.sh
set -euo pipefail

DOMAIN=cyberfondo.yangarch.net
WEBROOT=/var/www/certbot
CONF_DIR=/etc/nginx/conf.d

cd "$(dirname "$0")/.."

command -v certbot >/dev/null || apt-get install -y certbot

# 1) 80포트 인증 경로 먼저 열기
mkdir -p "$WEBROOT"
rm -f "$CONF_DIR/cyberfondo.conf"          # 이전 http 버전이 있으면 제거 (인증서 없이 ssl 설정이 있으면 nginx -t 실패)
cp deploy/nginx/cyberfondo-acme.conf "$CONF_DIR/"
nginx -t && systemctl reload nginx

# 2) 인증서 발급 (이메일/약관 동의는 대화형으로 입력), 갱신 시 nginx 자동 reload
certbot certonly --webroot -w "$WEBROOT" -d "$DOMAIN" \
    --deploy-hook "systemctl reload nginx"

# 3) https(4080) 사이트 설정
cp deploy/nginx/cyberfondo.conf "$CONF_DIR/"
nginx -t && systemctl reload nginx

echo "완료: https://$DOMAIN:4080"
echo "자동 갱신 확인: certbot renew --dry-run"
