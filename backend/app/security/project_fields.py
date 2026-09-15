"""Lista explícita, no servidor, dos campos de `Project` que
`project.edit_own_progress` (tipicamente um PM, no seu próprio projeto)
pode alterar — ver docs/DECISIONS.md D-028, revisto em D-035.

Deliberadamente uma allowlist, não uma denylist: um campo novo adicionado
a `ProjectUpdate` no futuro fica administrativo (só `project.edit_all`) por
omissão, a menos que seja explicitamente acrescentado aqui. O inverso
(denylist) seria inseguro por desenho — bastaria esquecer de atualizar a
lista de bloqueados para um campo novo ficar acessível sem se querer.

`project.edit_all` (Chefe de Operações, Administrador) não tem esta
restrição — edita qualquer campo de `ProjectUpdate`.

**Revisão D-035 (fecho de Fase 1 para staging/produção):** potência
(`power_kwp`/`power_raw`), coordenadas (`lat`/`lon`), datas legadas
(`start_date`, `upac_connection_date_raw`, `award_year_raw`) e
`commercial_assumptions` passaram de PM-editável para administrativo —
são campos com impacto comercial/de identidade do projeto (potência
instalada, localização, pressupostos comerciais, datas contratuais) cuja
regra de negócio exata ("um PM pode corrigir a potência do seu próprio
projeto sem aprovação?") nunca foi confirmada pelo responsável
operacional. Sem essa confirmação, aplica-se a opção mais restritiva —
ver a pergunta registada em `docs/OPEN_QUESTIONS.md` ("Allowlist de
campos editáveis por PM: campos com impacto comercial"). Só ficam
PM-editáveis os campos claramente operacionais/de progresso, sem
ambiguidade de negócio: notas de acompanhamento e o campo de papel/role
legado, nenhum dos quais afeta identidade do cliente, atribuição, valor
comercial, ou dados usados fora desta plataforma.
"""
from __future__ import annotations

# Campos "de progresso/operacionais" — texto livre de acompanhamento que o
# PM ajusta no seu próprio projeto, sem qualquer valor comercial ou de
# identidade associado. Nenhum destes é usado por outra integração nem
# aparece em relatórios comerciais.
PM_EDITABLE_PROJECT_FIELDS: frozenset[str] = frozenset(
    {
        "role",
        "equipment_notes",
        "injection_notes",
        "om_notes",
        "notes",
    }
)

# Campos explicitamente administrativos — nunca editáveis por
# project.edit_own_progress, mesmo que alguém os acrescente por engano à
# allowlist acima (verificado por teste — ver
# tests/test_project_field_permissions.py).
#
# Dois grupos, por motivos diferentes:
# 1) Identidade do cliente/atribuição/estado — nunca foram PM-editáveis
#    (D-028): name, client_*, address, pm_person_id, is_active,
#    upac_registration, m2m_card.
# 2) Impacto comercial/contratual sem regra de negócio confirmada —
#    movidos de PM-editável para aqui em D-035 (ver docstring do módulo e
#    docs/OPEN_QUESTIONS.md): lat, lon, power_kwp, power_raw, start_date,
#    commercial_assumptions, upac_connection_date_raw, award_year_raw.
#    Se o responsável operacional confirmar que um PM pode editar algum
#    destes no seu próprio projeto, mover para PM_EDITABLE_PROJECT_FIELDS
#    nessa altura — nunca assumir antecipadamente.
ADMIN_ONLY_PROJECT_FIELDS: frozenset[str] = frozenset(
    {
        # --- Identidade/atribuição/estado (D-028, sem alteração) ---
        "name",
        "client_name",
        "client_contact",
        "client_email",
        "address",
        "pm_person_id",
        "is_active",
        "upac_registration",
        "m2m_card",
        # --- Impacto comercial/contratual, pendente de decisão de negócio (D-035) ---
        "lat",
        "lon",
        "power_kwp",
        "power_raw",
        "start_date",
        "commercial_assumptions",
        "upac_connection_date_raw",
        "award_year_raw",
    }
)
