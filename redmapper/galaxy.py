import fitsio
import esutil as eu
from esutil.htm import Matcher
import numpy as np
import itertools
from catalog import Catalog, Entry
import healpy as hp
import os


class Galaxy(Entry): 

    """ docstring """

    pass


class GalaxyCatalog(Catalog):

    """ docstring """

    entry_class = Galaxy

    def __init__(self, *arrays, **kwargs):
        super(GalaxyCatalog, self).__init__(*arrays)
        self._htm_matcher = None
        self.depth = 10 if 'depth' not in kwargs else kwargs['depth']

    @classmethod
    def from_galfile(cls, filename, nside=None, hpix=None, border=0.0):
        """ docstring """
        if hpix is not None and nside is None:
            raise ValueError("If hpix is specified, must also specify nside")
        if border < 0.0:
            raise ValueError("Border must be >= 0.0.")
        # ensure that nside is valid, and hpix is within range (if necessary)
        if nside is not None:
            if not hp.isnsideok(nside):
                raise ValueError("Nside not valid")
            if hpix is not None:
                if hpix < 0 or hpix >= hp.nside2npix(nside):
                    raise ValueError("hpix out of range.")
        # check that the file is there and the right format
        # this will raise an exception if it's not there.
        hdr = fitsio.read_header(filename, ext=1)
        if 'PIXELS' not in hdr:
            return super(GalaxyCatalog, self).from_fits_file(filename)
        pixelated = hdr['PIXELS']
        # this is to keep us from trying to use old IDL galfiles
        if 'FITS' not in hdr:
            raise ValueError("Input galfile must describe fits files.")
        fitsformat = hdr['FITS']
        # now we can read in the galaxy table summary file...
        tab = fitsio.read(filename, ext=1)
        nside_tab = tab['NSIDE']
        if (nside > nside_tab):
            raise ValueError("""Requested nside (%d) must not be larger than
                                    table nside (%d).""" % (nside, nside_tab))
        # which files do we want to read?
        path = os.path.dirname(os.path.abspath(filename))
        if hpix is None:
            # all of them!
            indices = np.arange(tab[0]['FILENAMES'].size)
        else:
            # first we need all the pixels that are contained in the big pixel
            theta, phi = hp.pix2ang(nside_tab, tab[0]['HPIX'])
            ipring_big = hp.ang2pix(nside, theta, phi)
            indices = np.where(ipring_big == hpix)
            if border > 0.0:
                # now we need to find the extra boundary...
                boundaries = hp.boundaries(nside, hpix, step=nside_tab/nside)
                inhpix = tab[0]['HPIX'][indices]
                for i in xrange(boundaries.shape[1]):
                    pixint = hp.query_disc(nside_tab, boundaries[:,i],
                                    border*np.pi/180., inclusive=True, fact=8)
                    inhpix = np.append(inhpix, pixint)
                inhpix = np.unique(inhpix)
                _, indices = eu.numpy_util.match(inhpix, tab[0]['HPIX'])
        # create the catalog array to read into
        elt = fitsio.read('%s/%s' % (path, tab[0]['FILENAMES'][indices[0]]),
                                                                ext=1, rows=0)
        cat = np.zeros(np.sum(tab[0]['NGALS'][indices]), dtype=elt.dtype)
        # read the files
        ctr = 0
        for index in indices:
            cat[ctr : ctr+tab[0]['NGALS'][index]] = fitsio.read('%s/%s' % (path, tab[0]['FILENAMES'][index]),ext=1)
            ctr += tab[0]['NGALS'][index]
        # In the IDL version this is trimmed to the precise boundary requested.
        # that's easy in simplepix.  Not sure how to do in healpix.
        return cls(cat)

    def match(self, galaxy, radius):
        if self._htm_matcher is None:
            self._htm_matcher = Matcher(self.depth, self.ra, self.dec)
        _, indices, dists = self._htm_matcher.match(galaxy.ra, galaxy.dec, 
                                                        radius, maxmatch=0)
        return indices, dists

