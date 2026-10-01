"""Constants for the Marstek Energy System integration."""
from typing import Final

DOMAIN: Final = "marstek"
DEFAULT_NAME: Final = "Marstek"
DEFAULT_PORT: Final = 30000
DEFAULT_SCAN_INTERVAL: Final = 10  # seconds, fast for Switchbot response
MIN_SCAN_INTERVAL: Final = 5
MAX_SCAN_INTERVAL: Final = 60
# Slow-changing endpoints (mode, PV, meter, wifi, BLE) are polled once every N cycles
SLOW_UPDATE_CYCLES: Final = 6

# Configuration keys
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_DEVICE_ID: Final = "device_id"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_DATA_SOURCE: Final = "data_source"
CONF_EMAIL: Final = "email"
CONF_PASSWORD: Final = "password"
CONF_CLOUD_DEVID: Final = "cloud_devid"

# Telemetry sources. "cloud" reads from Marstek's servers and sends nothing to the
# station at all - no control entities, but also no UDP load that could reboot it.
SOURCE_LOCAL: Final = "local"
SOURCE_CLOUD: Final = "cloud"
DATA_SOURCES: Final = [SOURCE_LOCAL, SOURCE_CLOUD]

# Cloud API (read-only - it has no control endpoints)
CLOUD_API_LOGIN: Final = "https://eu.hamedata.com/app/Solar/v2_get_device.php"
CLOUD_API_DEVICES: Final = "https://eu.hamedata.com/ems/api/v1/getDeviceList"
CLOUD_TIMEOUT: Final = 10

# API Methods
METHOD_GET_DEVICE: Final = "Marstek.GetDevice"
METHOD_WIFI_GET_STATUS: Final = "Wifi.GetStatus"
METHOD_BLE_GET_STATUS: Final = "BLE.GetStatus"
METHOD_BAT_GET_STATUS: Final = "Bat.GetStatus"
METHOD_PV_GET_STATUS: Final = "PV.GetStatus"
METHOD_ES_GET_STATUS: Final = "ES.GetStatus"
METHOD_ES_GET_MODE: Final = "ES.GetMode"
METHOD_ES_SET_MODE: Final = "ES.SetMode"
METHOD_EM_GET_STATUS: Final = "EM.GetStatus"
METHOD_DOD_SET: Final = "DOD.SET"
METHOD_BLE_ADV: Final = "Ble.Adv"
METHOD_LED_CTRL: Final = "Led.Ctrl"

# Operating Modes
MODE_AUTO: Final = "Auto"
MODE_AI: Final = "AI"
MODE_MANUAL: Final = "Manual"
MODE_PASSIVE: Final = "Passive"
MODE_UPS: Final = "UPS"

OPERATING_MODES: Final = [
    MODE_AUTO,
    MODE_AI,
    MODE_MANUAL,
    MODE_PASSIVE,
    MODE_UPS,
]

# DOD Range
MIN_DOD: Final = 30
MAX_DOD: Final = 88
DEFAULT_DOD: Final = 88

# Passive mode power limits (W)
MIN_PASSIVE_POWER: Final = 0
MAX_PASSIVE_POWER: Final = 5000
DEFAULT_PASSIVE_CD_TIME: Final = 3600  # 1 hour default countdown

# Platforms
PLATFORMS: Final = [
    "binary_sensor",
    "sensor",
    "select",
    "number",
    "switch",
]

# The cloud API is read-only, so control platforms are not loaded in cloud mode.
CLOUD_PLATFORMS: Final = [
    "sensor",
]
