import importlib
import importlib.util
import os
import sys
import time
from datetime import datetime
from typing import Annotated, Optional, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from agent.config import MLX_MODEL, MLX_BASE_URL
from agent.core.prompts import get_system_prompt
from agent.core.registry import load_skills
from agent.memory.context_store import search_context_dumps
from agent.integrations.apple_calendar import fetch_all_events, request_permissions


# ---------------------------------------------------------------------------
# State Definition
# ---------------------------------------------------------------------------

class State(TypedDict):
    messages: Annotated[list, add_messages]
    pending_action_id: Optional[str]   # set by call_tools when a write tool fires


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_trace_id(trace_id: str) -> None:
    """Set _current_trace_id on write-skill execute modules so pending actions
    are linked to the current conversation trace."""
    skills_root = os.path.join(os.path.dirname(__file__), "skills")
    for skill_dir in ("store_context", "create_event", "move_event"):
        exec_path = os.path.join(skills_root, skill_dir, "execute.py")
        mod_name = f"skill_{skill_dir}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, exec_path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mod._current_trace_id = trace_id
            sys.modules[mod_name] = mod
        except Exception as ex:
            print(f"  [graph] WARNING: could not inject trace_id into {skill_dir}: {ex}")


# ---------------------------------------------------------------------------
# Graph Construction
# ---------------------------------------------------------------------------

def build_agent(
    trace_id: str | None = None,
    tool_names: list[str] | None = None,
    think: bool = False,
):
    """Build the LangGraph state machine.

    Args:
        trace_id: Forwarded to write skills so every pending action is linked
                  to the current conversation.
        tool_names: Subset of tool names to bind (from intent router).
                    None means bind all tools. Empty list means no tools.
        think: Whether to enable reasoning mode (Qwen 3 thinking).
    """
    if trace_id:
        _inject_trace_id(trace_id)

    llm = ChatOpenAI(
        base_url=MLX_BASE_URL,
        api_key="not-needed",
        model=MLX_MODEL,
        temperature=0.1,
    )

    # Bind tools: None = all tools, [] = no tools, [...] = specific subset
    all_tools = load_skills()
    if tool_names is None:
        selected = all_tools
    elif len(tool_names) == 0:
        selected = []
    else:
        tool_map = {t.name: t for t in all_tools}
        selected = [tool_map[n] for n in tool_names if n in tool_map]

    if selected:
        llm = llm.bind_tools(selected)

    print(f"  [graph] tools={[t.name for t in selected]} think={think}")

    def call_model(state: State):
        print("  [graph] -> node: agent (thinking...)")
        t0 = time.perf_counter()
        response = llm.invoke(state["messages"])
        ms = int((time.perf_counter() - t0) * 1000)

        # MLX/OpenAI may return content as list of dicts instead of string
        if isinstance(response.content, list):
            text_parts = [
                c["text"] if isinstance(c, dict) and "text" in c else str(c)
                for c in response.content
            ]
            response.content = "".join(text_parts)

        # Strip <think> tags if model leaks them
        if response.content and "<think>" in response.content:
            import re
            response.content = re.sub(
                r"<think>.*?</think>", "", response.content, flags=re.DOTALL
            ).strip()

        reasoning = response.additional_kwargs.get("reasoning_content", "")
        r_len = len(reasoning) if reasoning else 0
        c_len = len(response.content) if response.content else 0
        print(f"  [graph]    llm call: {ms}ms (reasoning: {r_len} chars, content: {c_len} chars)")
        return {"messages": [response]}

    def call_tools(state: State):
        last_message = state["messages"][-1]
        tools_dict = {t.name: t for t in load_skills()}
        results = []
        detected_pending_id: Optional[str] = None

        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"  [graph] -> node: tools (executing {tool_name} with {tool_args})")

            t0 = time.perf_counter()
            if tool_name in tools_dict:
                try:
                    result = tools_dict[tool_name].invoke(tool_args)
                except Exception as e:
                    result = f"Error: {str(e)}"
            else:
                result = f"Tool {tool_name} not found."
            tool_ms = int((time.perf_counter() - t0) * 1000)
            print(f"  [graph]    tool {tool_name}: {tool_ms}ms")

            result_str = str(result)

            # Detect pending-action signal from write tools
            if result_str.startswith("PENDING_ACTION:"):
                parts = result_str.split("|", 1)
                detected_pending_id = parts[0].replace("PENDING_ACTION:", "").strip()
                display = parts[1].strip() if len(parts) > 1 else result_str
                results.append(ToolMessage(
                    content=(
                        f"NOT WRITTEN YET -- waiting for user to tap Confirm button: {display}. "
                        f"Tell the user the action is queued and they need to confirm it."
                    ),
                    name=tool_name,
                    tool_call_id=tool_call["id"],
                ))
            else:
                results.append(ToolMessage(
                    content=result_str,
                    name=tool_name,
                    tool_call_id=tool_call["id"],
                ))

        update: dict = {"messages": results}
        if detected_pending_id:
            update["pending_action_id"] = detected_pending_id
        return update

    def should_continue(state: State):
        # Safety cap: prevent infinite tool-call loops (max 10 iterations)
        tool_call_count = sum(
            1 for m in state["messages"]
            if hasattr(m, "tool_calls") and m.tool_calls
        )
        if tool_call_count >= 10:
            print("  [graph] WARNING: hit 10-iteration cap, forcing END")
            return END
        if state["messages"][-1].tool_calls:
            return "tools"
        return END

    workflow = StateGraph(State)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", call_tools)
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, ["tools", END])
    workflow.add_edge("tools", "agent")
    return workflow.compile()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def chat_with_llm(
    user_message: str,
    recent_context: list,
    trace_id: str | None = None,
) -> tuple[str, int, str | None]:
    """Entry point for telegram_handler.

    Returns:
        (response_text, latency_ms, pending_action_id)
        pending_action_id is non-None when a write tool was called and
        is awaiting user confirmation via Telegram inline buttons.
    """
    from agent.core.intent_router import classify

    t0 = time.perf_counter()
    intent = classify(user_message)
    router_ms = int((time.perf_counter() - t0) * 1000)
    print(f"  [router] intent={intent} ({router_ms}ms)")

    graph = build_agent(
        trace_id=trace_id,
        tool_names=intent["tools"],
        think=intent["think"],
    )

    sys_content = get_system_prompt()
    sys_content += f"\n\nCurrent time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"

    # Inject relevant stored memories via FTS5 search
    t0 = time.perf_counter()
    memories = search_context_dumps(user_message, limit=3)
    fts_ms = int((time.perf_counter() - t0) * 1000)
    if memories:
        sys_content += "\n\n--- THINGS THE USER PREVIOUSLY TOLD YOU (use these to answer) ---"
        for m in memories:
            sys_content += f"\n- {m['content']} ({m['created_at']})"
        sys_content += "\n--- END MEMORIES ---"
    print(f"  [fts5] {len(memories)} memories ({fts_ms}ms)")

    messages = [SystemMessage(content=sys_content)]
    for msg in recent_context:
        role = msg["role"] if isinstance(msg, dict) else msg[0]
        content = msg["content"] if isinstance(msg, dict) else msg[1]
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            messages.append(AIMessage(content=content))
    messages.append(HumanMessage(content=user_message))

    start_time = datetime.now()
    result = graph.invoke({"messages": messages, "pending_action_id": None})

    final_message = result["messages"][-1].content or ""

    # Retry once if LLM returned empty (e.g. after tool call it forgot to respond)
    if not final_message.strip():
        print("  [graph] WARNING: empty response, retrying...")
        result = graph.invoke({"messages": result["messages"], "pending_action_id": result.get("pending_action_id")})
        final_message = result["messages"][-1].content or ""

    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    # Final safety strip for any remaining <think> tags
    if final_message and "<think>" in final_message:
        import re
        final_message = re.sub(
            r"<think>.*?</think>", "", final_message, flags=re.DOTALL
        ).strip()
    pending_id = result.get("pending_action_id")
    return final_message, latency_ms, pending_id


# ---------------------------------------------------------------------------
# Dev / standalone test
# ---------------------------------------------------------------------------

def test_chat(graph, user_message: str):
    """Run a test message through the graph."""
    print(f"\nUser: {user_message}")

    sys_content = get_system_prompt()
    sys_content += f"\n\nCurrent time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"

    messages = [
        SystemMessage(content=sys_content),
        HumanMessage(content=user_message),
    ]

    start_time = datetime.now()
    result = graph.invoke({"messages": messages, "pending_action_id": None})
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    final_message = result["messages"][-1].content
    print(f"\nAgent ({latency_ms}ms): {final_message}\n")


if __name__ == "__main__":
    print("Initializing EventKit...")
    request_permissions()
    fetch_all_events()  # Warm up the daemon cache

    print("Compiling LangGraph...")
    graph = build_agent()

    test_chat(graph, "Hi! Just testing to see if you work.")
    test_chat(graph, "What is on my schedule for today?")
    test_chat(graph, "Do I have any reminders pending?")
