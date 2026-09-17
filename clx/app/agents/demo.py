import time
from typing import ClassVar

from django.utils import timezone
from pydantic import Field

from clx.app.agents.base import Agent, AgentState, Tool, ToolOutput
from clx.app.models import DemoChatThread

CALL_CARD_DELAY_SECONDS = 2
MOCK_TEMP_F = 72


class WeatherState(AgentState):
    """Per-thread state the weather agent accumulates."""

    recent_locations: list[str] = []


class CheckWeather(Tool):
    """Check the current weather for a location."""

    name = "check_weather"
    tool_call_template = "cotton/demos/chat/tools/check_weather_call.html"
    tool_result_template = "cotton/demos/chat/tools/check_weather_result.html"

    location: str = Field(description="City or place to check the weather for")

    def __call__(self, *, thread_id: str) -> ToolOutput:
        from clx.app.services.demo import demo_chat_thread_state_update

        time.sleep(CALL_CARD_DELAY_SECONDS)

        thread = DemoChatThread.objects.get(id=thread_id)
        state = WeatherState.model_validate(thread.state or {})
        if self.location not in state.recent_locations:
            state.recent_locations.append(self.location)
            demo_chat_thread_state_update(
                thread_id=thread_id, state=state.model_dump()
            )

        return ToolOutput(
            result=f"It is {MOCK_TEMP_F} degrees in {self.location}.",
            render_data={"location": self.location, "temp_f": MOCK_TEMP_F},
            refresh_system_prompt=True,
        )


class DemoAgent(Agent):
    """Demo agent that reports the weather with a mock tool."""

    name = "demo"
    model = "openai/gpt-5.6-luna"
    state_template = "cotton/demos/chat/state/weather.html"
    tools: ClassVar[list[type[Tool]]] = [CheckWeather]

    def get_system_prompt(self, thread: DemoChatThread) -> str:
        state = WeatherState.model_validate(thread.state or {})
        now = timezone.localtime().strftime("%A, %B %-d, %Y at %-I:%M %p")
        locations = ", ".join(state.recent_locations) or "none yet"
        return (
            "You are a cheerful weather assistant. Answer questions about "
            "the weather by calling the check_weather tool, and keep "
            "replies to a sentence or two of markdown. "
            f"The current time is {now}. Locations checked so far in this "
            f"conversation: {locations}."
        )
