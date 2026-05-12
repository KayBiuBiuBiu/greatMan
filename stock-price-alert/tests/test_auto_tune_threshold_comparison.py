"""auto_tune_selector_filters.validate_new_threshold_on_history 与格式化。"""

from __future__ import annotations

import pandas as pd

from auto_tune_selector_filters import (
    validate_new_threshold_on_history,
    _format_threshold_comparison_human,
)


def test_validate_new_threshold_on_history_improvement() -> None:
    df = pd.DataFrame(
        {
            "range_pos": [0.3, 0.4, 0.8, 0.9],
            "sell_side_max": [40.0, 40.0, 40.0, 40.0],
            "forward_ret": [0.02, 0.01, -0.01, -0.02],
        }
    )
    cmp = validate_new_threshold_on_history(
        df,
        old_range_max=0.5,
        old_sell_max=70.0,
        new_range_max=0.95,
        new_sell_max=70.0,
        require_range_pos=True,
    )
    assert cmp["old"]["n"] == 2
    assert cmp["new"]["n"] == 4
    assert cmp["improvement_mean_ret"] is not None
    assert cmp["improvement_win_rate"] is not None
    text = _format_threshold_comparison_human(
        cmp,
        old_range=0.5,
        old_sell=70.0,
        new_range=0.95,
        new_sell=70.0,
    )
    assert "旧过滤样本" in text
    assert "理论提升" in text
