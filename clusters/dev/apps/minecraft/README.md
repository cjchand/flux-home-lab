# Minecraft Server

This directory contains the Flux configuration for deploying a crossplay Minecraft server using PaperMC with GeyserMC and Floodgate plugins.

## Features

- **Java Edition Server**: PaperMC server for optimal performance
- **Bedrock Edition Support**: GeyserMC plugin enables PS5, Windows 10/11, and mobile clients
- **Authentication**: Floodgate plugin handles Bedrock player authentication
- **Crossplay**: Both Java and Bedrock clients can play together
- **Persistent Storage**: World data persisted using NFS storage
- **LoadBalancer**: Exposes both TCP (25565) and UDP (19132) ports

## Components

- `namespace.yaml`: Creates the minecraft namespace
- `helm-repository.yaml`: Adds the itzg/minecraft-server-charts repository
- `helmrelease.yaml`: Deploys the Minecraft server with PaperMC
- `geyser-config.yaml`: Configuration for GeyserMC plugin
- `floodgate-config.yaml`: Configuration for Floodgate plugin
- `minecraft-traefik-ingress.yaml`: Traefik ingress for web access

## Access

- **Java Clients**: Connect to `minecraft.internal:25565` (via Traefik ingress)
- **Bedrock Clients**: Connect to `<LoadBalancer-IP>:19132` (direct LoadBalancer access)
- **RCON**: Available on `<LoadBalancer-IP>:25575` for server administration

**Note**: Bedrock Edition requires UDP support, which Traefik doesn't provide. Bedrock clients must connect directly to the LoadBalancer IP address on port 19132.

## Plugin Installation

The server automatically downloads and installs the required plugins using initContainers:

- **GeyserMC**: Automatically downloaded from the official repository
- **Floodgate**: Automatically downloaded from the official repository

The plugins are installed during pod startup and will be available immediately when the server starts. No manual intervention required!

## Configuration

The server is configured with:
- 2GB initial memory allocation (expandable to 4GB)
- Aikar's JVM flags for optimal performance
- RCON enabled for remote administration
- Both Java (25565) and Bedrock (19132) ports exposed
- Persistent world storage using NFS

## DNS Setup

For external access, add DNS records pointing to your LoadBalancer IP:
- `minecraft.internal` → LoadBalancer IP
- `play.inpvp.net` → LoadBalancer IP (for Bedrock clients)
