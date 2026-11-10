"""
BOILERPLATE: Dialog-RSN-1 plumbing, the same for any agent. No need to edit it to build one.

PolyAI's Dialog-RSN-1, over its realtime WebSocket API.

This file is only the protocol: what goes over the wire and what comes back.
What Raven does with each event lives in conversation_runtime/session.py.

The conversation is one long-lived WebSocket. Both sides send JSON events:

  We send                              Dialog-RSN-1 sends
  ---------------------------------    ------------------------------------------
  session.update (instructions,        session.created / session.updated
    tools, audio format, knowledge)
  input_audio_buffer.append            input_audio_buffer.speech_started / _stopped
    (mic audio, 16-bit 16 kHz)           (it hears you start and finish a turn)
  conversation.item.create             conversation.item.input_audio_transcription
    (typed text, tool results,             .completed (what it heard you say)
     system messages)                  response.created
                                       response.output_item.added (a tool call is coming)
  response.create                      response.output_text.delta / .done (its reply)
  poly.output_audio.started / .delta   response.function_call_arguments.done (a tool call)
    / .stopped (how much of a reply    response.done (status; poly_cited_topics,
    the person actually heard)           poly_out_of_domain)
  session.update {} (keepalive)

The ordering rules that keep a session healthy are listed at the top of
conversation_runtime/session.py.

Docs: https://docs.poly.ai/dialog-rsn-1 (it speaks the OpenAI Realtime protocol,
plus PolyAI's poly_* extensions).
"""
import asyncio
import base64
import json
import time

import websockets
from websockets.exceptions import InvalidStatus


class DialogError(RuntimeError):
    pass


class DialogRSN1:
    KEEPALIVE_AFTER_S = 240  # the server closes a connection that's idle for 300 s

    def __init__(self, url, api_key):
        self.url = url
        self.api_key = api_key
        self.ws = None
        self.loop = None
        self.last_sent = time.monotonic()
        self.keepalive = None

    async def connect(self, instructions, tools, knowledge, input_rate):
        """Open the connection and set up the session."""
        try:
            self.ws = await websockets.connect(self.url, additional_headers={"X-API-KEY": self.api_key})
        except InvalidStatus as error:
            raise DialogError(f"connection refused (HTTP {error.response.status_code}). Check "
                              "POLY_API_KEY, and POLY_URL if your workspace is regional.") from None
        self.loop = asyncio.get_running_loop()
        await self.ws.recv()  # session.created
        session = {
            "instructions": instructions,
            "output_modalities": ["text"],  # text out; ElevenLabs does the voice
            "tools": tools,
            "audio": {"input": {
                "format": {"type": "audio/pcm", "rate": input_rate},
                # Dialog-RSN-1 decides when you've finished, then replies by itself
                "turn_detection": {"type": "server_vad", "create_response": True},
            }},
        }
        if knowledge:
            session["poly_knowledge"] = knowledge  # topics: [{"name": ..., "content": ...}]
        await self.send({"type": "session.update", "session": session})
        updated = json.loads(await self.ws.recv())
        if updated["type"] != "session.updated":
            # A refused update applies nothing, so the session would run on defaults
            raise DialogError(f"session setup refused: {updated.get('error', updated)}")
        self.keepalive = asyncio.create_task(self._keep_alive())

    async def events(self):
        """Every event Dialog-RSN-1 sends, as a dict."""
        async for raw in self.ws:
            yield json.loads(raw)

    async def send(self, event):
        self.last_sent = time.monotonic()
        await self.ws.send(json.dumps(event))

    async def send_audio(self, pcm16):
        await self.send({"type": "input_audio_buffer.append",
                         "audio": base64.b64encode(pcm16).decode()})

    async def create_response(self):
        """Ask the model to reply now. Only one may be waiting at a time."""
        await self.send({"type": "response.create"})

    async def say(self, text):
        """A typed turn from the person (instead of speaking), then a reply."""
        await self.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
        await self.send({"type": "response.create"})

    async def tool_output(self, call_id, output):
        """Answer one tool call. Send all of a reply's outputs, then create_response() once."""
        await self.send({"type": "conversation.item.create", "item": {
            "type": "function_call_output", "call_id": call_id, "output": json.dumps(output)}})

    async def system_message(self, text):
        """Tell the model something mid-conversation (not from the person), and let it respond."""
        await self.send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "system", "content": [{"type": "input_text", "text": text}]}})
        await self.send({"type": "response.create"})

    def report_playback(self, event):
        """Send a poly.output_audio.* report from any thread."""
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send(event), self.loop)

    async def _keep_alive(self):
        """An empty session.update changes nothing and stops the server closing an idle line."""
        while True:
            await asyncio.sleep(min(30, self.KEEPALIVE_AFTER_S))
            if time.monotonic() - self.last_sent >= self.KEEPALIVE_AFTER_S:
                await self.send({"type": "session.update", "session": {}})

    async def close(self):
        if self.keepalive:
            self.keepalive.cancel()
        if self.ws:
            await self.ws.close()
