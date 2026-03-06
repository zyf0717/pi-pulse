import plotly.graph_objects as go
import shinyswatch
from shiny import reactive

from app.ingest import GLOBAL_INGEST, ensure_global_ingest_started
from app.renders.h10 import register_h10_renders
from app.renders.pulse import register_pulse_renders
from app.renders.sen66 import register_sen66_renders


def server(input, output, session):
    shinyswatch.theme_picker_server()
    ensure_global_ingest_started()

    @reactive.calc
    def plotly_tpl() -> str:
        return input.chart_style()

    pulse_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    pulse_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_pulse_renders(
        input,
        GLOBAL_INGEST.pulse_latest,
        GLOBAL_INGEST.pulse_temp_history,
        plotly_tpl,
        pulse_widget,
        pulse_state,
    )

    sen66_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    sen66_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_sen66_renders(
        input,
        GLOBAL_INGEST.sen66_latest,
        GLOBAL_INGEST.sen66_nc_latest,
        GLOBAL_INGEST.sen66_history,
        GLOBAL_INGEST.sen66_nc_history,
        plotly_tpl,
        sen66_widget,
        sen66_state,
    )

    h10_widget = go.FigureWidget(layout=dict(autosize=True, height=400))
    h10_state: dict = {"chart": None, "dev": None, "tpl": None}
    register_h10_renders(
        input,
        GLOBAL_INGEST.h10_latest,
        GLOBAL_INGEST.h10_history,
        GLOBAL_INGEST.h10_ecg_latest,
        GLOBAL_INGEST.h10_ecg_samples,
        GLOBAL_INGEST.h10_ecg_chunks,
        GLOBAL_INGEST.h10_acc_latest,
        GLOBAL_INGEST.h10_acc_history,
        GLOBAL_INGEST.h10_motion_latest,
        plotly_tpl,
        h10_widget,
        h10_state,
        session,
    )
