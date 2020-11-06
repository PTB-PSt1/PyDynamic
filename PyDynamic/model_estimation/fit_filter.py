# -*- coding: utf-8 -*-
"""
The module :mod:`PyDynamic.model_estimation.fit_filter` contains several functions to
carry out a least-squares fit to a given complex frequency response and the design of
digital deconvolution filters by least-squares fitting to the reciprocal of a given
frequency response each with associated uncertainties.

This module contains the following functions:

* :func:`LSIIR`: Least-squares IIR filter fit to a given frequency response
* :func:`LSFIR`: Least-squares fit of a digital FIR filter to a given frequency
  response
* :func:`invLSFIR`: Least-squares fit of a digital FIR filter to the reciprocal of a
  given frequency response.
* :func:`invLSFIR_unc`: Design of FIR filter as fit to reciprocal of frequency response
  values with uncertainty
* :func:`invLSFIR_uncMC`: Design of FIR filter as fit to reciprocal of frequency
  response values with uncertainty via Monte Carlo
* :func:`invLSIIR`: Design of a stable IIR filter as fit to reciprocal of frequency
  response values
* :func:`invLSIIR_unc`: Design of a stable IIR filter as fit to reciprocal of frequency
  response values with uncertainty

"""
from typing import Optional, Tuple
from warnings import warn

import numpy as np
import scipy.signal as dsp

from ..misc.filterstuff import grpdelay, mapinside

__all__ = [
    "LSIIR",
    "LSFIR",
    "invLSFIR",
    "invLSFIR_unc",
    "invLSIIR",
    "invLSIIR_unc",
    "invLSFIR_uncMC"
    ]


def _fitIIR(
    Hvals: np.ndarray,
    tau: int,
    w: np.ndarray,
    E: np.ndarray,
    Na: int,
    Nb: int,
    inv: bool = False
) -> Tuple[np.ndarray, np.ndarray]:
    r"""The actual fitting routing for the least-squares IIR filter.

    Parameters
    ----------
    Hvals : np.ndarray of shape (M,)
        (complex) frequency response values
    tau : integer
        initial estimate of time delay
    w : np.ndarray
        :math:`2 * \pi * f / Fs`
    E : np.ndarray
        :math:`exp(-1j * np.dot(w[:, np.newaxis], Ns.T))`
    Nb : int
        numerator polynomial order
    Na : int
        denominator polynomial order
    inv : bool, optional
        If True the least-squares fitting is performed for the reciprocal, if False
        (default) for the actual frequency response

    Returns
    -------
    b : np.ndarray
        The IIR filter numerator coefficient vector in a 1-D sequence.
    a : np.ndarray
        The IIR filter denominator coefficient vector in a 1-D sequence.
    """
    exponent = -1 if inv else 1
    Ea = E[:, 1:Na + 1]
    Eb = E[:, :Nb + 1]
    Htau = np.exp(-1j * w * tau) * Hvals ** exponent
    HEa = np.dot(np.diag(Htau), Ea)
    D = np.hstack((HEa, -Eb))
    Tmp1 = np.real(np.dot(np.conj(D.T), D))
    Tmp2 = np.real(np.dot(np.conj(D.T), -Htau))
    ab = np.linalg.lstsq(Tmp1, Tmp2, rcond=None)[0]
    a = np.hstack((1.0, ab[:Na]))
    b = ab[Na:]
    return b, a


def LSIIR(
    Hvals: np.ndarray,
    Nb: int,
    Na: int,
    f: np.ndarray,
    Fs: float,
    tau: Optional[int] = 0,
    justFit: Optional[bool] = False,
    verbose: Optional[bool] = True,
    max_stab_iter: Optional[int] = 50,
    inv: Optional[bool] = False,
    UHvals: Optional[np.ndarray] = None,
    mc_runs: Optional[int] = 1000,
) -> Tuple[np.ndarray, np.ndarray, int]:
    """Least-squares IIR filter fit to a given frequency response or its reciprocal

    For the forward problem this method uses Gauss-Newton non-linear optimization.
    For the inverse problem it uses the equation-error method. The filter then is
    stabilized by pole mapping and introduction of a time delay. Associated
    uncertainties are optionally propagated when provided using the Monte Carlo method.
    
    Parameters
    ----------
    Hvals : array_like of shape (M,)
        (Complex) frequency response values.
    Nb : int
        Order of IIR numerator polynomial.
    Na : int
        Order of IIR denominator polynomial.
    f : array_like of shape (M,)
        Frequencies at which `Hvals` is given.
    Fs : float
        Sampling frequency for digital IIR filter.
    tau : int, optional
        Initial estimate of time delay for filter stabilization (default = 0). If
        `justFit = True` this parameter is not used and `tau = 0` will be returned.
    justFit : bool, optional
        If True then no stabilization is carried out, if False  (default) filter is
        stabilized. This parameter is only available for reasons of backward
        compatibility. Please use `max_stab_iter = 0` from now on and leave `justFit`
        untouched. `justFit` will be removed in a future release.
    verbose : bool, optional
        If True (default) be more talkative on stdout. Otherwise no output is written
        anywhere.
    max_stab_iter : int, optional
        Maximum count of iterations for stabilizing the resulting filter. If no
        stabilization is should be carried out, this parameter can be set to 0.
        Default is 50
    inv : bool, optional
        If False (default) apply the forward method, otherwise perform the fit for
        the reciprocal of the frequency response.
    UHvals : array_like of shape (2M, 2M), optional
        Uncertainties associated with real and imaginary part of H.
    mc_runs : int, optional
        Number of Monte Carlo runs (default = 1000)
    
    Returns
    -------
    b : np.ndarray
        The IIR filter numerator coefficient vector in a 1-D sequence.
    a : np.ndarray
        The IIR filter denominator coefficient vector in a 1-D sequence.
    tau : int
        Filter time delay (in samples).
    # TODO adapt comment to final implementation
    Uab : np.ndarray of shape (Nb+Na+1, Nb+Na+1)
        Uncertainties associated with [a[1:],b] based on `UHvals`.

    References
    ----------
    * Eichstädt et al. 2010 [Eichst2010]_
    * Vuerinckx et al. 1996 [Vuer1996]_

    .. seealso:: :func:`PyDynamic.uncertainty.propagate_filter.IIRuncFilter`
    """
    def check_stability(denominator_coeff: np.ndarray) -> bool:
        """Determine if filter with certain denominator coefficients is stable

        Parameters
        ----------
        denominator_coeff : array_like
            The filter denominator coefficient vector in a 1-D sequence.

        Returns
        -------
        bool
            True if filter designed with denominator coefficients `denominator_coeff`
            is stable, False otherwise.
        """
        return np.count_nonzero(np.abs(np.roots(denominator_coeff)) > 1) > 0

    if UHvals:
        # Step 1: Propagation of uncertainties to frequency response

        # Draw real and imaginary parts of frequency response values with white noise.
        HRI = np.random.multivariate_normal(mean=np.hstack((np.real(Hvals), np.imag(
            Hvals))), cov=UHvals, size=mc_runs)
        HHvals = HRI[:, : len(f)] + 1j * HRI[:, len(f):]

    if verbose:
        monte_carlo_message = f" Uncertainties of the filter coefficients are " \
                              f"evaluated using the GUM S2 Monte Carlo method " \
                              f"with {mc_runs} runs."
        print(
            f"LSIIR: Least-squares fit of an order {max(Nb, Na)} digital IIR filter to"
            f"{' the reciprocal of' if inv else ''} a frequency response "
            f"given by {len(Hvals)} values.{monte_carlo_message if UHvals else ''}"
            )

    # Initialize the warning message in case the final filter will still be unstable.
    warning_unstable = "CAUTION - The algorithm did NOT result in a stable IIR filter!"
# TODO rewrite this part to incorporate the MC method if needed.
    # In case we have a covariance matrix for (the reciprocal of) the frequency
    # response values given, we propagate the corresponding uncertainties using the
    # Monte Carlo method.
    if UHvals:

        # Prepare and conduct actual fit.
        w = 2 * np.pi * f / Fs
        Ns = np.arange(0, max(Nb, Na) + 1)[:, np.newaxis]
        E = np.exp(-1j * np.dot(w[:, np.newaxis], Ns.T))
        b, a = _fitIIR(Hvals, tau, w, E, Na, Nb, inv=inv)

        # Determine if the computed filter already is stable.
        unstable = not check_stability(a)

        # In case the user specified not to check for stability and stabilize the filter
        # if necessary, we just return the result so far and inform
        if justFit:
            if verbose:
                sos = np.sum(
                    np.abs((dsp.freqz(b, a, 2 * np.pi * f / Fs)[1] - Hvals) ** 2))
                if unstable:
                    print(f"LSIIR: Calculation done. No stabilization requested"
                          f". {warning_unstable if unstable else ''}Final sum of squares = "
                          f"{sos}")
            # Since no stabilization was done, we return tau = 0 regardless of the
            # desired initial estimate of the time delay provided for the stabilization.
            return b, a, 0

        # Initialize counter which we use to report about required iteration count.
        current_stab_iter = 1
        while unstable and current_stab_iter < max_stab_iter:
            # Stabilize filter coefficients with a maximum of 50 iterations.
            astab = mapinside(a)
            g1 = grpdelay(b, a, Fs)[0]
            g2 = grpdelay(b, astab, Fs)[0]
            tau = np.ceil(tau + np.median(g2 - g1))

            b, a = _fitIIR(Hvals, tau, w, E, Na, Nb, inv=inv)

            # Prepare abortion in case filter is stable.
            if check_stability(a):
                unstable = False
            current_stab_iter += 1
########################################################################################
    if verbose:
        if unstable:
            print(f"LSIIR: {warning_unstable} Maybe try again with a higher value of "
                  f"tau or a higher filter order? Least squares fit finished after "
                  f"{current_stab_iter} stabilization iterations (tau = {tau}).")

        Hd = dsp.freqz(b, a, 2 * np.pi * f / Fs)[1]
        Hd = Hd * np.exp(1j * 2 * np.pi * f / Fs * tau)
        res = np.hstack(
            (np.real(Hd) - np.real(Hvals), np.imag(Hd) - np.imag(Hvals)))
        rms = np.sqrt(np.sum(res ** 2) / len(f))
        print(f"LSIIR: Final rms error = {rms}.\n\n")

    return b, a, int(tau)


def LSFIR(H, N, tau, f, Fs, Wt=None):
    """
    Least-squares fit of a digital FIR filter to a given frequency response.

    Parameters
    ----------
        H : (complex) frequency response values of shape (M,)
        N : FIR filter order
        tau : delay of filter
        f : frequencies of shape (M,)
        Fs : sampling frequency of digital filter
        Wt : (optional) vector of weights of shape (M,) or shape (M,M)

    Returns
    -------
        filter coefficients bFIR (ndarray) of shape (N+1,)

    """

    print("\nLeast-squares fit of an order %d digital FIR filter to the" % N)
    print("reciprocal of a frequency response given by %d values.\n" % len(H))

    H = H[:, np.newaxis]

    w = 2 * np.pi * f / Fs
    w = w[:, np.newaxis]

    ords = np.arange(N + 1)[:, np.newaxis]
    ords = ords.T

    E = np.exp(-1j * np.dot(w, ords))

    if Wt is not None:
        if len(np.shape(Wt)) == 2:  # is matrix
            weights = np.diag(Wt)
        else:
            weights = np.eye(len(f)) * Wt
        X = np.vstack(
            [np.real(np.dot(weights, E)), np.imag(np.dot(weights, E))])
    else:
        X = np.vstack([np.real(E), np.imag(E)])

    H = H * np.exp(1j * w * tau)
    iRI = np.vstack([np.real(1.0 / H), np.imag(1.0 / H)])

    bFIR, res = np.linalg.lstsq(X, iRI)[:2]

    if not isinstance(res, np.ndarray):
        print(
            "Calculation of FIR filter coefficients finished with residual "
            "norm %e" % res)

    return np.reshape(bFIR, (N + 1,))


def invLSFIR(H, N, tau, f, Fs, Wt=None):
    """	Least-squares fit of a digital FIR filter to the reciprocal of a given
    frequency response.

    Parameters
    ----------
        H: np.ndarray of shape (M,) and dtype complex
            frequency response values
        N: int
            FIR filter order
        tau: float
            delay of filter
        f: np.ndarray of shape (M,)
            frequencies
        Fs: float
            sampling frequency of digital filter
        Wt: np.ndarray of shape (M,) - optional
            vector of weights

    Returns
    -------
        bFIR: np.ndarray of shape (N,)
            filter coefficients

    References
    ----------
        * Elster and Link [Elster2008]_

    .. see_also ::mod::`PyDynamic.uncertainty.propagate_filter.FIRuncFilter`

    """

    print("\nLeast-squares fit of an order %d digital FIR filter to the" % N)
    print("reciprocal of a frequency response given by %d values.\n" % len(H))

    H = H[:, np.newaxis]  # extend to matrix-like for simplified algebra

    w = 2 * np.pi * f / Fs  # set up radial frequencies
    w = w[:, np.newaxis]

    ords = np.arange(N + 1)[:, np.newaxis]  # set up design matrix
    ords = ords.T

    E = np.exp(-1j * np.dot(w, ords))

    if Wt is not None:  # set up weighted design matrix if necessary
        if len(np.shape(Wt)) == 2:  # is matrix
            weights = np.diag(Wt)
        else:
            weights = np.eye(len(f)) * Wt
        X = np.vstack([np.real(np.dot(weights, E)), np.imag(np.dot(weights, E))])
    else:
        X = np.vstack([np.real(E), np.imag(E)])

    Hs = H * np.exp(1j * w * tau)  # apply time delay for improved fit quality
    iRI = np.vstack([np.real(1.0 / Hs), np.imag(1.0 / Hs)])

    bFIR, res = np.linalg.lstsq(X, iRI)[:2]  # the actual fitting

    if (not isinstance(res, np.ndarray)) or (len(res) == 1):  # summarise results
        print(
            "Calculation of FIR filter coefficients finished with residual "
            "norm %e" % res
        )
        Hd = dsp.freqz(bFIR, 1, 2 * np.pi * f / Fs)[1]
        Hd = Hd * np.exp(1j * 2 * np.pi * f / Fs * tau)
        res = np.hstack((np.real(Hd) - np.real(H), np.imag(Hd) - np.imag(H)))
        rms = np.sqrt(np.sum(res ** 2) / len(f))
        print("Final rms error = %e \n\n" % rms)

    return bFIR.flatten()


def invLSFIR_unc(H, UH, N, tau, f, Fs, wt=None, verbose=True, trunc_svd_tol=None):
    """Design of FIR filter as fit to reciprocal of frequency response values
    with uncertainty


    Least-squares fit of a digital FIR filter to the reciprocal of a
    frequency response
    for which associated uncertainties are given for its real and imaginary
    part.
    Uncertainties are propagated using a truncated svd and linear matrix
    propagation.

    Parameters
    ----------
        H: np.ndarray of shape (M,)
            frequency response values
        UH: np.ndarray of shape (2M,2M)
            uncertainties associated with the real and imaginary part
        N: int
            FIR filter order
        tau: float
            delay of filter
        f: np.ndarray of shape (M,)
            frequencies
        Fs: float
            sampling frequency of digital filter
        wt: np.ndarray of shape (2M,) - optional
            array of weights for a weighted least-squares method (default = None
            results in no weighting)
        verbose: bool, optional
            whether to print statements to the command line (default = True)
        trunc_svd_tol: float, optional
            lower bound for singular values to be considered for pseudo-inverse

    Returns
    -------
        b: np.ndarray of shape (N+1,)
            filter coefficients of shape
        Ub: np.ndarray of shape (N+1,N+1)
            uncertainties associated with b

    References
    ----------
        * Elster and Link [Elster2008]_
    """

    if verbose:
        print("\nLeast-squares fit of an order %d digital FIR filter to the" % N)
        print("reciprocal of a frequency response given by %d values" % len(H))
        print("and propagation of associated uncertainties.")

    # Step 1: Propagation of uncertainties to reciprocal of frequency response
    runs = 10000
    Nf = len(f)

    if not len(H) == UH.shape[0]:
        # Assume that H is given as complex valued frequency response.
        RI = np.hstack((np.real(H), np.imag(H)))
    else:
        RI = H.copy()
        H = H[:Nf] + 1j * H[Nf:]
    HRI = np.random.multivariate_normal(RI, UH, runs)  # random draws of real,imag of
    # freq response values
    omtau = 2 * np.pi * f / Fs * tau

    # Vectorized Monte Carlo for propagation to inverse
    absHMC = HRI[:, :Nf] ** 2 + HRI[:, Nf:] ** 2
    HiMC = np.hstack(((HRI[:, :Nf] * np.tile(np.cos(omtau), (runs, 1)) +
                       HRI[:, Nf:] * np.tile(np.sin(omtau), (runs, 1))) /
                      absHMC,
                      (HRI[:, Nf:] * np.tile(np.cos(omtau), (runs, 1)) -
                       HRI[:, :Nf] * np.tile(np.sin(omtau), (runs, 1))) /
                      absHMC))
    UiH = np.cov(HiMC, rowvar=False)

    # Step 2: Fit filter coefficients and evaluate uncertainties
    if isinstance(wt, np.ndarray):
        if wt.shape != np.diag(UiH).shape[0]:
            raise ValueError("invLSFIR_unc: User-defined weighting has wrong "
                             "dimension. wt is expected to be of length "
                             f"{2 * Nf} but is of length {wt.shape}.")
    else:
        wt = np.ones(2 * Nf)

    E = np.exp(-1j * 2 * np.pi * np.dot(f[:, np.newaxis] / Fs,
                                        np.arange(N + 1)[:, np.newaxis].T))
    X = np.vstack((np.real(E), np.imag(E)))
    X = np.dot(np.diag(wt), X)
    Hm = H * np.exp(1j * 2 * np.pi * f / Fs * tau)
    Hri = np.hstack((np.real(1.0 / Hm), np.imag(1.0 / Hm)))

    u, s, v = np.linalg.svd(X, full_matrices=False)
    if isinstance(trunc_svd_tol, float):
        s[s < trunc_svd_tol] = 0.0
    StSInv = np.zeros_like(s)
    StSInv[s > 0] = s[s > 0] ** (-2)

    M = np.dot(np.dot(np.dot(v.T, np.diag(StSInv)), np.diag(s)), u.T)

    bFIR = np.dot(M, Hri[:, np.newaxis])  # actual fitting
    UbFIR = np.dot(np.dot(M, UiH), M.T)  # evaluation of uncertainties

    bFIR = bFIR.flatten()

    if verbose:
        Hd = dsp.freqz(bFIR, 1, 2 * np.pi * f / Fs)[1]
        Hd = Hd * np.exp(1j * 2 * np.pi * f / Fs * tau)
        res = np.hstack((np.real(Hd) - np.real(H), np.imag(Hd) - np.imag(H)))
        rms = np.sqrt(np.sum(res ** 2) / len(f))
        print("Final rms error = %e \n\n" % rms)

    return bFIR, UbFIR


def invLSFIR_uncMC(H, UH, N, tau, f, Fs, wt=None, verbose=True):
    """Design of FIR filter as fit to reciprocal of frequency response values
    with uncertainty

    Least-squares fit of a FIR filter to the reciprocal of a frequency response
    for which associated uncertainties are given for its real and imaginary
    parts.
    Uncertainties are propagated using a Monte Carlo method. This method may
    help in cases where
    the weighting matrix or the Jacobian are ill-conditioned, resulting in
    false uncertainties
    associated with the filter coefficients.

    Parameters
    ----------
        H: np.ndarray of shape (M,) and dtype complex
            frequency response values
        UH: np.ndarray of shape (2M,2M)
            uncertainties associated with the real and imaginary part of H
        N: int
            FIR filter order
        tau: int
            time delay of filter in samples
        f: np.ndarray of shape (M,)
            frequencies corresponding to H
        Fs: float
            sampling frequency of digital filter
        wt: np.ndarray of shape (2M,) - optional
            array of weights for a weighted least-squares method (default = None
            results in no weighting)
        verbose: bool, optional
            whether to print statements to the command line (default = True)

    Returns
    -------
        b: np.ndarray of shape (N+1,)
            filter coefficients of shape
        Ub: np.ndarray of shape (N+1, N+1)
            uncertainties associated with b

    References
    ----------
        * Elster and Link [Elster2008]_
    """

    if verbose:
        print("\nLeast-squares fit of an order %d digital FIR filter to the" % N)
        print("reciprocal of a frequency response given by %d values" % len(H))
        print("and propagation of associated uncertainties.")

    # Step 1: Propagation of uncertainties to reciprocal of frequency response
    runs = 10000
    HRI = np.random.multivariate_normal(np.hstack((np.real(H), np.imag(H))), UH, runs)

    # Step 2: Fitting the filter coefficients
    Nf = len(f)
    if isinstance(wt, np.ndarray):
        if wt.shape != 2 * Nf:
            raise ValueError("invLSFIR_uncMC: User-defined weighting has wrong "
                             "dimension. wt is expected to be of length "
                             f"{2 * Nf} but is of length {wt.shape}.")
    else:
        wt = np.ones(2 * Nf)

    E = np.exp(-1j * 2 * np.pi * np.dot(f[:, np.newaxis] / Fs,
                                        np.arange(N + 1)[:, np.newaxis].T))
    X = np.vstack((np.real(E), np.imag(E)))
    X = np.dot(np.diag(wt), X)
    bF = np.zeros((N + 1, runs))
    resn = np.zeros((runs,))
    for k in range(runs):
        Hk = HRI[k, :Nf] + 1j * HRI[k, Nf:]
        Hkt = Hk * np.exp(1j * 2 * np.pi * f / Fs * tau)
        iRI = np.hstack([np.real(1.0 / Hkt), np.imag(1.0 / Hkt)])
        bF[:, k], res = np.linalg.lstsq(X, iRI)[:2]
        resn[k] = np.linalg.norm(res)

    bFIR = np.mean(bF, axis=1)
    UbFIR = np.cov(bF, rowvar=True)

    return bFIR, UbFIR


def invLSIIR(Hvals, Nb, Na, f, Fs, tau, justFit=False, verbose=True):
    """Least-squares IIR filter fit to the reciprocal of given frequency response values

    Least-squares fit of a digital IIR filter to the reciprocal of a given set
    of frequency response values using the equation-error method and
    stabilization by pole mapping and introduction of a time delay.

    Parameters
    ----------
    Hvals : array_like of shape (M,)
        (Complex) frequency response values.
    Nb : int
        Order of IIR numerator polynomial.
    Na : int
        Order of IIR denominator polynomial.
    f : array_like of shape (M,)
        Frequencies at which `Hvals` is given.
    Fs : float
        Sampling frequency for digital IIR filter.
    tau : int, optional
        Initial estimate of time delay for filter stabilization (default = 0). If
        `justFit = True` this parameter is not used and `tau = 0` will be returned.
    justFit : bool, optional
        If True then no stabilization is carried out, if False  (default) filter is
        stabilized.
    verbose : bool, optional
        If True (default) be more talkative on stdout. Otherwise no output is written
        anywhere.

    Returns
    -------
    b : array_like
        The IIR filter numerator coefficient vector in a 1-D sequence.
    a : array_like
        The IIR filter denominator coefficient vector in a 1-D sequence.
    tau : int
        Filter time delay (in samples).

    References
    ----------
    * Eichstädt, Elster, Esward, Hessling [Eichst2010]_

    """
    warn("invLSIIR: The method invLSIIR() will be removed in the next major release "
         "3.0.0. Please switch to the current method LSIIR() with the same input "
         "parameters as in your call of invLSIIR in the same order and "
         "additionally specify inv=True.", PendingDeprecationWarning)
    return LSIIR(Hvals=Hvals, Nb=Nb, Na=Na, f=f, Fs=Fs, tau=tau, justFit=justFit,
                 verbose=verbose, inv=True)


# TODO continue introducing this logic into LSIIR based on UHvals=None or not
def invLSIIR_unc(H, UH, Nb, Na, f, Fs, tau=0):
    """Design of stabel IIR filter as fit to reciprocal of given frequency
    response with uncertainty

    Least-squares fit of a digital IIR filter to the reciprocal of a given set
    of frequency response values with given associated uncertainty.
    Propagation of uncertainties is
    carried out using the Monte Carlo method.

    Parameters
    ----------

        H: np.ndarray of shape (M,) and dtype complex
            frequency response values.
        UH: np.ndarray of shape (2M,2M)
            uncertainties associated with real and imaginary part of H
        Nb: int
            order of IIR numerator polynomial.
        Na: int
            order of IIR denominator polynomial.
        f: np.ndarray of shape (M,)
            frequencies corresponding to H
        Fs: float
            sampling frequency for digital IIR filter.
        tau: float
            initial estimate of time delay for filter stabilization.

    Returns
    -------
        b,a: np.ndarray
            IIR filter coefficients
        tau: int
            time delay (in samples)
        Uba: np.ndarray of shape (Nb+Na+1, Nb+Na+1)
            uncertainties associated with [a[1:],b]

    References
    ----------
        * Eichstädt, Elster, Esward and Hessling [Eichst2010]_

    .. seealso:: :mod:`PyDynamic.uncertainty.propagate_filter.IIRuncFilter`
                 :mod:`PyDynamic.model_estimation.fit_filter.invLSIIR`
    """

    runs = 1000

    print("\nLeast-squares fit of an order %d digital IIR filter to the" % max(Nb, Na))
    print("reciprocal of a frequency response given by %d values.\n" % len(H))
    print(
        "Uncertainties of the filter coefficients are evaluated using\n"
        "the GUM S2 Monte Carlo method with %d runs.\n" % runs
    )

    # Step 1: Propagation of uncertainties to frequency response
    HRI = np.random.multivariate_normal(np.hstack((np.real(H), np.imag(H))), UH, runs)
    HH = HRI[:, : len(f)] + 1j * HRI[:, len(f) :]
# TODO From here on the logic needs to be transferred into lines 204--248.
    # Step 2: Fit filter and evaluate uncertainties (Monte Carlo method)
    AB = np.zeros((runs, Nb + Na + 1))
    Tau = np.zeros((runs,))
    for k in range(runs):
        bi, ai, Tau[k] = invLSIIR(HH[k, :], Nb, Na, f, Fs, tau, verbose=False)
        AB[k, :] = np.hstack((ai[1:], bi))

    bi = np.mean(AB[:, Na:], axis=0)
    ai = np.hstack((np.array([1.0]), np.mean(AB[:, :Na], axis=0)))
    Uab = np.cov(AB, rowvar=False)
    tau = np.mean(Tau)
    return bi, ai, tau, Uab
