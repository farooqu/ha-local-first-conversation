"""An isolated HA instance: real registries, recognizers, handlers, and sessions."""

import shutil
from pathlib import Path

import pytest
from homeassistant import auth, config_entries, loader
from homeassistant.components import conversation
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import (
    area_registry,
    device_registry,
    entity,
    entity_registry,
    floor_registry,
    frame,
    label_registry,
    translation,
)
from homeassistant.setup import async_setup_component


@pytest.fixture
async def hass(tmp_path, unused_tcp_port):
    """Boot only the components needed by the spike; never connect to a real home."""
    shutil.copytree(
        Path(__file__).parents[1] / "custom_components", tmp_path / "custom_components"
    )
    hass = HomeAssistant(str(tmp_path))
    hass.config.skip_pip = True
    hass.config.language = "en"
    hass.config.country = "US"
    await hass.config.async_set_time_zone("America/Indiana/Indianapolis")
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await hass.config_entries.async_initialize()
    loader.async_setup(hass)
    frame.async_setup(hass)
    entity.async_setup(hass)
    translation.async_setup(hass)
    device_registry.async_setup(hass)
    await floor_registry.async_load(hass)
    await area_registry.async_load(hass)
    await label_registry.async_load(hass)
    await device_registry.async_load(hass)
    await entity_registry.async_load(hass)
    hass.auth = await auth.auth_manager_from_config(hass, [], [])
    assert await async_setup_component(hass, "homeassistant", {})
    assert await async_setup_component(
        hass,
        "conversation",
        {"http": {"server_host": "127.0.0.1", "server_port": unused_tcp_port}},
    )
    yield hass
    await hass.async_stop(force=True)


@pytest.fixture
def home(hass):
    """A synthetic kitchen and bedroom; service calls only change in-memory state."""
    registry = entity_registry.async_get(hass)
    kitchen = area_registry.async_get(hass).async_get_or_create("Kitchen")
    bedroom = area_registry.async_get(hass).async_get_or_create("Bedroom")
    for entity_id, name, area in (
        ("light.kitchen_ceiling", "Kitchen Ceiling Lights", kitchen),
        ("light.kitchen_strip", "Kitchen Strip", kitchen),
        ("cover.bedroom_blinds", "Bedroom Blinds", bedroom),
    ):
        domain, object_id = entity_id.split(".")
        entry = registry.async_get_or_create(
            domain, "spike", object_id, suggested_object_id=object_id
        )
        registry.async_update_entity(entry.entity_id, name=name, area_id=area.id)
        hass.states.async_set(entity_id, "off", {"friendly_name": name})

    calls = []

    async def handle(call):
        calls.append(call)
        ids = call.data["entity_id"]
        if isinstance(ids, str):
            ids = [ids]
        for entity_id in ids:
            old = hass.states.get(entity_id)
            if old.state == "unavailable":
                raise HomeAssistantError("Synthetic device is unavailable")
            hass.states.async_set(
                entity_id,
                "on" if call.service in ("turn_on", "open_cover") else "off",
                old.attributes,
            )

    for domain, services in (
        ("light", ("turn_on", "turn_off")),
        ("cover", ("open_cover", "close_cover")),
    ):
        for service in services:
            hass.services.async_register(domain, service, handle)
    return kitchen, calls


class RecordingFallback(conversation.ConversationEntity):
    """Synthetic provider: real HA prompt preparation and streaming, no model/API."""

    _attr_name = "Synthetic fallback"
    _attr_unique_id = "spike_fallback"
    _attr_supports_streaming = True
    supported_languages = "*"

    def __init__(self):
        self.inputs = []
        self.prompts = []
        self.raise_error = False

    async def _async_handle_message(self, user_input, chat_log):
        self.inputs.append(user_input)
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context("spike"),
            user_llm_prompt="Synthetic fallback, no tools.",
            user_extra_system_prompt=user_input.extra_system_prompt,
        )
        self.prompts.append(chat_log.content[0].content)
        if self.raise_error:
            raise RuntimeError("Synthetic provider failure")

        async def deltas():
            yield {"role": "assistant"}
            yield {"content": "Fallback "}
            yield {"content": "answer"}

        async for _ in chat_log.async_add_delta_content_stream(
            user_input.agent_id, deltas()
        ):
            pass
        result = conversation.async_get_result_from_chat_log(user_input, chat_log)
        result.continue_conversation = True
        return result


@pytest.fixture
async def router(hass):
    """Load the custom integration through its actual config flow/platform."""
    fallback = RecordingFallback()
    component = hass.data[conversation.DATA_COMPONENT]
    await component.async_add_entities([fallback])
    result = await hass.config_entries.flow.async_init(
        "local_first_conversation", context={"source": "user"}
    )
    assert result["type"] == "form", result
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Local First", "fallback_agent": fallback.entity_id}
    )
    assert result["type"] == "create_entry", result
    await hass.async_block_till_done()
    entry = result["result"]
    entity_id = entity_registry.async_get(hass).async_get_entity_id(
        "conversation", "local_first_conversation", entry.entry_id
    )
    assert entity_id is not None
    return entity_id, fallback, entry
