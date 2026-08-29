#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from serpent_core.device import DeviceModel
from serpent_core.fixtures import FixtureError


@dataclass(frozen=True, order=True)
class MatrixCell:
    row: int
    column: int


@dataclass(frozen=True)
class TopologyRegion:
    id: str
    name: str
    region_type: str
    cells: tuple[MatrixCell, ...]
    visible: bool
    confirmed: bool
    controllable: bool
    notes: str | None = None


@dataclass(frozen=True)
class LightingTopology:
    """Spatial description of a lighting surface and its device class."""

    rows: int
    columns: int
    regions: tuple[TopologyRegion, ...]
    device_class: str | None = None

    @property
    def cell_count(self) -> int:
        return self.rows * self.columns

    def all_cells(self) -> tuple[MatrixCell, ...]:
        return tuple(
            MatrixCell(row, column)
            for row in range(self.rows)
            for column in range(self.columns)
        )

    def region_by_id(self, region_id: str) -> TopologyRegion:
        for region in self.regions:
            if region.id == region_id:
                return region

        raise FixtureError(
            f"Unknown topology region {region_id!r}."
        )

    def visible_regions(self) -> tuple[TopologyRegion, ...]:
        return tuple(
            region
            for region in self.regions
            if region.visible
        )

    def controllable_regions(self) -> tuple[TopologyRegion, ...]:
        return tuple(
            region
            for region in self.regions
            if region.controllable
        )

    def confirmed_regions(self) -> tuple[TopologyRegion, ...]:
        return tuple(
            region
            for region in self.regions
            if region.confirmed
        )

    def validate(self) -> None:
        if self.rows < 1 or self.columns < 1:
            raise FixtureError(
                "Lighting topology rows and columns "
                "must both be at least 1."
            )

        owners: dict[MatrixCell, str] = {}

        for region in self.regions:
            if not region.cells:
                raise FixtureError(
                    f"Topology region {region.id!r} has no cells."
                )

            for cell in region.cells:
                if (
                    cell.row < 0
                    or cell.row >= self.rows
                    or cell.column < 0
                    or cell.column >= self.columns
                ):
                    raise FixtureError(
                        f"Topology region {region.id!r} contains "
                        f"out-of-range cell "
                        f"({cell.row}, {cell.column})."
                    )

                previous = owners.get(cell)

                if previous is not None:
                    raise FixtureError(
                        f"Topology cell "
                        f"({cell.row}, {cell.column}) belongs to both "
                        f"{previous!r} and {region.id!r}."
                    )

                owners[cell] = region.id


def _matrix_columns_cells(
    columns: Iterable[int],
) -> tuple[MatrixCell, ...]:
    return tuple(
        MatrixCell(0, int(column))
        for column in columns
    )


def _matrix_grid_cells(
    rows: int,
    columns: int,
) -> tuple[MatrixCell, ...]:
    return tuple(
        MatrixCell(row, column)
        for row in range(rows)
        for column in range(columns)
    )


def build_lighting_topology(
    device: DeviceModel,
) -> LightingTopology | None:
    matrix = device.capabilities.matrix

    if matrix is None:
        return None

    regions: list[TopologyRegion] = []

    if device.zones:
        for zone in device.zones:
            if zone.mapping_type == "matrix-columns":
                cells = _matrix_columns_cells(
                    zone.columns
                )
            else:
                raise FixtureError(
                    f"{device.id}: unsupported lighting-zone "
                    f"mapping type {zone.mapping_type!r}."
                )

            regions.append(
                TopologyRegion(
                    id=zone.id,
                    name=zone.name,
                    region_type=zone.zone_type,
                    cells=cells,
                    visible=zone.visible,
                    confirmed=zone.confirmed,
                    controllable=zone.controllable,
                    notes=zone.notes,
                )
            )
    else:
        # A matrix-capable device with no explicit zones is represented
        # as one region spanning the complete matrix. This keeps existing
        # keyboard fixtures valid while making them topology-aware.
        regions.append(
            TopologyRegion(
                id="matrix",
                name="Lighting Matrix",
                region_type="matrix",
                cells=_matrix_grid_cells(
                    matrix.rows,
                    matrix.columns,
                ),
                visible=True,
                confirmed=True,
                controllable=True,
            )
        )

    topology = LightingTopology(
        rows=matrix.rows,
        columns=matrix.columns,
        regions=tuple(regions),
        device_class=device.fixture.device_class,
    )
    topology.validate()
    return topology
