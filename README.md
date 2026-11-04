# Cybersecurity Tuner – Home Assistant integration

[![Validate](https://github.com/mar-eid/ha-unifi-cs-tuner-integration/actions/workflows/validate.yml/badge.svg)](https://github.com/mar-eid/ha-unifi-cs-tuner-integration/actions/workflows/validate.yml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/)

A small Home Assistant integration for the
[Cybersecurity Tuner](https://github.com/mar-eid/ha-unifi-cs-tuner) app (add-on),
which monitors UniFi firewall syslog, devices, rules and diagnostics.

The integration only does two things:

1. **Status sensors** for the app (health, learning, temporary exceptions,
   unknown devices, blocked events, packet-capture status).
2. **Events** on the Home Assistant event bus (`cybersecurity_tuner_<type>`)
   that you can feed into your alarm system or notifications.

> **Firewall rule switches are not part of this integration.** Enabling and
> disabling ordinary UniFi firewall rules stays in the official
> [UniFi Network integration](https://www.home-assistant.io/integrations/unifi/).
> This integration deliberately does not duplicate them.

Requires Home Assistant 2025.2 or newer.

## Installation

### HACS (custom repository)

1. HACS → ⋮ → **Custom repositories**.
2. Add `https://github.com/mar-eid/ha-unifi-cs-tuner-integration` with
   category **Integration**.
3. Install **Cybersecurity Tuner** and restart Home Assistant.

### Manual

Copy `custom_components/cybersecurity_tuner/` into the
`custom_components/` folder of your Home Assistant configuration directory and
restart Home Assistant.

## Setup

### Automatic (Supervisor discovery)

When the Cybersecurity Tuner app runs on Home Assistant OS / Supervised, it
announces itself to Home Assistant. Go to **Settings → Devices & services**,
where it shows up as **Discovered**, and click **Configure** → **Submit**. Host,
port and token come from the app; there is nothing to type.

If the app's hostname or token changes later, the discovery updates the
existing entry automatically.

### Manual

**Settings → Devices & services → Add integration → Cybersecurity Tuner**, then
enter:

| Field | Value |
|-------|-------|
| Host | App hostname or IP, e.g. `local-cybersecurity-tuner` (HA OS) or the Docker/Proxmox host's IP |
| Port | `8099` (default) |
| API token | The app option `ha_api_token`. If that option is empty, the app generates a token at first start and stores it in `/data/ha_api_token` |

The integration checks the connection by calling `/api/v1/ha/status`. Each app
installation can be added only once (`instance_id` is the unique ID).

If the token is rejected (HTTP 401), Home Assistant starts a **re-authenticate**
flow that asks for the new token.

### Options

**Configure** on the integration entry:

| Option | Default | Description |
|--------|---------|-------------|
| Status interval | 30 s | How often `/status` is polled (sensors) |
| Event interval | 10 s | How often new security events are polled |

## Entities

All entities belong to one device, **Cybersecurity Tuner**.

| Entity | Description |
|--------|-------------|
| `binary_sensor.cybersecurity_tuner_healthy` | `on` = app healthy. `off` when a required subsystem has failed (database, enabled syslog listener not running, or an unresolved failed rollback). Attributes: `syslog_mode`, `syslog_healthy`, `syslog_received`, `syslog_invalid`, `syslog_dropped`, `syslog_last_message_at`, `unifi_connected`, `unifi_last_sync`, `unifi_error` |
| `binary_sensor.cybersecurity_tuner_learning_active` | A learning session is running |
| `binary_sensor.cybersecurity_tuner_temporary_exception_active` | At least one temporary firewall exception is active. Attribute `temporary_exceptions`: list of `{id, rule_id, rule_name, expires_at}` |
| `sensor.cybersecurity_tuner_unknown_devices` | Number of unknown devices (state class measurement) |
| `sensor.cybersecurity_tuner_blocked_events_1h` | Blocked firewall events in the last hour (state class measurement) |
| `sensor.cybersecurity_tuner_last_capture_status` | Enum: `none`, `running`, `completed`, `failed`, `stopped`. Attribute `last_capture_at` |

**If the app cannot be reached, all entities become `unavailable`**, including
`healthy`. Alarm automations should therefore trigger on `unavailable` as well
as `off` (see the example below).

## Events

New security events are fired on the Home Assistant event bus as
`cybersecurity_tuner_<type>`. The event data is the event's `data` object plus
`seq` (sequence number) and `ts` (ISO 8601 UTC timestamp).

| Event type | Data (all optional except **bold**) |
|------------|---------------------------------------|
| `cybersecurity_tuner_unknown_client_detected` | **`mac`**, `ip`, `display_name`, `network`, `vendor` |
| `cybersecurity_tuner_suspected_security_incident` | `severity`, **`summary`**, `src_ip`, `dst_ip`, `device_mac`, `rule` |
| `cybersecurity_tuner_learning_completed` | **`session_id`**, `device_mac`, `display_name`, `connections`, `recommendations` |
| `cybersecurity_tuner_rule_change_detected` | `rule_id`, `rule_name`, `change` (`added`/`removed`/`modified`), `by` (`tuner`/`external`) |
| `cybersecurity_tuner_temporary_exception_expiring` | `id`, `rule_id`, `rule_name`, `expires_at`, `seconds_left` |
| `cybersecurity_tuner_rollback_failed` | `id`, `rule_id`, `rule_name`, **`error`** |

Delivery details:

- On the very first start, polling begins at the app's current
  `last_event_seq`, so old history is **not** replayed into Home Assistant.
- The last seen `seq` is stored in Home Assistant's `.storage`, so a restart of
  Home Assistant neither replays nor loses events. Events that happen while Home
  Assistant is down are delivered when it comes back.
- Delivery is at-least-once. If Home Assistant crashes between firing an event
  and saving the sequence number, the event may be fired again; `seq` can be
  used to de-duplicate.
- Unknown event types from newer app versions are forwarded under the same
  `cybersecurity_tuner_` prefix.

You can watch the events live under **Developer tools → Events → Listen to
events**, e.g. `cybersecurity_tuner_unknown_client_detected`.

### Example: alarm automations

```yaml
automation:
  - alias: "Security: rollback of firewall rule failed"
    triggers:
      - trigger: event
        event_type: cybersecurity_tuner_rollback_failed
    actions:
      - action: alarm_control_panel.alarm_trigger
        target:
          entity_id: alarm_control_panel.home_alarm
      - action: notify.mobile_app_my_phone
        data:
          title: "Firewall rollback failed"
          message: >-
            Rule {{ trigger.event.data.rule_name | default(trigger.event.data.rule_id) }}
            could not be rolled back: {{ trigger.event.data.error }}

  - alias: "Security: unknown client on the network"
    triggers:
      - trigger: event
        event_type: cybersecurity_tuner_unknown_client_detected
    conditions:
      # Only escalate when the alarm is armed.
      - condition: not
        conditions:
          - condition: state
            entity_id: alarm_control_panel.home_alarm
            state: disarmed
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "Unknown device detected"
          message: >-
            {{ trigger.event.data.display_name | default('Unknown device') }}
            ({{ trigger.event.data.mac }}, {{ trigger.event.data.ip | default('no IP') }})
            joined {{ trigger.event.data.network | default('the network') }}.

  - alias: "Security: Cybersecurity Tuner unhealthy or unreachable"
    triggers:
      - trigger: state
        entity_id: binary_sensor.cybersecurity_tuner_healthy
        to:
          - "off"
          - "unavailable"
        for: "00:02:00"
    actions:
      - action: notify.mobile_app_my_phone
        data:
          title: "Cybersecurity Tuner problem"
          message: >-
            Cybersecurity Tuner is {{ 'unreachable' if trigger.to_state.state == 'unavailable' else 'unhealthy' }}.
```

## Diagnostics

**Settings → Devices & services → Cybersecurity Tuner → ⋮ → Download
diagnostics** includes the latest status payload and event-poller state. The
API token is redacted.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
python -m pytest
```

CI (`.github/workflows/validate.yml`) runs hassfest, HACS validation and the
test suite.

The API contract implemented here is documented in the app repository:
`docs/ha-api.md` (Home Assistant API contract v1).

## License

MIT, see [LICENSE](LICENSE).
