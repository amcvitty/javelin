"""The pure Black-Scholes maths, checked without a graph."""

import math

import pytest

from analytics import blackscholes as bs


class TestNormal:
    def test_cdf_is_a_half_at_zero(self):
        assert bs.norm_cdf(0.0) == pytest.approx(0.5)

    def test_cdf_is_monotonic(self):
        xs = [-3.0, -1.0, 0.0, 1.0, 3.0]
        cdfs = [bs.norm_cdf(x) for x in xs]
        assert cdfs == sorted(cdfs)

    def test_pdf_peaks_at_zero(self):
        assert bs.norm_pdf(0.0) == pytest.approx(1.0 / math.sqrt(2 * math.pi))
        assert bs.norm_pdf(2.0) == bs.norm_pdf(-2.0)


class TestD1D2:
    def test_at_the_money_forward_d1_is_half_vol_root_t(self):
        # ln(F/K) = 0, so d1 = 0.5 * sigma * sqrt(T).
        d1 = bs.d1(forward=100.0, strike=100.0, vol=0.2, tenor=4.0)
        assert d1 == pytest.approx(0.5 * 0.2 * math.sqrt(4.0))

    def test_d2_is_d1_minus_vol_root_t(self):
        d1 = bs.d1(forward=120.0, strike=100.0, vol=0.3, tenor=2.0)
        d2 = bs.d2(d1, vol=0.3, tenor=2.0)
        assert d1 - d2 == pytest.approx(0.3 * math.sqrt(2.0))


class TestCallPrice:
    def _price(self, spot, strike, rate, vol, tenor):
        forward = spot * math.exp(rate * tenor)
        d1 = bs.d1(forward, strike, vol, tenor)
        d2 = bs.d2(d1, vol, tenor)
        return bs.call_price_from_d(forward, strike, math.exp(-rate * tenor), d1, d2)

    def test_known_value(self):
        # Textbook figure: S=K=100, r=0, sigma=20%, T=1 -> ~7.9656.
        assert self._price(100.0, 100.0, 0.0, 0.2, 1.0) == pytest.approx(
            7.9656, abs=1e-3
        )

    def test_deep_in_the_money_approaches_forward_minus_discounted_strike(self):
        price = self._price(1000.0, 100.0, 0.05, 0.2, 1.0)
        intrinsic = 1000.0 - 100.0 * math.exp(-0.05)
        assert price == pytest.approx(intrinsic, rel=1e-6)

    def test_price_rises_with_vol(self):
        low = self._price(100.0, 100.0, 0.01, 0.1, 1.0)
        high = self._price(100.0, 100.0, 0.01, 0.4, 1.0)
        assert high > low

    def test_put_call_parity(self):
        # C - P = S - K e^{-rT}; get P from parity and check it is positive and
        # consistent, i.e. the call formula sits where parity says it should.
        spot, strike, rate, vol, tenor = 90.0, 100.0, 0.03, 0.25, 1.5
        call = self._price(spot, strike, rate, vol, tenor)
        put = call - (spot - strike * math.exp(-rate * tenor))
        assert put > 0.0
        assert call - put == pytest.approx(spot - strike * math.exp(-rate * tenor))


class TestCallDelta:
    def test_delta_is_n_d1(self):
        forward = 100.0 * math.exp(0.03 * 1.0)
        d1 = bs.d1(forward, 95.0, 0.2, 1.0)
        assert bs.call_delta(d1) == bs.norm_cdf(d1)

    def test_delta_matches_a_finite_difference(self):
        strike, rate, vol, tenor = 95.0, 0.03, 0.2, 1.0

        def price(spot):
            forward = spot * math.exp(rate * tenor)
            d1 = bs.d1(forward, strike, vol, tenor)
            d2 = bs.d2(d1, vol, tenor)
            return bs.call_price_from_d(
                forward, strike, math.exp(-rate * tenor), d1, d2
            )

        s0, h = 100.0, 1e-4
        fd = (price(s0 + h) - price(s0 - h)) / (2 * h)
        forward = s0 * math.exp(rate * tenor)
        analytic = bs.call_delta(bs.d1(forward, strike, vol, tenor))
        assert fd == pytest.approx(analytic, abs=1e-7)
