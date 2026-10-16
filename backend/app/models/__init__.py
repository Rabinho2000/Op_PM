"""Modelos SQLAlchemy. Importar este pacote garante que todas as tabelas
estão registadas em `Base.metadata` antes de `create_all`/Alembic correrem.
"""
from app.models.client_report import ClientReportConfig, ClientReportSend  # noqa: F401
from app.models.absence import Absence  # noqa: F401
from app.models.ai import AiAuditLog  # noqa: F401
from app.models.calendar import CalendarEvent, Visit  # noqa: F401
from app.models.cable_designs import (  # noqa: F401
    CableDesign,
    CableDesignHistory,
    CableDesignRevision,
)
from app.models.cost import CostLine  # noqa: F401
from app.models.document import Document, Photo  # noqa: F401
from app.models.form import FormResponse, FormTemplate  # noqa: F401
from app.models.identity import (  # noqa: F401
    AuthAuditLog,
    Permission,
    Role,
    RolePermission,
    User,
    UserRole,
)
from app.models.imports import (  # noqa: F401
    FieldImportBatch,
    FieldImportConflict,
    FieldImportRecord,
    SurplusContract,
)
from app.models.installer import Installer, InstallerTeam  # noqa: F401
from app.models.installer_access import (  # noqa: F401
    InstallerAccessMembership,
    InstallerAccessMembershipHistory,
)
from app.models.inventory import (  # noqa: F401
    InventoryCatalogHistory,
    InventoryItem,
    InventoryLocation,
    InventoryMovement,
    MaterialRequest,
    MaterialRequestHistory,
    MaterialRequestItem,
    ProjectMaterialRequirement,
)
from app.models.map_ops import PickupPoint, ProjectIssue  # noqa: F401
from app.models.material_prices import (  # noqa: F401
    CatalogDataset,
    MaterialPrice,
    PriceImportBatch,
    PriceSource,
)
from app.models.migration import (  # noqa: F401
    ImportBatch,
    PersonReconciliationItem,
    StagingProjectRecord,
)
from app.models.notification import Notification  # noqa: F401
from app.models.people import Person  # noqa: F401
from app.models.planning import UserPlanningPreference  # noqa: F401
from app.models.works_preferences import UserWorksPreference  # noqa: F401
from app.models.works_saved_views import WorksCalendarSavedView  # noqa: F401
from app.models.performance import GoalPeriod, GoalPeriodHistory  # noqa: F401
from app.models.project import (  # noqa: F401
    Project,
    ProjectExternalId,
    ProjectHistory,
    ProjectStageProgress,
    ProjectSubtaskProgress,
    ProjectTeamAssignment,
)
from app.models.project_data import (
    ProjectCommunicationData,
    ProjectDataHistory,
    ProjectInstallationData,
    ProjectLicensingData,
)
from app.models.project_list_views import (  # noqa: F401
    ProjectListView,
    UserProjectListPreference,
)
from app.models.supplier import Supplier, SupplierContact, SupplierMaterialType  # noqa: F401
from app.models.task import Task, TaskHistory  # noqa: F401
from app.models.task_list_views import TaskListView, UserTaskListPreference  # noqa: F401
from app.models.time_bank import (  # noqa: F401
    TimeBankAdjustment,
    TimeBankAudit,
    TimeBankEntry,
    TimeBankImportBatch,
)
from app.models.workflow import (  # noqa: F401
    Phase,
    SupportDelegation,
    WorkflowStage,
    WorkflowSubtask,
)
