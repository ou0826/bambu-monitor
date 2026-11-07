"""用真实抓包数据回放，检查 Watcher 判定是否正确。

用法: python -m tests.replay_capture D:\\path\\to\\_capture.jsonl
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _s in (sys.stdout, sys.stderr):
    try:
        if _s is not None and hasattr(_s, "reconfigure"):
            _s.reconfigure(errors="replace")
    except Exception:
        pass

from bambu_monitor.state import Watcher  # noqa: E402


def main(path: str) -> int:
    w = Watcher()
    total = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        total += 1
        for ev in w.feed(rec.get("d") or {}):
            print(f"{rec.get('t')}  [{ev.level}] {ev.title} | {ev.body}"
                  f"{'  (需处理)' if ev.need_action else ''}")
    s = w.summary()
    print("-" * 70)
    print(f"回放 {total} 帧，最终状态={s['state_text']} 进度={s['percent']}% "
          f"阶段={s['stage_text']} 文件={s['file']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "_capture.jsonl"))
