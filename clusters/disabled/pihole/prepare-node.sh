#!/bin/bash

# Check if systemd-resolved is running
if systemctl is-active --quiet systemd-resolved; then
    echo "Stopping systemd-resolved..."
    sudo systemctl stop systemd-resolved
    sudo systemctl disable systemd-resolved
fi

# Check if dnsmasq is running
if systemctl is-active --quiet dnsmasq; then
    echo "Stopping dnsmasq..."
    sudo systemctl stop dnsmasq
    sudo systemctl disable dnsmasq
fi

# Check if port 53 is in use
if lsof -i :53; then
    echo "Port 53 is still in use. Please check what's using it:"
    sudo lsof -i :53
    exit 1
fi

echo "Node is ready for Pi-hole DNS" 