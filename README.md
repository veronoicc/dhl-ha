# DHL Integration for Home Assistant

A modern Home Assistant custom component integration for DHL Web Internal API (`dhl.de`).

This integration provides real-time tracking of DHL parcels, incoming and outgoing shipments, interactive To-do list delivery cards, status overview sensors, and automations for deliveries.

---

## Features

- **Real-Time Parcel Tracking**: Track all current, incoming, outgoing, and delivered shipments.
- **Interactive To-do List (`todo.dhl_*`)**: View deliveries directly in Home Assistant's To-do list card, complete with tracking numbers, progress steps, recipient details, and expected delivery dates.
- **Summary Sensors**:
  - In Transit parcels count (`sensor.dhl_*_in_transit`) with parcel details in attributes
  - Delivered parcels count (`sensor.dhl_*_delivered`)
  - Incoming parcels count (`sensor.dhl_*_incoming`)
  - Outgoing parcels count (`sensor.dhl_*_outgoing`)
  - Total monitored parcels count (`sensor.dhl_*_total`)
  - Last API update timestamp (`sensor.dhl_*_last_update`)
- **Multi-Account Support**: Connect multiple DHL accounts (e.g. family members or business accounts). Each account is represented as an individual device in Home Assistant.
- **Interactive Action Services**:
  - `dhl.get_parcels`: Query parcels with response data and filters (`all`, `in_transit`, `delivered`, `incoming`, `outgoing`, optional `include_archived`).
  - `dhl.refresh_parcels`: Manually trigger an immediate update from DHL servers.
- **Flexible Authentication**:
  - **Account Credentials**: Log in with your DHL account email and password.
  - **Session Cookies**: Log in using exported cookies (`dhla0`, `dhlr0`, `dhlb`, `verfolgenCsrfToken`).
- **Options Flow**: Configure the update interval (5–120 minutes) and choose whether to include archived parcels.

---

## Installation

### Via HACS (Recommended)

1. Ensure [HACS](https://hacs.xyz/) is installed in your Home Assistant instance.
2. In HACS, open the three dots menu in the top right and select **Custom repositories**.
3. Add the repository URL: `https://github.com/veronoicc/dhl-ha` (or your repository URL), with category **Integration**.
4. Click **Download**, then restart Home Assistant.

### Manual Installation

1. Download the `custom_components/dhl` folder from the latest release.
2. Copy the `dhl` folder into your Home Assistant `<config>/custom_components/` directory.
3. Restart Home Assistant.

---

## Configuration

1. In Home Assistant, go to **Settings** -> **Devices & Services** -> **Add Integration**.
2. Search for **DHL**.
3. Choose your preferred authentication method:
   - **Credentials**: Enter your DHL account email and password.
   - **Session Cookies**: Provide your `dhla0`, `dhlr0`, `dhlb`, and `verfolgenCsrfToken` values extracted from your browser.
4. Click **Submit**. The integration will validate your login and register your DHL account.

### Options

Click **Configure** on the DHL integration entry in Home Assistant to customize:
- **Scan Interval**: Update polling frequency (5 to 120 minutes, default: 15 minutes).
- **Include Archived Shipments**: Toggle whether archived shipments are tracked and shown in entities and services.

---

## Dashboard Examples

### 1. Deliveries To-do Card

Use Home Assistant's native **To-do list** card to display active deliveries in your dashboard:

```yaml
type: todo-list
entity: todo.dhl_parcels
title: DHL Deliveries
```

### 2. Markdown Card with Active Parcels

Display active shipments and status details:

```yaml
type: markdown
title: DHL Incoming Packages
content: >
  {% set parcels = state_attr('sensor.dhl_in_transit', 'parcels') %}
  {% if parcels %}
    | Sender / Package | Tracking | Status |
    | :--- | :--- | :--- |
    {% for p in parcels %}
    | **{{ p.name }}** | `{{ p.tracking_number }}` | {{ p.status }} |
    {% endfor %}
  {% else %}
    No parcels currently in transit.
  {% endif %}
```

### 3. Sensor Badges / Glance Card

Show quick counts of your parcel deliveries:

```yaml
type: glance
title: DHL Summary
entities:
  - entity: sensor.dhl_in_transit
    name: In Transit
  - entity: sensor.dhl_incoming
    name: Incoming
  - entity: sensor.dhl_delivered
    name: Delivered
  - entity: sensor.dhl_last_update
    name: Last Sync
```

---

## Automation Examples

### Notify when a parcel is out for delivery or delivered

```yaml
alias: "DHL: Parcel Delivered Notification"
trigger:
  - platform: state
    entity_id: sensor.dhl_delivered
condition:
  - condition: template
    value_template: "{{ trigger.to_state.state | int > trigger.from_state.state | int }}"
action:
  - service: notify.persistent_notification
    data:
      title: "DHL Delivery"
      message: "A parcel has just been delivered! Check your DHL deliveries list."
```

### Fetch parcel list in an automation or script using `dhl.get_parcels`

```yaml
alias: "Query DHL In-Transit Parcels"
sequence:
  - action: dhl.get_parcels
    data:
      status_filter: "in_transit"
    response_variable: response
  - service: notify.notify
    data:
      message: >
        You have {{ response.parcels | length }} packages in transit:
        {% for p in response.parcels %}
        - {{ p.name }}: {{ p.status_text }}
        {% endfor %}
```

---

## Services

### `dhl.get_parcels`
Returns the list of monitored parcels matching specified filters.

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `config_entry_id` | string | No | Target specific DHL account config entry ID. Omit to query all accounts. |
| `status_filter` | select | No | Filter shipments: `all`, `in_transit`, `delivered`, `incoming`, `outgoing`. Default is `all`. |
| `include_archived` | boolean | No | Whether to include archived shipments in the result. Default is `false`. |

Returns:
```json
{
  "parcels": [
    {
      "id": "00340000000000000001",
      "tracking_number": "00340000000000000001",
      "name": "Example Store GmbH",
      "direction": "ANKOMMEND",
      "list_type": "AKTUELL",
      "is_delivered": false,
      "status_text": "Die Sendung wird zur Zustellbasis transportiert.",
      "summary_text": "Example Store GmbH (00340000000000000001) - In Transit",
      "progress": {
        "status": "In Bearbeitung",
        "current_step": 3,
        "max_steps": 5,
        "datum_aktueller_status": "2026-09-15T08:30:00+02:00"
      },
      "recipient": {
        "name": "Max Mustermann",
        "city": "Berlin"
      },
      "delivery": {
        "zugestellt_an_empfaenger": false,
        "zugestellt_an_wunschort": false,
        "abholcode_available": false
      }
    }
  ]
}
```

### `dhl.refresh_parcels`
Forces an immediate API refresh for one or all configured DHL accounts.

| Parameter | Type | Required | Description |
| :--- | :--- | :--- | :--- |
| `config_entry_id` | string | No | Target specific DHL account config entry ID. Omit to refresh all accounts. |

---

## Diagnostics

The integration supports Home Assistant diagnostics. Download diagnostics from the device page in Home Assistant to inspect coordinator health and API status. All sensitive tokens (cookies, passwords, emails, post numbers) are automatically redacted.

---

## License

MIT License. This integration is an independent community project and is not affiliated with or endorsed by Deutsche Post DHL Group.
