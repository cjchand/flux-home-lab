# cert-manager Setup with Internal CA

This guide explains the complete setup for using cert-manager with an internal CA to automatically manage SSL certificates for all services.

## Overview

cert-manager has been configured to:
- Automatically generate certificates for all services
- Sign certificates with your internal CA
- Handle certificate renewal automatically
- Store certificates in Kubernetes secrets

## Architecture

```
Internal CA (home-lab-internal-ca Secret)
    ↓
ClusterIssuer (internal-ca)
    ↓
cert-manager watches ingress resources
    ↓
Generates certificates signed by CA
    ↓
Stores in service namespaces
    ↓
Traefik uses certificates for TLS
```

## Setup Steps

### Step 1: Generate Internal CA Certificate

Before cert-manager can work, you need to generate the CA certificate:

```bash
./scripts/generate-internal-ca.sh
```

This creates:
- CA certificate and private key stored as Kubernetes Secret `home-lab-internal-ca` in `traefik` namespace
- Local copy saved to `~/home-lab-internal-ca.crt`

### Step 2: Wait for cert-manager Installation

After committing and pushing changes, Flux will install cert-manager. Monitor the installation:

```bash
# Check cert-manager namespace
kubectl get pods -n cert-manager

# Check HelmRelease status
kubectl get helmrelease cert-manager -n flux-system

# Wait for cert-manager pods to be ready
kubectl wait --for=condition=ready pod \
  -l app.kubernetes.io/name=cert-manager \
  -n cert-manager \
  --timeout=300s
```

Expected output:
```
NAME           READY   STATUS    RESTARTS   AGE
cert-manager-xxx   1/1     Running   0         2m
cert-manager-cainjector-xxx   1/1     Running   0         2m
cert-manager-webhook-xxx   1/1     Running   0         2m
```

**Important**: The ClusterIssuer is not included in the initial kustomization because it requires cert-manager CRDs to exist first. You'll apply it in the next step.

### Step 3: Apply ClusterIssuer

Once cert-manager is installed and ready, apply the ClusterIssuer:

**Option A: Using the helper script (Recommended)**
```bash
./scripts/apply-cluster-issuer.sh
```

This script will:
- Wait for cert-manager CRDs to be available
- Wait for cert-manager pods to be ready
- Verify the CA secret exists
- Apply the ClusterIssuer

**Option B: Manual application**
```bash
kubectl apply -f clusters/dev/cluster-services/internal-ca-issuer.yaml
```

### Step 4: Verify ClusterIssuer

Once cert-manager is installed, verify the ClusterIssuer is ready:

```bash
kubectl get clusterissuer internal-ca -o yaml
```

Look for:
```yaml
status:
  conditions:
  - lastTransitionTime: "2024-..."
    status: "True"
    type: Ready
```

### Step 5: Add CA to Your Trust Store

Export and trust the CA certificate on your devices:

#### macOS
```bash
# Export CA certificate
kubectl get secret home-lab-internal-ca -n traefik \
  -o jsonpath='{.data.tls\.crt}' | base64 -d > ~/home-lab-internal-ca.crt

# Add to system trust store
sudo security add-trusted-cert -d -r trustRoot \
  -k /Library/Keychains/System.keychain \
  ~/home-lab-internal-ca.crt
```

#### Linux (Debian/Ubuntu)
```bash
# Export CA certificate
kubectl get secret home-lab-internal-ca -n traefik \
  -o jsonpath='{.data.tls\.crt}' | base64 -d | \
  sudo tee /usr/local/share/ca-certificates/home-lab-internal-ca.crt

# Update trust store
sudo update-ca-certificates
```

#### Windows
1. Export the certificate:
   ```powershell
   kubectl get secret home-lab-internal-ca -n traefik `
     -o jsonpath='{.data.tls\.crt}' | `
     [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String($_)) `
     | Out-File -Encoding ASCII home-lab-internal-ca.crt
   ```
2. Double-click `home-lab-internal-ca.crt`
3. Click "Install Certificate" → "Local Machine"
4. Select "Place all certificates in the following store"
5. Browse to "Trusted Root Certification Authorities" → OK

#### Firefox
1. Settings → Privacy & Security → Certificates → View Certificates
2. Click "Authorities" tab → "Import"
3. Select the CA certificate file
4. Check "Trust this CA to identify websites" → OK

### Step 6: Monitor Certificate Generation

After services are updated, cert-manager will automatically create certificates:

```bash
# Check Certificate resources
kubectl get certificates -A

# Check Certificate status
kubectl describe certificate <certificate-name> -n <namespace>

# Check if secrets are created
kubectl get secrets -n <namespace> | grep tls
```

You should see certificates created for each service:
- `homepage-tls` in `homepage` namespace
- `homeassistant-tls` in `homeassistant` namespace
- `unifi-tls` in `unifi` namespace
- etc.

## How It Works

### Certificate Request Flow

1. **Ingress Created**: You create/update an ingress with:
   - `cert-manager.io/cluster-issuer: internal-ca` annotation
   - `tls.secretName` specified

2. **cert-manager Detects**: cert-manager's ingress-shim detects the annotation

3. **Certificate Resource Created**: cert-manager creates a `Certificate` resource

4. **Certificate Signed**: cert-manager uses the `internal-ca` ClusterIssuer to sign the certificate

5. **Secret Created**: The signed certificate is stored in a Kubernetes Secret

6. **Traefik Uses It**: Traefik automatically uses the secret for TLS termination

### Automatic Renewal

cert-manager automatically renews certificates before they expire:
- Default renewal is 30 days before expiration
- Renewal is handled automatically, no manual intervention needed
- Certificates are valid for 365 days (1 year)

## Troubleshooting

### cert-manager Not Installing

```bash
# Check HelmRepository
kubectl get helmrepository cert-manager -n flux-system

# Check HelmRelease status
kubectl describe helmrelease cert-manager -n flux-system

# Check Flux logs
kubectl logs -n flux-system -l app=helm-controller
```

### ClusterIssuer Not Ready

```bash
# Check ClusterIssuer status
kubectl describe clusterissuer internal-ca

# Verify CA secret exists
kubectl get secret home-lab-internal-ca -n traefik

# Check cert-manager logs
kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager
```

### Certificates Not Being Created

```bash
# Check for Certificate resources
kubectl get certificates -A

# Check ingress annotations
kubectl get ingress -A -o yaml | grep cert-manager

# Check cert-manager controller logs
kubectl logs -n cert-manager -l app.kubernetes.io/name=cert-manager --tail=100

# Check ingress-shim logs
kubectl logs -n cert-manager -l app.kubernetes.io/name=cainjector --tail=100
```

### Certificate Secret Not Created

```bash
# Describe the Certificate resource
kubectl describe certificate <name> -n <namespace>

# Check CertificateRequest
kubectl get certificaterequest -n <namespace>

# Check cert-manager events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep cert-manager
```

### Certificate Still Self-Signed

If you're still seeing browser warnings:
1. Verify CA is in trust store
2. Clear browser cache/cookies
3. Verify certificate is signed by CA:
   ```bash
   kubectl get secret <cert-name> -n <namespace> -o jsonpath='{.data.tls\.crt}' | \
     base64 -d | openssl x509 -text -noout | grep "Issuer"
   ```
   Should show: `Issuer: CN = home-lab-internal-ca`

## Configuration Files

### cert-manager Resources

- **HelmRepository**: `clusters/dev/cluster-services/source-helmrepo-cert-manager.yaml`
- **Namespace**: `clusters/dev/cluster-services/cert-manager-namespace.yaml`
- **HelmRelease**: `clusters/dev/cluster-services/cert-manager-helmrelease.yaml`
- **ClusterIssuer**: `clusters/dev/cluster-services/internal-ca-issuer.yaml`

### Service Configuration

All ingress resources have been updated with:
- Annotation: `cert-manager.io/cluster-issuer: internal-ca`
- TLS secret name specified

## Next Steps

1. ✅ Generate CA certificate: `./scripts/generate-internal-ca.sh`
2. ✅ Commit and push changes (Flux will install cert-manager)
3. ✅ Wait for cert-manager installation (~2-5 minutes)
4. ✅ Apply ClusterIssuer: `./scripts/apply-cluster-issuer.sh`
5. ✅ Verify ClusterIssuer is ready
6. ✅ Add CA to your trust store (see Step 5 above)
7. ✅ Monitor certificate generation
8. ✅ Test services - they should work without browser warnings!

## Troubleshooting

### ClusterIssuer Error: "no matches for kind ClusterIssuer"

This error occurs if you try to apply the ClusterIssuer before cert-manager is installed. The ClusterIssuer is intentionally excluded from the initial kustomization for this reason.

**Solution**: Wait for cert-manager to install first, then apply the ClusterIssuer:
```bash
# Wait for cert-manager CRDs
kubectl wait --for=condition=established crd/clusterissuers.cert-manager.io --timeout=300s

# Then apply ClusterIssuer
./scripts/apply-cluster-issuer.sh
```

## Security Notes

- The CA private key is stored in a Kubernetes Secret in the `traefik` namespace
- Use RBAC to limit access to the CA secret
- Consider rotating the CA certificate every 1-2 years
- Keep the CA certificate backed up securely

