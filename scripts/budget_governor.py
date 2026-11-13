#!/usr/bin/env python3
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(__file__).resolve().parent.parent / "PROJECT_STATE.json"

def main():
    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    policy = state["budget_policy"]
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    weekday_name = datetime.now(timezone.utc).strftime("%A")

    is_burn_day = (weekday_name.lower() == policy["burn_day_weekday"].lower())
    max_tasks = policy["burn_day_max_tasks"] if is_burn_day else policy["daily_cruise_max_tasks"]
    done_today = policy["history"].get(today_str, 0)

    if "--record-task" in sys.argv:
        policy["history"][today_str] = done_today + 1
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[GOVERNOR] WorkPackage registrado em {today_str} ({done_today + 1}/{max_tasks}).")
        return

    mode = "BURN_MODE (Véspera da Renovação - Carga Total!)" if is_burn_day else "CRUISE_MODE (Meta Diária ~5%)"
    remaining = max(0, max_tasks - done_today)
    print(f"[GOVERNOR] Data UTC: {today_str} ({weekday_name}) | Modo: {mode}")
    print(f"[GOVERNOR] WorkPackages concluídos hoje: {done_today}/{max_tasks} | Restantes hoje: {remaining}")

    if remaining <= 0:
        print("[GOVERNOR] STOP: Limite diário atingido. Encerre a sessão do agente imediatamente.")
        sys.exit(2)
    sys.exit(0)

if __name__ == "__main__":
    main()
