# Overview

I've always wanted to build out a home lab, both for the overall tinker factor but also to have a place to experiment with new solutions outside the friction of Enterprise processes.

Initially, I was thinking about something like a [TuringPi](https://turingpi.com/). Seeing the soaring prices of everything in the microcomputer landscape, my attention turned to a pile of old laptops collecting dust in my closet. Beyond being free, they had the additional benefit of being x86-based and easily upgradable.

With that, I installed Ubuntu on a couple of laptops and set out to build a 2-node [microk8s](https://microk8s.io/) cluster. Having some initial success, I went about making things a bit more robust. I migrated off of WiFi onto a dedicated switch (which was a [bit of an adventure](https://github.com/canonical/microk8s/issues/1955#issuecomment-1214434568)) and bought a used NAS setup to enable proper PersistentVolumes.

Since then, I've upgraded to 3x HP EliteDesk 800 G3 mini PCs running a proper 3-node cluster. See the [Topology docs](./docs/Topology/README.md) for current hardware specs.

At this point, I knew I wanted to bring [Flux](https://fluxcd.io/) into the mix, as I am a huge proponent of automation and repeatability. After all, if I go much further down the rabbit hole, I am likely to upgrade hardware, etc.

That brings us to this repo: This is how I manage not only underlying cluster-wide services ([NFS-backed PVs](https://github.com/kubernetes-sigs/nfs-subdir-external-provisioner), [SealedSecrets](https://fluxcd.io/docs/guides/sealed-secrets/), etc), but also any apps/services I want to run on top.

# Documentation

- **[Flux](./docs/Flux/README.md)** - GitOps setup and cluster management
- **[Topology](./docs/Topology/README.md)** - Network and hardware architecture
- **[Applications](./docs/Applications/README.md)** - Deployed services and namespace diagrams

# The Future

Like any nerdy endeavor, there's always more left to do, so I catalog those [future improvements here](./TODO.md).