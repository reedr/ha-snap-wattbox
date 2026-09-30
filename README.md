# SnapAV WattBox

A Home Assistant integration for **SnapAV WattBox** power conditioners (800 series and other
IP models). It uses the WattBox telnet Integration Protocol on port 23 and keeps one logged-in
session open per unit. Outlet changes, including ones made from the front panel or OvrC, are
pushed to Home Assistant straight away. Meters are polled every 10 s.

## Entities

| Entity | What it does |
|---|---|
| `switch` per outlet | Turns the outlet on or off. Named after the outlet's name on the WattBox. |
| `button` *Outlet* Reset | Power-cycles the outlet, using its power-on delay. Configuration category. |
| `switch` Auto reboot | Turns the unit's auto-reboot (host monitoring) on or off. Configuration category. |
| `sensor` Power, Current, Voltage | Whole-unit meter. |
| `binary_sensor` Supply voltage | On (unsafe) when the unit reports the supply voltage is out of range. |
| `sensor` *Outlet* Power / Current | Per-outlet meter. Current is disabled by default. Can be turned off in **Configure**. |
| UPS: Battery, UPS load, UPS runtime, UPS utility power, UPS battery | Only created when a UPS is attached. If you attach one later, reload the entry. |

Meter entities aren't created on models without a meter (WB-150/250).

## Install

Add this repository to HACS as a custom repository (category: Integration), install
**SnapAV WattBox**, restart, then add **SnapAV WattBox** under **Settings → Devices & services**.
Setup asks for the unit's host, username and password (the integration login set on the unit).

Each unit is identified by its service tag, so changing its address (**Reconfigure**) or its outlet
names doesn't change any entity IDs. If the login changes, Home Assistant asks for the new one.

If a unit drops the connection or stops answering, its entities go unavailable and the next poll
reconnects. The unit accepts at most 10 simultaneous sessions; this integration uses one.

## Migrating from the old `snapav_wattbox` package

The pre-HACS package (repository `reedr/snapav_wattbox`) used the domain `Wattbox`. This one
uses `snapav_wattbox`. Setup imports all the old entries at once and keeps their devices and entity
IDs, so history, areas, labels, dashboards and automations (including device-based ones) keep
working.

1. Install **SnapAV WattBox** from HACS. It installs to the same
   `custom_components/snapav_wattbox` folder and replaces the old files. Restart Home Assistant.
2. The old entries now show as failed ("integration not found"). Leave them in place.
3. Go to **Settings → Devices & services → Add integration → SnapAV WattBox**, and choose
   **Import the existing Wattbox setup**. Every old entry is imported, with the same host and login.
4. Each unit's device and entities move to its new entry and the old entry is removed.

Old outlet entities are matched to outlets by name. If you renamed an outlet on the WattBox after
the old integration created its entity, that entity can't be matched: it's left unavailable, and the
outlet gets a new entity. Delete the old one, and rename the new one's entity ID if you want.

Also new after migrating: the reset buttons move to the device's Configuration section, and the
meter, voltage-safety and auto-reboot entities are added.

If you choose **Set up a new WattBox** instead, the old entities are left behind and the new ones
get new entity IDs.
