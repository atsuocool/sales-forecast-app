import pytest

from src.db.schema import create_all_tables
from src.pipeline.master_loader import load_masters
from src.pipeline.inventory_loader import load_regulatory_events
from src.forecast.scenario import build_penetration_events, AXIS2_SCALE_DEFAULTS

DATA_DIR    = "docs/sample_data"
REG_CSV     = "docs/sample_data/regulatory_events_sample.csv"
FORECAST_START = "2026-06"
HORIZON        = 36


@pytest.fixture
def event_conn(mem_conn):
    create_all_tables(mem_conn)
    load_masters(mem_conn, DATA_DIR)
    load_regulatory_events(mem_conn, REG_CSV)
    return mem_conn


# --- 軸1: regulatory_excluded ---

def test_excluded_returns_empty(event_conn):
    events = build_penetration_events(
        event_conn, FORECAST_START, HORIZON,
        scenario_axis1="regulatory_excluded",
    )
    assert events == []


# --- 軸1: regulatory_adjusted ---

def test_adjusted_returns_events(event_conn):
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    assert len(events) > 0


def test_adjusted_base_total_L_delta(event_conn):
    """base シナリオで pen_L_delta の合計が CSV の impact_value に等しい"""
    events = build_penetration_events(
        event_conn, FORECAST_START, HORIZON, scenario_axis2="base"
    )
    total_L = sum(e.ceiling_delta for e in events)
    assert abs(total_L - 0.05) < 1e-9


def test_adjusted_base_total_k_delta(event_conn):
    events = build_penetration_events(
        event_conn, FORECAST_START, HORIZON, scenario_axis2="base"
    )
    total_k = sum(e.speed_delta for e in events)
    assert abs(total_k - 0.02) < 1e-9


# --- 漸増ランプ ---

def test_ramp_spans_lag_months(event_conn):
    """effect_lag_months=3 → L_delta は 3 ステップに分割される"""
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    l_events = [e for e in events if e.ceiling_delta > 0]
    assert len(l_events) == 3


def test_ramp_equal_steps(event_conn):
    """各ステップの ceiling_delta が等しい"""
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    l_events = sorted([e for e in events if e.ceiling_delta > 0], key=lambda e: e.month_offset)
    steps = [e.ceiling_delta for e in l_events]
    assert abs(max(steps) - min(steps)) < 1e-9


def test_ramp_offsets_consecutive(event_conn):
    """ランプステップは連続した month_offset を持つ"""
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    l_events = sorted([e for e in events if e.ceiling_delta > 0], key=lambda e: e.month_offset)
    offsets = [e.month_offset for e in l_events]
    for i in range(1, len(offsets)):
        assert offsets[i] == offsets[i - 1] + 1


def test_ramp_starts_at_event_month(event_conn):
    """event_date=2026-06 かつ forecast_start=2026-06 → 最初の offset=1"""
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    l_events = sorted([e for e in events if e.ceiling_delta > 0], key=lambda e: e.month_offset)
    assert l_events[0].month_offset == 1


def test_events_beyond_horizon_excluded(event_conn):
    """horizon=1 では offset > 1 のイベントが除外される"""
    events = build_penetration_events(event_conn, FORECAST_START, horizon=1)
    for e in events:
        assert e.month_offset <= 1


# --- 軸2: 楽観/悲観スケール ---

def test_optimistic_larger_than_base(event_conn):
    base_events = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="base")
    opt_events  = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="optimistic")
    base_L = sum(e.ceiling_delta for e in base_events)
    opt_L  = sum(e.ceiling_delta for e in opt_events)
    assert opt_L > base_L


def test_pessimistic_smaller_than_base(event_conn):
    base_events = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="base")
    pes_events  = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="pessimistic")
    base_L = sum(e.ceiling_delta for e in base_events)
    pes_L  = sum(e.ceiling_delta for e in pes_events)
    assert pes_L < base_L


def test_optimistic_multiplier_applied(event_conn):
    scale = AXIS2_SCALE_DEFAULTS["optimistic"]
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="optimistic")
    total_L = sum(e.ceiling_delta for e in events)
    assert abs(total_L - 0.05 * scale) < 1e-9


def test_pessimistic_multiplier_applied(event_conn):
    scale = AXIS2_SCALE_DEFAULTS["pessimistic"]
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON, scenario_axis2="pessimistic")
    total_L = sum(e.ceiling_delta for e in events)
    assert abs(total_L - 0.05 * scale) < 1e-9


def test_custom_multiplier_override(event_conn):
    events = build_penetration_events(
        event_conn, FORECAST_START, HORIZON,
        scenario_axis2="optimistic",
        axis2_multipliers={"optimistic": 2.0},
    )
    total_L = sum(e.ceiling_delta for e in events)
    assert abs(total_L - 0.05 * 2.0) < 1e-9


# --- ラベル ---

def test_label_on_first_L_delta_step(event_conn):
    events = build_penetration_events(event_conn, FORECAST_START, HORIZON)
    labeled = [e for e in events if e.label]
    assert len(labeled) == 1
    assert labeled[0].month_offset == 1
    assert labeled[0].ceiling_delta > 0
