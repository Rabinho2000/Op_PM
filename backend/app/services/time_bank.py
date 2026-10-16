"""Regras determinísticas do Banco de Horas.

Os cálculos usam segundos inteiros e horas locais representadas como minutos
from midnight.  Não há conversão de timezone nem arredondamento de floats.
"""
from __future__ import annotations

import datetime as dt


class TimeBankValidationError(ValueError):
    """Erro de contrato de negócio, seguro para devolver como 422."""


def _validate_minutes(value: int | None, *, name: str, allow_none: bool = False) -> None:
    if value is None and allow_none:
        return
    if isinstance(value, bool) or not isinstance(value, int):
        raise TimeBankValidationError(f"{name} deve ser um inteiro em minutos.")
    upper = 1440 if name == "end_minute" else 1439
    if value < 0 or value > upper:
        raise TimeBankValidationError(f"{name} deve estar entre 0 e {upper}.")


def calculate_work_seconds(
    *,
    work_date: dt.date,
    start_minute: int | None,
    end_minute: int | None,
    lunch_taken: bool | None,
    calculation_mode: str,
    manual_balance_seconds: int | None = None,
    reason: str | None = None,
) -> int:
    """Calcula o lançamento contabilizado segundo o contrato aprovado.

    ``standard`` aplica a referência segunda–quinta 09:00–18:30 e sexta
    09:00–14:00. ``saturday`` aplica 1.5 ao tempo líquido do sábado.
    ``manual`` exige um valor explícito; domingos só podem ser manuais.
    Resultados negativos são válidos.
    """
    if not isinstance(work_date, dt.date) or isinstance(work_date, dt.datetime):
        raise TimeBankValidationError("work_date deve ser uma data sem hora.")
    if calculation_mode not in {"standard", "saturday", "manual", "imported"}:
        raise TimeBankValidationError("calculation_mode inválido.")

    if calculation_mode == "manual":
        if manual_balance_seconds is None or isinstance(manual_balance_seconds, bool) or not isinstance(manual_balance_seconds, int):
            raise TimeBankValidationError("manual_balance_seconds é obrigatório no modo manual.")
        if not reason or not reason.strip():
            raise TimeBankValidationError("reason é obrigatório no modo manual.")
        return manual_balance_seconds

    if calculation_mode == "imported":
        if manual_balance_seconds is None or isinstance(manual_balance_seconds, bool) or not isinstance(manual_balance_seconds, int):
            raise TimeBankValidationError("manual_balance_seconds é obrigatório no modo imported.")
        return manual_balance_seconds

    _validate_minutes(start_minute, name="start_minute")
    _validate_minutes(end_minute, name="end_minute")
    if end_minute is None or start_minute is None:  # for type checkers
        raise TimeBankValidationError("Horários completos são obrigatórios.")
    if end_minute <= start_minute:
        raise TimeBankValidationError("A hora de saída não pode ser anterior ou igual à entrada.")
    if not isinstance(lunch_taken, bool):
        raise TimeBankValidationError("lunch_taken deve ser booleano.")

    weekday = work_date.weekday()
    if weekday == 6:
        raise TimeBankValidationError("Domingo exige calculation_mode=manual.")
    if weekday == 5:
        if calculation_mode != "saturday":
            raise TimeBankValidationError("Sábado exige calculation_mode=saturday.")
        net_minutes = end_minute - start_minute - (60 if lunch_taken else 0)
        return net_minutes * 60 * 3 // 2
    if calculation_mode != "standard":
        raise TimeBankValidationError("Dias úteis exigem calculation_mode=standard.")

    reference_minutes = 5 * 60 if weekday == 4 else 9 * 60 + 30
    net_minutes = end_minute - start_minute - reference_minutes + (0 if lunch_taken else 60)
    return net_minutes * 60
