"""Config flow for Marstek Energy System integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .api import MarstekApiClient
from .const import (
    CONF_HOST,
    CONF_PORT,
    CONF_SCAN_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_PORT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

MANUAL_ENTRY_KEY = "manual_entry"


class MarstekConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Marstek Energy System."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovered_devices: dict[str, dict[str, Any]] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - discover devices or choose manual entry."""
        errors: dict[str, str] = {}

        if user_input is not None:
            selected = user_input.get("device")
            if selected == MANUAL_ENTRY_KEY:
                return await self.async_step_manual()
            
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

        device_options: list[selector.SelectOptionDict] = []
        for mac, dev in self._discovered_devices.items():
            label = f"{dev.get('device', 'Marstek')} ({dev['ip']}) [MAC: {mac}]"
            device_options.append({"value": mac, "label": label})

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

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_SCAN_INTERVAL, default=current_interval): vol.All(
                    int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
