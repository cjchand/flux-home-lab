# Internal CA Setup for Trusted Self-Signed Certificates

## The Problem

Traefik's **automatic self-signed certificate generation** does not use a Certificate Authority (CA). Each certificate is individually self-signed, which means:
- ❌ No single CA certificate to add to your trust store
- ❌ You'd need to trust each service certificate individually
- ❌ Not practical for managing multiple services

## The Solution

To have a single CA certificate you can trust, you need to:

1. **Create an internal CA** (Certificate Authority)
2. **Generate certificates signed by that CA** for each service
3. **Add the CA certificate to your system's trust store** (one-time setup)
4. **All services will then be trusted automatically**

## Option 1: Using cert-manager (Recommended)

cert-manager can automatically manage certificates signed by your internal CA.

### Benefits
- ✅ Automatic certificate generation for all services
- ✅ Automatic renewal
- ✅ Single CA to trust
- ✅ Works seamlessly with Traefik

### Setup Steps

1. **Install cert-manager** (see setup files below)
2. **Generate and store CA certificate** using the provided script
3. **Create a ClusterIssuer** that uses your CA
4. **Update ingress annotations** to use `cert-manager.io/cluster-issuer: internal-ca`
5. **Export and trust the CA certificate** (one-time per device)

### Files to Create

See the cert-manager setup section below for complete implementation.

## Option 2: Manual Certificate Generation (Simpler, More Work)

If you prefer not to install cert-manager, you can manually generate certificates.

### Benefits
- ✅ No additional software to install
- ✅ Full control over certificate generation
- ✅ Single CA to trust

### Drawbacks
- ❌ Manual work for each service
- ❌ Manual renewal required
- ❌ More maintenance

## Quick Start: Generate Your Internal CA

Use the provided script to generate a CA certificate:

```bash
./scripts/generate-internal-ca.sh
```

This will:
1. Generate a CA certificate and private key (valid for 10 years)
2. Store it as a Kubernetes Secret in the `traefik` namespace
3. Save a copy to `~/home-lab-internal-ca.crt` for easy access

## Adding the CA to Your Trust Store

After generating the CA, add it to your system's trust store:

### macOS
```bash
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/home-lab-internal-ca.crt
```

### Linux (Debian/Ubuntu)
```bash
sudo cp ~/home-lab-internal-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

### Windows
1. Double-click `~/home-lab-internal-ca.crt`
2. Click "Install Certificate" → "Local Machine"
3. Select "Place all certificates in the following store"
4. Browse to "Trusted Root Certification Authorities"
5. Complete the wizard

### Firefox (all platforms)
1. Settings → Privacy & Security → Certificates → View Certificates
2. Click "Authorities" tab → "Import"
3. Select the CA certificate
4. Check "Trust this CA to identify websites" → OK

## Exporting the CA Certificate Anytime

You can export your CA certificate from the cluster at any time:

```bash
kubectl get secret home-lab-internal-ca -n traefik \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > home-lab-internal-ca.crt
```

## Using the CA with cert-manager

If you install cert-manager, create a ClusterIssuer:

```yaml
# clusters/dev/cluster-services/internal-ca-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: internal-ca
spec:
  ca:
    secretName: home-lab-internal-ca
```

Then update your ingress resources:

```yaml
metadata:
  annotations:
    cert-manager.io/cluster-issuer: internal-ca
spec:
  tls:
    - hosts:
        - service.internal
      secretName: service-tls  # cert-manager creates this
```

## Using the CA Manually

For each service, generate a certificate signed by your CA:

```bash
# 1. Generate service private key
openssl genrsa -out service-key.pem 2048

# 2. Create Certificate Signing Request
openssl req -new -key service-key.pem -out service.csr \
  -subj "/CN=service.internal/O=Home Lab/C=US"

# 3. Create SAN config file
cat > service.conf <<EOF
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
[req_distinguished_name]
[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names
[alt_names]
DNS.1 = service.internal
EOF

# 4. Sign certificate with CA (get CA from secret first)
kubectl get secret home-lab-internal-ca -n traefik \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ca-cert.pem
kubectl get secret home-lab-internal-ca -n traefik \
  -o jsonpath='{.data.tls\.key}' | base64 -d > ca-key.pem

# 5. Sign the certificate
openssl x509 -req -in service.csr \
  -CA ca-cert.pem -CAkey ca-key.pem -CAcreateserial \
  -out service-cert.pem -days 365 \
  -extensions v3_req -extfile service.conf

# 6. Create Kubernetes secret
kubectl create secret tls service-tls \
  --cert=service-cert.pem \
  --key=service-key.pem \
  -n service-namespace

# 7. Clean up
rm service-*.pem service.csr service.conf ca-*.pem
```

Then reference the secret in your ingress:

```yaml
spec:
  tls:
    - hosts:
        - service.internal
      secretName: service-tls  # The manually created secret
```

## Current State vs. Recommended State

### Current State (What We Just Configured)
- ✅ Traefik auto-generates self-signed certificates
- ✅ Each certificate is individually self-signed
- ❌ No single CA to trust
- ❌ Browser warnings for each service

### Recommended State (With Internal CA)
- ✅ Internal CA certificate stored in Kubernetes
- ✅ All service certificates signed by the CA
- ✅ Single CA certificate in your trust store
- ✅ No browser warnings for any service

## Next Steps

1. **Run the CA generation script**: `./scripts/generate-internal-ca.sh`
2. **Choose your approach**:
   - **Option A**: Install cert-manager for automatic certificate management
   - **Option B**: Manually generate certificates for each service (simpler setup, more maintenance)
3. **Add the CA to your trust store** using the instructions above
4. **Update your services** to use certificates signed by your CA

## Security Considerations

⚠️ **Keep CA private key secure** - The CA private key in the Kubernetes secret should be protected
⚠️ **Limit access** - Use RBAC to limit who can access the CA secret
⚠️ **Regular rotation** - Consider rotating the CA every 1-2 years
⚠️ **Internal use only** - This CA should only be used for internal services
