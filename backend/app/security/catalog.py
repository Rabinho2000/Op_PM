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
    "project.change_status": "Alterar o estado do ciclo de vida dos projetos visíveis (todos, ou só os próprios como PM)",
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
    "task.edit_own": (
        "Criar tarefas atribuídas a si mesmo e editar tarefas que criou ou que lhe "
        "estão atribuídas — nunca atribuir/reatribuir a outra pessoa (ver "
        "app/security/permissions.py:can_edit_task/can_create_task)"
    ),
    "absence.view_all": "Ver férias/ausências de todas as pessoas",
    "absence.view_own": "Ver as próprias férias/ausências",
    "absence.manage_all": "Registar/cancelar férias de qualquer pessoa",
    "absence.manage_own": "Registar/cancelar as próprias férias",
    # --- MVP de Operações (ver docs/PLAN_OPERATIONS_MVP.md) ---
    "inventory.manage_central": "Registar entradas/ajustes no stock físico central (armazém IdealMinde)",
    "inventory.allocate_project": "Reservar material do stock central para um projeto",
    "inventory.consume_project": "Consumir material reservado de um projeto",
    "inventory.release_project": "Libertar uma reserva de material de um projeto",
    "inventory.deliver_project": "Registar material entregue numa instalação",
    "inventory.collect_project": "Registar material recolhido de uma instalação",
    "inventory.manage_requirements": "Criar/editar necessidades de material de um projeto",
    "project.view_installation_data": "Ver dados de instalação do projeto",
    "project.edit_installation_data": "Editar dados de instalação do projeto (combinado com o âmbito de project.edit_*)",
    "project.view_licensing_data": "Ver dados de licenciamento do projeto",
    "project.edit_licensing_data": "Editar dados de licenciamento do projeto (combinado com o âmbito de project.edit_*)",
    "project.view_communication_data": "Ver dados de comunicação/M2M do projeto (nunca inclui credenciais)",
    "project.edit_communication_data": "Editar dados de comunicação/M2M do projeto",
    "map.view": "Ver o mapa operacional (projetos, fornecedores, recolhas, pendências)",
    "supplier.view": "Ver a lista de fornecedores (contactos, tipos de material, localização)",
    "supplier.manage": "Criar/editar fornecedores",
    "pickup_point.manage": "Criar/editar pontos de recolha",
    "project_issue.view": "Ver pendências de obra",
    "project_issue.manage": "Criar/editar pendências de obra e convertê-las em tarefa",
    "calendar.view": "Ver eventos de calendário/planeamento",
    "calendar.manage": "Criar/editar/cancelar eventos de calendário/planeamento",
    "performance.view_all": "Ver metas e indicadores de toda a operação",
    "performance.view_own": "Ver metas e indicadores próprios (como PM)",
    "performance.manage_goals": "Criar/editar metas (GoalPeriod)",
    "import.notes": "Importar notas iniciais (pré-visualizar, resolver conflitos, aplicar)",
    "import.licensing": "Importar o Excel de licenciamento (dry-run/aplicar/reverter)",
}

# Matriz papel -> permissões concedidas por omissão.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    ROLE_ADMIN: list(PERMISSIONS.keys()),
    ROLE_CHEFE_OPERACOES: [
        "supplier.view",
        "project.view_all",
        "project.edit_all",
        "project.change_status",
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
        # MVP de Operações — Chefe opera qualquer projeto/inventário/mapa.
        "inventory.manage_central",
        "inventory.allocate_project",
        "inventory.consume_project",
        "inventory.release_project",
        "inventory.deliver_project",
        "inventory.collect_project",
        "inventory.manage_requirements",
        "project.view_installation_data",
        "project.edit_installation_data",
        "project.view_licensing_data",
        "project.edit_licensing_data",
        "project.view_communication_data",
        "project.edit_communication_data",
        "map.view",
        "supplier.manage",
        "pickup_point.manage",
        "project_issue.view",
        "project_issue.manage",
        "calendar.view",
        "calendar.manage",
        "performance.view_all",
        "performance.manage_goals",
        "import.notes",
        "import.licensing",
    ],
    ROLE_PM: [
        "supplier.view",
        "project.view_own",
        "project.edit_own_progress",
        "project.change_status",
        "cost.view",
        "inventory.view",
        "material_request.create",
        "document.view",
        "document.edit",
        "calendar.propose",
        "calendar.approve_send",
        "ai.use_tools",
        # PM vê tarefas de todos os projetos (visibilidade global), mas só
        # pode criar/editar as suas (ver task.edit_own e
        # app/security/permissions.py:can_edit_task/can_create_task) — a
        # separação entre "ver" e "escrever" é o que torna isto seguro.
        "task.view_all",
        "task.edit_own",
        "absence.view_own",
        "absence.manage_own",
        # MVP de Operações — decisão de negócio confirmada: Administrador,
        # Chefe de Operações e PM podem todos gerir o inventário central
        # (entrada/ajuste), além de reservar/consumir/libertar material dos
        # projetos que gerem (ver docs/PLAN_OPERATIONS_MVP.md secção 4,
        # revista — a versão anterior deste catálogo excluía PM de
        # inventory.manage_central; corrigido a pedido explícito do
        # negócio).
        "inventory.manage_central",
        "inventory.allocate_project",
        "inventory.consume_project",
        "inventory.release_project",
        "inventory.deliver_project",
        "inventory.collect_project",
        "inventory.manage_requirements",
        "project.view_installation_data",
        "project.edit_installation_data",
        "project.view_licensing_data",
        "project.edit_licensing_data",
        "project.view_communication_data",
        "project.edit_communication_data",
        "map.view",
        "project_issue.view",
        "project_issue.manage",
        "calendar.view",
        "calendar.manage",
        "performance.view_own",
    ],
    ROLE_COMERCIAL: [
        "project.view_all",
        "cost.view",
        "document.view",
        "task.view_all",
        "absence.view_own",
        "absence.manage_own",
        "project.view_installation_data",
        "project.view_licensing_data",
        "map.view",
        "project_issue.view",
        "calendar.view",
        "performance.view_all",
        # O formulário de notas iniciais é usado pelo Comercial/Sales
        # Support (papel não modelado à parte — reaproveita Comercial).
        "import.notes",
    ],
    ROLE_FINANCEIRO: [
        "project.view_all",
        "cost.view",
        "cost.edit_real",
        "document.view",
        "task.view_all",
        "absence.view_own",
        "absence.manage_own",
        "project.view_installation_data",
        "project.view_licensing_data",
        "map.view",
        "project_issue.view",
        "calendar.view",
        "performance.view_all",
    ],
}
