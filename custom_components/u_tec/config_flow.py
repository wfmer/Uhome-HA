"""Config flow for Uhome."""

import logging

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import _LOGGER, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_entry_oauth2_flow
import homeassistant.helpers.config_validation as cv
from homeassistant.util import Mapping

from .const import (
    CONF_API_SCOPE,
    DEFAULT_API_SCOPE,
    DOMAIN,
    OAUTH2_AUTHORIZE,
    OAUTH2_TOKEN,
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_CLIENT_ID): str,
        vol.Required(CONF_CLIENT_SECRET): str,
        vol.Optional(CONF_API_SCOPE, default=DEFAULT_API_SCOPE): str,
    }
)


class UhomeOAuth2FlowHandler(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Config flow to handle Uhome OAuth2 authentication."""

    DOMAIN = DOMAIN
    VERSION = 1

    def __init__(self) -> None:
        """Initialize Uhome OAuth2 flow."""
        super().__init__()
        self._client_id = None
        self._client_secret = None
        self._api_scope = None
        self.data = {}

    @property
    def logger(self) -> logging.Logger:
        """Return logger."""
        return _LOGGER

    @property
    def extra_authorize_data(self) -> dict[str, vol.Any]:
        """Extra data that needs to be appended to the authorize url."""
        return {"scope": self._api_scope or DEFAULT_API_SCOPE}

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Prompt the user to enter their client credentials and API scope."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        if user_input is not None:
            # Save client credentials and api_scope to be used later.
            await self.async_set_unique_id(user_input[CONF_CLIENT_ID])
            self._abort_if_unique_id_configured()

            self._client_id = user_input[CONF_CLIENT_ID]
            self._client_secret = user_input[CONF_CLIENT_SECRET]
            self._api_scope = user_input.get(CONF_API_SCOPE, DEFAULT_API_SCOPE)

            self.logger.debug(
                "Retrieved client credentials, starting oauth authentication"
            )

            # Store client credentials in the flow data for later use
            self.data = {
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "api_scope": self._api_scope,
            }

            # Create and register the implementation
            self.flow_impl = config_entry_oauth2_flow.LocalOAuth2Implementation(
                self.hass,
                DOMAIN,
                self._client_id,
                self._client_secret,
                OAUTH2_AUTHORIZE,
                OAUTH2_TOKEN,
            )

            # Register the implementation
            self.async_register_implementation(
                self.hass,
                self.flow_impl,
            )

            return await self.async_step_pick_implementation()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_DATA_SCHEMA)

    async def _get_oauth2_implementation(
        self,
    ) -> config_entry_oauth2_flow.LocalOAuth2Implementation:
        """Get OAuth2 implementation."""
        return config_entry_oauth2_flow.LocalOAuth2Implementation(
            self.hass,
            DOMAIN,
            self._client_id,
            self._client_secret,
            OAUTH2_AUTHORIZE,
            OAUTH2_TOKEN,
        )

    async def async_oauth_create_entry(
        self, data: dict[str, vol.Any]
    ) -> config_entries.FlowResult:
        """Create the config entry after successful OAuth2 authentication."""
        self.logger.debug(
            "Creating OAuth2 config entry with client_id=%s",
            self._client_id,
        )
        return self.async_create_entry(
            title="Uhome Integration",
            data={
                "auth_implementation": DOMAIN,
                "token": data["token"],
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "api_scope": self._api_scope,
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler()

    async def async_step_reauth(
        self, entry_data: Mapping[str, vol.Any]
    ) -> ConfigFlowResult:
        """Perform reauth upon migration of old entries."""
        return await self.async_step_reauth_confirm(entry_data)

    async def async_step_reauth_confirm(
        self, user_input: Mapping[str, vol.Any] | None = None
    ) -> ConfigFlowResult:
        """Dialog that informs the user that reauth is required."""
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
            )

        return await self.async_step_user()

    async def async_migrate_entry(self, hass: HomeAssistant, config_entry: ConfigEntry):
        """Migrate old entry."""
        _LOGGER.debug(
            "Migrating configuration from version %s.%s",
            config_entry.version,
            config_entry.minor_version,
        )

        if config_entry.version > 1:
            # This means the user has downgraded from a future version
            return False

        if config_entry.version == 1:
            pass

        _LOGGER.debug(
            "Migration to configuration version %s.%s successful",
            config_entry.version,
            config_entry.minor_version,
        )

        return True


class OptionsFlowHandler(OptionsFlow):
    """Handle options flow for Uhome integration."""

    def __init__(self) -> None:
        """Initialize options flow."""
        self.api = None
        self.devices: dict[str, vol.Any] = {}

    async def async_step_init(
        self, user_input: dict[str, vol.Any] | None
    ) -> ConfigFlowResult:
        """Present the main options menu."""
        if user_input is None:
            return self.async_show_menu(
                step_id="init",
                menu_options={
                    "select_devices": "Select Devices",
                    "api_reauth_opt": "Change API Config",
                },
            )
        return self.async_show_form(step_id=user_input)

    async def async_step_select_devices(
        self, user_input: dict[str, vol.Any] | None
    ) -> ConfigFlowResult:
        """Allow user to select devices to add or remove."""
        errors = {}

        if (
            DOMAIN in self.hass.data
            and self.config_entry.entry_id in self.hass.data[DOMAIN]
        ):
            self.api = self.hass.data[DOMAIN][self.config_entry.entry_id]["api"]
        else:
            return self.async_abort(reason="no_api_conf")

        try:
            response = await self.api.discover_devices()
            if "payload" in response:
                self.discovered_devices = {
                    device[
                        "id"
                    ]: f"{device.get('name', 'Unknown')} ({device.get('category', 'unknown')})"
                    for device in response["payload"].get("devices", [])
                }
        except (ValueError, TypeError):
            errors["base"] = "cannot_connect"
            discovered_devices = {}

        existing_devices = self.config_entry.options.get("selected_devices", [])
        all_devices = {discovered_devices}
        default_selected = [
            device_id for device_id in existing_devices if device_id in all_devices
        ]

        if user_input is not None:
            new_selected_devices = user_input.get("selected_devices", [])
            options_data = {"selected_devices": new_selected_devices}
            return self.async_create_entry(title="", data=options_data)

        options_schema = vol.Schema(
            {
                vol.Optional(
                    "selected_devices", default=default_selected
                ): cv.multi_select(all_devices)
            }
        )

        return self.async_show_form(
            step_id="select_devices", data_schema=options_schema, errors=errors
        )

    async def async_step_api_reauth_opt(
        self, user_input: dict[str, vol.Any] | None = None
    ) -> ConfigFlowResult:
        """Trigger reauthentication process."""
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        return self.async_show_form(step_id="user")


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""

