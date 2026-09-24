from __future__ import annotations

from sqlalchemy import Column, Float, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import GUID, Base
from app.models.base import TimestampMixin, UUIDPk

# Associação fornecedor <-> tipo de material (D-070): um fornecedor tem vários
# tipos e um tipo tem vários fornecedores.
supplier_material_type_links = Table(
    "supplier_material_type_links",
    Base.metadata,
    Column("supplier_id", GUID(), ForeignKey("suppliers.id"), primary_key=True),
    Column("material_type_id", GUID(), ForeignKey("supplier_material_types.id"), primary_key=True),
)


class SupplierMaterialType(UUIDPk, TimestampMixin, Base):
    """Tipo de material (ex. "Estruturas de fixação"). `name_key` é o nome sem
    maiúsculas/acentos e garante que "Inversores" e "inversores" são o mesmo
    tipo; `name` é o texto a apresentar."""

    __tablename__ = "supplier_material_types"

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    name_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)


class Supplier(UUIDPk, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(256), nullable=False)
    # Legado (anterior a D-070): um único tipo em texto. Os tipos passaram a
    # ser `material_types`; este campo mantém-se só para não perder dados.
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Pessoa de contacto (nome). O telefone tem campo próprio: `phone`.
    contact: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    website: Mapped[str | None] = mapped_column(String(512), nullable=True)
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_preferred: Mapped[bool] = mapped_column(default=False, nullable=False)
    lead_time_days: Mapped[int | None] = mapped_column(nullable=True)
    # Lista livre de materiais fornecidos (texto, sem tabela de associação
    # nesta fase — ver docs/PLAN_OPERATIONS_MVP.md secção 11, decisão assumida).
    materials: Mapped[str] = mapped_column(Text, default="")
    # Outros contactos, lojas, observações.
    notes: Mapped[str] = mapped_column(Text, default="", nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)

    material_types: Mapped[list[SupplierMaterialType]] = relationship(
        secondary=supplier_material_type_links,
        order_by=SupplierMaterialType.name_key,
        lazy="selectin",
    )
