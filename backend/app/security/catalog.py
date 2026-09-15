"""Catálogo inicial de papéis e permissões (ver docs/PRODUCT_SCOPE.md e
docs/ARCHITECTURE_PROPOSAL.md, "Matriz de permissões"). Usado pelo seed de
desenvolvimento (`app/migration/seed_dev.py`) e pelos testes — não é a fonte
de verdade em produção, que fica na tabela `roles`/`permissions` e pode ser
ajustada sem alterar código.
"""
from __future__ import annotations

ROLE_ADMIN = "administrador"
ROLE_CHEFE_OPERACOES = "chefe_operacoes"
ROLE_PM = "project_manager"
ROLE_COMERCIAL = "comercial"
ROLE_FINANCEIRO = "financeiro"

ROLES: dict[str, str] = {
    ROLE_ADMIN: "Administrador",
    ROLE_CHEFE_OPERACOES: "Chefe de Operações",
    ROLE_PM: "Project Manager",
    ROLE_COMERCIAL: "Comercial",
    ROLE_FINANCEIRO: "Financeiro",
}

# Permissões (código, descrição)
PERMISSIONS: dict[str, str] = {
    "project.view_all": "Ver todos os projetos",
    "project.view_own": "Ver os projetos próprios (como PM)",
    "project.edit_all": "Editar identidade/atribuição de qualquer projeto",
    "project.edit_own_progress": "Editar progresso/checklist dos projetos próprios",
    "cost.view": "Ver custos e margens",
    "cost.edit_estimate": "Editar custo estimado/orçamentado",
    "cost.edit_real": "Editar/importar custo real (normalmente espelhado do Financial)",
    "inventory.view": "Ver stock e movimentos",
    "inventory.edit": "Registar movimentos de stock",
    "material_request.create": "Criar pedido de material",
    "material_request.approve": "Aprovar pedido de material",
    "material_request.adjudicate": "Marcar pedido de material como adjudicado",
    "document.view": "Ver biblioteca documental",
    "document.edit": "Anexar/editar documentos",
    "calendar.propose": "Propor datas/rascunhos de visita",
    "calendar.approve_send": "Aprovar e enviar email / criar evento real",
    "ai.use_tools": "Usar ferramentas de IA (propostas/rascunhos)",
    "ai.approve_actions": "Aprovar uma ação de IA para execução",
    "admin.manage_users": "Gerir utilizadores e permissões",
    "migration.view": "Ver lotes de importação, registos de staging e fila de reconciliação de PM",
    "migration.resolve": "Resolver conflitos, promover, reverter, e resolver reconciliação de PM",
    "migration.link_arbitrary_project": (
        "Ligar um registo de staging a um projeto fora dos candidatos detetados "
        "automaticamente (exige sempre uma nota — ver D-030)"
    ),
    "task.view_all": "Ver tarefas de qualquer projeto",
    "task.view_own": "Ver tarefas dos projetos próprios (como PM) e tarefas atribuídas a si",
    "task.edit_all": "Criar/editar/atribuir/concluir tarefas de qualquer projeto",
    "task.edit_own": "Criar/editar/atribuir/concluir tarefas dos projetos próprios (como PM)",
    "absence.view_all": "Ver férias/ausências de todas as pessoas",
    "absence.view_own": "Ver as próprias férias/ausências",
    "absence.manage_all": "Registar/cancelar férias de qualquer pessoa",
    "absence.manage_own": "Registar/cancelar as próprias férias",
}

# Matriz papel -> permissões concedidas por omissão.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_ADMIN: list(PERMISSIONS.keys()),
    ROLE_CHEFE_OPERACOES: [
        "project.view_all",
        "project.edit_all",
        "cost.view",
        "cost.edit_estimate",
        "inventory.view",
        "inventory.edit",
        "material_request.create",
        "material_request.approve",
        "material_request.adjudicate",
        "document.view",
        "document.edit",
        "calendar.propose",
        "calendar.approve_send",
        "ai.use_tools",
        "ai.approve_actions",
        "migration.view",
        "migration.resolve",
        "task.view_all",
        "task.edit_all",
        "absence.view_all",
        "absence.manage_all",
    ],
    ROLE_PM: [
        "project.view_own",
        "project.edit_own_progress",
        "cost.view",
        "inventory.view",
        "material_request.create",
        "document.view",
        "document.edit",
        "calendar.propose",
        "calendar.approve_send",
        "ai.use_tools",
        "task.view_own",
        "task.edit_own",
        "absence.view_own",
        "absence.manage_own",
    ],
    ROLE_COMERCIAL: [
        "project.view_all",
        "cost.view",
        "document.view",
        "task.view_all",
        "absence.view_own",
        "absence.manage_own",
    ],
    ROLE_FINANCEIRO: [
        "project.view_all",
        "cost.view",
        "cost.edit_real",
        "document.view",
        "task.view_all",
        "absence.view_own",
        "absence.manage_own",
    ],
}
