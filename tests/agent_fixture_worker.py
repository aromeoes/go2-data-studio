"""Deterministic model only; exercises the real DimOS MCP/LangGraph agent loop."""

import time

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
import langchain.chat_models


class FixtureModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "studio-test-model"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, ToolMessage):
            message = AIMessage(content="The tool returned: " + last.content)
        elif isinstance(last.content, list):
            message = AIMessage(content="A test doorway is visible.")
        elif "delayed" in last.content:
            time.sleep(2)
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "id": "test-call",
                        "name": "move_relative",
                        "args": {"direction": "backward", "distance_m": 1},
                    }
                ],
            )
        elif "camera" in last.content:
            message = AIMessage(
                content="", tool_calls=[{"id": "test-call", "name": "camera_view", "args": {}}]
            )
        elif "error" in last.content:
            raise RuntimeError("sk-test-private-key-must-not-leak")
        else:
            name, args = (
                ("move_relative", {"direction": "backward", "distance_m": 1})
                if "back" in last.content
                else ("robot_status", {})
            )
            message = AIMessage(
                content="", tool_calls=[{"id": "test-call", "name": name, "args": args}]
            )
        return ChatResult(generations=[ChatGeneration(message=message)])


langchain.chat_models.init_chat_model = lambda **kwargs: FixtureModel()
from go2_setup.agent_worker import main  # noqa: E402

raise SystemExit(main())
