from __future__ import division, absolute_import, print_function
from past.builtins import xrange

import numpy as np
import scipy.optimize
import scipy.integrate
import copy
import os
import fitsio

from .utilities import gaussFunction
from .utilities import CubicSpline
from .catalog import Entry

class Zlambda(object):
    """

    Class for computing zlambda cluster redshift on clusters

    """

    def __init__(self, cluster):
        # We make a link to the parent cluster
        self.cluster_parent = cluster

        # Make a copy of the cluster for modifications
        # note that this makes a deep copy of the neighbors so we can modify at will.
        self.cluster = cluster.copy()

        # For convenience, make references to these structures
        self.zredstr = cluster.zredstr
        self.config = cluster.config
        self.cosmo = cluster.cosmo

    def calc_zlambda(self, zin, mask, maxmag_in=None, calcpz=False, calc_err=True,
                     correction=False, record_values=True):
        """
        compute z_lambda with uncertainty - Cluster Redshift Estimation
        from redmapper_zlambda.pro

        parameters
        ----------
        zin: input redshift
        mask: mask object
        calc_err: if False, no error calculated

        returns
        -------
        z_lambda: estimated cluster redshift
        z_lambda_err: uncertainty
        """

        z_lambda = copy.copy(zin)

        maxmag = self.zredstr.mstar(z_lambda) - 2.5*np.log10(self.config.lval_reference)
        if maxmag_in is not None:
            if maxmag_in.size == 1:
                maxmag = maxmag_in

        maxrad = 1.2 * self.cluster.r0 * 3.**self.cluster.beta

        self.niter = 0
        pzdone = False

        if not calc_err:
            z_lambda_e = 0.0

        # When running in p(z) mode, we might need a second iteration to zero-in on
        # the peak redshift (because this has slightly greater sensitivity while
        # being a bit slower, which we don't always need).
        for pz_iter in xrange(2):
            # skip second iteration if p(z) is converged
            if pzdone: break

            # This is the main iteration loop where we get consistency between
            # the member selection / richness / and redshift
            i = 0
            while i < self.config.zlambda_maxiter:
                # Update the redshift, and it also updates the neighbor r's
                self.cluster.redshift = z_lambda

                in_r, = np.where(self.cluster.neighbors.r < maxrad)

                if in_r.size < 1:
                    # Total fail, kick out
                    z_lambda = -1.0
                    break

                # compute the richness here, but don't store it.
                # This will compute neighbors.pcol which we can use for members to
                # compute z_lambda
                lam = self.cluster.calc_richness(mask, calc_err=False, index=in_r)

                if lam < self.config.percolation_minlambda:
                    # Total fail, kick out
                    z_lambda = -1.0
                    break

                wtvals_mod = self.cluster.neighbors.pcol

                if maxmag_in is not None:
                   maxmag = (self.zredstr.mstar(z_lambda) -
                       2.5 * np.log10(self.config.lval_reference))

                self._zlambda_select_neighbors(wtvals_mod, maxrad, maxmag)

                # break if too few neighbors
                if self.zlambda_fail:
                    z_lambda = -1.0
                    z_lambda_new = -1.0
                    break
                else:
                    # Compute the new z_lambda by fitting a parabola to the
                    # likelihood surface near the input z_lambda
                    z_lambda_new = self._zlambda_calcz(z_lambda)

                # check for convergence, but make sure we get at least 1 iteration
                if (i > 0 and (np.abs(z_lambda_new-z_lambda) < self.config.zlambda_tol or
                    z_lambda_new < 0.0)):
                    break

                z_lambda = z_lambda_new

                i += 1

            # Record number of iterations
            self.niter = i

            # If it's a valid z_lambda and we want to compute error...
            if z_lambda > 0.0 and calc_err:
                # Set the redshift here, since it's valid
                self.cluster.redshift = z_lambda

                if not calcpz:
                    # regular Gaussian error
                    z_lambda_e = self._zlambda_calc_gaussian_err(z_lambda)

                    # mark a failure
                    if z_lambda_e < 0.0:
                        z_lambda = -1.0
                        z_lamba_e = -1.0
                    pzdone = True
                else:
                    # Calculating p(z)
                    pzdone, z_lambda, z_lambda_e = self._zlambda_calc_pz_and_check(z_lambda, wtvals_mod, self.cluster.r_lambda, maxmag, convergence_warning=(pz_iter > 0))
                    #if not pzdone and pz_iter > 0 and z_lambda < 0.4 and z_lambda > 0.15 and self.cluster_parent.Lambda > 20.0 and self.cluster_parent.scaleval < 2.0:
                    #    asdljflkjasdf
            else:
                # Invalid z_lambda, we're done here.
                z_lambda_e = -1.0
                if calcpz:
                    # Put in dummy values for pzbins/pz
                    self.pzbins = np.zeros(self.config.npzbins)
                    self.pz = np.zeros_like(self.pzbins)

                pzdone = True

        # If we are told to record the values in the parent cluster, do so here.
        if record_values:
            self.cluster_parent.z_lambda = z_lambda
            self.cluster_parent.z_lambda_err = z_lambda_e

        self.z_lambda = z_lambda
        self.z_lambda_err = z_lambda_e

        return z_lambda, z_lambda_e

    def _zlambda_select_neighbors(self, wtvals, maxrad, maxmag):
        """
        select neighbours internal to r < maxrad

        parameters
        ----------
        wtvals: weights
        maxrad: maximum radius for considering neighbours
        maxmag: maximum magnitude for considering neighbours

        returns
        -------
        sets zrefmagbin, refmag, refmag_err, mag, mag_err, c, pw, targval
        for selected neighbors
        """
        topfrac = self.config.zlambda_topfrac

        #we need the zrefmagbin
        nzrefmag    = self.zredstr.refmagbins.size
        zrefmagbin  = np.clip(np.around(nzrefmag*(self.cluster.neighbors.refmag -
                                                  self.zredstr.refmagbins[0])/
                                        (self.zredstr.refmagbins[nzrefmag-2] -
                                         self.zredstr.refmagbins[0])), 0, nzrefmag-1)

        ncount = topfrac*np.sum(wtvals)
        # We need a check here for zero-weight members
        # FIXME: change wtvals to pcol (or p)
        use,   = np.where((self.cluster.neighbors.r < maxrad) &
                          (self.cluster.neighbors.refmag < maxmag) &
                          (wtvals > 0.0))

        if ncount < 3:
            ncount = 3

        #exit variable in case use.size < 3
        self.zlambda_fail = False
        if use.size < 3:
            self.zlambda_fail = True
            return

        if use.size < ncount:
            ncount = use.size

        st = np.argsort(wtvals[use])[::-1]
        pthresh = wtvals[use[st[np.int(np.around(ncount)-1)]]]

        pw  = 1./(np.exp((pthresh-wtvals[use])/0.04)+1)
        gd, = np.where(pw > 1e-3)

        # record these values
        self._zlambda_in_rad = use[gd]

        self._zlambda_zrefmagbin = zrefmagbin[self._zlambda_in_rad]
        self._zlambda_refmag = self.cluster.neighbors.refmag[self._zlambda_in_rad]
        self._zlambda_refmag_err = self.cluster.neighbors.refmag_err[self._zlambda_in_rad]
        self._zlambda_mag = self.cluster.neighbors.mag[self._zlambda_in_rad,:]
        self._zlambda_mag_err = self.cluster.neighbors.mag_err[self._zlambda_in_rad,:]
        self._zlambda_c = self.cluster.neighbors.galcol[self._zlambda_in_rad,:]
        self._zlambda_pw = pw[gd]
        self._zlambda_targval = 0

    def _zlambda_calcz(self, z_lambda):
        """
        calculate z_lambda

        parameters
        ----------
        z_lambda: input

        returns
        -------
        z_lambda: output
        """
        nsteps = 10
        steps = self.config.zlambda_parab_step * np.arange(nsteps) + z_lambda - self.config.zlambda_parab_step * (nsteps - 1) / 2
        likes = np.zeros(nsteps)
        for i in xrange(nsteps):
             likes[i] = self._bracket_fn(steps[i])
        fit = np.polyfit(steps, likes, 2)

        if fit[0] > 0.0:
            z_lambda = -fit[1]/(2.0 * fit[0])
        else:
            z_lambda = -1.0

        z_lambda = np.clip(z_lambda, steps[0] - self.config.zlambda_parab_step,
                           steps[-1] + self.config.zlambda_parab_step)

        return z_lambda


    def _bracket_fn(self, z):
        """
        bracketing function
        """
        likelihoods = self.zredstr.calculate_chisq(self.cluster.neighbors[self._zlambda_in_rad],
                                                   z, calc_lkhd=True)
        t = -np.sum(self._zlambda_pw*likelihoods)
        return t

    def _delta_bracket_fn(self, z):
        t  = self._bracket_fn(z)
        dt = np.abs(t-self._zlambda_targval)
        return dt

    def _zlambda_calc_gaussian_err(self, z_lambda):
        """
        calculate z_lambda error

        parameters
        ----------
        z_lambda: input

        returns
        -------
        z_lambda_e: z_lambda error
        """

        minlike = self._bracket_fn(z_lambda) # of course this is negative
        # now we want to aim for minlike+1
        self._zlambda_targval = minlike+1

        z_lambda_lo = scipy.optimize.minimize_scalar(self._delta_bracket_fn,
            bracket = (z_lambda-0.1, z_lambda-0.001), method='bounded',
            bounds = (z_lambda-0.1, z_lambda-0.001))
        z_lambda_hi = scipy.optimize.minimize_scalar(self._delta_bracket_fn,
            bracket = (z_lambda+0.001, z_lambda+0.1), method='bounded',
            bounds = (z_lambda+0.001, z_lambda+0.1))
        z_lambda_e = (z_lambda_hi.x-z_lambda_lo.x)/2.

        return z_lambda_e

    def _zlambda_calc_pz_and_check(self, z_lambda, wtvals, maxrad, maxmag, convergence_warning=False):
        """
        Parent to set pz and pzbins, with checking

        parameters
        ----------
        z_lambda: input
        wtvals: weights
        maxrad: maximum radius for considering neighbours
        maxmag: maximum magnitude for considering neighbours
        convergence_warning: print warning if we haven't converged
        """

        # First do with fast mode
        self._zlambda_calc_pz(z_lambda, wtvals, maxrad, maxmag, slow=False)

        pzdone = False

        # check for bad values, and do slow run if necessary...
        if (self.pz[(self.config.npzbins - 1) // 2] > 0.0 and
            ((self.pz[0] / self.pz[(self.config.npzbins - 1) // 2] > 0.01) and
             (self.pzbins[0] >= (self.zredstr.z[0] + 0.01))) or
            ((self.pz[-1] >= self.pz[(self.config.npzbins-1) // 2] > 0.01) and
             (self.pzbins[-1] <= (self.zredstr.z[-2] - 0.01)))):

            self._zlambda_calc_pz(z_lambda, wtvals, maxrad, maxmag, slow=True)

        if self.pz[0] < 0:
            # this is very bad
            z_lambda = -1.0
            z_lambda_e = -1.0
        else:
            m = np.argmax(self.pz)
            p0 = np.array([self.pz[m], self.pzbins[m], 0.01])

            try:
                coeff, varMatrix = scipy.optimize.curve_fit(gaussFunction,
                                                            self.pzbins,
                                                            self.pz,
                                                            p0=p0)
            except:
                # This was a failure, but this happens on marginal clusters
                coeff = [-10.0, -10.0, -10.0]

            if coeff[2] > 0 or coeff[2] > 0.2:
                z_lambda_e = coeff[2]
            else:
                # revert to old school
                z_lambda_e = self._zlambda_calc_gaussian_err(z_lambda)

            # check peak of p(z)...
            pmind = np.argmax(self.pz)
            if (np.abs(self.pzbins[pmind] - z_lambda) < self.config.zlambda_tol):
                pzdone = True
            else:
                if (convergence_warning):
                    print('Warning: z_lambda / p(z) inconsistency detected.')
                    #if ((z_lambda < 0.4) & (self.cluster_parent.Lambda > 20.0) & (self.cluster_parent.scaleval < 2.0) & (z_lambda > 0.15)):
                    #    asdfjlsdfjkl

                # Record the new peak z_lambda and kick back out saying that p(z) isn't done
                z_lambda = self.pzbins[pmind]
                pzdone = False

        return pzdone, z_lambda, z_lambda_e

    def _zlambda_calc_pz(self, z_lambda, wtvals, maxrad, maxmag, slow=False):
        """
        set pz and pzbins

        parameters
        ----------
        z_lambda: input
        wtvals: weights
        maxrad: maximum radius for considering neighbours
        maxmag: maximum magnitude for considering neighbours
        slow: slow or fast mode
        """
        minlike = self._bracket_fn(z_lambda)
        # 4 sigma
        self._zlambda_targval=minlike+16

        if not slow:
            # Fast mode
            # for speed, just do one direction
            z_lambda_hi = scipy.optimize.minimize_scalar(self._delta_bracket_fn,
                                                         bracket=(z_lambda + 0.001, z_lambda + 0.15),
                                                         method='bounded',
                                                         bounds=(z_lambda + 0.001, z_lambda + 0.15),
                                                         options={'xatol':1e-5})

            # we will not allow a dz smaller than 0.005
            dz = np.clip((z_lambda_hi.x - z_lambda), 0.005, 0.15)
            pzbinsize = 2.*dz/(self.config.npzbins-1)
            pzbins = pzbinsize*np.arange(self.config.npzbins)+z_lambda - dz

        else:
            # slow mode

            # First, find the center, this is the likelihood (inverted)
            pk = -self._bracket_fn(z_lambda)
            pz0 = self.zredstr.volume_factor[self.zredstr.zindex(z_lambda)]

            # go to lower redshift
            dztest = 0.05

            lowz = z_lambda - dztest
            ratio = 1.0
            while (lowz >= self.zredstr.z[0] and (ratio > 0.01)):
                val = -self._bracket_fn(lowz)

                ln_lkhd = val - pk
                with np.errstate(over="raise"):
                    pz = np.exp(val - pk) * self.zredstr.volume_factor[self.zredstr.zindex(lowz)]

                ratio = pz/pz0

                if (ratio > 0.01):
                    lowz -= dztest

            # clip to lower value
            lowz = np.clip(lowz, self.zredstr.z[0], None)

            highz = z_lambda + dztest
            ratio = 1.0
            while (highz <= self.zredstr.z[-2] and ratio > 0.01):
                val = -self._bracket_fn(highz)

                ln_lkhd = val - pk
                pz = np.exp(ln_lkhd) * self.zredstr.volume_factor[self.zredstr.zindex(highz)]

                ratio = pz / pz0

                if ratio > 0.01:
                    highz += dztest

            highz = np.clip(highz, None, self.zredstr.z[-2])

            pzbinsize = (highz - lowz)/(self.config.npzbins-1)

            pzbins = pzbinsize*np.arange(self.config.npzbins) + lowz

            # and finally offset so that we're centered on z_lambda.  Important!
            zmind = np.argmin(np.abs(pzbins - z_lambda))
            pzbins = pzbins - (pzbins[zmind] - z_lambda)

        # Now compute for each of the bins

        ln_lkhd = np.zeros(self.config.npzbins)
        for i in xrange(self.config.npzbins):
            ln_lkhd[i] = -self._bracket_fn(pzbins[i])

        ln_lkhd = ln_lkhd - np.max(ln_lkhd)
        pz = np.exp(ln_lkhd) * self.zredstr.volume_factor[self.zredstr.zindex(pzbins)]

        # now normalize
        n = scipy.integrate.simps(pz, pzbins)
        pz = pz / n

        self.pzbins = pzbins
        self.pzbinsize = pzbinsize
        self.pz = pz

        return pzbins, pz

class ZlambdaCorrectionPar(object):
    """
    """
    def __init__(self, parfile=None, pars=None, zrange=None, zbinsize=None, zlambda_pivot=None):

        # We can either send in a parfile or the actual pars (used in calibration)

        if parfile is None and pars is None:
            raise RuntimeError("Must supply either parfile or pars")

        if parfile is not None:
            # We have specified a parfile
            if not os.path.isfile(parfile):
                raise IOError("Could not find ZlambdaCorrectionPar file %s" % (parfile))

            hdr = fitsio.read_header(parfile, ext=1)

            if zrange is None:
                zrange = [hdr['ZRANGE0'], hdr['ZRANGE1']]
            self.zrange = zrange

            if zbinsize is None:
                zbinsize = hdr['ZBINSIZE']
            self.zbinsize = zbinsize

            if zlambda_pivot is None:
                zlambda_pivot = hdr['ZLAMPIV']
            self.zlambda_pivot = zlambda_pivot

            pars = Entry.from_fits_file(parfile, ext=1)

        else:
            if zrange is None:
                raise ValueError("Must specify zrange with a par structure")
            self.zrange = zrange

            if zbinsize is None:
                raise ValueError("Must specify zbinsize with a par structure")
            self.zbinsize = zbinsize

            if zlambda_pivot is None:
                raise ValueError("Must specify zlambda_pivot with a par structure")
            self.zlambda_pivot = zlambda_pivot

        nbins = np.round((zrange[1] - zrange[0])/zbinsize).astype(np.int32)
        self.z = zbinsize*np.arange(nbins) + zrange[0]

        self.niter = 1
        try:
            self.niter = pars.niter_true
        except:
            pass

        self.extrapolated = np.zeros_like(self.z, dtype=np.bool)

        self.offset = np.zeros((self.niter, nbins))
        self.slope = np.zeros_like(self.offset)
        self.scatter = np.zeros_like(self.offset)

        loz, = np.where(self.z < pars.offset_z[0])
        hiz, = np.where(self.z > pars.offset_z[-1])

        self.extrapolated[loz] = True
        self.extrapolated[hiz] = True

        if self.niter == 1:
            spl = CubicSpline(pars.offset_z, pars.offset_true)
            self.offset[0, :] = spl(self.z)

            spl = CubicSpline(pars.slope_z, pars.slope_true)
            self.slope[0, :] = spl(self.z)

            spl = CubicSpline(pars.slope_z, pars.scatter_true)
            self.scatter[0, :] = np.clip(spl(self.z), 0.001, None)
        else:
            for i in xrange(self.niter):
                spl = CubicSpline(pars.offset_z, pars.offset_true[:, i])
                self.offset[i, :] = spl(self.z)

                spl = CubicSpline(pars.slope_z, pars.slope_true[:, i])
                self.slope[i, :] = spl(self.z)

                spl = CubicSpline(pars.slope_z, pars.scatter_true[:, i])
                self.scatter[i, :] = np.clip(spl(self.z), 0.001, None)

        spl = CubicSpline(pars.offset_z, pars.zred_uncorr)
        self.zred_uncorr = spl(self.z)

    def apply_correction(self, lam, zlam, zlam_e, pzbins=None, pzvals=None, noerr=False):
        """
        """

        if pzbins is None:
            npzbins = 0
        else:
            npzbins = pzbins.size

        for i in xrange(self.niter):
            correction = self.offset[i, :] + self.slope[i, :] * np.log(lam / self.zlambda_pivot)
            extra_err = np.interp(zlam, self.z, self.scatter[i, :])

            dz = np.interp(zlam, self.z, correction)

            ozlam = copy.deepcopy(zlam)

            zlam += dz

            if pzbins is None and not noerr:
                # No P(z).  Simple error application
                zlam_e = np.sqrt(zlam_e**2. + extra_err**2.)
            else:
                # With P(z).  Do "space density expansion"
                # modify width of bins by expansion, and also
                # shift the center to the new zlam

                offset = pzbins[int((float(npzbins) - 1)/2.)] - ozlam

                opdz = pzbins[1] - pzbins[0]
                pdz = opdz * np.sqrt(extra_err**2. + zlam_e**2.) / zlam_e

                pzbins = pdz * np.arange(npzbins) + zlam - pdz * (npzbins - 1)/2. + offset

                n = scipy.integrate.simps(pzvals, pzbins)
                pzvals /= n

                zlam_e = np.sqrt(zlam_e**2. + extra_err**2.)

        if pzbins is None:
            return zlam, zlam_e
        else:
            return zlam, zlam_e, pzbins, pzvals

