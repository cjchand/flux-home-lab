# Flux

All of the Flux-related assets are in the [dev cluster directory](../../clusters/dev/). Currently, the directory structure is:

```
├── clusters
│   ├── dev
│   │   ├── apps
│   │   │   ├── homeassistant/
│   │   │   ├── homebridge/
│   │   │   ├── homepage/
│   │   │   ├── loki-stack/
│   │   │   ├── metallb/
│   │   │   ├── tandoor/
│   │   │   ├── teslamate/
│   │   │   ├── traefik/
│   │   │   ├── unifi-controller/
│   │   │   └── uptime-kuma/
│   │   ├── cluster-services
│   │   │   ├── nfs-external-provisioner-helmrelease.yaml
│   │   │   ├── sealed-secrets-helmrelease.yaml
│   │   │   ├── source-helmrepo-nfs-external-provisioner.yaml
│   │   │   └── source-helmrepo-sealed-secrets.yaml
│   │   └── flux-system
│   │       ├── gotk-components.yaml
│   │       ├── gotk-sync.yaml
│   │       └── kustomization.yaml
│   └── disabled
│       ├── mosquitto-helmrelease.yaml
│       ├── pihole/
│       ├── source-helmrepo-velero.yaml
│       └── velero-helmrelease.yaml
```

Note: The `disabled` directory is a simple way to remove items from Flux's purview without deleting the file itself. This is because `gotk-sync.yaml` tells the Flux components deployed in my cluster to only look at files under `./clusters/dev`:

```spec:
  interval: 10m0s
  path: ./clusters/dev
  prune: true
  sourceRef:
    kind: GitRepository
    name: flux-system
```

## SealedSecrets

A key feature used is [SealedSecrets](https://fluxcd.io/docs/guides/sealed-secrets/), which allows for encrypted secrets to be safely committed to a public repo. Absent this, secrets would have to be managed manually outside of Flux.

Check out the [SealedSecrets doc](../sealed-secrets.md) for details on how it all works. 