from shiny import App, run_app

from layout import app_ui
from server import server

app = App(app_ui, server)

if __name__ == "__main__":
    run_app(
        app,
        host="127.0.0.1",
        port=8009,
        reload=False,
        ws_ping_interval=10,  # send ping every 10 s
        ws_ping_timeout=300,  # wait up to 5 min for pong (handles throttled/backgrounded tabs)
    )
