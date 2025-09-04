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

- **Java Clients**: Connect to `minecraft.internal:25565`
- **Bedrock Clients**: Connect to `minecraft.internal:19132`
- **RCON**: Available on port 25575 for server administration

## Plugin Installation

The server is configured to support plugins. To install GeyserMC and Floodgate:

1. Download the latest JAR files:
   - GeyserMC: https://download.geysermc.org/v2/projects/geyser/versions/latest/builds/latest/downloads/spigot
   - Floodgate: https://download.geysermc.org/v2/projects/floodgate/versions/latest/builds/latest/downloads/spigot

2. Copy the plugins to the server:
   ```bash
   kubectl cp geyser-spigot.jar minecraft/minecraft-server-0:/data/plugins/
   kubectl cp floodgate-spigot.jar minecraft/minecraft-server-0:/data/plugins/
   ```

3. Restart the server to load the plugins

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
