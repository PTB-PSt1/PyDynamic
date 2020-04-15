# -*- coding: utf-8 -*-
""" Perform tests on the method *make_equidistant*."""
from typing import Dict, Tuple, Union

import hypothesis.extra.numpy as hnp
import hypothesis.strategies as st
import numpy as np
from hypothesis import assume, given
from hypothesis.strategies import composite, nothing
from pytest import raises

from PyDynamic.misc.tools import make_equidistant

n = 50
t, y, uy, dt, kind = (
    np.linspace(0, 1, n),
    np.random.uniform(size=n),
    np.random.uniform(size=n),
    5e-2,
    "previous",
)


@composite
def timestamps_values_uncertainties_kind(
    draw,
    min_count: int = 2,
    max_count: int = None,
    kind_tuple: Tuple[str] = ("linear", "previous", "next", "nearest"),
) -> Dict[str, Union[np.ndarray, str]]:
    """Set custom strategy for _hypothesis_ to draw desired input from

    Parameters
    ----------
        draw: callable
            this is a hypothesis internal callable to actually draw from provided
            strategies
        min_count: int
            the minimum number of elements expected inside the arrays of timestamps,
            measurement values and associated uncertainties
        max_count: int
            the maximum number of elements expected inside the arrays of timestamps,
            measurement values and associated uncertainties
        kind_tuple: tuple(str), optional
            the tuple of strings out of "linear", "previous", "next", "nearest",
            "spline", "lagrange", "least-squares" from which the strategy for the
            kind randomly chooses. Defaults to the valid options "linear",
            "previous", "next", "nearest".

    Returns
    -------
        A dict containing the randomly generated expected input parameters t, y, uy,
        dt, kind for make_equidistant()
    """
    # Set all common parameters for timestamps, measurements values and associated
    # uncertainties including allowed ranges and number of elements.
    shape_for_timestamps = hnp.array_shapes(
        max_dims=1, min_side=min_count, max_side=max_count
    )
    strategy_params = {
        "dtype": np.float,
        "shape": shape_for_timestamps,
        "elements": st.floats(
            min_value=0, max_value=1e300, allow_nan=False, allow_infinity=False
        ),
        "unique": True,
    }
    # Draw "original" timestamps.
    t = draw(hnp.arrays(**strategy_params))
    # Sort timestamps in ascending order.
    t.sort()
    # Reuse "original" timestamps shape for measurements values and associated
    # uncertainties and draw both.
    strategy_params["shape"] = np.shape(t)
    y = draw(hnp.arrays(**strategy_params))
    uy = draw(hnp.arrays(**strategy_params))
    dt = draw(
        st.floats(
            min_value=(np.max(t) - np.min(t)) * 1e-3,
            max_value=np.max(t) - np.min(t),
            exclude_min=True,
            allow_nan=False,
            allow_infinity=False,
        )
    )
    kind = draw(st.sampled_from(kind_tuple))
    return {"t": t, "y": y, "uy": uy, "dt": dt, "kind": kind}


@given(timestamps_values_uncertainties_kind())
def test_too_short_call_make_equidistant(interp_inputs):
    # Check erroneous calls with too few inputs.
    with raises(TypeError):
        make_equidistant(interp_inputs["t"])
        make_equidistant(interp_inputs["t"], interp_inputs["y"])


@given(timestamps_values_uncertainties_kind())
def test_full_call_make_equidistant(interp_inputs):
    assume(interp_inputs["t"][0] < interp_inputs["t"][-1])
    t_new, y_new, uy_new = make_equidistant(**interp_inputs)
    # Check the equal dimensions of the minimum calls output.
    assert len(t_new) == len(y_new) == len(uy_new)


# @given(timestamps_values_uncertainties_kind())
# def test_wrong_input_lengths_call_make_equidistant(interp_inputs):
#     # Check erroneous calls with unequally long inputs.
#     with raises(ValueError):
#         y_wrong = np.tile(interp_inputs["y"], 2)
#         uy_wrong = np.tile(interp_inputs["uy"], 3)
#         make_equidistant(interp_inputs["t"], y_wrong, uy_wrong)
#
#
# def test_wrong_input_order_call_make_equidistant():
#     # Check erroneous calls with not ascending timestamps.
#     with raises(ValueError):
#         # Assure first and last value are correctly ordered and COUNT matches.
#         t_wrong = np.empty_like(t)
#         t_wrong[0] = t[0]
#         t_wrong[-1] = t[-1]
#         t_wrong[1:-1] = -np.sort(-t[1:-1])
#         make_equidistant(t_wrong, y, uy)
#
#
# def test_minimal_call_make_equidistant():
#     # Check the minimum working call.
#     t_new, y_new, uy_new = make_equidistant(t, y, uy)
#     # Check the equal dimensions of the minimum calls output.
#     assert len(t_new) == len(y_new) == len(uy_new)


def test_t_new_to_dt_make_equidistant():
    from numpy.testing import assert_almost_equal

    t_new = make_equidistant(t, y, uy, dt)[0]
    delta_t_new = np.diff(t_new)
    # Check if the new timestamps are ascending.
    assert np.all(delta_t_new > 0)
    # Check if the timesteps have the desired length.
    assert_almost_equal(delta_t_new - dt, 0)


@given(timestamps_values_uncertainties_kind(kind_tuple=("previous", "next", "nearest")))
def test_prev_in_make_equidistant(interp_inputs):
    assume(interp_inputs["t"][0] < interp_inputs["t"][-1])
    y_new, uy_new = make_equidistant(**interp_inputs)[1:3]
    # Check if all 'interpolated' values are present in the actual values.
    assert np.all(np.isin(y_new, interp_inputs["y"]))
    assert np.all(np.isin(uy_new, interp_inputs["uy"]))


@given(timestamps_values_uncertainties_kind(kind_tuple=["linear"]))
def test_linear_in_make_equidistant(interp_inputs):
    assume(interp_inputs["t"][0] < interp_inputs["t"][-1])
    y_new, uy_new = make_equidistant(**interp_inputs)[1:3]
    # Check if all interpolated values lie in the range of the original values.
    assert np.all(np.amin(interp_inputs["y"]) <= y_new)
    assert np.all(np.amax(interp_inputs["y"]) >= y_new)


def test_linear_uy_in_make_equidistant():
    # Check for given input, if interpolated uncertainties equal 1 and
    # :math:`sqrt(2) / 2`.
    dt_unit = 2
    t_unit = np.arange(0, n, dt_unit)
    y = np.ones_like(t_unit)
    uy_unit = np.ones_like(t_unit)
    dt_half = 1
    uy_new = make_equidistant(t_unit, y, uy_unit, dt_half, "linear")[2]
    assert np.all(uy_new[0:n:2] == 1) and np.all(uy_new[1:n:2] == np.sqrt(2) / 2)


@given(
    timestamps_values_uncertainties_kind(
        kind_tuple=("spline", "lagrange", "least-squares")
    )
)
def test_raise_not_implemented_yet_make_equidistant(interp_inputs):
    assume(interp_inputs["t"][0] < interp_inputs["t"][-1])
    # Check that not implemented versions raise exceptions.
    with raises(NotImplementedError):
        make_equidistant(**interp_inputs)
