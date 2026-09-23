"""One isolated, cancellable turn using the pinned DimOS McpClient agent.

JSON-lines IPC replaces HTTP MCP transport inside this private subprocess. No
robot credentials, filesystem tools, shell tools, or public MCP port are exposed.
"""

import json
import os
import sys
import threading


def main():
    wire_in, wire_out = sys.stdin, sys.stdout
    # Upstream pretty-printing must never write prompts or images into app logs
    # or corrupt the protocol. Only explicitly serialized events leave stdout.
    sink = open(os.devnull, "w")
    sys.stdout = sys.stderr = sink

    def emit(value):
        wire_out.write(json.dumps(value) + "\n")
        wire_out.flush()

    request = json.loads(wire_in.readline())
    try:
        from dimos.agents.mcp.mcp_client import McpClient
        from dimos.protocol.rpc.spec import RPCSpec
        from langchain.agents import create_agent
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import HumanMessage, messages_from_dict, messages_to_dict

        class Output:
            def publish(self, message):
                # Keep images out of the transcript and IPC results.
                if hasattr(message, "type"):
                    content = message.content
                    text = (
                        content
                        if isinstance(content, str)
                        else "\n".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    )
                    emit(
                        {
                            "event": "message",
                            "role": message.type,
                            "text": text,
                            "calls": [
                                {"name": c["name"], "args": c.get("args", {})}
                                for c in getattr(message, "tool_calls", [])
                            ],
                        }
                    )

        tool_lock = threading.Lock()

        class StudioMcpClient(McpClient):
            def _mcp_request(self, method, params=None):
                # LangGraph may dispatch independent tools concurrently. Keep
                # each IPC request paired with its own response.
                with tool_lock:
                    return self._private_request(method, params)

            def _private_request(self, method, params=None):
                if method == "initialize":
                    return {"capabilities": {"tools": {}}}
                if method == "tools/list":
                    return {"tools": request["tools"]}
                if method == "tools/call":
                    emit(
                        {
                            "event": "tool",
                            "name": params["name"],
                            "arguments": params.get("arguments", {}),
                        }
                    )
                    response = wire_in.readline()
                    if not response:
                        raise RuntimeError("Parent disconnected")
                    return json.loads(response)
                raise ValueError("Unsupported private MCP operation")

            def _rebuild_agent(self):
                cfg = request["config"]
                kwargs = {"timeout": 40, "max_retries": 0, "max_tokens": 2048}
                if cfg["provider"] != "ollama":
                    kwargs["api_key"] = cfg["api_key"]
                else:
                    kwargs = {"client_kwargs": {"timeout": 40}, "num_predict": 2048}
                if cfg["base_url"]:
                    kwargs["base_url"] = cfg["base_url"]
                if cfg["provider"] == "openai":
                    kwargs["store"] = False
                model = init_chat_model(
                    model=cfg["model"], model_provider=cfg["provider"], **kwargs
                )
                self._state_graph = create_agent(
                    model=model, tools=self._agent_tools, system_prompt=request["prompt"]
                )

        class PrivateRPC(RPCSpec):
            def __init__(self, **kwargs):
                pass

            def serve_module_rpc(self, module, name=None):
                pass  # No externally callable RPC methods in this worker.

            def call(self, *args, **kwargs):
                raise RuntimeError("External RPC is disabled in the HumanCLI worker")

        agent = StudioMcpClient(rpc_transport=PrivateRPC)
        agent.agent = Output()
        agent.agent_idle = type("Idle", (), {"publish": lambda self, value: None})()
        agent._agent_tools = agent._fetch_tools(timeout=1)
        agent._rebuild_agent()
        agent._history = messages_from_dict(request.get("history", []))
        # Cap each graph run, in addition to the parent process deadline/tool cap.
        graph = agent._state_graph.with_config({"recursion_limit": 18})
        agent._process_message(graph, HumanMessage(content=request["text"]))
        # DimOS feeds image tool results back as follow-up HumanMessages.
        for _ in range(3):
            if agent._message_queue.empty():
                break
            agent._process_message(graph, agent._message_queue.get_nowait())
        history = messages_to_dict(agent._history)
        for message in history:
            if isinstance(message["data"].get("content"), list):
                message["data"]["content"] = [
                    b for b in message["data"]["content"] if b.get("type") == "text"
                ] or "[Image omitted from previous turn]"
        emit({"event": "done", "history": history})
        agent.stop()
    except Exception as error:
        # Provider errors can embed keys, signed URLs, images or prompt contents.
        kind = type(error).__name__
        emit(
            {
                "event": "error",
                "text": "HumanCLI could not complete the request. Check the provider, model, credentials and tool/vision support.",
                "kind": kind
                if kind
                in {
                    "ImportError",
                    "ModuleNotFoundError",
                    "AuthenticationError",
                    "RateLimitError",
                    "GraphRecursionError",
                }
                else "AgentError",
            }
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
