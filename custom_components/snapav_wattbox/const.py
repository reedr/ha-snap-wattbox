"""Constants for the SnapAV WattBox integration."""

from datetime import timedelta

DOMAIN = "snapav_wattbox"
# The pre-HACS package (reedr/snapav_wattbox) registered under this domain.
LEGACY_DOMAIN = "Wattbox"

MANUFACTURER = "SnapAV"
DEFAULT_TITLE = "WattBox"

CONF_LEGACY_ENTRY = "legacy_entry_id"
CONF_OUTLET_METERING = "outlet_metering"
DEFAULT_OUTLET_METERING = True

WATTBOX_PORT = 23
WATTBOX_CONNECT_TIMEOUT = 5
WATTBOX_LOGIN_TIMEOUT = 5
WATTBOX_RESPONSE_TIMEOUT = 5

UPDATE_INTERVAL = timedelta(seconds=10)
