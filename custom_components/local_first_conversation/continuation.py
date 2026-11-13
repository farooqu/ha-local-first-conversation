"""Optional follow-up API for turns routed through Local First Conversation."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

from . import DOMAIN


@dataclass
class ContinuationTurn:
    """Shared by the delegating task and its tool tasks, never cached by an API."""

    requested: bool = False
    active: bool = True


_current_turn: ContextVar[ContinuationTurn | None] = ContextVar(
    "local_first_continuation_turn", default=None
)


@contextmanager
def continuation_turn():
    """Isolate each fallback turn, including cancellation and late tool calls."""
    turn = ContinuationTurn()
    token = _current_turn.set(turn)
    try:
        yield turn
    finally:
        turn.active = False
        _current_turn.reset(token)


class ListenForFollowUp(llm.Tool):
    """Request one more user turn without putting control text in model output."""

    name = "listen_for_follow_up"
    description = (
        "Keep listening for another user turn in an ongoing conversation, without "
        "requiring a spoken follow-up question. Use when the user has more to add "
        "or you are waiting for their next part; not for a completed standalone command. "
        "This requests one follow-up, not continuous listening. If your completed "
        "assistant response has no text, Local First supplies a listening indicator "
        "and a compatible TTS provider supplies a listening cue. Any response text "
        "is spoken normally."
    )
    integration = DOMAIN
    annotations = llm.ToolAnnotations(
        destructive=False, idempotent=True, open_world=False
    )

    async def async_call(self, hass, tool_input, llm_context):
        turn = _current_turn.get()
        if turn is None or not turn.active:
            raise HomeAssistantError(
                "No active Local First Conversation fallback turn; use the Local First agent."
            )
        turn.requested = True
        return llm.ToolResult(
            data={
                "follow_up_requested": True,
                "message": "One follow-up requested. A spoken question or acknowledgment is not required.",
            }
        )


class ContinuationAPI(llm.API):
    """Selectable alongside Assist, without replacing its home-control tools."""

    def __init__(self, hass: HomeAssistant):
        super().__init__(
            hass=hass, id=DOMAIN, name="Local First Conversation follow-up"
        )

    async def async_get_api_instance(self, llm_context):
        return llm.APIInstance(
            api=self,
            api_prompt="",
            llm_context=llm_context,
            tools=[ListenForFollowUp()],
        )
