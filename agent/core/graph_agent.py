import os
from datetime import datetime
from typing import Annotated, TypedDict

from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_ollama import ChatOllama

from agent.config import OLLAMA_MODEL
from agent.core.prompts import get_system_prompt
from agent.core.registry import load_skills
from agent.integrations.apple_calendar import request_permissions, fetch_all_events

# 1. State Definition
class State(TypedDict):
    messages: Annotated[list, add_messages]

def build_agent():
    """Build the LangGraph state machine."""
    llm = ChatOllama(model=OLLAMA_MODEL, temperature=0.1)
    tools = load_skills()
    if tools:
        llm = llm.bind_tools(tools)
        
    def call_model(state: State):
        print("  [graph] -> node: agent (thinking...)")
        messages = state["messages"]
        response = llm.invoke(messages)
        return {"messages": [response]}
        
    def call_tools(state: State):
        messages = state["messages"]
        last_message = messages[-1]
        
        tools_dict = {t.name: t for t in load_skills()}
        results = []
        
        for tool_call in last_message.tool_calls:
            tool_name = tool_call["name"]
            tool_args = tool_call["args"]
            print(f"  [graph] -> node: tools (executing {tool_name} with {tool_args})")
            
            if tool_name in tools_dict:
                tool = tools_dict[tool_name]
                try:
                    result = tool.invoke(tool_args)
                except Exception as e:
                    result = f"Error: {str(e)}"
            else:
                result = f"Tool {tool_name} not found."
                
            results.append(ToolMessage(
                content=str(result),
                name=tool_name,
                tool_call_id=tool_call["id"]
            ))
            
        return {"messages": results}
        
    def should_continue(state: State):
        last_message = state["messages"][-1]
        if last_message.tool_calls:
            return "tools"
        return END

    # Build Graph
    workflow = StateGraph(State)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", call_tools)
    
    workflow.add_edge(START, "agent")
    workflow.add_conditional_edges("agent", should_continue, ["tools", END])
    workflow.add_edge("tools", "agent")
    
    return workflow.compile()

def chat_with_llm(user_message: str, recent_context: list, calendar_context: str = ""):
    """Entry point for telegram_handler to talk to the LangGraph agent."""
    graph = build_agent()
    
    sys_content = get_system_prompt()
    sys_content += f"\n\nCurrent time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"
    if calendar_context:
        sys_content += f"\n\n--- CALENDAR DATA (use this if the user asked about schedule) ---\n{calendar_context}\n---"
    
    messages = [SystemMessage(content=sys_content)]
    
    for msg in recent_context:
        # Expected tuple format from SQLite fetchall: (role, content, timestamp)
        # However, let's handle dicts or tuples
        role = msg["role"] if isinstance(msg, dict) else msg[0]
        content = msg["content"] if isinstance(msg, dict) else msg[1]
        
        if role == "user":
            messages.append(HumanMessage(content=content))
        else:
            # For assistant messages we ideally use AIMessage, but a standard tool-less one
            from langchain_core.messages import AIMessage
            messages.append(AIMessage(content=content))
            
    messages.append(HumanMessage(content=user_message))
    
    start_time = datetime.now()
    result = graph.invoke({"messages": messages})
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    
    final_message = result["messages"][-1].content
    return final_message, latency_ms

def test_chat(graph, user_message: str):
    """Run a test message through the graph."""
    print(f"\nUser: {user_message}")
    
    sys_content = get_system_prompt()
    sys_content += f"\n\nCurrent time: {datetime.now().strftime('%A, %B %d, %Y at %I:%M %p')}"
    
    messages = [
        SystemMessage(content=sys_content),
        HumanMessage(content=user_message)
    ]
    
    start_time = datetime.now()
    result = graph.invoke({"messages": messages})
    latency_ms = int((datetime.now() - start_time).total_seconds() * 1000)
    
    final_message = result["messages"][-1].content
    print(f"\nAgent ({latency_ms}ms): {final_message}\n")

if __name__ == "__main__":
    print("Initializing EventKit...")
    request_permissions()
    fetch_all_events() # Warm up the daemon cache
    
    print("Compiling LangGraph...")
    graph = build_agent()
    
    test_chat(graph, "Hi! Just testing to see if you work.")
    test_chat(graph, "What is on my schedule for today?")
    test_chat(graph, "Do I have any reminders pending?")
