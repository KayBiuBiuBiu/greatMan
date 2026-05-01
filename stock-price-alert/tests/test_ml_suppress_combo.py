# -*- coding: utf-8 -*-
import unittest

from run_alert import _dual_ml_trend_suppress


class TestDualMlTrendSuppress(unittest.TestCase):
    def test_any_either_low(self):
        s, nb, kl = _dual_ml_trend_suppress(
            nb_on=True,
            kl_on=True,
            ml_prob=0.2,
            k_prob=0.8,
            nb_th=0.6,
            k_th=0.3,
            combo="any",
        )
        self.assertTrue(s)
        self.assertTrue(nb)
        self.assertFalse(kl)

    def test_any_both_high(self):
        s, _, _ = _dual_ml_trend_suppress(
            nb_on=True,
            kl_on=True,
            ml_prob=0.9,
            k_prob=0.9,
            nb_th=0.6,
            k_th=0.3,
            combo="any",
        )
        self.assertFalse(s)

    def test_all_requires_both_when_both_on(self):
        s, _, _ = _dual_ml_trend_suppress(
            nb_on=True,
            kl_on=True,
            ml_prob=0.2,
            k_prob=0.8,
            nb_th=0.6,
            k_th=0.3,
            combo="all",
        )
        self.assertFalse(s)
        s2, _, _ = _dual_ml_trend_suppress(
            nb_on=True,
            kl_on=True,
            ml_prob=0.2,
            k_prob=0.1,
            nb_th=0.6,
            k_th=0.3,
            combo="all",
        )
        self.assertTrue(s2)

    def test_all_nb_only(self):
        s, _, _ = _dual_ml_trend_suppress(
            nb_on=True,
            kl_on=False,
            ml_prob=0.2,
            k_prob=None,
            nb_th=0.6,
            k_th=0.3,
            combo="all",
        )
        self.assertTrue(s)


if __name__ == "__main__":
    unittest.main()
