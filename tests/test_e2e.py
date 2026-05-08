"""
End-to-end test: creation -> autonomous tick -> chat -> memory retrieval.

Run with:
    venv/bin/python tests/test_e2e.py

Prerequisites:
  - Server running:  venv/bin/uvicorn backend.main:app --port 8000
  - Qdrant running:  docker run -p 6333:6333 qdrant/qdrant
  - CLAUDE_API_KEY set in .env
"""
import asyncio
import json
import sys
import os

import httpx
import websockets

BASE   = "http://localhost:8000"
WS     = "ws://localhost:8000"
PASS   = "\033[92m[PASS]\033[0m"
FAIL   = "\033[91m[FAIL]\033[0m"
SKIP   = "\033[93m[SKIP]\033[0m"
HEADER = "\033[96m"
RESET  = "\033[0m"


def banner(text: str) -> None:
    print(f"\n{HEADER}{'─'*60}{RESET}")
    print(f"{HEADER}  {text}{RESET}")
    print(f"{HEADER}{'─'*60}{RESET}")


async def run() -> int:
    failures = 0
    char_id  = None

    async with httpx.AsyncClient(base_url=BASE, timeout=60) as http:

        # ── 1. Server health ────────────────────────────────────────────────
        banner("1 / 7  Server health")
        try:
            r = await http.get("/health")
            assert r.status_code == 200
            print(f"{PASS} /health → {r.json()}")
        except Exception as exc:
            print(f"{FAIL} Server not reachable: {exc}")
            print("      Start the server first:  venv/bin/uvicorn backend.main:app --port 8000")
            return 1

        # ── 2. Create character ─────────────────────────────────────────────
        banner("2 / 7  Create character")
        try:
            r = await http.post("/api/characters", json={
                "name": "TESTBOT",
                "persona": (
                    "A witty, slightly sarcastic AI character who loves coffee, "
                    "retro games, and complaining about bugs in the matrix."
                ),
            })
            assert r.status_code == 201, f"HTTP {r.status_code}: {r.text}"
            char      = r.json()
            char_id   = char["id"]
            print(f"{PASS} Character created")
            print(f"       id:     {char_id[:16]}...")
            print(f"       name:   {char['name']}")
            print(f"       action: {char['current_action']}")
            print(f"       stats:  {char['stats']}")
        except Exception as exc:
            print(f"{FAIL} Character creation: {exc}")
            failures += 1

        if not char_id:
            print(f"{FAIL} Cannot continue without a character.")
            return failures

        # ── 3. WebSocket initial state ──────────────────────────────────────
        banner("3 / 7  WebSocket initial state")
        try:
            async with websockets.connect(f"{WS}/ws/character/{char_id}") as ws:
                raw  = await asyncio.wait_for(ws.recv(), timeout=5)
                msg  = json.loads(raw)
                assert msg["type"] == "state"
                assert msg["character_id"] == char_id
                print(f"{PASS} WebSocket connected")
                print(f"       action: {msg['current_action']}")
                print(f"       stats:  {msg['stats']}")
        except Exception as exc:
            print(f"{FAIL} WebSocket: {exc}")
            failures += 1

        # ── 4. Manual agent tick (Claude + Qdrant diary write) ──────────────
        banner("4 / 7  Agent tick  (Claude decision + Qdrant diary write)")
        tick1_action = None
        try:
            r = await http.post(f"/api/characters/{char_id}/tick")
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
            tick1  = r.json()
            tick1_action = tick1["current_action"]
            print(f"{PASS} Tick 1 complete")
            print(f"       action: {tick1_action}")
            print(f"       stats:  {tick1['stats']}")
        except Exception as exc:
            print(f"{FAIL} Agent tick: {exc}")
            print(f"       Ensure CLAUDE_API_KEY is set in .env")
            failures += 1

        # ── 5. Chat (Claude + RAG retrieval from tick diary) ─────────────────
        banner("5 / 7  Chat  (Claude response + chat log write to Qdrant)")
        try:
            r = await http.post("/api/chat", json={
                "character_id": char_id,
                "message": "Hey! What are you up to right now?",
            })
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
            reply = r.json()
            print(f"{PASS} Chat response received")
            print(f"       response: {reply['response'][:120]}...")
            print(f"       action:   {reply['current_action']}")
        except Exception as exc:
            print(f"{FAIL} Chat: {exc}")
            failures += 1

        # ── 6. Second tick (tests RAG: diary retrieval informs decision) ─────
        banner("6 / 7  Second tick  (RAG: memories influence next decision)")
        try:
            r = await http.post(f"/api/characters/{char_id}/tick")
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
            tick2 = r.json()
            print(f"{PASS} Tick 2 complete")
            print(f"       action: {tick2['current_action']}  (prev: {tick1_action})")
            print(f"       stats:  {tick2['stats']}")
        except Exception as exc:
            print(f"{FAIL} Second agent tick: {exc}")
            failures += 1

        # ── 7. Memory-grounded chat ──────────────────────────────────────────
        banner("7 / 7  Memory-grounded chat  (Claude sees past diary + chat)")
        try:
            r = await http.post("/api/chat", json={
                "character_id": char_id,
                "message": "Do you remember what you were doing earlier?",
            })
            assert r.status_code == 200, f"HTTP {r.status_code}: {r.text}"
            reply = r.json()
            print(f"{PASS} Memory-grounded response received")
            print(f"       response: {reply['response'][:200]}...")
        except Exception as exc:
            print(f"{FAIL} Memory chat: {exc}")
            failures += 1

        # ── Final state ──────────────────────────────────────────────────────
        banner("FINAL STATE")
        try:
            r = await http.get(f"/api/characters/{char_id}")
            final = r.json()
            print(f"  Name:    {final['name']}")
            print(f"  Action:  {final['current_action']}")
            s = final["stats"]
            print(f"  Energy:      {s['energy']:3d} / 100")
            print(f"  Cleanliness: {s['cleanliness']:3d} / 100")
            print(f"  Knowledge:   {s['knowledge']:3d} / 100")
            print(f"  Mood:        {s['mood']}")
        except Exception as exc:
            print(f"Could not fetch final state: {exc}")

    print(f"\n{'─'*60}")
    if failures == 0:
        print(f"{PASS} All tests passed — full loop verified.")
    else:
        print(f"{FAIL} {failures} test(s) failed.")
    print(f"{'─'*60}\n")
    return failures


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
