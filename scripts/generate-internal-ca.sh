#!/bin/bash
set -e

# Script to generate an internal CA and certificates for Kubernetes services
# This allows you to add the CA to your trust store to avoid browser warnings

CA_NAME="home-lab-internal-ca"
CA_NAMESPACE="traefik"
CA_VALIDITY_DAYS=3650  # 10 years
CERT_VALIDITY_DAYS=365  # 1 year

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Home Lab Internal CA Generator ===${NC}"
echo ""

# Create temporary directory
TEMP_DIR=$(mktemp -d)
trap "rm -rf $TEMP_DIR" EXIT

cd "$TEMP_DIR"

# Check if CA secret already exists
if kubectl get secret "$CA_NAME" -n "$CA_NAMESPACE" &>/dev/null; then
    echo -e "${YELLOW}CA secret already exists. Do you want to regenerate? (y/N)${NC}"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "Exiting..."
        exit 0
    fi
    echo "Removing existing CA secret..."
    kubectl delete secret "$CA_NAME" -n "$CA_NAMESPACE"
fi

# Generate CA private key
echo -e "${GREEN}Generating CA private key...${NC}"
openssl genrsa -out ca-key.pem 4096

# Generate CA certificate
echo -e "${GREEN}Generating CA certificate (valid for $CA_VALIDITY_DAYS days)...${NC}"
openssl req -new -x509 -days "$CA_VALIDITY_DAYS" \
    -key ca-key.pem \
    -out ca-cert.pem \
    -subj "/CN=$CA_NAME/O=Home Lab/C=US" \
    -extensions v3_ca \
    -config <(
        cat <<EOF
[req]
distinguished_name = req_distinguished_name
[req_distinguished_name]
[v3_ca]
basicConstraints = critical,CA:TRUE
keyUsage = critical, keyCertSign, cRLSign
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer:always
EOF
    )

# Create Kubernetes secret for CA
echo -e "${GREEN}Creating Kubernetes secret for CA...${NC}"
kubectl create secret tls "$CA_NAME" \
    --cert=ca-cert.pem \
    --key=ca-key.pem \
    -n "$CA_NAMESPACE" \
    --dry-run=client -o yaml | kubectl apply -f -

# Copy CA certificate to current directory for easy access
cp ca-cert.pem "$HOME/${CA_NAME}.crt"

echo ""
echo -e "${GREEN}✅ CA certificate generated successfully!${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "1. Add the CA certificate to your system trust store:"
echo -e "   ${GREEN}   macOS:${NC}"
echo "   sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain $HOME/${CA_NAME}.crt"
echo ""
echo -e "   ${GREEN}   Linux (Debian/Ubuntu):${NC}"
echo "   sudo cp $HOME/${CA_NAME}.crt /usr/local/share/ca-certificates/"
echo "   sudo update-ca-certificates"
echo ""
echo -e "   ${GREEN}   Windows:${NC}"
echo "   Double-click $HOME/${CA_NAME}.crt and install to 'Trusted Root Certification Authorities'"
echo ""
echo "2. Export CA certificate from cluster anytime:"
echo "   kubectl get secret $CA_NAME -n $CA_NAMESPACE -o jsonpath='{.data.tls\\.crt}' | base64 -d > ${CA_NAME}.crt"
echo ""
echo "3. The CA certificate is also saved at: $HOME/${CA_NAME}.crt"
echo ""

