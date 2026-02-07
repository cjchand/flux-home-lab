# Topology

## Hardware

The cluster runs on 3x **HP EliteDesk 800 G3** mini PCs with identical specs:

| Component | Specification |
|-----------|---------------|
| CPU | Intel Core i5-7500T @ 2.70GHz (4 cores) |
| RAM | 16GB DDR4 |
| Storage | 256GB NVMe SSD (Toshiba KXG50ZNV256G) |
| OS | Ubuntu 24.04 LTS |

### Nodes

| Hostname | Role |
|----------|------|
| microk8s-node-01 | Control plane + worker |
| microk8s-node-03 | Control plane + worker |
| microk8s-node-04 | Control plane + worker |

## Network

![Network](../assets/images/home-lab-physical.png)

Note: There are Calico VLANs managed by MicroK8s that aren't (yet) represented on this diagram. 