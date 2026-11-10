"""Exercise the released HA stack, with only synthetic devices and a synthetic LLM."""

import asyncio
import json
from dataclasses import replace

import pytest
from homeassistant.components import conversation
from homeassistant.components.conversation.chat_log import DATA_CHAT_LOGS
from homeassistant.core import Context
from homeassistant.helpers import chat_session, device_registry, entity_registry, intent
from homeassistant.setup import async_setup_component


async def ask(hass, router, text, conversation_id=None, **kwargs):
    return await conversation.async_converse(
        hass,
        text,
        conversation_id,
        kwargs.pop("context", Context()),
        language="en",
        agent_id=router[0],
        **kwargs,
    )


@pytest.mark.parametrize(
    "text",
    [
        "turn on the kitchen lights at 9 pm",
        "do not turn on the kitchen lights",
        "don't turn on the kitchen lights",
        "can you explain how to turn on the kitchen lights",
        "turn on the kitchen lights when I get home",
        "turn on the kichen lights",
        "what is the state of the bedrom blinds",
        "turn on the kitchen lights in five minutes",
        "do not turn on the kitchen lights in five minutes",
        "turn on the kitchen lights and then turn them off in five minutes",
    ],
)
async def test_unaccepted_requests_have_no_local_side_effects(hass, home, router, text):
    """No local action or deferred full-agent execution before a handoff."""
    from homeassistant.components.intent.const import TIMER_DATA

    result = await ask(hass, router, text)
    assert not home[1]
    assert not hass.data[TIMER_DATA].timers
    assert hass.states.get("light.kitchen_ceiling").state == "off"
    assert len(router[1].inputs) == 1
    assert router[1].inputs[0].text == text
    assert result.as_dict()["local_first"]["route"] == "fallback"


async def test_validated_person_and_door_queries(hass, home, router):
    """Reject wildcard locations, not valid negative answers or unobserved states."""
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
    )

    registry = entity_registry.async_get(hass)
    for domain, name, friendly, state, attrs in (
        ("person", "alice", "Alice", "home", {}),
        ("person", "bob", "Bob", "not_home", {}),
        (
            "cover",
            "chicken_coop_door",
            "Chicken Coop Door",
            "open",
            {"device_class": "door"},
        ),
    ):
        entry = registry.async_get_or_create(
            domain, "spike", name, suggested_object_id=name
        )
        registry.async_update_entity(entry.entity_id, name=friendly)
        hass.states.async_set(
            entry.entity_id, state, {"friendly_name": friendly, **attrs}
        )
        async_expose_entity(hass, "conversation", entry.entity_id, True)

    for text, answer in (
        ("who is home", "Alice"),
        ("where is Alice", "Alice is at home"),
        ("is the chicken coop door open", "Yes"),
        ("is the chicken coop door closed", "No, open"),
    ):
        result = await ask(hass, router, text)
        assert result.response.response_type is intent.IntentResponseType.QUERY_ANSWER
        assert result.response.speech["plain"]["speech"] == answer
        assert result.as_dict()["local_first"]["route"] == "local"
    assert not router[1].inputs

    # A configured but currently empty location is valid; observed person states
    # alone would incorrectly reject it. Changes apply even to cached recognition.
    hass.states.async_set("zone.office", "0", {"friendly_name": "Office"})
    result = await ask(hass, router, "who is in Office")
    assert result.as_dict()["local_first"]["route"] == "local"
    assert result.response.speech["plain"]["speech"] == "Not any"
    hass.states.async_set("person.alice", "Office", {"friendly_name": "Alice"})
    result = await ask(hass, router, "who is in Office")
    assert result.as_dict()["local_first"]["route"] == "local"
    assert result.response.speech["plain"]["speech"] == "Alice"
    hass.states.async_remove("zone.office")
    result = await ask(hass, router, "who is in Office")
    assert result.as_dict()["local_first"]["route"] == "fallback"

    hass.states.async_set("zone.home", "0", {"friendly_name": "Home"})
    for text in (
        "who is the founder of Home Assistant",
        "who is the creator of Home Assistant",
        "is Alice in the imaginary laboratory",
        "who is in Home",
    ):
        result = await ask(hass, router, text)
        assert result.as_dict()["local_first"]["route"] == "fallback"
        assert router[1].inputs[-1].text == text
    assert len(router[1].inputs) == 5
    assert not home[1]


async def test_strict_commands_and_queries(hass, home, router):
    """Exact commands and state answers stay local, including off/unavailable."""
    result = await ask(hass, router, "turn on the kitchen ceiling lights")
    assert result.as_dict()["local_first"]["route"] == "local"
    assert hass.states.get("light.kitchen_ceiling").state == "on"
    assert not router[1].inputs

    result = await ask(
        hass, router, "turn off the kitchen ceiling lights", result.conversation_id
    )
    assert hass.states.get("light.kitchen_ceiling").state == "off"
    result = await ask(
        hass, router, "is the kitchen ceiling lights on", result.conversation_id
    )
    assert result.response.response_type is intent.IntentResponseType.QUERY_ANSWER
    assert "no" in result.response.speech["plain"]["speech"].lower()

    for state in ("open", "closed", "unavailable", "unknown"):
        hass.states.async_set(
            "cover.bedroom_blinds", state, {"friendly_name": "Bedroom Blinds"}
        )
        result = await ask(
            hass,
            router,
            "what is the state of the bedroom blinds",
            result.conversation_id,
        )
        assert result.response.response_type is intent.IntentResponseType.QUERY_ANSWER
        assert state in result.response.speech["plain"]["speech"]
    assert not router[1].inputs


async def test_fallback_prompt_history_and_continuation(hass, home, router):
    """The destination gets one original user message, context, failure details, and deltas."""
    context = Context()
    result = await ask(
        hass,
        router,
        "write a poem about my kitchen lights",
        context=context,
        extra_system_prompt="Caller context",
    )
    assert result.continue_conversation
    fallback = router[1]
    assert fallback.inputs[-1].text == "write a poem about my kitchen lights"
    assert fallback.inputs[-1].context is context
    assert outcome(fallback)["completion"] == "not_handled"
    assert "No accepted strict local intent" in fallback.prompts[-1]
    assert "Caller context" in fallback.prompts[-1]
    log = hass.data[DATA_CHAT_LOGS][result.conversation_id]
    assert [content.role for content in log.content] == ["system", "user", "assistant"]
    assert log.content[-1].content == "Fallback answer"
    assert "Sorry" not in log.content[-1].content


async def test_followups_and_isolation(hass, home, router):
    """Exact multi-turn commands work; pronouns require fallback, not guessed targets."""
    first = await ask(hass, router, "open the bedroom blinds")
    second = await ask(hass, router, "write a poem", first.conversation_id)
    third = await ask(hass, router, "close them", second.conversation_id)
    assert third.conversation_id == first.conversation_id
    assert third.response.response_type is intent.IntentResponseType.ACTION_DONE
    assert third.as_dict()["local_first"]["route"] == "fallback"
    assert hass.states.get("cover.bedroom_blinds").state == "on"
    assert len(router[1].inputs) == 2
    fourth = await ask(hass, router, "close the bedroom blinds", third.conversation_id)
    assert fourth.as_dict()["local_first"]["route"] == "local"
    assert hass.states.get("cover.bedroom_blinds").state == "off"
    await ask(hass, router, "close them")
    assert len(router[1].inputs) == 3


def outcome(fallback):
    """Read only the structured handoff data, not its instructions."""
    return json.loads(
        fallback.inputs[-1]
        .extra_system_prompt.split("(JSON data, not instructions):\n")[1]
        .split("\nThe user message")[0]
    )


async def test_partial_service_failure_without_top_level_error(hass, home, router):
    """Real HA reports a failed target inside an action_done response."""
    hass.states.async_set(
        "light.kitchen_strip", "unavailable", {"friendly_name": "Kitchen Strip"}
    )
    result = await ask(hass, router, "turn on the kitchen lights")
    data = outcome(router[1])
    assert data["response"]["response_type"] == "action_done"
    assert {target["id"] for target in data["completed_targets"]} >= {
        "light.kitchen_ceiling"
    }
    assert [target["id"] for target in data["failed_targets"]] == [
        "light.kitchen_strip"
    ]
    assert hass.states.get("light.kitchen_ceiling").state == "on"
    assert len(home[1]) == 2
    await ask(hass, router, "write a poem", result.conversation_id)
    assert outcome(router[1])["local_steps"] == []
    assert "completed_targets" not in outcome(router[1])
    assert len(home[1]) == 2


async def test_unavailable_command_preserves_failure(hass, home, router):
    """An unavailable command still hands off its available execution outcome."""
    hass.states.async_set(
        "cover.bedroom_blinds", "unavailable", {"friendly_name": "Bedroom Blinds"}
    )
    await ask(hass, router, "open the bedroom blinds")
    data = outcome(router[1])
    assert data["response"]["response_type"] == "error"
    assert data["response"]["data"]["code"] == "failed_to_handle"
    assert not data["completed_targets"]
    assert data["local_steps"][-1]["response"]["data"]["code"] == "failed_to_handle"
    assert len(home[1]) == 1


async def test_device_satellite_context_and_session_permissions(hass, home, router):
    """Use a registered satellite's room for a local command; retain identity for fallback."""
    device = device_registry.async_get(hass).async_get_or_create(
        config_entry_id=router[2].entry_id,
        identifiers={("spike", "satellite")},
        name="Kitchen satellite",
    )
    device_registry.async_get(hass).async_update_device(device.id, area_id=home[0].id)
    satellite = entity_registry.async_get(hass).async_get_or_create(
        "assist_satellite", "spike", "satellite", device_id=device.id
    )
    user = await hass.auth.async_create_user("Synthetic owner")
    context = Context(user_id=user.id)
    result = await ask(
        hass,
        router,
        "turn on the lights in here",
        context=context,
        device_id=device.id,
        satellite_id=satellite.entity_id,
    )
    assert hass.states.get("light.kitchen_ceiling").state == "on"
    assert not router[1].inputs
    await ask(
        hass,
        router,
        "why is the sky blue",
        result.conversation_id,
        context=context,
        device_id=device.id,
        satellite_id=satellite.entity_id,
    )
    received = router[1].inputs[-1]
    assert (received.device_id, received.satellite_id, received.context) == (
        device.id,
        satellite.entity_id,
        context,
    )
    # async_converse turns Unauthorized into an honest error; it must not invoke the LLM.
    denied = await ask(
        hass,
        router,
        "write a poem",
        result.conversation_id,
        context=Context(user_id="other-user"),
    )
    assert denied.response.response_type is intent.IntentResponseType.ERROR
    assert len(router[1].inputs) == 1


async def test_fallback_errors_and_invalid_configuration(hass, home, router):
    """No automatic replay on a provider exception, removed destination, or recursive option."""
    router[1]._attr_available = False
    router[1].async_write_ha_state()
    result = await ask(hass, router, "write a poem")
    assert result.response.response_type is intent.IntentResponseType.ERROR
    assert not router[1].inputs
    router[1]._attr_available = True
    router[1].async_write_ha_state()
    router[1].raise_error = True
    result = await ask(hass, router, "write a poem")
    assert result.response.response_type is intent.IntentResponseType.ERROR
    assert "Fallback failed" in result.response.speech["plain"]["speech"]
    assert result.as_dict()["local_first"]["route"] == "fallback"
    assert result.as_dict()["local_first"]["agent_id"] == router[1].entity_id
    options = await hass.config_entries.options.async_init(router[2].entry_id)
    options = await hass.config_entries.options.async_configure(
        options["flow_id"], {"fallback_agent": router[0]}
    )
    assert options["errors"] == {"fallback_agent": "invalid_fallback"}
    await router[1].async_remove()
    result = await ask(hass, router, "write a poem")
    assert result.response.response_type is intent.IntentResponseType.ERROR
    assert len(router[1].inputs) == 1


async def test_options_reload_and_nonstreaming_destination(hass, home, router):
    """A buffered agent can return speech without touching the caller's log."""

    class BufferedAgent(conversation.ConversationEntity):
        _attr_name = "Buffered fallback"
        supported_languages = "*"

        async def async_process(self, user_input):
            response = intent.IntentResponse(user_input.language)
            response.async_set_speech("Buffered answer")
            return conversation.ConversationResult(response=response)

    buffered = BufferedAgent()
    await hass.data[conversation.DATA_COMPONENT].async_add_entities([buffered])
    options = await hass.config_entries.options.async_init(router[2].entry_id)
    result = await hass.config_entries.options.async_configure(
        options["flow_id"], {"fallback_agent": buffered.entity_id}
    )
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    answer = await ask(hass, router, "write a poem")
    assert answer.response.speech["plain"]["speech"] == "Buffered answer"
    assert not answer.continue_conversation
    log = hass.data[DATA_CHAT_LOGS][answer.conversation_id]
    assert [item.role for item in log.content] == ["system", "user", "assistant"]
    assert log.content[-1].content == "Buffered answer"
    assert not router[1].inputs


async def test_exposure_and_fallback_failure_preserve_partial_details(
    hass, home, router
):
    """Hidden targets remain hidden; a provider error retains known local execution."""
    from homeassistant.components.homeassistant.exposed_entities import (
        async_expose_entity,
    )

    async_expose_entity(hass, "conversation", "cover.bedroom_blinds", False)
    await ask(hass, router, "open the bedroom blinds")
    assert not home[1]
    assert len(router[1].inputs) == 1
    router[1].raise_error = True
    hass.states.async_set(
        "light.kitchen_strip", "unavailable", {"friendly_name": "Kitchen Strip"}
    )
    result = await ask(hass, router, "turn on the kitchen lights")
    assert result.response.response_type is intent.IntentResponseType.ERROR
    card = result.as_dict()["response"]["card"]["simple"]["content"]
    data = json.loads(card)
    assert "light.kitchen_ceiling" in {
        target["id"] for target in data["completed_targets"]
    }
    assert [target["id"] for target in data["failed_targets"]] == [
        "light.kitchen_strip"
    ]
    assert len(home[1]) == 2


async def test_local_timeout_is_uncertain_and_cancellation_propagates(
    hass, home, router, monkeypatch
):
    """Fault injection only: time out real handling while a synthetic service is in flight."""
    from custom_components.local_first_conversation import conversation as router_module

    release = asyncio.Event()
    entered = asyncio.Event()

    async def slow_service(call):
        entered.set()
        await release.wait()

    await conversation.async_prepare_intents(hass, "en")
    hass.services.async_register("cover", "open_cover", slow_service)
    monkeypatch.setattr(router_module, "LOCAL_TIMEOUT", 0.15)
    try:
        task = asyncio.create_task(ask(hass, router, "open the bedroom blinds"))
        await asyncio.wait_for(entered.wait(), 1)
        result = await task
        assert outcome(router[1])["completion"] == "uncertain"
        assert result.as_dict()["local_first"] == {
            "route": "fallback",
            "agent_id": router[1].entity_id,
            "local_outcome": "uncertain",
        }
        entered.clear()
        task = asyncio.create_task(ask(hass, router, "open the bedroom blinds"))
        await asyncio.wait_for(entered.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(router[1].inputs) == 1
    finally:
        release.set()
        await hass.async_block_till_done()


async def test_fallback_timeout_is_not_retried(hass, home, router, monkeypatch):
    """Fault injection: cancellation of a slow destination returns an honest error."""
    from custom_components.local_first_conversation import conversation as router_module

    attempts = []

    async def slow_fallback(user_input, chat_log):
        attempts.append(user_input.text)
        await asyncio.Event().wait()

    monkeypatch.setattr(router_module, "FALLBACK_TIMEOUT", 0.01)
    monkeypatch.setattr(router[1], "_async_handle_message", slow_fallback)
    result = await ask(hass, router, "write a poem")
    assert result.response.response_type is intent.IntentResponseType.ERROR
    assert "no automatic retry" in result.response.speech["plain"]["speech"]
    assert attempts == ["write a poem"]


async def test_real_assist_pipeline_triggers_stream_and_shortcut(hass, home, router):
    """Run the actual text intent pipeline, without patching core or recognizers."""
    from homeassistant.components import assist_pipeline
    from homeassistant.components.assist_pipeline.pipeline import (
        PipelineInput,
        PipelineRun,
    )

    assert await async_setup_component(hass, "assist_pipeline", {})
    pipeline = assist_pipeline.Pipeline(
        conversation_engine=router[0],
        conversation_language="en",
        language="en",
        name="Spike",
        stt_engine=None,
        stt_language=None,
        tts_engine=None,
        tts_language=None,
        tts_voice=None,
        wake_word_entity=None,
        wake_word_id=None,
        prefer_local_intents=False,
    )

    async def run(text, selected=pipeline):
        events = []
        with chat_session.async_get_chat_session(hass, context=None) as session:
            request = PipelineInput(
                intent_input=text,
                session=session,
                run=PipelineRun(
                    hass,
                    context=Context(),
                    pipeline=selected,
                    start_stage=assist_pipeline.PipelineStage.INTENT,
                    end_stage=assist_pipeline.PipelineStage.INTENT,
                    event_callback=events.append,
                ),
            )
            await request.validate()
            await request.execute()
        assert not [event for event in events if event.type == "error"], events
        return events

    triggers = []

    async def triggered(user_input, match):
        triggers.append(user_input.text)
        return "Synthetic trigger response"

    unsubscribe = conversation.get_agent_manager(hass).register_trigger(
        ["spike trigger"], triggered
    )
    try:
        events = await run("spike trigger")
        assert triggers == ["spike trigger"]
        assert not router[1].inputs
        end = next(event for event in events if event.type == "intent-end")
        assert "local_first" not in end.data["intent_output"]
        result = await ask(hass, router, "spike trigger")
        assert result.response.speech["plain"]["speech"] == "Synthetic trigger response"
        assert triggers == ["spike trigger", "spike trigger"]
        events = await run("write a poem about my kitchen lights")
        deltas = [event.data for event in events if event.type == "intent-progress"]
        assert "Fallback " in str(deltas) and "answer" in str(deltas)
        assert "Sorry" not in str(deltas)
        end = next(event for event in events if event.type == "intent-end")
        assert end.data["intent_output"]["continue_conversation"]
        assert end.data["intent_output"]["local_first"] == {
            "route": "fallback",
            "agent_id": router[1].entity_id,
            "local_outcome": "not_handled",
        }
        # The debug UI serializes intent_output in full-run Raw data.
        for text in (
            "turn on the kitchen lights",
            "is the kitchen ceiling lights on",
        ):
            events = await run(text)
            end = next(event for event in events if event.type == "intent-end")
            assert end.data["intent_output"]["local_first"] == {
                "route": "local",
                "agent_id": "conversation.home_assistant",
            }
            # Core's flag describes its shortcut, not the router's delegation.
            assert end.data["processed_locally"] is False
        assert hass.states.get("light.kitchen_ceiling").state == "on"

        before = len(home[1])
        for text in (
            "turn on the kitchen lights at 9 pm",
            "do not turn on the kitchen lights",
            "who is the founder of Home Assistant",
        ):
            events = await run(text)
            end = next(event for event in events if event.type == "intent-end")
            assert end.data["intent_output"]["local_first"] == {
                "route": "fallback",
                "agent_id": router[1].entity_id,
                "local_outcome": "not_handled",
            }
            assert router[1].inputs[-1].text == text
        assert len(home[1]) == before

        hass.states.async_set(
            "light.kitchen_strip", "unavailable", {"friendly_name": "Kitchen Strip"}
        )
        events = await run("turn on the kitchen lights")
        end = next(event for event in events if event.type == "intent-end")
        routing = end.data["intent_output"]["local_first"]
        assert routing["route"] == "fallback"
        assert routing["agent_id"] == router[1].entity_id
        assert routing["local_response_type"] == "action_done"
        assert routing["local_error_code"] is None
        assert routing["local_failed_targets"] == 1

        # Contrast the released shortcut with the router, using the same home and LLM.
        shortcut = replace(
            pipeline, conversation_engine=router[1].entity_id, prefer_local_intents=True
        )
        router[
            1
        ]._attr_supported_features = conversation.ConversationEntityFeature.CONTROL
        router[1].async_write_ha_state()
        before = len(router[1].inputs)
        await run("turn on the kichen lights", shortcut)
        await run("is the kitchen ceiling lights on", shortcut)
        assert len(router[1].inputs) == before + 2
    finally:
        unsubscribe()
