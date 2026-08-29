from __future__ import annotations

from collections.abc import Mapping

from serpent_core.effect_sdk import EffectFrame
from serpent_core.topology import LightingTopology


def black_frame(topology: LightingTopology) -> EffectFrame:
    frame = EffectFrame(
        rows=topology.rows,
        columns=topology.columns,
        pixels=tuple(
            tuple((0, 0, 0) for _column in range(topology.columns))
            for _row in range(topology.rows)
        ),
    )
    frame.validate()
    return frame


def compose_region_frames(
    topology: LightingTopology,
    frames_by_region: Mapping[str, EffectFrame],
) -> EffectFrame:
    topology.validate()
    rows = [
        [(0, 0, 0) for _column in range(topology.columns)]
        for _row in range(topology.rows)
    ]
    regions = {region.id: region for region in topology.regions}
    for region_id, frame in frames_by_region.items():
        region = regions.get(region_id)
        if region is None:
            raise ValueError(f"Unknown topology region {region_id!r}.")
        frame.validate()
        if frame.rows != topology.rows or frame.columns != topology.columns:
            raise ValueError(
                f"Region frame {region_id!r} is {frame.rows}x{frame.columns}; "
                f"device topology is {topology.rows}x{topology.columns}."
            )
        for cell in region.cells:
            rows[cell.row][cell.column] = frame.pixels[cell.row][cell.column]
    result = EffectFrame(
        rows=topology.rows,
        columns=topology.columns,
        pixels=tuple(tuple(row) for row in rows),
    )
    result.validate()
    return result


def contribution_key(instance_id: str, region_id: str) -> str:
    return f"{instance_id}:{region_id}"
