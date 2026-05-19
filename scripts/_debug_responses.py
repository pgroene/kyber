"""Dump raw model responses for the failing eval scenarios."""
import sys
sys.path.insert(0, ".")
import scripts.prompt_eval as e

e._MEMORY_ENABLED = True

FAILING = ["lights_off_werkamer", "lights_on_keuken", "tv_off_woonkamer", "all_lights_off", "morning_automation"]

for sc in [s for s in e.TEST_SCENARIOS if s["id"] in FAILING]:
    instructions = e.build_instructions(e._BASE_PROMPT, sc["user"])
    result = e.run_loop("qwen3:4b-instruct", "http://localhost:11434", instructions, no_think=True)

    sep = "=" * 64
    print(f"\n{sep}")
    print(f"SCENARIO : {sc['id']}")
    print(f"USER     : {sc['user']}")
    print(f"TOOLS    : {[t['name'] for t in result.tool_calls_made]}")
    print(f"PLAN     : {result.plan_block}")
    print(f"ROUNDS   : {result.rounds}")
    print(f"RESPONSE (first 1000):\n{result.final_response[:1000]}")
