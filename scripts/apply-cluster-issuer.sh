#!/bin/bash
set -e

# Script to apply the ClusterIssuer after cert-manager is installed
# This waits for cert-manager CRDs to be available before applying

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Applying Internal CA ClusterIssuer ===${NC}"
echo ""

CLUSTER_ISSUER_FILE="clusters/dev/cluster-services/internal-ca-issuer.yaml"

# Check if cert-manager CRDs are available
echo -e "${YELLOW}Waiting for cert-manager CRDs to be available...${NC}"
MAX_ATTEMPTS=30
ATTEMPT=0

while [ $ATTEMPT -lt $MAX_ATTEMPTS ]; do
    if kubectl get crd clusterissuers.cert-manager.io &>/dev/null; then
        echo -e "${GREEN}✓ cert-manager CRDs are available${NC}"
        break
    fi
    
    ATTEMPT=$((ATTEMPT + 1))
    echo "  Attempt $ATTEMPT/$MAX_ATTEMPTS: Waiting for cert-manager CRDs..."
    sleep 5
done

if [ $ATTEMPT -eq $MAX_ATTEMPTS ]; then
    echo -e "${RED}✗ Timeout waiting for cert-manager CRDs. Is cert-manager installed?${NC}"
    echo "  Check cert-manager installation:"
    echo "    kubectl get pods -n cert-manager"
    exit 1
fi

# Wait a bit more for cert-manager to be fully ready
echo -e "${YELLOW}Waiting for cert-manager to be ready...${NC}"
kubectl wait --for=condition=ready pod \
    -l app.kubernetes.io/name=cert-manager \
    -n cert-manager \
    --timeout=300s || {
    echo -e "${RED}✗ cert-manager pods are not ready${NC}"
    exit 1
}

echo -e "${GREEN}✓ cert-manager is ready${NC}"
echo ""

# Check if CA secret exists
if ! kubectl get secret home-lab-internal-ca -n traefik &>/dev/null; then
    echo -e "${RED}✗ CA secret 'home-lab-internal-ca' not found in traefik namespace${NC}"
    echo "  Please run ./scripts/generate-internal-ca.sh first"
    exit 1
fi

echo -e "${GREEN}✓ CA secret exists${NC}"
echo ""

# Apply ClusterIssuer
echo -e "${YELLOW}Applying ClusterIssuer...${NC}"
kubectl apply -f "$CLUSTER_ISSUER_FILE"

# Wait for ClusterIssuer to be ready
echo -e "${YELLOW}Waiting for ClusterIssuer to be ready...${NC}"
sleep 5

# Check ClusterIssuer status
if kubectl get clusterissuer internal-ca &>/dev/null; then
    echo ""
    echo -e "${GREEN}✓ ClusterIssuer applied successfully!${NC}"
    echo ""
    echo "Checking status:"
    kubectl get clusterissuer internal-ca -o yaml | grep -A 5 "status:" || echo "  (Status will appear after cert-manager processes it)"
    echo ""
    echo -e "${GREEN}You can now check certificate generation for your services:${NC}"
    echo "  kubectl get certificates -A"
else
    echo -e "${RED}✗ Failed to apply ClusterIssuer${NC}"
    exit 1
fi

