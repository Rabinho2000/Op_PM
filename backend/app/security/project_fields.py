"""Lista explícita, no servidor, dos campos de `Project` que
`project.edit_own_progress` (tipicamente um PM, no seu próprio projeto)
pode alterar — ver docs/DECISIONS.md D-028.

Deliberadamente uma allowlist, não uma denylist: um campo novo adicionado
a `ProjectUpdate` no futuro fica administrativo (só `project.edit_all`) por
omissão, a menos que seja explicitamente acrescentado aqui. O inverso
(denylist) seria inseguro por desenho — bastaria esquecer de atualizar a
lista de bloqueados para um campo novo ficar acessível sem se querer.

`project.edit_all` (Chefe de Operações, Administrador) não tem esta
restrição — edita qualquer campo de `ProjectUpdate`.
"""
from __future__ import annotations

# Campos "de progresso/operacionais" — o PM pode ajustá-los no seu próprio
# projeto sem tocar em identidade do cliente, atribuição, ou estado
# administrativo.
PM_EDITABLE_PROJECT_FIELDS: frozenset[str] = frozenset(
    {
        "lat",
        "lon",
        "power_kwp",
        "power_raw",
        "start_date",
        "role",
        "equipment_notes",
        "injection_notes",
        "om_notes",
        "commercial_assumptions",
        "upac_connection_date_raw",
        "award_year_raw",
        "notes",
    }
)

# Campos explicitamente administrativos — nunca editáveis por
# project.edit_own_progress, mesmo que alguém os acrescente por engano à
# allowlist acima (verificado por teste — ver
# tests/test_project_field_permissions.py). Existe só como documentação
# executável do pedido original ("um PM nunca pode alterar name,
# client_email, client_contact, pm_person_id, is_active, ou outros campos
# administrativos sem permissão específica").
ADMIN_ONLY_PROJECT_FIELDS: frozenset[str] = frozenset(
    {
        "name",
        "client_name",
        "client_contact",
        "client_email",
        "address",
        "pm_person_id",
        "is_active",
        "upac_registration",
        "m2m_card",
    }
)
