"""Explicit selection and grouping contracts for named regression datasets."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictFloat, StrictInt, StrictStr, AfterValidator, model_validator

from experiment_to_cpfe.schema.models import RESERVED_TABLE_NAMES
from experiment_to_cpfe.schema.validation import _unit_is_declared


def _declared(value: str) -> str:
    if not _unit_is_declared(value) or value != value.strip():
        raise ValueError("an explicit nonblank declaration without outer whitespace is required")
    return value


Declared = Annotated[StrictStr, AfterValidator(_declared)]
Index = Annotated[StrictInt, Field(ge=0)]
Finite = Annotated[StrictFloat, Field(allow_inf_nan=False)]
Split = Literal["train", "validation", "test"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quantity(Contract):
    name: Declared
    unit: Declared


class AffineConversion(Contract):
    factor: Finite
    offset: Finite = 0.
    reason: Declared

    @model_validator(mode="after")
    def nonzero_factor(self):
        if self.factor == 0:
            raise ValueError("conversion factor must be nonzero")
        return self


class Column(Contract):
    source_unit: Declared
    unit_key: Declared | None = None
    conversion: AffineConversion | None = None


class TableColumn(Column):
    kind: Literal["table"]
    table: Declared
    column: Declared
    asset_id: Declared | None = None
    id_columns: list[Declared] = Field(min_length=1)
    where: dict[Declared, StrictStr | StrictInt | Finite] = Field(default_factory=dict)

    @model_validator(mode="after")
    def table_contract(self):
        if self.table not in RESERVED_TABLE_NAMES:
            raise ValueError(f"unknown normalized table {self.table!r}")
        if len(set(self.id_columns)) != len(self.id_columns):
            raise ValueError("duplicate identity columns")
        return self


class ArrayColumn(Column):
    kind: Literal["array"]
    array: Declared
    asset_id: Declared
    ids: Declared
    row_axis: Index = 0
    component: list[Index] = Field(default_factory=list)


Selector = Annotated[TableColumn | ArrayColumn, Field(discriminator="kind")]


class RowSelection(Contract):
    indices: list[Index] | None = Field(default=None, min_length=1)
    start: Index = 0
    stop: Index | None = None
    step: Annotated[StrictInt, Field(gt=0)] = 1

    @model_validator(mode='after')
    def explicit_indices(self):
        if self.indices is not None:
            if self.start != 0 or self.stop is not None or self.step != 1:
                raise ValueError('indices cannot be combined with slice selection')
            if self.indices != sorted(set(self.indices)):
                raise ValueError('indices must be unique and increasing')
        return self


class Layout(Contract):
    columns: dict[Declared, Selector]
    alignment_evidence: Declared
    rows: RowSelection = Field(default_factory=RowSelection)


class TargetSpecimen(Contract):
    """Original table column identifying independent specimens within a file."""

    column: Declared
    evidence: Declared


class TrainingInput(Contract):
    path: Declared
    sample_id: Declared
    layout: Declared
    split: Split
    group_id: Declared | None = None
    target_specimen: TargetSpecimen | None = None


class TrainingDatasetConfig(Contract):
    version: Literal[1, 2]
    features: list[Quantity] = Field(min_length=1)
    target: Quantity | None = None
    targets: list[Quantity] | None = Field(default=None, min_length=1)
    group_by: Literal["sample_id", "experiment_id", "explicit"]
    grouping_evidence: Declared
    layouts: dict[Declared, Layout]
    inputs: list[TrainingInput] = Field(min_length=1)
    task_contract: dict | None = None

    @model_validator(mode="after")
    def collection_contract(self):
        if self.version == 1:
            if self.target is None or self.targets is not None:
                raise ValueError("version 1 requires scalar target and forbids targets")
        elif self.target is not None or self.targets is None:
            raise ValueError("version 2 requires ordered targets and forbids scalar target")
        names = [quantity.name for quantity in [*self.features, *self.target_quantities]]
        from experiment_to_cpfe.datasets.task_contract import validate_task
        self.task_contract = validate_task(self.task_contract, self.features, self.target_quantities)
        if len(names) != len(set(names)):
            raise ValueError("feature and target names must be unique")
        for key, layout in self.layouts.items():
            if set(layout.columns) != set(names):
                raise ValueError(f"layout {key!r} columns must match features and target exactly")
            for quantity in [*self.features, *self.target_quantities]:
                column = layout.columns[quantity.name]
                if column.source_unit != quantity.unit and column.conversion is None:
                    raise ValueError(f"layout {key!r} field {quantity.name!r}: unit change requires conversion")
        seen = set()
        for item in self.inputs:
            if item.sample_id in seen:
                raise ValueError(f"duplicate sample identity {item.sample_id!r}")
            seen.add(item.sample_id)
            if item.layout not in self.layouts:
                raise ValueError(f"sample {item.sample_id!r}: unknown layout {item.layout!r}")
            if (self.group_by == "explicit") != (item.group_id is not None):
                raise ValueError(f"sample {item.sample_id!r}: group_id is required only for explicit grouping")
        return self

    @property
    def target_quantities(self) -> list[Quantity]:
        return [self.target] if self.version == 1 else self.targets
