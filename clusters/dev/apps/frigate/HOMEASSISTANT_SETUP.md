# Home Assistant Setup for Frigate

These steps must be done manually in the HA UI after Frigate is running. They cannot be automated via Kubernetes manifests.

---

## 1. MQTT Integration

Connect HA to the Mosquitto broker running in the `frigate` namespace.

1. **Settings → Devices & Services → Add Integration → MQTT**
2. Broker: `mosquitto.mqtt.svc.cluster.local`
3. Port: `1883`
4. Username / Password: leave blank (anonymous access is enabled)
5. Click **Submit**

Frigate will automatically publish camera events and object detection results to MQTT topics like `frigate/camera_kitchen/person`.

---

## 2. Frigate Integration (via HACS)

Install the community Frigate integration so HA can consume Frigate's event stream.

### Install via HACS

1. **HACS → Integrations → Explore & Download Repositories**
2. Search for **Frigate** → select `blakeblackshear/frigate-hass-integration`
3. Download → restart HA when prompted

### Configure the Integration

1. **Settings → Devices & Services → Add Integration → Frigate**
2. URL: `http://frigate.frigate.svc.cluster.local:5000`
3. Click **Submit**

HA will create binary sensors, cameras, and event entities for each Frigate camera automatically.

---

## 3. Frigate Card for Lovelace (Optional but Recommended)

Adds a polished camera dashboard with live streams, snapshots, and event replay.

1. **HACS → Frontend → Explore & Download Repositories**
2. Search for **Frigate Card** → select `dermotduffy/frigate-hass-card`
3. Download → clear browser cache

Add to a dashboard:
- Edit dashboard → Add Card → search **Frigate**
- Configure with your camera entity (e.g., `camera.camera_kitchen`)

---

## 4. Mobile Push Notifications

Use the community Frigate Mobile Notifications Blueprint to send push alerts via the HA Companion App.

1. Go to: [Frigate Mobile App Notifications 2.0 Blueprint](https://community.home-assistant.io/t/frigate-mobile-app-notifications-2-0/559732)
2. Click **Import Blueprint** → confirm in HA
3. **Settings → Automations & Scenes → Blueprints → Frigate Mobile Notifications**
4. Create an automation from the blueprint
5. Set `notify_device` to your mobile device

**Finding your notify service name:**
Settings → Devices & Services → Companion App → your device → the service is `notify.mobile_app_<device_name>`

---

## 5. Presence-Based Notification Suppression (Recommended)

Prevent daytime false positives while keeping overnight/away detection active.

Add a **Condition** to the notification automation:

```yaml
condition:
  - condition: or
    conditions:
      # Fire when everyone is away
      - condition: state
        entity_id: group.household
        state: not_home
      # OR fire during quiet hours (10pm–7am)
      - condition: time
        after: "22:00:00"
        before: "07:00:00"
```

Adjust `group.household` to match your people/group entity. This prevents alerts while you're home during the day but keeps overnight detection active.

---

## 6. Enable Media Source

Required for the HA Media Browser to show Frigate clips and snapshots.

In `configuration.yaml` (or via the UI if using `default_config:`):

```yaml
media_source:
```

If `default_config:` is already in your config, `media_source` is included automatically. If you've removed it, add the line above and restart HA.
