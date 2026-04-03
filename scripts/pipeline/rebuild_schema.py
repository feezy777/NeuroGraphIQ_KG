from __future__ import annotations

import argparse

from scripts.services.runtime_config import apply_runtime_env, load_runtime_config
from scripts.services.schema_service import rebuild_schema


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop and rebuild neurokg schema, then run seeds.")
    _ = parser.parse_args()

    runtime = load_runtime_config()
    apply_runtime_env(runtime)
    stats = rebuild_schema()
    print(f"schema rebuild done: tables={stats['table_count']} indexes={stats['index_count']} triggers={stats['trigger_count']}")


if __name__ == "__main__":
    main()

