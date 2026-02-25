from shiny import run_app

if __name__ == "__main__":
    run_app(
        "app:app",
        host="127.0.0.1",
        port=8009,
        reload=False,
        ws_ping_interval=30,  # send ping every 30 s
        ws_ping_timeout=120,  # wait up to 2 min for pong (handles throttled tabs)
    )
