"""Explicit follow-up through the registered API and real HA tool execution."""

import asyncio

import pytest
from homeassistant.components import conversation
from homeassistant.components.conversation.chat_log import DATA_CHAT_LOGS
from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm
from homeassistant.setup import async_setup_component


@pytest.fixture
def scripted(hass, router, monkeypatch):
    """Choose provider output, not tool behavior; HA executes the actual tool."""
    scripts = {}

    async def handle(user_input, chat_log):
        script = scripts[user_input.text]
        await chat_log.async_provide_llm_data(
            user_input.as_llm_context("synthetic"),
            script.get("apis", "local_first_conversation"),
            user_llm_prompt="Synthetic provider",
            user_extra_system_prompt=user_input.extra_system_prompt,
        )
        if late_gate := script.get("late_gate"):

            async def late_call():
                await late_gate.wait()
                return await chat_log.llm_api.async_call_tool(
                    llm.ToolInput(tool_name="listen_for_follow_up", tool_args={})
                )

            script["late_task"] = asyncio.create_task(late_call())
        if before := script.get("before"):
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id, content=before
                )
            )
        if script.get("tool", True):
            async for result in chat_log.async_add_assistant_content(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id,
                    content=None,
                    tool_calls=[
                        llm.ToolInput(tool_name="listen_for_follow_up", tool_args={})
                    ],
                )
            ):
                assert result.result.data["follow_up_requested"]
        if entered := script.get("entered"):
            entered.set()
        if gate := script.get("gate"):
            await gate.wait()
        if script.get("error"):
            raise HomeAssistantError("Synthetic failure after tool")
        if script.get("final", True):
            chat_log.async_add_assistant_content_without_tools(
                conversation.AssistantContent(
                    agent_id=user_input.agent_id, content=script.get("answer", "")
                )
            )
        return conversation.async_get_result_from_chat_log(user_input, chat_log)

    monkeypatch.setattr(router[1], "_async_handle_message", handle)
    return scripts


async def ask(hass, router, text, conversation_id=None):
    return await conversation.async_converse(
        hass, text, conversation_id, Context(), language="en", agent_id=router[0]
    )


@pytest.mark.parametrize("answer", ["", "Ready when you are."])
async def test_tool_controls_continuation_without_changing_speech(
    hass, router, scripted, answer
):
    scripted["continue my story"] = {"answer": answer}
    result = await ask(hass, router, "continue my story")
    assert result.continue_conversation
    assert result.response.speech["plain"]["speech"] == (answer or "👂")
    log = hass.data[DATA_CHAT_LOGS][result.conversation_id]
    assert log.content[-1].content == (answer or "👂")
    cached_api = log.llm_api

    # A new turn using cached tools must not inherit the previous request.
    scripted["that is everything"] = {"tool": False}
    ended = await ask(hass, router, "that is everything", result.conversation_id)
    assert not ended.continue_conversation
    assert ended.response.speech["plain"]["speech"] == ""
    assert log.llm_api is cached_api

    # A cached API used directly cannot change a completed router turn.
    with pytest.raises(HomeAssistantError, match="No active Local First"):
        await cached_api.async_call_tool(
            llm.ToolInput(tool_name="listen_for_follow_up", tool_args={})
        )


async def test_existing_questions_and_pre_tool_speech_are_preserved(
    hass, router, scripted
):
    scripted["tell me another story"] = {"tool": False, "answer": "Which story?"}
    question = await ask(hass, router, "tell me another story")
    assert question.continue_conversation
    assert question.response.speech["plain"]["speech"] == "Which story?"

    scripted["continue my story"] = {"before": "Go ahead."}
    result = await ask(hass, router, "continue my story")
    assert result.continue_conversation
    assert result.response.speech["plain"]["speech"] == ""
    log = hass.data[DATA_CHAT_LOGS][result.conversation_id]
    assert all(
        item.content != "👂"
        for item in log.content
        if isinstance(item, conversation.AssistantContent)
    )


@pytest.mark.parametrize("marker", ["[listening]", "Listening for more"])
async def test_options_apply_custom_marker_to_response_and_history(
    hass, router, scripted, marker
):
    options = await hass.config_entries.options.async_init(router[2].entry_id)
    assert (
        options["data_schema"]({"fallback_agent": router[1].entity_id})[
            "listening_marker"
        ]
        == "👂"
    )
    saved = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {"fallback_agent": router[1].entity_id, "listening_marker": f" {marker} "},
    )
    assert saved["type"] == "create_entry"
    await hass.async_block_till_done()
    assert router[2].options["listening_marker"] == marker

    scripted["continue my story"] = {}
    result = await ask(hass, router, "continue my story")
    assert result.continue_conversation
    assert result.response.speech["plain"]["speech"] == marker
    log = hass.data[DATA_CHAT_LOGS][result.conversation_id]
    assert log.content[-1].content == marker

    scripted["say something"] = {"answer": "Your turn."}
    spoken = await ask(hass, router, "say something")
    assert spoken.response.speech["plain"]["speech"] == "Your turn."
    scripted["that is everything"] = {"tool": False}
    ended = await ask(hass, router, "that is everything")
    assert not ended.continue_conversation
    assert ended.response.speech["plain"]["speech"] == ""

    # Reopening and saving unrelated options preserves the configured string.
    options = await hass.config_entries.options.async_init(router[2].entry_id)
    assert (
        options["data_schema"]({"fallback_agent": router[1].entity_id})[
            "listening_marker"
        ]
        == marker
    )
    await hass.config_entries.options.async_configure(
        options["flow_id"], {"fallback_agent": router[1].entity_id}
    )
    await hass.async_block_till_done()
    assert router[2].options["listening_marker"] == marker


async def test_options_reject_blank_listening_marker(hass, router):
    options = await hass.config_entries.options.async_init(router[2].entry_id)
    result = await hass.config_entries.options.async_configure(
        options["flow_id"],
        {"fallback_agent": router[1].entity_id, "listening_marker": "   "},
    )
    assert result["type"] == "form"
    assert result["errors"] == {"listening_marker": "empty_marker"}
    assert not router[2].options


@pytest.mark.parametrize("failure", ["error", "missing_final", "timeout", "cancel"])
async def test_failed_and_cancelled_turns_do_not_request_a_followup(
    hass, router, scripted, monkeypatch, failure
):
    entered, gate = asyncio.Event(), asyncio.Event()
    script = scripted["continue my story"] = {"entered": entered}
    if failure == "error":
        script["error"] = True
    elif failure == "missing_final":
        script["final"] = False
    else:
        script["gate"] = gate
    if failure == "timeout":
        monkeypatch.setattr(
            "custom_components.local_first_conversation.conversation.FALLBACK_TIMEOUT",
            0.05,
        )
    task = asyncio.create_task(ask(hass, router, "continue my story"))
    await entered.wait()
    if failure == "cancel":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result.response.response_type.value == "error"
        assert not result.continue_conversation
        assert result.response.speech["plain"]["speech"] != "👂"
    scripted["that is everything"] = {"tool": False}
    ended = await ask(hass, router, "that is everything")
    assert not ended.continue_conversation


async def test_concurrent_conversations_keep_their_own_decisions(
    hass, router, scripted
):
    entered, gate = asyncio.Event(), asyncio.Event()
    scripted["continue my story"] = {"entered": entered, "gate": gate}
    listening = asyncio.create_task(ask(hass, router, "continue my story"))
    await entered.wait()
    scripted["that is everything"] = {"tool": False}
    ended = await ask(hass, router, "that is everything")
    gate.set()
    continued = await listening
    assert continued.continue_conversation
    assert continued.response.speech["plain"]["speech"] == "👂"
    assert not ended.continue_conversation
    assert ended.response.speech["plain"]["speech"] == ""
    assert continued.conversation_id != ended.conversation_id


async def test_late_tool_tasks_cannot_reuse_a_finished_turn(hass, router, scripted):
    gate = asyncio.Event()
    script = scripted["that is everything"] = {"tool": False, "late_gate": gate}
    result = await ask(hass, router, "that is everything")
    gate.set()
    with pytest.raises(HomeAssistantError, match="No active Local First"):
        await script["late_task"]
    assert not result.continue_conversation


async def test_followup_api_can_be_selected_alongside_assist(
    hass, home, router, scripted
):
    assert await async_setup_component(hass, "llm", {})
    scripted["continue my story"] = {"apis": ["assist", "local_first_conversation"]}
    result = await ask(hass, router, "continue my story")
    assert result.continue_conversation
    log = hass.data[DATA_CHAT_LOGS][result.conversation_id]
    names = {tool.name for tool in log.llm_api.tools}
    assert "listen_for_follow_up" in names
    assert len(names) > 1  # Assist's existing tools were not replaced.
