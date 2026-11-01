"""Config flow for Marstek Energy System integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_ADDRESS
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MarstekApiClient
from .cloud import MarstekCloudAuthError, MarstekCloudClient, MarstekCloudError
from .const import (
    CONF_CLOUD_DEVID,
    CONF_DATA_SOURCE,
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DATA_SOURCES,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
    SOURCE_LOCAL,
)

_LOGGER = logging.getLogger(__name__)

MANUAL_ENTRY_KEY = "manual_entry"
# Kept here rather than imported from v500.py, which pulls in bleak.
V500_NAME_PREFIX = "HM_V500_"


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Energy System."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, dict[str, Any]] = {}
        # V500 power stations found over Bluetooth: address -> advertised name
        self._ble_devices: dict[str, str] = {}

    async def async_step_bluetooth(self, discovery_info: Any) -> FlowResult:
        """Handle a V500 that Home Assistant's Bluetooth scanner found."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        self._ble_devices[discovery_info.address] = discovery_info.name
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm adding a discovered V500."""
        if user_input is not None:
            return self._create_v500_entry(self.unique_id)
        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={"name": self._ble_devices[self.unique_id]},
        )

    def _create_v500_entry(self, address: str) -> FlowResult:
        return self.async_create_entry(
            title=f"Marstek V500 ({self._ble_devices[address]})",
            data={CONF_ADDRESS: address, CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL},
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - discover devices or choose manual entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get("device")
            if selected == MANUAL_ENTRY_KEY:
                return await self.async_step_manual()
            
            if selected in self._ble_devices:
                await self.async_set_unique_id(selected)
                self._abort_if_unique_id_configured()
                return self._create_v500_entry(selected)

            if selected and selected in self._discovered_devices:
                dev = self._discovered_devices[selected]
                host = dev["ip"]
                port = DEFAULT_PORT
                name = dev.get("device", DEFAULT_NAME)

                # Set unique ID based on MAC address
                await self.async_set_unique_id(selected)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                return self.async_create_entry(
                    title=f"{name} ({host})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    },
                )

        # Run discovery
        _LOGGER.debug("Running UDP broadcast discovery for Marstek devices...")
        try:
            devices = await MarstekApiClient.async_discover_devices(timeout=2.5)
            for dev in devices:
                mac = dev.get("wifi_mac") or dev.get("ble_mac") or dev["ip"]
                self._discovered_devices[mac] = dev
        except Exception as err:
            _LOGGER.debug("Discovery error: %s", err)

        if "bluetooth" in self.hass.config.components:
            from homeassistant.components import bluetooth

            configured = self._async_current_ids()
            for info in bluetooth.async_discovered_service_info(self.hass, connectable=True):
                if (info.name or "").startswith(V500_NAME_PREFIX) and info.address not in configured:
                    self._ble_devices[info.address] = info.name

        device_options: list[selector.SelectOptionDict] = []
        for mac, dev in self._discovered_devices.items():
            label = f"{dev.get('device', 'Marstek')} ({dev['ip']}) [MAC: {mac}]"
            device_options.append({"value": mac, "label": label})
        for address, name in self._ble_devices.items():
            device_options.append({"value": address, "label": f"{name} (Bluetooth) [{address}]"})

        device_options.append({"value": MANUAL_ENTRY_KEY, "label": "Ввести IP та Порт вручну / Manual IP Entry"})

        schema = vol.Schema(
            {
                vol.Required("device", default=device_options[0]["value"]): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=device_options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_manual(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle manual entry of host and port."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = user_input.get(CONF_PORT, DEFAULT_PORT)

            self._async_abort_entries_match({CONF_HOST: host})

            client = MarstekApiClient(host=host, port=port)
            try:
                if await client.async_test_connection():
                    # Try to get unique ID from device info
                    res = await client.async_get_device()
                    unique_id = host
                    name = DEFAULT_NAME
                    if res and "result" in res:
                        r = res["result"]
                        unique_id = r.get("wifi_mac") or r.get("ble_mac") or host
                        name = r.get("device", DEFAULT_NAME)

                    await self.async_set_unique_id(unique_id)
                    self._abort_if_unique_id_configured(updates={CONF_HOST: host})

                    return self.async_create_entry(
                        title=f"{name} ({host})",
                        data={
                            CONF_HOST: host,
                            CONF_PORT: port,
                            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        },
                    )
                errors["base"] = "cannot_connect"
            except Exception as err:
                _LOGGER.error("Error connecting to %s:%s - %s", host, port, err)
                errors["base"] = "cannot_connect"
            finally:
                client.close()

        schema = vol.Schema(
            {
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )

        return self.async_show_form(
            step_id="manual",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return MarstekOptionsFlowHandler()


class MarstekOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle Marstek options.

    `config_entry` is provided by the base class - assigning to it raises, since
    it is a read-only property.
    """

    def __init__(self) -> None:
        """Initialize the options flow."""
        self._options: dict[str, Any] = {}
        self._devices: list[dict[str, Any]] = []

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        options = self.config_entry.options

        if CONF_ADDRESS in self.config_entry.data:
            return await self.async_step_v500(user_input)

        if user_input is not None:
            # Carry the existing options forward so the credentials stay on file even
            # while running local - flipping the source back is then a one-click
            # change with nothing to re-enter.
            self._options = {
                **options,
                CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                CONF_DATA_SOURCE: user_input[CONF_DATA_SOURCE],
            }
            email = user_input.get(CONF_EMAIL, "").strip()
            password = user_input.get(CONF_PASSWORD, "")
            if email:
                self._options[CONF_EMAIL] = email
            if password:
                self._options[CONF_PASSWORD] = password

            if user_input[CONF_DATA_SOURCE] == SOURCE_LOCAL:
                return self.async_create_entry(title="", data=self._options)

            if not email or not password:
                errors["base"] = "cloud_credentials_required"
            else:
                client = MarstekCloudClient(
                    async_get_clientsession(self.hass), email, password
                )
                try:
                    devices = await client.async_get_devices()
                except MarstekCloudAuthError:
                    errors["base"] = "cloud_auth"
                except MarstekCloudError as err:
                    _LOGGER.debug("Marstek cloud unreachable: %s", err)
                    errors["base"] = "cloud_unavailable"
                else:
                    if not devices:
                        errors["base"] = "cloud_no_devices"
                    else:
                        self._devices = devices
                        known = str(options.get(CONF_CLOUD_DEVID, ""))
                        chosen = next(
                            (d for d in devices if str(d.get("devid")) == known),
                            devices[0] if len(devices) == 1 else None,
                        )
                        if chosen is not None:
                            return self._save_cloud(chosen)
                        return await self.async_step_cloud_device()

        current_interval = options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_DATA_SOURCE,
                    default=options.get(CONF_DATA_SOURCE, SOURCE_LOCAL),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=DATA_SOURCES,
                        translation_key=CONF_DATA_SOURCE,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
                vol.Optional(
                    CONF_EMAIL, default=options.get(CONF_EMAIL, "")
                ): str,
                vol.Optional(
                    CONF_PASSWORD, default=options.get(CONF_PASSWORD, "")
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )

        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )

    async def async_step_v500(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """A V500 has neither a cloud mode nor UDP, only the poll interval."""
        if user_input is not None:
            return self.async_create_entry(
                title="", data={**self.config_entry.options, **user_input}
            )

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )
        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="v500", data_schema=schema)

    async def async_step_cloud_device(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Pick which battery on the cloud account this entry represents."""
        if user_input is not None:
            devid = user_input[CONF_CLOUD_DEVID]
            device = next(
                (d for d in self._devices if str(d.get("devid")) == devid),
                None,
            )
            if device is not None:
                return self._save_cloud(device)

        schema = vol.Schema(
            {
                vol.Required(CONF_CLOUD_DEVID): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": str(dev.get("devid")),
                                "label": f"{dev.get('name', 'Marstek')} ({dev.get('sn', dev.get('devid'))})",
                            }
                            for dev in self._devices
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            }
        )

        return self.async_show_form(step_id="cloud_device", data_schema=schema)

    def _save_cloud(self, device: dict[str, Any]) -> FlowResult:
        """Store the chosen cloud device and finish the flow."""
        self._options[CONF_CLOUD_DEVID] = str(device.get("devid"))
        return self.async_create_entry(title="", data=self._options)
