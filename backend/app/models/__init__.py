"""Modelos SQLAlchemy. Importar este pacote garante que todas as tabelas
estão registadas em `Base.metadata` antes de `create_all`/Alembic correrem.
"""
from app.models.identity import AuthAuditLog, Permission, Role, RolePermission, User, UserRole  # noqa: F401
from app.models.people import Person  # noqa: F401
from app.models.workflow import Phase, WorkflowStage, WorkflowSubtask  # noqa: F401
from app.models.project import (  # noqa: F401
    Project,
    ProjectExternalId,
    ProjectHistory,
    ProjectStageProgress,
    ProjectSubtaskProgress,
)
from app.models.calendar import CalendarEvent, Visit  # noqa: F401
from app.models.task import Task, TaskHistory  # noqa: F401
from app.models.absence import Absence  # noqa: F401
from app.models.supplier import Supplier  # noqa: F401
from app.models.inventory import (  # noqa: F401
    InventoryItem,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestItem,
)
from app.models.cost import CostLine  # noqa: F401
from app.models.document import Document, Photo  # noqa: F401
from app.models.form import FormResponse, FormTemplate  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.migration import ImportBatch, PersonReconciliationItem, StagingProjectRecord  # noqa: F401
from app.models.ai import AiAuditLog  # noqa: F401
