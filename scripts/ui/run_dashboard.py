from __future__ import annotations

from scripts.ui.dashboard import create_app


def main() -> None:
    app = create_app()
    app.run(host="127.0.0.1", port=8899, debug=False)


if __name__ == "__main__":
    main()
