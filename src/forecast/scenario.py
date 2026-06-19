import sqlite3
from typing import Dict, List, Optional

from src.forecast.penetration import EventAdjustment

# 軸2（楽観/悲観）のデフォルト乗数
# optimistic: 使用促進策の効果が想定より上振れ（仮値の1.5倍）
# pessimistic: 効果がほぼ出ない（仮値の10%）
AXIS2_SCALE_DEFAULTS: Dict[str, float] = {
    "base":        1.0,
    "optimistic":  1.5,
    "pessimistic": 0.1,
}


def _months_between(from_period: str, to_period: str) -> int:
    """from_period → to_period の月数差（正=未来、負=過去）"""
    fy, fm = int(from_period[:4]), int(from_period[5:7])
    ty, tm = int(to_period[:4]), int(to_period[5:7])
    return (ty - fy) * 12 + (tm - fm)


def build_penetration_events(
    conn:               sqlite3.Connection,
    forecast_start:     str,
    horizon:            int,
    scenario_axis1:     str = "regulatory_adjusted",
    scenario_axis2:     str = "base",
    axis2_multipliers:  Optional[Dict[str, float]] = None,
) -> List[EventAdjustment]:
    """
    DB の regulatory_events (impact_target='penetration') から
    EventAdjustment リストを構築する。

    漸増ランプ:
      effect_lag_months = N の場合、total_delta を N ステップに均等分割し、
      event_date から始まる連続 N ヶ月にわたって 1/N ずつ積み上げる。
      → ステップ関数ではなく、N ヶ月かけて緩やかに上昇するカーブになる。
      effect_lag_months = 0 の場合は即時（1 ステップ）適用。

    Parameters
    ----------
    forecast_start : str
        予測配列の 1 ヶ月目に対応する YYYY-MM（実績最終月の翌月）。
    scenario_axis1 : str
        "regulatory_adjusted"  → 制度変更イベントを反映
        "regulatory_excluded"  → 反映しない（空リストを返す）
    scenario_axis2 : str
        "base" / "optimistic" / "pessimistic"
        impact_value にスケール乗数を掛けて効果量を上下させる。
    axis2_multipliers : dict, optional
        AXIS2_SCALE_DEFAULTS をオーバーライドしたい場合に指定。
    """
    if scenario_axis1 == "regulatory_excluded":
        return []

    multipliers = {**AXIS2_SCALE_DEFAULTS, **(axis2_multipliers or {})}
    scale = multipliers.get(scenario_axis2, 1.0)

    rows = conn.execute(
        """
        SELECT event_date, impact_parameter, impact_value, effect_lag_months
        FROM regulatory_events
        WHERE impact_target = 'penetration'
        ORDER BY event_date, impact_parameter
        """
    ).fetchall()

    events: List[EventAdjustment] = []

    for row in rows:
        event_date = row["event_date"]
        param      = row["impact_parameter"]
        raw_value  = row["impact_value"]
        lag        = int(row["effect_lag_months"])

        if raw_value is None:
            continue

        scaled  = raw_value * scale
        n_steps = max(lag, 1)
        per_step = scaled / n_steps

        # 予測配列における 1-based 月オフセット
        # （event_date == forecast_start のとき base_offset = 1）
        base_offset = _months_between(forecast_start, event_date) + 1

        for step in range(n_steps):
            mo = base_offset + step
            if mo < 1 or mo > horizon:
                continue

            # イベント開始月・L_delta の第 1 ステップのみラベルを付与（プロット用）
            label = (
                f"{event_date} 制度変更"
                if step == 0 and param == "pen_L_delta"
                else ""
            )

            if param == "pen_L_delta":
                events.append(
                    EventAdjustment(month_offset=mo, ceiling_delta=per_step, label=label)
                )
            elif param == "pen_k_delta":
                events.append(
                    EventAdjustment(month_offset=mo, speed_delta=per_step, label=label)
                )

    return events
