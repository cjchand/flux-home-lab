# Eero Exporter

## Overview

The Eero Exporter is a Prometheus exporter that provides metrics from your Eero WiFi network. It exposes various metrics about your Eero network including:

- Upload/download speeds
- Network health status
- Connected client count
- Network performance metrics

## Architecture

The eero-exporter is deployed as a containerized application using the `acaranta/eero-exporter` Docker image. It runs as a single pod in the `eero-exporter` namespace.

### Components

- **Deployment**: Runs the eero-exporter container
- **Service**: Exposes metrics on port 9118
- **Ingress**: Provides web access via Traefik
- **Namespace**: Isolates the application

## Configuration

### Initial Setup

Before the eero-exporter can function properly, you need to configure it with your Eero account credentials. The exporter requires authentication to access your Eero network data.

1. **Access the exporter**: Visit `https://eero-exporter.internal` in your browser
2. **Follow the setup process**: The exporter will guide you through the authentication process
3. **Enter credentials**: Provide your Eero login (email or phone number)
4. **Verify**: Check your email/SMS for a one-time password and enter it

### Metrics

The exporter provides the following Prometheus metrics:

- `eero_speed_upload_mbps`: Current upload speed in Mbps
- `eero_speed_download_mbps`: Current download speed in Mbps  
- `eero_health_status`: Network health status (1 = healthy, 0 = unhealthy)
- `eero_clients_count`: Number of connected clients

## Access

- **Web Interface**: `https://eero-exporter.internal`
- **Metrics Endpoint**: `https://eero-exporter.internal/metrics`
- **Prometheus Scraping**: Automatically configured via service annotations

## Monitoring

The eero-exporter is automatically discovered by the existing Prometheus Operator setup. It uses multiple discovery mechanisms:

### Service Annotations
The service includes the necessary annotations for Prometheus scraping:
```yaml
prometheus.io/scrape: "true"
prometheus.io/port: "9118"
prometheus.io/path: "/metrics"
```

### ServiceMonitor
A ServiceMonitor resource is deployed to the monitoring namespace with the `release: prometheus` label, ensuring it's picked up by the Prometheus Operator:

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: eero-exporter
  namespace: monitoring
  labels:
    release: prometheus
spec:
  selector:
    matchLabels:
      app: eero-exporter
  endpoints:
  - port: metrics
    path: /metrics
    interval: 30s
```

## Troubleshooting

### Common Issues

1. **Authentication Required**: The exporter needs valid Eero credentials to function
2. **Network Access**: Ensure the pod can reach the Eero API endpoints
3. **Metrics Not Available**: Check that the authentication process was completed successfully

### Logs

View logs with:
```bash
kubectl logs -n eero-exporter deployment/eero-exporter
```

### Health Checks

The deployment includes liveness and readiness probes to ensure the exporter is functioning properly.

## Resources

- [GitHub Repository](https://github.com/brmurphy/eero-exporter)
- [Docker Image](https://hub.docker.com/r/acaranta/eero-exporter) 