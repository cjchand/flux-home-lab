# Ansible Configuration for Home Lab

Ansible automation for managing the 3 HP EliteDesk microk8s nodes. Handles OS-level configuration while Flux CD manages Kubernetes workloads.

## Prerequisites

Install Ansible on your Mac:

```bash
brew install ansible
```

Install required Galaxy roles and collections:

```bash
cd ansible
ansible-galaxy collection install community.general
ansible-galaxy install -r requirements.yml
```

## Inventory

The inventory defines three nodes:

| Hostname | IP | Group |
|----------|-----|-------|
| microk8s-node-01 | 192.168.1.101 | microk8s_primary |
| microk8s-node-02 | 192.168.1.102 | microk8s_workers |
| microk8s-node-03 | 192.168.1.103 | microk8s_workers |

Update `inventory/hosts.yml` if your IPs differ.

## Usage

### Verify Connectivity

```bash
ansible all -m ping
```

### Full Site Setup (Idempotent)

Configures OS, microk8s, and Tailscale on all nodes:

```bash
ansible-playbook playbooks/site.yml
```

Dry run first:

```bash
ansible-playbook playbooks/site.yml --check --diff
```

### Rolling OS Upgrade

Updates packages one node at a time, rebooting if needed:

```bash
ansible-playbook playbooks/upgrade-os.yml
```

### Rolling microk8s Upgrade

First, update the channel in `group_vars/microk8s.yml`:

```yaml
microk8s_channel: "1.32/stable"
```

Then run the upgrade:

```bash
ansible-playbook playbooks/upgrade-microk8s.yml
```

### Bootstrap New Node

Set up a fresh node (does not join to cluster):

```bash
ansible-playbook playbooks/bootstrap-node.yml --limit microk8s-node-04
```

### Join Node to Cluster

After bootstrap, join the node:

```bash
ansible-playbook playbooks/join-cluster.yml -e 'new_node=microk8s-node-04'
```

## Roles

### common

- apt update/upgrade with autoremove
- Installs base packages (curl, htop, vim, etc.)
- Sets timezone
- Reboots if required

### microk8s

- Installs microk8s via snap with channel pinning
- Configures user access and kubeconfig
- Enables addons: dns, ha-cluster, helm3, rbac, hostpath-storage
- Disables Flux-managed addons: ingress, metallb, dashboard

### tailscale

- Installs Tailscale via Galaxy role
- Authenticates using auth key from `TAILSCALE_AUTH_KEY` environment variable
- Configures subnet routing on designated nodes (microk8s-node-01 advertises 192.168.86.0/24)
- All nodes accept routes from other tailnet members

**Subnet routing** enables remote access to `*.internal` domains via PiHole when away from home.

## Configuration

### inventory/group_vars/all.yml

Common settings for all hosts:

- `base_packages`: List of packages to install
- `timezone`: System timezone

### inventory/group_vars/microk8s.yml

microk8s-specific settings:

- `microk8s_channel`: Snap channel (e.g., "1.31/stable")
- `microk8s_addons_enabled`: Addons managed by Ansible
- `microk8s_addons_disabled`: Addons managed by Flux (disabled here)
- `microk8s_user`: User to configure for microk8s access

## Design Notes

1. **Cluster join is explicit** - Not part of `site.yml`. Join tokens expire, and joining should be intentional.

2. **Primary node** - `microk8s-node-01` generates join tokens. Any HA node could, but consistency helps.

3. **No addon duplication** - Ansible disables microk8s addons that Flux manages (metallb, ingress, dashboard).

4. **Rolling updates** - OS and microk8s upgrades use `serial: 1` with drain/cordon to maintain availability.

## Tailscale Setup

The Tailscale role configures subnet routing so you can access `*.internal` domains when away from home.

### Prerequisites

1. Tailscale account with admin access
2. Generate a reusable auth key from Tailscale Admin Console:
   - Go to Settings → Keys → Generate auth key
   - Enable "Reusable" for multiple nodes
   - Optionally set expiration

### Running the Playbook

```bash
TAILSCALE_AUTH_KEY=tskey-auth-xxx ansible-playbook playbooks/site.yml
```

Or for just Tailscale:

```bash
TAILSCALE_AUTH_KEY=tskey-auth-xxx ansible-playbook playbooks/site.yml --tags tailscale
```

### Post-Playbook Manual Steps (Tailscale Admin Console)

1. **Approve subnet route**: Machines → microk8s-node-01 → Edit route settings → Approve 192.168.86.0/24
2. **Configure Split DNS** for `*.internal` domains:
   - Go to DNS → Add nameserver
   - Nameserver: `192.168.86.53` (PiHole)
   - Restrict to domain: `internal`

### Verification

From your Mac (connected to Tailscale, not on home WiFi):

```bash
# Check DNS resolution
dig teslamate-grafana.internal

# Test HTTPS access
curl -k https://teslamate-grafana.internal
```

## Verification

After running playbooks, verify on a node:

```bash
ssh microk8s-node-01
microk8s status
tailscale status
microk8s kubectl get nodes
```
