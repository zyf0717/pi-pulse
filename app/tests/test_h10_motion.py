from app.renders.h10_motion import motion_detail_row_svg, motion_plane_svg


def test_motion_plane_svg_preview_renders_labels_and_head() -> None:
    svg = motion_plane_svg(
        [(0.0, 0.0, 1000.0), (12.0, -8.0, 990.0)],
        axes=(0, 1),
        axis_names=("X", "Y"),
        detail=False,
    )

    assert svg.startswith("<svg")
    assert "polyline" in svg
    assert "<circle " in svg
    assert ">X<" in svg
    assert ">Y<" in svg
    assert "+1500" not in svg


def test_motion_plane_svg_detail_renders_tick_labels_and_latest_values() -> None:
    svg = motion_plane_svg(
        [(0.0, 0.0, 1000.0), (12.0, -8.0, 990.0)],
        axes=(0, 2),
        axis_names=("X", "Z"),
        detail=True,
    )

    assert svg.startswith("<svg")
    assert "polyline" in svg
    assert "+1500" in svg
    assert "-1500" in svg
    assert "X: +12 mg" in svg
    assert "Z: +990 mg" in svg


def test_motion_detail_row_svg_renders_three_planes() -> None:
    svg_row = motion_detail_row_svg([(0.0, 0.0, 1000.0), (12.0, -8.0, 990.0)])

    assert svg_row.count("<svg") == 3
    assert svg_row.count("polyline") == 3
