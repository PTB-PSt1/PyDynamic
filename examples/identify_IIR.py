# -*- coding: utf-8 -*-
"""
.. moduleauthor:: Sascha Eichstaedt (sascha.eichstaedt@ptb.de)

    Fit of an IIR filter to a simulated frequency response of a second-order dynamic system. 
    This is a python script which can, for instance, be run directly by calling "python identify_IIR.py" from
    a command line.
    
    Try to play with this script by changing the parameters of the 2nd order system or the order of the fitted filter.
    
.. seealso:: :mod:`ADM.identification.fit_filter`
"""
# if run as script, add parent path for relative importing
if __name__ == "__main__" and __package__ is None:
	from os import sys, path
	sys.path.append(path.dirname(path.dirname(path.abspath(__file__))))

import numpy as np
from scipy.signal import freqz
from matplotlib.pyplot import figure, cla, show


from misc.filterstuff import db
import identification.fit_filter as fit_filter
from misc.SecondOrderSystem import FreqResp

#%% sensor/measuring system

f0 = 36e3           # system resonance frequency in Hz
S0 = 0.124          # system static gain
delta = 0.0055      # system damping

f = np.linspace(0, 80e3, 30)               # frequencies for fitting the system
Hvals = FreqResp(S0, delta, f0, f)      # frequency response of the 2nd order system

#%% fitting the IIR filter

Fs = 500e3          # sampling frequency
Na = 4; Nb = 4     # IIR filter order (Na - denominator, Nb - numerator)

b, a, tau = fit_filter.LSIIR(Hvals, Na, Nb, f, Fs)

#%% plot the result

fplot = np.linspace(0, 80e3, 1000)             # frequency range for the plot
Hc = FreqResp(S0, delta, f0, fplot)         # frequency response of the 2nd order system
Hf = freqz(b, a, 2 * np.pi * fplot / Fs)[1]    # frequency response of the fitted IIR filter
Hf = Hf*np.exp(2j*np.pi*fplot/Fs*tau)             # take into account the filter time delay tau

fig1 = figure(1); cla()
ax1 = fig1.add_subplot(111)
ax1.plot(fplot, db(Hc), "+",fplot, db(Hf))
ax1.legend(('System', 'LSIIR fit'))
ax1.set_xlabel("frequency / Hz",fontsize=18)
ax1.set_ylabel("freq. response amplitude / a.u.",fontsize=18)

fig2 = figure(2); cla()
ax2 = fig2.add_subplot(111)
ax2.plot(fplot, np.angle(Hc), "+",fplot, np.angle(Hf))
ax2.legend(('System', 'LSIIR fit'))
ax2.set_xlabel("frequency / Hz",fontsize=18)
ax2.set_ylabel("freq. response angle / rad",fontsize=18)

show()
