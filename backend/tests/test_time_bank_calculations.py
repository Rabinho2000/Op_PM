from __future__ import annotations

import datetime as dt

import pytest

from app.services.time_bank import TimeBankValidationError, calculate_work_seconds


def test_standard_monday_uses_nine_and_half_hour_reference_and_lunch_branch():
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 12), start_minute=9 * 60, end_minute=18 * 60 + 30, lunch_taken=True,
        calculation_mode="standard",
    ) == 0
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 12), start_minute=9 * 60, end_minute=18 * 60 + 30, lunch_taken=False,
        calculation_mode="standard",
    ) == 3600


def test_standard_friday_uses_five_hour_reference_and_lunch_branch():
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 16), start_minute=9 * 60, end_minute=14 * 60, lunch_taken=True,
        calculation_mode="standard",
    ) == 0
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 16), start_minute=9 * 60, end_minute=14 * 60, lunch_taken=False,
        calculation_mode="standard",
    ) == 3600


def test_saturday_applies_one_and_half_to_net_worked_time():
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 17), start_minute=9 * 60, end_minute=17 * 60, lunch_taken=True,
        calculation_mode="saturday",
    ) == 7 * 3600 * 3 // 2


def test_negative_standard_result_is_allowed():
    assert calculate_work_seconds(
        work_date=dt.date(2026, 10, 12), start_minute=9 * 60, end_minute=16 * 60, lunch_taken=True,
        calculation_mode="standard",
    ) == -2 * 3600 - 1800


def test_sunday_requires_manual_mode_and_reason_is_checked_by_service():
    with pytest.raises(TimeBankValidationError, match="manual"):
        calculate_work_seconds(
            work_date=dt.date(2026, 10, 18), start_minute=9 * 60, end_minute=13 * 60, lunch_taken=False,
            calculation_mode="standard",
        )


def test_manual_mode_does_not_infer_hours():
    with pytest.raises(TimeBankValidationError, match="manual_balance_seconds"):
        calculate_work_seconds(
            work_date=dt.date(2026, 10, 12), start_minute=None, end_minute=None, lunch_taken=None,
            calculation_mode="manual",
        )


def test_start_and_end_are_local_minute_boundaries():
    with pytest.raises(TimeBankValidationError):
        calculate_work_seconds(
            work_date=dt.date(2026, 10, 12), start_minute=24 * 60, end_minute=24 * 60,
            lunch_taken=True, calculation_mode="standard",
        )
    with pytest.raises(TimeBankValidationError, match="anterior"):
        calculate_work_seconds(
            work_date=dt.date(2026, 10, 12), start_minute=17 * 60, end_minute=9 * 60,
            lunch_taken=True, calculation_mode="standard",
        )
