import chainlit as cl
import dotenv
import os
import asyncio

from openai.types.responses import ResponseTextDeltaEvent

from agents import Runner, SQLiteSession
#from nutrition_agent import nutrition_agent
#from nutrition_agent_v5 import nutrition_agent
#exa search is kell
from nutrition_agent_v5 import exa_search_mcp,nutrition_agent
#hát még ezek is kellenek:
from agents import InputGuardrailTripwireTriggered, Runner, SQLiteSession
#from nutrition_agent import exa_search_mcp, nutrition_agent
#from openai.types.responses import ResponseTextDeltaEvent

dotenv.load_dotenv()

_mcp_lock = asyncio.Lock()

async def ensure_mcp_connected():
    # Per-user-session flag so we don't reconnect every message
    if cl.user_session.get("mcp_connected"):
        return

    async with _mcp_lock:
        # Double-check after acquiring lock
        if cl.user_session.get("mcp_connected"):
            return

        # Connect exactly what the agent will enumerate
        for server in nutrition_agent.mcp_servers:
            await server.connect()

        cl.user_session.set("mcp_connected", True)

@cl.on_chat_start
async def on_chat_start():
    
      
    session = SQLiteSession("conversation_history")
    cl.user_session.set("agent_session", session)
        # This is the only change in this file compared to the chatbot/agentic_chatbot.py file
    #vagy ez, de nem ment :(  ... nem volt exa_search_mcp definiálva
    #await exa_search_mcp.connect()
    # vagy ez
    #for server in nutrition_agent.mcp_servers:
    #    await server.connect()
    # vagy ez:
    await ensure_mcp_connected()
    print("MCP servers on agent:", [repr(s) for s in nutrition_agent.mcp_servers])

def _describe_server(s):
    flags = {}
    for k in ("initialized", "_initialized", "is_initialized", "_is_initialized", "connected", "_connected"):
        if hasattr(s, k):
            flags[k] = getattr(s, k)
    return f"{type(s).__name__} id={id(s)} flags={flags}"


@cl.on_message
async def on_message(message: cl.Message):

    # DEBUG: show what the agent thinks its MCP servers are
    print("Agent MCP servers:", [_describe_server(s) for s in nutrition_agent.mcp_servers])
    print("MCP servers:", [(type(s).__name__, id(s)) for s in nutrition_agent.mcp_servers])


    # Ensure connected (see section 2 for exact code)
    await ensure_mcp_connected()
    print("After connect:", [_describe_server(s) for s in nutrition_agent.mcp_servers])
    session = cl.user_session.get("agent_session")

    msg = cl.Message(content="")
    await msg.send()

    try:
      result = Runner.run_streamed(nutrition_agent, message.content, session=session)
      #msg = cl.Message(content="")

      async for event in result.stream_events():
        # Stream final message text to screen
        if event.type == "raw_response_event" and isinstance(
            event.data, ResponseTextDeltaEvent
        ):
            await msg.stream_token(token=event.data.delta)

        elif (
            event.type == "raw_response_event"
            and hasattr(event.data, "item")
            and hasattr(event.data.item, "type")
            and event.data.item.type == "function_call"
            and len(event.data.item.arguments) > 0
        ):
            with cl.Step(name=f"{event.data.item.name}", type="tool") as step:
                step.input = event.data.item.arguments

      await msg.update()

    except InputGuardrailTripwireTriggered as e:
        # Do not crash the app; show an explanation to the user.
        # If the exception exposes more fields in your SDK version, you can log them here.
        msg.content = (
            "Your message was blocked by the input safety/guardrail policy configured for this agent. "
            "Please rephrase and try again."
        )
        await msg.update()
        return

    except Exception as e:
        # Catch-all so the UI doesn't hard-fail.
        msg.content = f"Unexpected error: {type(e).__name__}: {e}"
        await msg.update()
        raise  # keep traceback in server logs for debugging


@cl.password_auth_callback
def auth_callback(username: str, password: str):
    if (username, password) == (
        os.getenv("CHAINLIT_USERNAME"),
        os.getenv("CHAINLIT_PASSWORD"),
    ):
        return cl.User(
            identifier="Student",
            metadata={"role": "student", "provider": "credentials"},
        )
    else:
        return None