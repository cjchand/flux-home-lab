# SSL/TLS Strategy for Kubernetes Services

## Current State

- ✅ Traefik has Let's Encrypt ACME configured with TLS challenge
- ✅ PiHole running outside Kubernetes handling DNS
- ⚠️ Services use `.internal` domains (cannot get Let's Encrypt certs)
- ⚠️ Some services reference cert-manager, but cert-manager is not installed
- ❌ Most services don't have TLS enabled

## Options for SSL/TLS

### Option 1: Self-Signed Certificates (Quick Start)

**Best for:** Services that will only be accessed internally, immediate implementation

**Pros:**
- Works immediately with `.internal` domains
- No external dependencies or DNS configuration needed
- Simple to implement
- PiHole already resolves `.internal` domains

**Cons:**
- Browser warnings on first visit (users must accept the certificate)
- Not suitable for publicly accessible services

**Implementation:**
Traefik can automatically generate self-signed certificates when you enable TLS on ingress routes without specifying a certificate resolver.

### Option 2: Let's Encrypt with HTTP-01 Challenge + Real Domain (Recommended)

**Best for:** Internal-only services with trusted certificates

**Pros:**
- Free, trusted certificates (no browser warnings)
- Automatic renewal
- Works with PiHole's local DNS - you can use real domains even for internal-only services
- PiHole resolves the domain locally to your cluster IP
- Domain doesn't need to be publicly accessible for PiHole DNS resolution

**Cons:**
- Requires owning a domain (can be cheap, e.g., $10-15/year)
- Domain must be publicly resolvable for Let's Encrypt validation
- Port 80 must be temporarily accessible from internet for initial certificate validation
- After validation, you can firewall port 80 if desired (cert renewals use port 443)

**Implementation:**
1. Get a domain (e.g., `yourdomain.com`)
2. Configure PiHole to create local DNS entries (e.g., `homepage.yourdomain.com` → cluster IP)
3. Set up public DNS records for Let's Encrypt validation (A record pointing to your public IP)
4. Update Traefik to use HTTP-01 challenge
5. Update services to use real domains instead of `.internal`

### Option 3: Let's Encrypt with DNS-01 Challenge (Wildcard Domain)

**Best for:** Mix of internal and public services, most flexible

**Pros:**
- Single wildcard certificate covers all subdomains (`*.yourdomain.com`)
- Works with internal-only services via PiHole local DNS
- No need to expose port 80 publicly for validation
- Trusted certificates, no browser warnings
- Perfect for services that should never be publicly accessible

**Cons:**
- Requires DNS provider API access (Cloudflare, Route53, etc.)
- More complex initial setup
- Requires storing DNS provider credentials securely

**Implementation:**
Configure Traefik with DNS-01 challenge using your DNS provider's API credentials (Cloudflare is the most common).

## Recommended Approach for Your Setup

Given that you run PiHole for DNS and use `.internal` domains:

### Best Long-Term Solution: Real Domain + Let's Encrypt + PiHole Local DNS

This gives you the best of all worlds:
1. **Use a real domain** (e.g., `home.example.com`) for your services
2. **Configure PiHole** to resolve subdomains locally to your cluster (Local DNS Records)
3. **Use Let's Encrypt** with HTTP-01 or DNS-01 challenge for trusted certificates
4. **Keep services internal-only** - PiHole handles local resolution, no public exposure needed

**Example Setup:**
- Domain: `home.example.com`
- Services: `homepage.home.example.com`, `homeassistant.home.example.com`, etc.
- PiHole Local DNS: All `*.home.example.com` → Traefik LoadBalancer IP
- Public DNS: `*.home.example.com` A record for Let's Encrypt validation (can use a dummy IP)
- Result: Services resolve internally via PiHole, get trusted SSL certs via Let's Encrypt

### Immediate Solution: Self-Signed Certificates

If you want to enable TLS immediately without domain setup:
1. **Update Traefik** to support automatic self-signed certificates
2. **Update all ingress resources** to enable TLS without certificate resolver
3. **Remove cert-manager annotations** (cert-manager isn't installed)

You can always migrate to Let's Encrypt later by:
1. Getting a domain
2. Configuring PiHole local DNS
3. Updating Traefik and service configurations

## PiHole Configuration for Real Domains

If you choose to use real domains with Let's Encrypt:

### Setting Up Local DNS in PiHole

1. **Log into PiHole admin interface**
2. **Navigate to:** Local DNS Records (or Local DNS → DNS Records)
3. **Add A records** for each service:
   - Domain: `homepage.yourdomain.com`
   - IP: `<your-traefik-loadbalancer-ip>` (get from `kubectl get svc -n traefik traefik`)
4. **Repeat** for all services

Alternatively, use a wildcard record:
- Domain: `*.yourdomain.com`
- IP: `<your-traefik-loadbalancer-ip>`

### Public DNS for Let's Encrypt Validation

You need public DNS records for Let's Encrypt to validate ownership:

**For HTTP-01 Challenge:**
- `A record`: `*.yourdomain.com` → Your public IP (where port 80 is accessible)
- Let's Encrypt will access `http://homepage.yourdomain.com/.well-known/acme-challenge/...`

**For DNS-01 Challenge:**
- No public A records needed!
- Let's Encrypt validates via DNS TXT records created via API

## Implementation Examples

### Example 1: Self-Signed Certificate (Traefik IngressRoute)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: service-ingress
  namespace: service-namespace
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - service.internal
      # No secretName = Traefik generates self-signed cert automatically
  rules:
    - host: service.internal
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service
                port:
                  number: 8080
```

### Example 2: Let's Encrypt Certificate (HTTP-01)

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: service-ingress
  namespace: service-namespace
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
    traefik.ingress.kubernetes.io/router.tls.certresolver: letsencrypt
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - service.yourdomain.com
  rules:
    - host: service.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service
                port:
                  number: 8080
```

### Example 3: Let's Encrypt Certificate (DNS-01 with Cloudflare)

First, configure Traefik with Cloudflare credentials in `traefik/helmrelease.yaml`:

```yaml
certificatesResolvers:
  letsencrypt:
    acme:
      email: your-email@example.com
      storage: /data/acme.json
      dnsChallenge:
        provider: cloudflare
        delayBeforeCheck: 0
        resolvers:
          - "1.1.1.1:53"
          - "8.8.8.8:53"
      # Store Cloudflare API token as Kubernetes secret
      # kubectl create secret generic cloudflare-api-token \
      #   --from-literal=CF_DNS_API_TOKEN=your-token \
      #   --namespace=traefik
```

Then in your ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: service-ingress
  namespace: service-namespace
  annotations:
    traefik.ingress.kubernetes.io/router.entrypoints: websecure
    traefik.ingress.kubernetes.io/router.tls: "true"
    traefik.ingress.kubernetes.io/router.tls.certresolver: letsencrypt
spec:
  ingressClassName: traefik
  tls:
    - hosts:
        - service.yourdomain.com
  rules:
    - host: service.yourdomain.com
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: service
                port:
                  number: 8080
```

## Migration Steps

### Step 1: Clean Up Existing Configuration

Remove cert-manager annotations from ingress resources:
- `clusters/dev/apps/homepage/homepage-traefik-ingress.yaml`
- `clusters/dev/apps/unifi-controller/helmrelease.yaml`

### Step 2: Update Traefik Configuration

Choose your certificate strategy and update `clusters/dev/apps/traefik/helmrelease.yaml` accordingly.

### Step 3: Update Service Ingress Resources

Add TLS configuration to all service ingress resources with appropriate annotations.

## Recommendation Summary

**Given your PiHole setup, here's the recommended path:**

### Short-term (Enable TLS Now)
✅ **Use self-signed certificates** for all `.internal` services
- Quick to implement
- Provides encryption
- Works with your current PiHole `.internal` domain setup
- Users accept certificate warning once per browser

### Long-term (Best Experience)
⭐ **Use a real domain + Let's Encrypt + PiHole local DNS**
- Get a domain (e.g., Namecheap, Cloudflare: $10-15/year)
- Configure PiHole local DNS to resolve `*.yourdomain.com` to your cluster
- Use Let's Encrypt DNS-01 challenge (no public port exposure needed)
- Single wildcard certificate covers all services
- Zero browser warnings, trusted certificates

**Why this is ideal:**
- PiHole handles internal DNS resolution (services stay internal-only)
- Let's Encrypt provides trusted certificates automatically
- DNS-01 challenge doesn't require exposing services publicly
- All services can share one wildcard certificate

## Notes

- The current Traefik configuration uses TLS challenge which requires port 443 to be accessible from the internet
- For internal `.internal` domains, Let's Encrypt won't work (domains must be publicly resolvable for validation)
- Self-signed certificates provide encryption but require users to accept the certificate warning once per browser
- With PiHole, you can use real domains for internal-only services by configuring local DNS records

